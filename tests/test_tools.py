from datetime import datetime, timezone
from decimal import Decimal
import uuid
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.read_tools import get_drop_entry_status, get_order, list_user_orders
from app.agent.tools.write_tools import cancel_order, issue_refund
from app.models.agent_action import AgentAction, AgentActionStatus
from app.models.drop import Drop, DropEntry, DropEntryStatus, DropStatus
from app.models.order import Order, OrderItem, OrderStatus
from app.models.refund import Refund, RefundStatus
from app.models.user import User


@pytest_asyncio.fixture
async def sample_data(db_session: AsyncSession):
    """Fixture providing two distinct users with orders and drop entries."""
    now = datetime.now(timezone.utc)

    user_a = User(name="User Alice", email="alice@test.com")
    user_b = User(name="User Bob", email="bob@test.com")
    db_session.add_all([user_a, user_b])
    await db_session.flush()

    # Alice's orders
    order_a_paid = Order(
        user_id=user_a.id,
        status=OrderStatus.PAID,
        total_amount=Decimal("200.00"),
        created_at=now,
    )
    order_a_pending = Order(
        user_id=user_a.id,
        status=OrderStatus.PENDING,
        total_amount=Decimal("150.00"),
        created_at=now,
    )

    # Bob's order
    order_b_paid = Order(
        user_id=user_b.id,
        status=OrderStatus.PAID,
        total_amount=Decimal("300.00"),
        created_at=now,
    )
    db_session.add_all([order_a_paid, order_a_pending, order_b_paid])
    await db_session.flush()

    # Items for Alice's paid order
    item1 = OrderItem(
        order_id=order_a_paid.id,
        product_name="Air Jordan 1",
        sku="AJ1-001",
        quantity=1,
        price=Decimal("200.00"),
    )
    db_session.add(item1)

    # Drop and Alice's entry
    drop = Drop(
        name="Nike Dunk Low",
        status=DropStatus.ACTIVE,
        total_inventory=50,
        start_time=now,
        end_time=now,
    )
    db_session.add(drop)
    await db_session.flush()

    drop_entry_a = DropEntry(
        user_id=user_a.id,
        drop_id=drop.id,
        status=DropEntryStatus.WAITLISTED,
        position=5,
    )
    db_session.add(drop_entry_a)
    await db_session.commit()

    return {
        "user_a": user_a,
        "user_b": user_b,
        "order_a_paid": order_a_paid,
        "order_a_pending": order_a_pending,
        "order_b_paid": order_b_paid,
        "drop": drop,
    }


# ==============================================================================
# READ TOOLS TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_get_order_authorized(db_session: AsyncSession, sample_data: dict):
    """User Alice should successfully look up her own order."""
    user_a = sample_data["user_a"]
    order_a = sample_data["order_a_paid"]
    conv_id = "test_conv_001"

    result = await get_order(
        session=db_session,
        conversation_id=conv_id,
        user_id=user_a.id,
        order_id=order_a.id,
    )

    assert result["success"] is True
    assert result["order"]["id"] == str(order_a.id)
    assert len(result["order"]["items"]) == 1
    assert result["order"]["items"][0]["product_name"] == "Air Jordan 1"

    # Verify audit log in agent_actions
    audit = (
        await db_session.execute(
            select(AgentAction).where(
                AgentAction.conversation_id == conv_id,
                AgentAction.tool_name == "get_order",
            )
        )
    ).scalar_one()
    assert audit.status == AgentActionStatus.SUCCESS
    assert audit.user_id == user_a.id


@pytest.mark.asyncio
async def test_get_order_cross_user_access_blocked(db_session: AsyncSession, sample_data: dict):
    """User Alice must be blocked from accessing Bob's order (IDOR defense)."""
    user_a = sample_data["user_a"]
    order_b = sample_data["order_b_paid"]
    conv_id = "test_conv_cross_user"

    result = await get_order(
        session=db_session,
        conversation_id=conv_id,
        user_id=user_a.id,
        order_id=order_b.id,
    )

    assert result["success"] is False
    assert "not found or access denied" in result["error"].lower()

    # Verify audit log recorded BLOCKED attempt
    audit = (
        await db_session.execute(
            select(AgentAction).where(
                AgentAction.conversation_id == conv_id,
                AgentAction.tool_name == "get_order",
            )
        )
    ).scalar_one()
    assert audit.status == AgentActionStatus.BLOCKED


@pytest.mark.asyncio
async def test_list_user_orders_only_returns_own_orders(db_session: AsyncSession, sample_data: dict):
    """Alice listing orders only receives her 2 orders, Bob's order is excluded."""
    user_a = sample_data["user_a"]
    conv_id = "test_conv_list"

    result = await list_user_orders(
        session=db_session,
        conversation_id=conv_id,
        user_id=user_a.id,
        limit=10,
    )

    assert result["success"] is True
    assert len(result["orders"]) == 2
    for o in result["orders"]:
        assert o["user_id"] == str(user_a.id)


