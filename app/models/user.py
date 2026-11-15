import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.agent_action import AgentAction
    from app.models.drop import DropEntry
    from app.models.order import Order


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    orders: Mapped[list["Order"]] = relationship(
        "Order",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    drop_entries: Mapped[list["DropEntry"]] = relationship(
        "DropEntry",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    agent_actions: Mapped[list["AgentAction"]] = relationship(
        "AgentAction",
        back_populates="user",
    )
