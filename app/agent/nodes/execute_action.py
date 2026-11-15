from decimal import Decimal
from typing import Any
import uuid
from langchain_core.runnables import RunnableConfig

from app.agent.state import AgentState
from app.agent.tools.write_tools import cancel_order, issue_refund
from app.database import async_session_factory


async def execute_action_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Execute authorized financial and order write actions.
    
    HARD SECURITY RULE: Refuses to execute any action unless
    approval_status is explicitly 'approved'.
    """
    approval_status = state.get("approval_status")
    proposed = state.get("proposed_action")
    conversation_id = str(state.get("conversation_id", "default_thread"))
    user_id_str = state.get("user_id")

    # 1. HARD SECURITY CHECK: Refuse execution without approval
    if approval_status != "approved" or not proposed:
        error_msg = f"Execution blocked: Action has approval_status='{approval_status}'. Must be 'approved'."
        return {
            "action_result": {"success": False, "error": error_msg},
            "order_context": {"success": False, "error": error_msg},
            "step_count": state.get("step_count", 0) + 1,
        }

    user_uuid = uuid.UUID(user_id_str)
    order_uuid = uuid.UUID(proposed["order_id"])
    action_type = proposed.get("action_type")
    idemp_key = proposed.get("idempotency_key", f"exec_{uuid.uuid4().hex[:12]}")
    reason = proposed.get("reason", "Approved customer request")

    # Get DB session
    configurable = config.get("configurable", {}) if config else {}
    custom_session = configurable.get("session")

    async def _execute(session):
        if action_type == "refund":
            amount = Decimal(str(proposed["amount"]))
            res = await issue_refund(
                session=session,
                conversation_id=conversation_id,
                user_id=user_uuid,
                order_id=order_uuid,
                amount=amount,
                reason=reason,
                idempotency_key=idemp_key,
            )
            return {
                "action_result": res,
                "order_context": res,
                "step_count": state.get("step_count", 0) + 1,
            }

        if action_type == "cancel":
            res = await cancel_order(
                session=session,
                conversation_id=conversation_id,
                user_id=user_uuid,
                order_id=order_uuid,
                reason=reason,
                idempotency_key=idemp_key,
            )
            return {
                "action_result": res,
                "order_context": res,
                "step_count": state.get("step_count", 0) + 1,
            }

        return {
            "action_result": {"success": False, "error": f"Unknown action_type '{action_type}'"},
            "order_context": {"success": False, "error": f"Unknown action_type '{action_type}'"},
            "step_count": state.get("step_count", 0) + 1,
        }

    if custom_session is not None:
        return await _execute(custom_session)
    async with async_session_factory() as session:
        return await _execute(session)
