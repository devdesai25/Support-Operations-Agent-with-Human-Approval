from decimal import Decimal
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.seed import seed_database
from app.models.drop import Drop, DropEntry, DropEntryStatus, DropStatus
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User


@pytest.mark.asyncio
async def test_seed_creates_minimum_users_and_orders(db_session: AsyncSession):
    """Verify that seed creates at least 50 users and 200 orders with varied statuses."""
    counts = await seed_database(db_session, user_count=50, order_count=200)

    assert counts["users"] >= 50
    assert counts["orders"] >= 200

    # Verify varied statuses exist in database
    statuses_result = await db_session.execute(select(Order.status).distinct())
    statuses = {row[0] for row in statuses_result.all()}

    assert OrderStatus.PAID in statuses
    assert OrderStatus.PENDING in statuses
    assert OrderStatus.CANCELLED in statuses
    assert OrderStatus.REFUNDED in statuses
    assert OrderStatus.EXPIRED in statuses


@pytest.mark.asyncio
async def test_user_cascade_delete(db_session: AsyncSession):
    """Deleting a user should cascade delete their orders."""
    user = User(name="Test User", email="test.cascade@example.com")
    db_session.add(user)
    await db_session.flush()

    order = Order(
        user_id=user.id,
        status=OrderStatus.PENDING,
        total_amount=Decimal("150.00"),
    )
    db_session.add(order)
    await db_session.commit()

    # Delete user
    await db_session.delete(user)
    await db_session.commit()

    # Order should no longer exist
    check_order = (await db_session.execute(select(Order).where(Order.id == order.id))).scalar_one_or_none()
    assert check_order is None


@pytest.mark.asyncio
async def test_drop_entry_unique_per_user_and_drop(db_session: AsyncSession):
    """A user cannot have multiple entries for the same drop."""
    from datetime import datetime, timezone

    user = User(name="Raffle User", email="raffle@example.com")
    db_session.add(user)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    drop = Drop(
        name="Exclusive Drop",
        status=DropStatus.ACTIVE,
        total_inventory=10,
        start_time=now,
        end_time=now,
    )
    db_session.add(drop)
    await db_session.flush()

    entry1 = DropEntry(
        user_id=user.id,
        drop_id=drop.id,
        status=DropEntryStatus.WAITLISTED,
        position=1,
    )
    db_session.add(entry1)
    await db_session.commit()

    # Second entry for same user and drop should fail unique constraint
    entry2 = DropEntry(
        user_id=user.id,
        drop_id=drop.id,
        status=DropEntryStatus.WAITLISTED,
        position=2,
    )
    db_session.add(entry2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
