import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import DateTime, Index, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PolicyChunk(Base):
    __tablename__ = "policy_chunks"
    __table_args__ = (
        Index("ix_policy_chunks_doc_name", "doc_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    doc_name: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
