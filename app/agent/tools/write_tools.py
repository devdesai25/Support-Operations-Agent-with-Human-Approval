from datetime import datetime, timezone
from decimal import Decimal
import time
from typing import Any
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.audit import record_tool_audit
from app.models.agent_action import AgentAction, AgentActionStatus
from app.models.order import Order, OrderStatus
from app.models.refund import Refund, RefundStatus
from app.schemas.shop import RefundRead


async def issue_refund(
    session: AsyncSession,
    conversation_id: str,
    user_id: uuid.UUID,
    order_id: uuid.UUID,
    amount: Decimal,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Execute a refund against an order.
    
    Hard constraints:
    1. Order must belong to the user (`user_id`).
    2. Order must be in PAID status.
    3. Refund amount cannot exceed remaining unrefunded total.
    4. Idempotency key guarantees that retries return the original refund record.
    5. Action is recorded in `agent_actions`.
    """
    start_time = time.perf_counter()
    tool_input = {
        "order_id": str(order_id),
        "amount": str(amount),
        "reason": reason,
        "idempotency_key": idempotency_key,
    }

    try:
        # 1. Idempotency check: Has this refund already been processed?
        stmt_idemp = select(Refund).where(Refund.idempotency_key == idempotency_key)
        existing_refund = (await session.execute(stmt_idemp)).scalar_one_or_none()
        if existing_refund:
            refund_data = RefundRead.model_validate(existing_refund).model_dump(mode="json")
            await record_tool_audit(
                session=session,
                conversation_id=conversation_id,
                user_id=user_id,
                tool_name="issue_refund",
                tool_input=tool_input,
                tool_output={"refund": refund_data, "idempotent_replay": True},
                status=AgentActionStatus.SUCCESS,
                start_time=start_time,
                idempotency_key=idempotency_key,
            )
            return {"success": True, "refund": refund_data, "idempotent_replay": True}

        # 2. Authorization & Order Lookup
        stmt_order = select(Order).where(Order.id == order_id, Order.user_id == user_id)
        order = (await session.execute(stmt_order)).scalar_one_or_none()
        if not order:
            error_msg = f"Order {order_id} not found or access denied."
            await record_tool_audit(
                session=session,
                conversation_id=conversation_id,
                user_id=user_id,
                tool_name="issue_refund",
                tool_input=tool_input,
                tool_output=None,
                status=AgentActionStatus.BLOCKED,
                start_time=start_time,
                idempotency_key=idempotency_key,
                error_message=error_msg,
            )
            return {"success": False, "error": error_msg}

        # 3. Status Check: Must be PAID
        if order.status != OrderStatus.PAID:
            error_msg = f"Cannot refund order with status '{order.status}'. Only PAID orders can be refunded."
            await record_tool_audit(
                session=session,
                conversation_id=conversation_id,
                user_id=user_id,
                tool_name="issue_refund",
                tool_input=tool_input,
                tool_output=None,
                status=AgentActionStatus.ERROR,
                start_time=start_time,
                idempotency_key=idempotency_key,
                error_message=error_msg,
            )
            return {"success": False, "error": error_msg}

        # 4. Amount Validation against total order amount and prior refunds
        stmt_sum = select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.order_id == order_id,
            Refund.status.in_([RefundStatus.PROCESSED, RefundStatus.APPROVED]),
        )
        already_refunded = Decimal(str((await session.execute(stmt_sum)).scalar_one()))
        remaining_refundable = order.total_amount - already_refunded

        if amount > remaining_refundable:
            error_msg = (
                f"Requested refund amount ${amount:.2f} exceeds remaining refundable "
                f"balance ${remaining_refundable:.2f} (Total: ${order.total_amount:.2f}, "
                f"Already Refunded: ${already_refunded:.2f})."
            )
            await record_tool_audit(
                session=session,
                conversation_id=conversation_id,
                user_id=user_id,
                tool_name="issue_refund",
                tool_input=tool_input,
                tool_output=None,
                status=AgentActionStatus.ERROR,
                start_time=start_time,
                idempotency_key=idempotency_key,
                error_message=error_msg,
            )
            return {"success": False, "error": error_msg}

        # 5. Create Refund record (Mocking instant payment gateway refund)
        now = datetime.now(timezone.utc)
        refund = Refund(
            order_id=order.id,
            amount=amount,
            reason=reason,
            status=RefundStatus.PROCESSED,
            idempotency_key=idempotency_key,
            processed_at=now,
        )
        session.add(refund)

        # Update order status if fully refunded
        if (already_refunded + amount) >= order.total_amount:
            order.status = OrderStatus.REFUNDED
            order.updated_at = now

        await session.flush()
        refund_data = RefundRead.model_validate(refund).model_dump(mode="json")

        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="issue_refund",
            tool_input=tool_input,
            tool_output=refund_data,
            status=AgentActionStatus.SUCCESS,
            start_time=start_time,
            idempotency_key=idempotency_key,
        )
        await session.commit()
        return {"success": True, "refund": refund_data}

    except Exception as e:
        await session.rollback()
        error_msg = f"Failed to issue refund: {e!s}"
        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="issue_refund",
            tool_input=tool_input,
            tool_output=None,
            status=AgentActionStatus.ERROR,
            start_time=start_time,
            idempotency_key=idempotency_key,
            error_message=error_msg,
        )
        return {"success": False, "error": error_msg}


async def cancel_order(
    session: AsyncSession,
    conversation_id: str,
    user_id: uuid.UUID,
    order_id: uuid.UUID,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Cancel an active order.
    
    Hard constraints:
    1. Order must belong to the user (`user_id`).
    2. Order status must be PENDING or PAID (cannot cancel EXPIRED, CANCELLED, or REFUNDED orders).
    3. Idempotency key prevents duplicate actions.
    4. Action is recorded in `agent_actions`.
    """
    start_time = time.perf_counter()
    tool_input = {
        "order_id": str(order_id),
        "reason": reason,
        "idempotency_key": idempotency_key,
    }

    try:
        # 1. Idempotency check: has this cancellation action already succeeded?
        stmt_idemp = select(AgentAction).where(
            AgentAction.idempotency_key == idempotency_key,
            AgentAction.tool_name == "cancel_order",
            AgentAction.status == AgentActionStatus.SUCCESS,
        )
        existing_action = (await session.execute(stmt_idemp)).scalar_one_or_none()
        if existing_action and existing_action.tool_output:
            return {
                "success": True,
                "order_id": str(order_id),
                "status": OrderStatus.CANCELLED,
                "idempotent_replay": True,
            }

        # 2. Authorization & Order Lookup
        stmt_order = select(Order).where(Order.id == order_id, Order.user_id == user_id)
        order = (await session.execute(stmt_order)).scalar_one_or_none()
        if not order:
            error_msg = f"Order {order_id} not found or access denied."
            await record_tool_audit(
                session=session,
                conversation_id=conversation_id,
                user_id=user_id,
                tool_name="cancel_order",
                tool_input=tool_input,
                tool_output=None,
                status=AgentActionStatus.BLOCKED,
                start_time=start_time,
                idempotency_key=idempotency_key,
                error_message=error_msg,
            )
            return {"success": False, "error": error_msg}

        # 3. Status Check: can only cancel PENDING or PAID
        if order.status not in (OrderStatus.PENDING, OrderStatus.PAID):
            error_msg = f"Cannot cancel order with status '{order.status}'. Only PENDING or PAID orders can be cancelled."
            await record_tool_audit(
                session=session,
                conversation_id=conversation_id,
                user_id=user_id,
                tool_name="cancel_order",
                tool_input=tool_input,
                tool_output=None,
                status=AgentActionStatus.ERROR,
                start_time=start_time,
                idempotency_key=idempotency_key,
                error_message=error_msg,
            )
            return {"success": False, "error": error_msg}

        # 4. Perform Cancellation
        now = datetime.now(timezone.utc)
        order.status = OrderStatus.CANCELLED
        order.updated_at = now

        output_data = {
            "order_id": str(order.id),
            "status": OrderStatus.CANCELLED,
            "cancellation_reason": reason,
        }

        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="cancel_order",
            tool_input=tool_input,
            tool_output=output_data,
            status=AgentActionStatus.SUCCESS,
            start_time=start_time,
            idempotency_key=idempotency_key,
        )
        await session.commit()
        return {"success": True, **output_data}

    except Exception as e:
        await session.rollback()
        error_msg = f"Failed to cancel order: {e!s}"
        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="cancel_order",
            tool_input=tool_input,
            tool_output=None,
            status=AgentActionStatus.ERROR,
            start_time=start_time,
            idempotency_key=idempotency_key,
            error_message=error_msg,
        )
        return {"success": False, "error": error_msg}
