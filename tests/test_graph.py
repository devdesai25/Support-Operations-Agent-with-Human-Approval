from decimal import Decimal
import uuid
from langchain_core.messages import HumanMessage
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import agent_graph, route_intent
from app.agent.nodes.classify import classify_intent_node, heuristic_classify
from app.data.index_policies import index_all_policies
from app.models.order import Order, OrderStatus
from app.models.user import User


def test_heuristic_classify_intents():
    """Verify deterministic intent classification across all primary intents."""
    c1 = heuristic_classify("Where is my order? When will it arrive?")
    assert c1.intent == "order_status"

    c2 = heuristic_classify("Did I win the Travis Scott sneaker drop raffle?")
    assert c2.intent == "drop_status"

    c3 = heuristic_classify("What is your return policy and return window?")
    assert c3.intent == "policy_question"

    c4 = heuristic_classify("I want a refund for my recent purchase")
    assert c4.intent == "refund_request"

    c5 = heuristic_classify("Please cancel my order immediately")
    assert c5.intent == "cancellation"

    c6 = heuristic_classify("Let me speak to a human representative right now")
    assert c6.intent == "escalate"


def test_route_intent_logic():
    """Verify graph routing branches correctly from classified intent."""
    assert route_intent({"intent": "order_status"}) == "read_tools"
    assert route_intent({"intent": "drop_status"}) == "read_tools"
    assert route_intent({"intent": "policy_question"}) == "read_tools"
    assert route_intent({"intent": "escalate"}) == "escalate_to_human"
    assert route_intent({"intent": "other"}) == "respond"


@pytest.mark.asyncio
async def test_classify_intent_node():
    """Test execution of the classify_intent_node with state update."""
    state = {
        "messages": [HumanMessage(content="Can you check tracking for my order?")],
        "user_id": str(uuid.uuid4()),
        "step_count": 0,
    }
    update = await classify_intent_node(state)
    assert update["intent"] == "order_status"
    assert update["step_count"] == 1


@pytest.mark.asyncio
async def test_graph_end_to_end_order_inquiry(db_session: AsyncSession):
    """End-to-end graph test: User queries order status and receives structured answer."""
    # Seed user and order into DB
    user = User(name="Test Buyer", email="buyer@test.com")
    db_session.add(user)
    await db_session.flush()

    order = Order(
        user_id=user.id,
        status=OrderStatus.PAID,
        total_amount=Decimal("180.00"),
    )
    db_session.add(order)
    await db_session.commit()

    initial_state = {
        "messages": [HumanMessage(content="What orders do I have?")],
        "user_id": str(user.id),
        "step_count": 0,
    }

    final_state = await agent_graph.ainvoke(
        initial_state,
        config={"configurable": {"session": db_session}},
    )

    assert final_state["intent"] == "order_status"
    assert final_state["step_count"] >= 3  # classify -> read_tools -> respond
    assert len(final_state["messages"]) >= 2
    ai_reply = final_state["messages"][-1].content
    assert str(order.id) in ai_reply or "orders" in ai_reply.lower()


@pytest.mark.asyncio
async def test_graph_end_to_end_policy_inquiry(db_session: AsyncSession):
    """End-to-end graph test: User queries policy and receives source-cited answer."""
    await index_all_policies(db_session)

    initial_state = {
        "messages": [HumanMessage(content="How many days do I have for returns?")],
        "user_id": str(uuid.uuid4()),
        "step_count": 0,
    }

    final_state = await agent_graph.ainvoke(
        initial_state,
        config={"configurable": {"session": db_session}},
    )

    assert final_state["intent"] == "policy_question"
    ai_reply = final_state["messages"][-1].content
    # Must include policy content and cite source
    assert "return" in ai_reply.lower()
    assert "return_policy.md" in ai_reply or "source" in ai_reply.lower()


@pytest.mark.asyncio
async def test_graph_end_to_end_escalation():
    """End-to-end graph test: User asks for a human and gets escalated with a ticket."""
    initial_state = {
        "messages": [HumanMessage(content="I demand to talk to a human supervisor!")],
        "user_id": str(uuid.uuid4()),
        "step_count": 0,
    }

    final_state = await agent_graph.ainvoke(initial_state)

    assert final_state["intent"] == "escalate"
    ai_reply = final_state["messages"][-1].content
    assert "Ticket" in ai_reply
    assert "Human Support" in ai_reply or "escalated" in ai_reply
