import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import random
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, init_db
from app.models.drop import Drop, DropEntry, DropEntryStatus, DropStatus
from app.models.order import Order, OrderItem, OrderStatus
from app.models.payment import Payment, PaymentStatus
from app.models.refund import Refund, RefundStatus
from app.models.user import User

# Sample streetwear / sneaker catalog
PRODUCTS = [
    ("Air Jordan 1 Retro High OG 'Chicago'", "AJ1-CHI-001", Decimal("180.00")),
    ("Yeezy Boost 350 V2 'Zebra'", "YZY-350-ZEB", Decimal("220.00")),
    ("Nike Dunk Low 'Panda'", "NK-DNK-PND", Decimal("115.00")),
    ("Travis Scott x Air Jordan 1 Low 'Reverse Mocha'", "TS-AJ1-RVM", Decimal("150.00")),
    ("New Balance 990v6 'Grey'", "NB-990-GRY", Decimal("200.00")),
    ("Adidas Samba Classic OG", "AD-SMB-OG", Decimal("100.00")),
    ("Asics Gel-Kayano 14 'Silver'", "ASC-GK14-SLV", Decimal("160.00")),
    ("Supreme Box Logo Hoodie 'Heather Grey'", "SUP-BOGO-HGY", Decimal("168.00")),
    ("Fear of God Essentials Sweatpants", "FOG-ESS-SWP", Decimal("95.00")),
    ("Stussy 8-Ball Mohair Cardigan", "STU-8BL-CRD", Decimal("175.00")),
]

DROP_DATA = [
    {
        "name": "Travis Scott x Air Jordan 1 Low 'Canary'",
        "description": "Exclusive raffle drop for the vibrant canary yellow Travis Scott edition.",
        "status": DropStatus.CLOSED,
        "total_inventory": 50,
        "offset_days": -5,
    },
    {
        "name": "Nike SB Dunk Low 'Verdy Visty'",
        "description": "Furry pastel SB Dunk collaboration with Japanese graphic artist Verdy.",
        "status": DropStatus.ACTIVE,
        "total_inventory": 75,
        "offset_days": 0,
    },
    {
        "name": "Yeezy Boost 700 'Wave Runner' Restock",
        "description": "The quintessential dad shoe returns in its iconic OG colorway.",
        "status": DropStatus.UPCOMING,
        "total_inventory": 100,
        "offset_days": 4,
    },
    {
        "name": "Kith x Asics Gel-Lyte III 'Remastered'",
        "description": "Ronnie Fieg brings back the heritage silhouette with Japanese pigskin suede.",
        "status": DropStatus.UPCOMING,
        "total_inventory": 60,
        "offset_days": 10,
    },
]

FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Sam", "Chris", "Pat", "Dev", "Marcus", "Elena",
    "Sophia", "Lucas", "Liam", "Maya", "Noah", "Olivia", "Ethan", "Aria", "Zoe", "Leo",
    "Gabriel", "Chloe", "Julian", "Hannah", "Ryan", "Emma", "Daniel", "Grace", "Aiden", "Ella",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Desai", "Rodriguez",
    "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
]


