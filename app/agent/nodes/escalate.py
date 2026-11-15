from typing import Any
import uuid
from langchain_core.messages import AIMessage

from app.agent.state import AgentState


async def escalate_to_human_node(state: AgentState) -> dict[str, Any]:
    """Escalate sensitive inquiries, repeated errors, or customer requests to a human agent."""
    ticket_id = f"TICK-{uuid.uuid4().hex[:8].upper()}"
    msg = (
        f"I have escalated your request to our Human Support Operations team under Ticket **#{ticket_id}**.\n\n"
        "A senior representative will review your account history and reach out via email shortly."
    )
    return {
        "messages": [AIMessage(content=msg)],
        "step_count": state.get("step_count", 0) + 1,
    }
