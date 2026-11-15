import re
from typing import Any, Literal, Optional
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, Field

from app.agent.llm import get_chat_model
from app.agent.state import AgentState

UUID_REGEX = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class IntentClassification(BaseModel):
    intent: Literal[
        "order_status",
        "drop_status",
        "policy_question",
        "refund_request",
        "cancellation",
        "other",
        "escalate",
    ] = Field(..., description="Primary classification of user's request.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence score.")
    order_id: Optional[str] = Field(None, description="Extracted order UUID if mentioned.")
    drop_id: Optional[str] = Field(None, description="Extracted drop UUID if mentioned.")
    policy_query: Optional[str] = Field(None, description="Search query terms for policy lookups.")
    reasoning: str = Field(..., description="Brief reasoning for classification.")


def heuristic_classify(user_text: str) -> IntentClassification:
    """Deterministic classifier used for fast tests, offline CI, or LLM fallback."""
    text = user_text.lower()
    found_uuids = UUID_REGEX.findall(user_text)
    first_uuid = found_uuids[0] if found_uuids else None

    # 1. Escalation
    if any(k in text for k in ["human", "representative", "agent", "supervisor", "support person", "lawyer", "sue"]):
        return IntentClassification(
            intent="escalate",
            confidence=0.95,
            reasoning="Customer requested human intervention or sensitive escalation.",
        )

    # 2. Refund request
    if any(k in text for k in ["refund", "money back", "reimburse", "return payment"]):
        return IntentClassification(
            intent="refund_request",
            confidence=0.95,
            order_id=first_uuid,
            reasoning="Customer is inquiring about or requesting a refund.",
        )

    # 3. Cancellation
    if any(k in text for k in ["cancel my order", "cancel order", "cancellation"]):
        return IntentClassification(
            intent="cancellation",
            confidence=0.95,
            order_id=first_uuid,
            reasoning="Customer requested order cancellation.",
        )

    # 4. Drop status
    if any(k in text for k in ["drop", "raffle", "waitlist", "draw", "entry status"]):
        return IntentClassification(
            intent="drop_status",
            confidence=0.90,
            drop_id=first_uuid,
            reasoning="Customer is checking drop or raffle entry status.",
        )

    # 5. Policy question
    if any(k in text for k in [
        "policy", "return", "returns", "exchange", "window", "shipping time",
        "defective", "damaged", "promo", "discount", "code", "coupon",
        "rules", "fee", "fees", "how many days", "how long",
    ]):
        return IntentClassification(
            intent="policy_question",
            confidence=0.90,
            policy_query=user_text,
            reasoning="Customer asked a policy, rules, or procedural question.",
        )

    # 6. Order status
    if any(k in text for k in ["order", "package", "tracking", "status", "where is", "delivery", "delivered"]):
        return IntentClassification(
            intent="order_status",
            confidence=0.90,
            order_id=first_uuid,
            reasoning="Customer asked about existing order or tracking status.",
        )

    return IntentClassification(
        intent="other",
        confidence=0.50,
        reasoning="General or unrecognized inquiry.",
    )


async def classify_intent_node(state: AgentState) -> dict[str, Any]:
    """Classify the user intent using structured output or heuristic fallback."""
    messages = state.get("messages", [])
    last_user_msg = next(
        (m.content for m in reversed(messages) if isinstance(m, HumanMessage) or getattr(m, "type", "") == "human"),
        "",
    )

    llm = get_chat_model()
    if llm:
        try:
            structured_llm = llm.with_structured_output(IntentClassification)
            system_prompt = (
                "You are an intent classification agent for a sneaker and streetwear e-commerce platform. "
                "Classify the user request strictly into: order_status, drop_status, policy_question, "
                "refund_request, cancellation, other, or escalate. Extract any relevant order_id or drop_id."
            )
            result: IntentClassification = await structured_llm.ainvoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": last_user_msg},
            ])
        except Exception:
            result = heuristic_classify(str(last_user_msg))
    else:
        result = heuristic_classify(str(last_user_msg))

    extracted_entities = {}
    if result.order_id:
        extracted_entities["order_id"] = result.order_id
    if result.drop_id:
        extracted_entities["drop_id"] = result.drop_id
    if result.policy_query:
        extracted_entities["query"] = result.policy_query
    elif result.intent == "policy_question":
        extracted_entities["query"] = str(last_user_msg)

    return {
        "intent": result.intent,
        "extracted_entities": extracted_entities,
        "step_count": state.get("step_count", 0) + 1,
    }
