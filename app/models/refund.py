import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.order import Order


class RefundStatus:
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PROCESSED = "PROCESSED"
    ALL = (PENDING_APPROVAL, APPROVED, REJECTED, PROCESSED)


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint("amount > 0", name="check_positive_refund_amount"),
        CheckConstraint(
            "status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'PROCESSED')",
            name="check_valid_refund_status",
        ),
        Index("ix_refunds_order_id", "order_id"),
        Index("ix_refunds_idempotency_key", "idempotency_key", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=RefundStatus.PENDING_APPROVAL, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    order: Mapped["Order"] = relationship("Order", back_populates="refunds")
