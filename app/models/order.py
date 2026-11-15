import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.payment import Payment
    from app.models.refund import Refund
    from app.models.user import User


class OrderStatus:
    PENDING = "PENDING"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    ALL = (PENDING, PAID, EXPIRED, CANCELLED, REFUNDED)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PAID', 'EXPIRED', 'CANCELLED', 'REFUNDED')",
            name="check_valid_order_status",
        ),
        Index("ix_orders_user_id", "user_id"),
        Index("ix_orders_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.PENDING, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="order",
        cascade="all, delete-orphan",
    )
    refunds: Mapped[list["Refund"]] = relationship(
        "Refund",
        back_populates="order",
        cascade="all, delete-orphan",
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="check_positive_quantity"),
        Index("ix_order_items_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    order: Mapped["Order"] = relationship("Order", back_populates="items")