async def seed_database(session: AsyncSession, user_count: int = 55, order_count: int = 220) -> dict[str, int]:
    """Populate database with reproducible seed data."""
    random.seed(42)
    now = datetime.now(timezone.utc)

    # 1. Check if already seeded
    existing_users = (await session.execute(select(User))).scalars().first()
    if existing_users:
        print("Database already contains data. Skipping seed.")
        return {"users": 0, "orders": 0, "drops": 0}

    # 2. Create Users
    users: list[User] = []
    used_emails = set()
    for i in range(user_count):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        while email in used_emails:
            email = f"{first.lower()}.{last.lower()}{random.randint(100, 99999)}@example.com"
        used_emails.add(email)

        user = User(
            email=email,
            name=f"{first} {last}",
            is_active=True,
            created_at=now - timedelta(days=random.randint(30, 365)),
        )
        users.append(user)
        session.add(user)

    await session.flush()
    print(f"Created {len(users)} users.")

    # 3. Create Drops
    drops: list[Drop] = []
    for d in DROP_DATA:
        start = now + timedelta(days=d["offset_days"])
        end = start + timedelta(days=2)
        drop = Drop(
            name=d["name"],
            description=d["description"],
            status=d["status"],
            total_inventory=d["total_inventory"],
            start_time=start,
            end_time=end,
            created_at=start - timedelta(days=3),
        )
        drops.append(drop)
        session.add(drop)

    await session.flush()
    print(f"Created {len(drops)} drops.")

    # 4. Create Drop Entries
    entry_count = 0
    for drop in drops:
        # Sample random users entering the drop
        participant_users = random.sample(users, k=min(len(users), random.randint(25, 45)))
        waitlist_rank = 1
        for idx, participant in enumerate(participant_users):
            if drop.status == DropStatus.CLOSED:
                status = DropEntryStatus.WON if idx < 15 else DropEntryStatus.LOST
                position = None
            elif drop.status == DropStatus.ACTIVE:
                status = DropEntryStatus.WAITLISTED
                position = waitlist_rank
                waitlist_rank += 1
            else:  # UPCOMING
                status = DropEntryStatus.WAITLISTED
                position = waitlist_rank
                waitlist_rank += 1

            entry = DropEntry(
                user_id=participant.id,
                drop_id=drop.id,
                status=status,
                position=position,
                created_at=drop.start_time + timedelta(minutes=random.randint(1, 120)),
            )
            session.add(entry)
            entry_count += 1

    await session.flush()
    print(f"Created {entry_count} drop entries.")

    # 5. Create Orders (at least 200 orders across varied statuses)
    statuses_pool = (
        [OrderStatus.PAID] * 50
        + [OrderStatus.PENDING] * 15
        + [OrderStatus.CANCELLED] * 15
        + [OrderStatus.REFUNDED] * 12
        + [OrderStatus.EXPIRED] * 8
    )

    orders: list[Order] = []
    total_items = 0
    total_refunds = 0
    total_payments = 0

    for i in range(order_count):
        user = random.choice(users)
        status = random.choice(statuses_pool)
        order_date = user.created_at + timedelta(days=random.randint(1, 25))
        if order_date > now:
            order_date = now - timedelta(hours=random.randint(1, 72))

        # Select 1 to 3 items
        chosen_products = random.sample(PRODUCTS, k=random.randint(1, 3))
        order_total = Decimal("0.00")
        items_for_order: list[OrderItem] = []

        for prod_name, sku, price in chosen_products:
            qty = random.randint(1, 2)
            item_total = price * qty
            order_total += item_total
            items_for_order.append(
                OrderItem(
                    product_name=prod_name,
                    sku=sku,
                    quantity=qty,
                    price=price,
                    created_at=order_date,
                )
            )

        order = Order(
            user_id=user.id,
            status=status,
            total_amount=order_total,
            currency="USD",
            shipping_address=f"{random.randint(100, 999)} Sneaker St, Cityville, CA {random.randint(90001, 99999)}",
            created_at=order_date,
            updated_at=order_date + timedelta(hours=random.randint(1, 48)),
        )
        session.add(order)
        await session.flush()

        for item in items_for_order:
            item.order_id = order.id
            session.add(item)
            total_items += 1

        orders.append(order)

        # Handle payments and refunds according to status
        if status in (OrderStatus.PAID, OrderStatus.REFUNDED):
            payment = Payment(
                order_id=order.id,
                amount=order_total,
                currency="USD",
                status=PaymentStatus.SUCCESS,
                payment_method=random.choice(["credit_card", "apple_pay", "paypal"]),
                transaction_ref=f"txn_{uuid.uuid4().hex[:16]}",
                created_at=order_date + timedelta(minutes=5),
            )
            session.add(payment)
            total_payments += 1

        if status == OrderStatus.REFUNDED:
            refund = Refund(
                order_id=order.id,
                amount=order_total,
                reason=random.choice([
                    "Customer returned item in original condition within 14 days",
                    "Item was out of stock during fulfillment",
                    "Damaged packaging during transit",
                    "Incorrect shoe size delivered",
                ]),
                status=RefundStatus.PROCESSED,
                idempotency_key=f"idemp_ref_{order.id.hex[:12]}",
                created_at=order.updated_at,
                processed_at=order.updated_at,
            )
            session.add(refund)
            total_refunds += 1

    await session.commit()
    print(
        f"Seeding completed successfully:\n"
        f" - Users: {len(users)}\n"
        f" - Drops: {len(drops)}\n"
        f" - Drop Entries: {entry_count}\n"
        f" - Orders: {len(orders)}\n"
        f" - Order Items: {total_items}\n"
        f" - Payments: {total_payments}\n"
        f" - Refunds: {total_refunds}"
    )
    return {
        "users": len(users),
        "orders": len(orders),
        "drops": len(drops),
        "drop_entries": entry_count,
        "order_items": total_items,
        "refunds": total_refunds,
    }


async def main() -> None:
    await init_db()
    async with async_session_factory() as session:
        await seed_database(session)


if __name__ == "__main__":
    asyncio.run(main())
