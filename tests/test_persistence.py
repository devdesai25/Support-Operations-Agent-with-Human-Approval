from decimal import Decimal
from pathlib import Path
import uuid
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import create_agent_graph
from app.models.order import Order, OrderStatus
from app.models.user import User


@pytest.mark.asyncio
async def test_paused_approval_survives_process_restart(db_session: AsyncSession):
    """PROVE THAT A PAUSED RUN SURVIVES PROCESS RESTART (Milestone 4 requirement).
    
    1. A customer asks for a refund.
    2. The graph gathers facts, proposes action, and pauses at `approval_gate` via `interrupt()`.
    3. The application process is simulated to terminate (graph instance & memory destroyed).
    4. A new process instance boots up connected to the persistent checkpointer.
    5. The thread is resumed with `Command(resume=...)`, and finishes execution successfully!
    """
    checkpoint_file = Path("./test_durable_checkpoint.db")
    if checkpoint_file.exists():
        checkpoint_file.unlink()

    conn_str = "test_durable_checkpoint.db"
    thread_id = f"durable-thread-{uuid.uuid4().hex[:8]}"

    # Setup User and Paid Order in database
    user = User(name="Restart Test User", email="restart@example.com")
    db_session.add(user)
    await db_session.flush()

    order = Order(
        user_id=user.id,
        status=OrderStatus.PAID,
        total_amount=Decimal("175.00"),
    )
    db_session.add(order)
    await db_session.commit()

    # =========================================================================
    # PROCESS 1: Initial execution until interrupt
    # =========================================================================
    async with AsyncSqliteSaver.from_conn_string(conn_str) as checkpointer_1:
        await checkpointer_1.setup()
        graph_process_1 = create_agent_graph(checkpointer=checkpointer_1)

        config_1 = {
            "configurable": {
                "thread_id": thread_id,
                "session": db_session,
            }
        }

        # Customer sends refund request mentioning the order ID
        input_state = {
            "messages": [HumanMessage(content=f"I want a refund for order {order.id}")],
            "user_id": str(user.id),
            "step_count": 0,
        }

        # Run graph in Process 1
        await graph_process_1.ainvoke(input_state, config=config_1)

        # Inspect state before process shutdown
        state_1 = await graph_process_1.aget_state(config_1)
        assert len(state_1.tasks) > 0
        assert any(t.interrupts for t in state_1.tasks)
        assert state_1.values.get("approval_status") == "pending"
        assert state_1.values.get("proposed_action")["order_id"] == str(order.id)

    # =========================================================================
    # SIMULATE COMPLETE PROCESS SHUTDOWN / SERVER RESTART
    # =========================================================================
    del graph_process_1
    del checkpointer_1

    # =========================================================================
    # PROCESS 2: Fresh instance starts up, inspects paused thread, and resumes
    # =========================================================================
    async with AsyncSqliteSaver.from_conn_string(conn_str) as checkpointer_2:
        # Re-attach to the same persistent SQLite checkpointer database
        graph_process_2 = create_agent_graph(checkpointer=checkpointer_2)

        config_2 = {
            "configurable": {
                "thread_id": thread_id,
                "session": db_session,
            }
        }

        # 1. Verify that the new process can see the preserved paused state
        resumed_state = await graph_process_2.aget_state(config_2)
        assert resumed_state is not None
        assert resumed_state.values.get("approval_status") == "pending"
        assert resumed_state.values.get("proposed_action")["order_id"] == str(order.id)
        assert float(resumed_state.values.get("proposed_action")["amount"]) == 175.00

        # 2. Human supervisor sends approval decision via Command(resume=...)
        final_state = await graph_process_2.ainvoke(
            Command(resume={"decision": "approve", "notes": "Approved after restart"}),
            config=config_2,
        )

        # 3. Verify workflow concluded execution with approval & refund creation
        assert final_state["approval_status"] == "approved"
        assert final_state["action_result"]["success"] is True
        assert final_state["action_result"]["refund"]["amount"] == "175.00"

    # Clean up checkpoint file
    if checkpoint_file.exists():
        checkpoint_file.unlink()
