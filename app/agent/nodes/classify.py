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

TYPO_MAPPINGS = {
    r"\bordr\b": "order",
    r"\brefnd\b": "refund",
    r"\bcancl\b": "cancel",
    r"\bcancle\b": "cancel",
    r"\bshippin\b": "shipping",
    r"\bretrn\b": "return",
    r"\bretun\b": "return",
    r"\bhooman\b": "human",
    r"\bhumon\b": "human",
    r"\bwher\b": "where",
    r"\bwut\b": "what",
    r"\bwat\b": "what",
    r"\bda\b": "the",
    r"\bpleas\b": "please",
    r"\bsneekr\b": "sneaker",
    r"\bsneekers\b": "sneakers",
    r"\bpostion\b": "position",
}


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


def normalize_text(text: str) -> str:
    """Normalize colloquial typos and slang."""
    lowered = text.lower()
    for pattern, replacement in TYPO_MAPPINGS.items():
        lowered = re.sub(pattern, replacement, lowered)
    return lowered


def heuristic_classify(user_text: str) -> IntentClassification:
    """Deterministic classifier with typo-normalization and priority ordering."""
    text = normalize_text(user_text)
    found_uuids = UUID_REGEX.findall(user_text)
    first_uuid = found_uuids[0] if found_uuids else None

    # Check if this is an exploratory/policy question about refunds, cancellations, drops, etc.
    is_question = any(text.startswith(q) for q in ["how", "can i", "is ", "are ", "what ", "why "]) or "return policy" in text or "how long" in text or "what happens" in text

    # 1. Escalation (Explicit request for human or legal threats)
    if any(k in text for k in [
        "speak to a human", "speak to a representative", "speak to a supervisor", "speak to a person",
        "talk to a human", "talk to a representative", "talk to a supervisor", "talk to a person",
        "speek to hooman", "speak to hooman", "demand to speak", "call my lawyer", "sue", "lawyer",
        "let me talk to a person", "let me speak to a representative",
    ]):
        return IntentClassification(
            intent="escalate",
            confidence=0.95,
            reasoning="Customer explicitly demanded human supervisor or legal escalation.",
        )

    # 2. Informational / Policy Questions (Even if mentioning refund/cancel/drops)
    if is_question and any(k in text for k in [
        "policy", "return", "refund", "cancel", "exchange", "window", "shipping",
        "waitlist", "raffle", "drop", "bot", "promo", "discount", "fee", "signature", "hours",
    ]) and not any(k in text for k in ["did i win", "where is my order"]):
        return IntentClassification(
            intent="policy_question",
            confidence=0.92,
            policy_query=user_text,
            reasoning="Customer asked an informational policy question.",
        )

    # 3. Direct Cancellation commands
    if any(k in text for k in ["cancel my order", "cancel order", "cancellation", "pleas cancel"]):
        return IntentClassification(
            intent="cancellation",
            confidence=0.95,
            order_id=first_uuid,
            reasoning="Customer requested order cancellation.",
        )

    # 4. Direct Refund commands
    if any(k in text for k in [
        "refund", "money back", "reimburse", "return payment",
        "give me my money", "chargeback",
    ]):
        return IntentClassification(
            intent="refund_request",
            confidence=0.95,
            order_id=first_uuid,
            reasoning="Customer is initiating a refund.",
        )

    # 5. Drop / Raffle Status
    if any(k in text for k in [
        "did i win", "raffle drop", "drop raffle", "drop entry", "waitlist position", "drop",
    ]) and not any(k in text for k in ["drop table"]):
        return IntentClassification(
            intent="drop_status",
            confidence=0.90,
            drop_id=first_uuid,
            reasoning="Customer is checking drop or raffle entry status.",
        )

    # 6. Policy Questions (Catchall for rules/restocking/fees)
    if any(k in text for k in [
        "policy", "return", "exchange", "window", "shipping", "shippin",
        "delivery", "defective", "damaged", "promo", "discount", "code",
        "coupon", "rules", "fee", "fees", "restocking", "signature", "international", "bot",
    ]):
        return IntentClassification(
            intent="policy_question",
            confidence=0.90,
            policy_query=user_text,
            reasoning="Customer asked a policy, rules, or procedural question.",
        )

    # 7. Order Status / Tracking
    if any(k in text for k in [
        "order", "package", "tracking", "status", "where is", "track", "delivery", "delivered", "waiting",
    ]):
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
