import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class AgentActionStatus:
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"
    INTERRUPTED = "INTERRUPTED"
    ALL = (SUCCESS, ERROR, BLOCKED, INTERRUPTED)


class AgentAction(Base):
    __tablename__ = "agent_actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('SUCCESS', 'ERROR', 'BLOCKED', 'INTERRUPTED')",
            name="check_valid_agent_action_status",
        ),
        Index("ix_agent_actions_conversation_id", "conversation_id"),
        Index("ix_agent_actions_user_id", "user_id"),
        Index("ix_agent_actions_tool_name", "tool_name"),
        Index("ix_agent_actions_idempotency_key", "idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    tool_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=AgentActionStatus.SUCCESS, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="agent_actions")
