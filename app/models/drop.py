import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class DropStatus:
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ALL = (UPCOMING, ACTIVE, CLOSED)


class DropEntryStatus:
    WON = "WON"
    LOST = "LOST"
    WAITLISTED = "WAITLISTED"
    ALL = (WON, LOST, WAITLISTED)


class Drop(Base):
    __tablename__ = "drops"
    __table_args__ = (
        CheckConstraint(
            "status IN ('UPCOMING', 'ACTIVE', 'CLOSED')",
            name="check_valid_drop_status",
        ),
        CheckConstraint("total_inventory >= 0", name="check_non_negative_inventory"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=DropStatus.UPCOMING, nullable=False)
    total_inventory: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    entries: Mapped[list["DropEntry"]] = relationship(
        "DropEntry",
        back_populates="drop",
        cascade="all, delete-orphan",
    )


class DropEntry(Base):
    __tablename__ = "drop_entries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('WON', 'LOST', 'WAITLISTED')",
            name="check_valid_drop_entry_status",
        ),
        UniqueConstraint("user_id", "drop_id", name="uq_user_drop_entry"),
        Index("ix_drop_entries_user_id", "user_id"),
        Index("ix_drop_entries_drop_id", "drop_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    drop_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("drops.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), default=DropEntryStatus.WAITLISTED, nullable=False)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="drop_entries")
    drop: Mapped["Drop"] = relationship("Drop", back_populates="entries")
