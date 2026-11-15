from decimal import Decimal
from typing import Any, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import agent_graph
from app.api.deps import get_db_session, verify_approval_api_key

router = APIRouter(prefix="/approvals", tags=["Approvals"])

# In-memory tracking of pending threads for the Swagger API
PENDING_APPROVAL_THREADS: set[str] = set()


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "edit"] = Field(
        ...,
        description="Supervisor decision: 'approve' to execute, 'reject' to deny, 'edit' to adjust amount.",
    )
    amount: Optional[Decimal] = Field(None, gt=0, description="Updated refund amount if editing.")
    notes: Optional[str] = Field(None, description="Reasoning or notes from the human reviewer.")


@router.get("", dependencies=[Depends(verify_approval_api_key)])
async def list_approvals(status_filter: str = Query("pending", alias="status")):
    """List threads currently paused at the approval gate awaiting human decision."""
    results = []
    for thread_id in list(PENDING_APPROVAL_THREADS):
        config = {"configurable": {"thread_id": thread_id}}
        state = await agent_graph.aget_state(config)
        if state and state.values.get("approval_status") == "pending":
            interrupts = [t.interrupts for t in state.tasks if t.interrupts]
            results.append({
                "thread_id": thread_id,
                "approval_status": "pending",
                "proposed_action": state.values.get("proposed_action"),
                "interrupt_details": interrupts[0] if interrupts else None,
            })
        else:
            PENDING_APPROVAL_THREADS.discard(thread_id)

    return {"status": status_filter, "count": len(results), "approvals": results}


@router.post("/{thread_id}/decision", dependencies=[Depends(verify_approval_api_key)])
async def submit_approval_decision(
    thread_id: str,
    payload: ApprovalDecisionRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Resume a paused thread by feeding the human supervisor's decision back into LangGraph."""
    config = {"configurable": {"thread_id": thread_id, "session": db}}

    # Check if thread is currently paused
    state = await agent_graph.aget_state(config)
    if not state or not state.tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread '{thread_id}' is not paused or does not exist.",
        )

    # Resume graph execution via Command(resume=...)
    resume_payload = {
        "decision": payload.decision,
        "amount": str(payload.amount) if payload.amount else None,
        "notes": payload.notes,
    }

    try:
        final_state = await agent_graph.ainvoke(
            Command(resume=resume_payload),
            config=config,
        )
        PENDING_APPROVAL_THREADS.discard(thread_id)

        last_ai_msg = ""
        if final_state.get("messages"):
            last_ai_msg = getattr(final_state["messages"][-1], "content", str(final_state["messages"][-1]))

        return {
            "success": True,
            "thread_id": thread_id,
            "decision": payload.decision,
            "approval_status": final_state.get("approval_status"),
            "action_result": final_state.get("action_result"),
            "final_response": last_ai_msg,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume thread: {e!s}",
        )
