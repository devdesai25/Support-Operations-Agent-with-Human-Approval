from typing import Any
from langgraph.types import interrupt

from app.agent.state import AgentState


def approval_gate_node(state: AgentState) -> dict[str, Any]:
    """Human-in-the-loop approval gate.
    
    Pauses execution using LangGraph `interrupt()`.
    Resumes when human supervisor submits a decision via `Command(resume=...)`.
    """
    proposed = state.get("proposed_action")
    if not proposed or state.get("approval_status") != "pending":
        # Nothing to approve or ineligible
        return {"step_count": state.get("step_count", 0) + 1}

    # Construct the interrupt payload visible to approval callers / API
    interrupt_payload = {
        "type": "approval_required",
        "action_type": proposed.get("action_type"),
        "order_id": proposed.get("order_id"),
        "amount": proposed.get("amount"),
        "reason": proposed.get("reason"),
        "policy_summary": proposed.get("policy_summary"),
        "message": (
            f"Approval required: execute {proposed.get('action_type')} of "
            f"${proposed.get('amount', 'N/A')} for order {proposed.get('order_id')}."
        ),
    }

    # ⏸️ PAUSE EXECUTION: interrupt() surfaces the payload and suspends the thread
    human_decision = interrupt(interrupt_payload)

    # ▶️ RESUMED: human_decision contains the value passed into Command(resume=...)
    decision_type = "reject"
    notes = ""
    updated_proposed = dict(proposed)

    if isinstance(human_decision, dict):
        decision_type = human_decision.get("decision", "reject").lower()
        notes = human_decision.get("notes", "")
        # Supervisor can edit amount before approving
        if decision_type == "edit" or "amount" in human_decision:
            if human_decision.get("amount"):
                updated_proposed["amount"] = str(human_decision["amount"])
            decision_type = "approved"
    elif isinstance(human_decision, str):
        decision_type = human_decision.lower()

    if decision_type in ("approve", "approved", "yes"):
        approval_status = "approved"
    else:
        approval_status = "rejected"
        updated_proposed["rejection_reason"] = notes or "Rejected by supervisor."

    return {
        "approval_status": approval_status,
        "proposed_action": updated_proposed,
        "step_count": state.get("step_count", 0) + 1,
    }
