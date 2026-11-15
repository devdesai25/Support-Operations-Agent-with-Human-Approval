import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.order import Order


class PaymentStatus:
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ALL = (PENDING, SUCCESS, FAILED)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'SUCCESS', 'FAILED')",
            name="check_valid_payment_status",
        ),
        Index("ix_payments_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=PaymentStatus.PENDING, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    transaction_ref: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    order: Mapped["Order"] = relationship("Order", back_populates="payments")
