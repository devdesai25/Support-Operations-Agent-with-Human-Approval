import time
from typing import Any
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.tools.audit import record_tool_audit
from app.models.agent_action import AgentActionStatus
from app.models.drop import Drop, DropEntry
from app.models.order import Order
from app.schemas.shop import DropEntryRead, DropRead, OrderRead


async def get_order(
    session: AsyncSession,
    conversation_id: str,
    user_id: uuid.UUID,
    order_id: uuid.UUID,
) -> dict[str, Any]:
    """Look up an order by order_id.
    
    CRITICAL SECURITY RULE: The query hard-filters by `orders.user_id == user_id`.
    Users cannot access another user's order even if the ID is known.
    """
    start_time = time.perf_counter()
    tool_input = {"order_id": str(order_id)}

    try:
        stmt = (
            select(Order)
            .where(Order.id == order_id, Order.user_id == user_id)
            .options(selectinload(Order.items))
        )
        result = await session.execute(stmt)
        order = result.scalar_one_or_none()

        if not order:
            error_msg = f"Order {order_id} not found or access denied."
            await record_tool_audit(
                session=session,
                conversation_id=conversation_id,
                user_id=user_id,
                tool_name="get_order",
                tool_input=tool_input,
                tool_output=None,
                status=AgentActionStatus.BLOCKED,
                start_time=start_time,
                error_message=error_msg,
            )
            return {"success": False, "error": error_msg}

        order_data = OrderRead.model_validate(order).model_dump(mode="json")
        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="get_order",
            tool_input=tool_input,
            tool_output=order_data,
            status=AgentActionStatus.SUCCESS,
            start_time=start_time,
        )
        return {"success": True, "order": order_data}

    except Exception as e:
        error_msg = f"Internal error looking up order: {e!s}"
        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="get_order",
            tool_input=tool_input,
            tool_output=None,
            status=AgentActionStatus.ERROR,
            start_time=start_time,
            error_message=error_msg,
        )
        return {"success": False, "error": error_msg}


async def list_user_orders(
    session: AsyncSession,
    conversation_id: str,
    user_id: uuid.UUID,
    limit: int = 10,
) -> dict[str, Any]:
    """List recent orders placed by the authenticated user."""
    start_time = time.perf_counter()
    tool_input = {"limit": limit}

    try:
        stmt = (
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .options(selectinload(Order.items))
        )
        result = await session.execute(stmt)
        orders = result.scalars().all()

        orders_data = [
            OrderRead.model_validate(o).model_dump(mode="json")
            for o in orders
        ]

        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="list_user_orders",
            tool_input=tool_input,
            tool_output={"count": len(orders_data)},
            status=AgentActionStatus.SUCCESS,
            start_time=start_time,
        )
        return {"success": True, "orders": orders_data}

    except Exception as e:
        error_msg = f"Internal error listing orders: {e!s}"
        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="list_user_orders",
            tool_input=tool_input,
            tool_output=None,
            status=AgentActionStatus.ERROR,
            start_time=start_time,
            error_message=error_msg,
        )
        return {"success": False, "error": error_msg}


async def get_drop_entry_status(
    session: AsyncSession,
    conversation_id: str,
    user_id: uuid.UUID,
    drop_id: uuid.UUID,
) -> dict[str, Any]:
    """Get the user's entry status for a specific sneaker/product drop."""
    start_time = time.perf_counter()
    tool_input = {"drop_id": str(drop_id)}

    try:
        stmt = (
            select(DropEntry)
            .where(DropEntry.user_id == user_id, DropEntry.drop_id == drop_id)
            .options(selectinload(DropEntry.drop))
        )
        result = await session.execute(stmt)
        entry = result.scalar_one_or_none()

        if not entry:
            error_msg = f"No entry found for drop {drop_id} under your account."
            await record_tool_audit(
                session=session,
                conversation_id=conversation_id,
                user_id=user_id,
                tool_name="get_drop_entry_status",
                tool_input=tool_input,
                tool_output=None,
                status=AgentActionStatus.BLOCKED,
                start_time=start_time,
                error_message=error_msg,
            )
            return {"success": False, "error": error_msg}

        entry_data = DropEntryRead.model_validate(entry).model_dump(mode="json")
        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="get_drop_entry_status",
            tool_input=tool_input,
            tool_output=entry_data,
            status=AgentActionStatus.SUCCESS,
            start_time=start_time,
        )
        return {"success": True, "entry": entry_data}

    except Exception as e:
        error_msg = f"Internal error retrieving drop status: {e!s}"
        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="get_drop_entry_status",
            tool_input=tool_input,
            tool_output=None,
            status=AgentActionStatus.ERROR,
            start_time=start_time,
            error_message=error_msg,
        )
        return {"success": False, "error": error_msg}
