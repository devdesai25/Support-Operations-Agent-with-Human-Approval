from collections.abc import Sequence
from typing import Annotated, Any, Literal, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

IntentType = Literal[
    "order_status",
    "drop_status",
    "policy_question",
    "refund_request",
    "cancellation",
    "other",
    "escalate",
]


class AgentState(TypedDict, total=False):
    """The complete state dictionary preserved across LangGraph steps and checkpoints."""

    # Chat history with LangGraph message reducer
    messages: Annotated[list[BaseMessage], add_messages]

    # Authenticated user scope (strictly enforced in code)
    user_id: str

    # Classified intent
    intent: Optional[str]

    # Extracted entity parameters (e.g. order_id, drop_id, query)
    extracted_entities: Optional[dict[str, Any]]

    # Context gathered by read tools (order details, drop entries, policy chunks)
    order_context: Optional[dict[str, Any]]

    # Action proposed by agent requiring human approval (Milestone 4)
    proposed_action: Optional[dict[str, Any]]

    # Approval gate status: "pending" | "approved" | "rejected" | "edited"
    approval_status: Optional[str]

    # Guardrail: execution step counter
    step_count: int
