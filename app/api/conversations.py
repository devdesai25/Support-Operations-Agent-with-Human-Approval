import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import agent_graph
from app.agent.guardrails import detect_prompt_injection, sanitize_input
from app.api.approvals import PENDING_APPROVAL_THREADS
from app.api.deps import get_db_session

router = APIRouter(prefix="/conversations", tags=["Conversations"])


class CreateConversationResponse(BaseModel):
    conversation_id: str
    status: str = "active"


class MessageRequest(BaseModel):
    user_id: str = Field(..., description="UUID of the authenticated customer.")
    message: str = Field(..., min_length=1, max_length=2000, description="Customer message text.")


@router.post("", response_model=CreateConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation():
    """Start a new customer support conversation thread."""
    conv_id = f"thread_{uuid.uuid4().hex}"
    return CreateConversationResponse(conversation_id=conv_id)


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    payload: MessageRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Send a customer message to the support agent."""
    # 1. Guardrail input sanitization (Milestone 5)
    cleaned_text = sanitize_input(payload.message)

    # 2. Configure LangGraph thread and dependency-injected session
    config = {
        "configurable": {
            "thread_id": conversation_id,
            "session": db,
        }
    }

    input_state = {
        "messages": [HumanMessage(content=cleaned_text)],
        "user_id": payload.user_id,
        "conversation_id": conversation_id,
        "step_count": 0,
    }

    # 3. Invoke graph
    try:
        current_state = await agent_graph.ainvoke(input_state, config=config)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution error: {e!s}",
        )

    # 4. Check if thread paused for human approval
    thread_state = await agent_graph.aget_state(config)
    is_paused = bool(thread_state and thread_state.tasks and any(t.interrupts for t in thread_state.tasks))

    if is_paused:
        PENDING_APPROVAL_THREADS.add(conversation_id)
        interrupt_data = thread_state.tasks[0].interrupts[0] if thread_state.tasks[0].interrupts else {}
        return {
            "conversation_id": conversation_id,
            "paused_for_approval": True,
            "message": "Your request involves financial or account changes and has been submitted to a human supervisor for approval.",
            "approval_details": interrupt_data,
        }

    # Regular completion
    last_msg = ""
    if current_state.get("messages"):
        last_msg = getattr(current_state["messages"][-1], "content", str(current_state["messages"][-1]))

    return {
        "conversation_id": conversation_id,
        "paused_for_approval": False,
        "response": last_msg,
        "intent": current_state.get("intent"),
    }
