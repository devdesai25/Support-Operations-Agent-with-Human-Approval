from decimal import Decimal
import uuid
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.config import settings
from app.main import app
from app.models.order import Order, OrderStatus
from app.models.user import User


@pytest.mark.asyncio
async def test_health_check_endpoint():
    """Verify health endpoint returns 200 OK and healthy status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_create_conversation_endpoint():
    """Test POST /conversations creates a new thread."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/conversations")
        assert res.status_code == 201
        data = res.json()
        assert "conversation_id" in data
        assert data["status"] == "active"


@pytest.mark.asyncio
async def test_send_message_and_approval_flow_api(db_session: AsyncSession):
    """Test full conversational message and approval API flow via HTTP."""
    # Override FastAPI DB session dependency with test fixture session
    app.dependency_overrides[get_db_session] = lambda: db_session

    try:
        # 1. Seed user and paid order
        user = User(name="API Test Buyer", email="apibuyer@example.com")
        db_session.add(user)
        await db_session.flush()

        order = Order(user_id=user.id, status=OrderStatus.PAID, total_amount=Decimal("150.00"))
        db_session.add(order)
        await db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 2. Create conversation
            conv_res = await client.post("/conversations")
            conv_id = conv_res.json()["conversation_id"]

            # 3. Send refund message -> Should pause for approval
            msg_res = await client.post(
                f"/conversations/{conv_id}/messages",
                json={
                    "user_id": str(user.id),
                    "message": f"I need a refund for order {order.id}",
                },
            )
            assert msg_res.status_code == 200
            msg_data = msg_res.json()
            assert msg_data["paused_for_approval"] is True

            # 4. Check GET /approvals with API key
            headers = {"X-API-Key": settings.approval_api_key}
            appr_res = await client.get("/approvals", headers=headers)
            assert appr_res.status_code == 200
            assert appr_res.json()["count"] >= 1

            # 5. Submit approval decision: POST /approvals/{id}/decision
            dec_res = await client.post(
                f"/approvals/{conv_id}/decision",
                headers=headers,
                json={"decision": "approve", "notes": "Approved via test suite"},
            )
            assert dec_res.status_code == 200
            dec_data = dec_res.json()
            assert dec_data["success"] is True
            assert dec_data["approval_status"] == "approved"
            assert dec_data["action_result"]["success"] is True
    finally:
        app.dependency_overrides.clear()