@pytest.mark.asyncio
async def test_get_drop_entry_status(db_session: AsyncSession, sample_data: dict):
    """Alice should see her waitlist rank; Bob (who didn't enter) should get an error."""
    user_a = sample_data["user_a"]
    user_b = sample_data["user_b"]
    drop = sample_data["drop"]

    # Alice's entry
    res_a = await get_drop_entry_status(
        session=db_session,
        conversation_id="conv_drop_a",
        user_id=user_a.id,
        drop_id=drop.id,
    )
    assert res_a["success"] is True
    assert res_a["entry"]["status"] == DropEntryStatus.WAITLISTED
    assert res_a["entry"]["position"] == 5

    # Bob's attempt
    res_b = await get_drop_entry_status(
        session=db_session,
        conversation_id="conv_drop_b",
        user_id=user_b.id,
        drop_id=drop.id,
    )
    assert res_b["success"] is False
    assert "no entry found" in res_b["error"].lower()


# ==============================================================================
# WRITE TOOLS TESTS (Idempotency & Business Rules)
# ==============================================================================


@pytest.mark.asyncio
async def test_issue_refund_success_and_idempotency(db_session: AsyncSession, sample_data: dict):
    """Successful refund issuance and idempotent replay on repeat call."""
    user_a = sample_data["user_a"]
    order_a = sample_data["order_a_paid"]
    conv_id = "test_refund_conv"
    idemp_key = f"refund_test_{uuid.uuid4().hex[:10]}"

    # 1. First execution
    res1 = await issue_refund(
        session=db_session,
        conversation_id=conv_id,
        user_id=user_a.id,
        order_id=order_a.id,
        amount=Decimal("200.00"),
        reason="Defective stitching on shoe collar",
        idempotency_key=idemp_key,
    )
    assert res1["success"] is True
    assert res1["refund"]["amount"] == "200.00"
    assert res1["refund"]["status"] == RefundStatus.PROCESSED

    # 2. Re-executing with the same idempotency key must return the existing refund without double-refunding
    res2 = await issue_refund(
        session=db_session,
        conversation_id=conv_id,
        user_id=user_a.id,
        order_id=order_a.id,
        amount=Decimal("200.00"),
        reason="Defective stitching on shoe collar",
        idempotency_key=idemp_key,
    )
    assert res2["success"] is True
    assert res2.get("idempotent_replay") is True
    assert res2["refund"]["id"] == res1["refund"]["id"]

    # Verify only 1 refund record was created in the database
    refunds = (
        await db_session.execute(
            select(Refund).where(Refund.order_id == order_a.id)
        )
    ).scalars().all()
    assert len(refunds) == 1


@pytest.mark.asyncio
async def test_issue_refund_fails_on_unpaid_order(db_session: AsyncSession, sample_data: dict):
    """Refunds must fail if an order is not in PAID status (e.g., PENDING)."""
    user_a = sample_data["user_a"]
    order_a_pending = sample_data["order_a_pending"]

    res = await issue_refund(
        session=db_session,
        conversation_id="conv_refund_pending",
        user_id=user_a.id,
        order_id=order_a_pending.id,
        amount=Decimal("50.00"),
        reason="Customer changed mind",
        idempotency_key=f"idemp_{uuid.uuid4().hex[:10]}",
    )
    assert res["success"] is False
    assert "only paid orders can be refunded" in res["error"].lower()


@pytest.mark.asyncio
async def test_issue_refund_exceeds_total_amount(db_session: AsyncSession, sample_data: dict):
    """Refund amount cannot exceed the order's total amount."""
    user_a = sample_data["user_a"]
    order_a = sample_data["order_a_paid"]

    res = await issue_refund(
        session=db_session,
        conversation_id="conv_refund_excess",
        user_id=user_a.id,
        order_id=order_a.id,
        amount=Decimal("999.00"),  # Order total is only $200.00
        reason="Requested excess refund",
        idempotency_key=f"idemp_{uuid.uuid4().hex[:10]}",
    )
    assert res["success"] is False
    assert "exceeds remaining refundable balance" in res["error"].lower()


@pytest.mark.asyncio
async def test_cancel_order_success_and_idempotency(db_session: AsyncSession, sample_data: dict):
    """Cancelling an order updates status and supports idempotent replays."""
    user_a = sample_data["user_a"]
    order_pending = sample_data["order_a_pending"]
    idemp_key = f"cancel_{uuid.uuid4().hex[:10]}"

    # First cancellation
    res1 = await cancel_order(
        session=db_session,
        conversation_id="conv_cancel",
        user_id=user_a.id,
        order_id=order_pending.id,
        reason="Ordered incorrect size",
        idempotency_key=idemp_key,
    )
    assert res1["success"] is True
    assert res1["status"] == OrderStatus.CANCELLED

    # Check order status in DB
    refreshed_order = (
        await db_session.execute(
            select(Order).where(Order.id == order_pending.id)
        )
    ).scalar_one()
    assert refreshed_order.status == OrderStatus.CANCELLED

    # Re-executing with the same idempotency key must succeed idempotently
    res2 = await cancel_order(
        session=db_session,
        conversation_id="conv_cancel",
        user_id=user_a.id,
        order_id=order_pending.id,
        reason="Ordered incorrect size",
        idempotency_key=idemp_key,
    )
    assert res2["success"] is True
    assert res2.get("idempotent_replay") is True
