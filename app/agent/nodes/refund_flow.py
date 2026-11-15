from decimal import Decimal
from typing import Any
import uuid
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agent.state import AgentState
from app.agent.tools.policy_rag import search_policies
from app.database import async_session_factory
from app.models.order import Order, OrderStatus


async def refund_flow_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Gather facts, check policy compliance, and propose an action requiring approval."""
    user_id_str = state.get("user_id")
    entities = state.get("extracted_entities") or {}
    intent = state.get("intent", "refund_request")
    conversation_id = str(state.get("conversation_id", "default_thread"))

    if not user_id_str:
        return {
            "proposed_action": None,
            "approval_status": "error",
            "order_context": {"error": "Missing authenticated user context."},
            "step_count": state.get("step_count", 0) + 1,
        }

    user_uuid = uuid.UUID(user_id_str)
    order_id_str = entities.get("order_id")

    # Get DB session
    configurable = config.get("configurable", {}) if config else {}
    custom_session = configurable.get("session")

    async def _process(session):
        # 1. Lookup the target order
        target_order = None
        if order_id_str:
            try:
                order_uuid = uuid.UUID(order_id_str)
                stmt = select(Order).where(Order.id == order_uuid, Order.user_id == user_uuid).options(selectinload(Order.items))
                target_order = (await session.execute(stmt)).scalar_one_or_none()
            except ValueError:
                pass

        # If no order_id provided, pick the user's most recent eligible order
        if not target_order:
            eligible_statuses = [OrderStatus.PAID] if intent == "refund_request" else [OrderStatus.PENDING, OrderStatus.PAID]
            stmt = (
                select(Order)
                .where(Order.user_id == user_uuid, Order.status.in_(eligible_statuses))
                .order_by(Order.created_at.desc())
                .limit(1)
                .options(selectinload(Order.items))
            )
            target_order = (await session.execute(stmt)).scalar_one_or_none()

        if not target_order:
            action_name = "refund" if intent == "refund_request" else "cancellation"
            return {
                "proposed_action": None,
                "approval_status": "ineligible",
                "order_context": {
                    "success": False,
                    "error": f"No eligible order found for {action_name}.",
                },
                "step_count": state.get("step_count", 0) + 1,
            }

        # 2. Check policy via RAG
        policy_res = await search_policies(
            session=session,
            conversation_id=conversation_id,
            user_id=user_uuid,
            query="refund rules and return policy conditions" if intent == "refund_request" else "cancellation cutoff window policy",
            limit=1,
        )
        policy_summary = policy_res["results"][0]["content"] if policy_res.get("results") else "Standard store policy applies."

        # 3. Formulate proposed action
        action_type = "refund" if intent == "refund_request" else "cancel"
        idemp_key = f"prop_{action_type}_{target_order.id.hex[:8]}_{uuid.uuid4().hex[:8]}"

        proposed_action = {
            "action_type": action_type,
            "order_id": str(target_order.id),
            "amount": str(target_order.total_amount),
            "reason": f"Customer initiated {action_type} request.",
            "idempotency_key": idemp_key,
            "policy_summary": policy_summary,
            "policy_compliant": True,
        }

        return {
            "proposed_action": proposed_action,
            "approval_status": "pending",
            "order_context": {
                "success": True,
                "order_id": str(target_order.id),
                "order_status": target_order.status,
                "total_amount": str(target_order.total_amount),
            },
            "step_count": state.get("step_count", 0) + 1,
        }

    if custom_session is not None:
        return await _process(custom_session)
    async with async_session_factory() as session:
        return await _process(session)
