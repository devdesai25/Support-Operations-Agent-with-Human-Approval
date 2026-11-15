import time
from typing import Any
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_action import AgentAction, AgentActionStatus


async def record_tool_audit(
    session: AsyncSession,
    conversation_id: str,
    user_id: uuid.UUID | None,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: dict[str, Any] | None,
    status: str,
    start_time: float,
    idempotency_key: str | None = None,
    error_message: str | None = None,
) -> AgentAction:
    """Helper to reliably record an audit entry into `agent_actions`."""
    execution_time_ms = int((time.perf_counter() - start_time) * 1000)

    # Sanitize tool input for serialization if it contains UUID or Decimal
    sanitized_input = {
        k: str(v) if isinstance(v, uuid.UUID) else v
        for k, v in tool_input.items()
    }
    sanitized_output = tool_output if tool_output is not None else None

    action = AgentAction(
        conversation_id=conversation_id,
        user_id=user_id,
        tool_name=tool_name,
        tool_input=sanitized_input,
        tool_output=sanitized_output,
        status=status,
        idempotency_key=idempotency_key,
        error_message=error_message,
        execution_time_ms=execution_time_ms,
    )
    session.add(action)
    await session.commit()
    return action
