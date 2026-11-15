import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.policy_rag import search_policies
from app.data.index_policies import index_all_policies
from app.models.agent_action import AgentAction, AgentActionStatus
from app.models.policy import PolicyChunk


@pytest.mark.asyncio
async def test_policy_indexing_and_search(db_session: AsyncSession):
    """Verify that policies are properly indexed and searchable with sources returned."""
    # 1. Index policies
    total_indexed = await index_all_policies(db_session)
    assert total_indexed >= 8

    # Check database rows
    chunks = (await db_session.execute(select(PolicyChunk))).scalars().all()
    assert len(chunks) == total_indexed

    # 2. Search for return policy
    res_return = await search_policies(
        session=db_session,
        conversation_id="conv_rag_001",
        user_id=None,
        query="What is the return window for unworn sneakers?",
        limit=3,
    )

    assert res_return["success"] is True
    assert len(res_return["results"]) > 0
    # Must include source document
    top_result = res_return["results"][0]
    assert "source" in top_result
    assert "return_policy.md" in [r["source"] for r in res_return["results"]]

    # 3. Search for raffle drop waitlist policy
    res_raffle = await search_policies(
        session=db_session,
        conversation_id="conv_rag_002",
        user_id=None,
        query="How does the raffle drop waitlist queue work?",
        limit=2,
    )
    assert res_raffle["success"] is True
    assert any("raffle_and_drops.md" in r["source"] for r in res_raffle["results"])

    # 4. Search for damaged goods policy
    res_damaged = await search_policies(
        session=db_session,
        conversation_id="conv_rag_003",
        user_id=None,
        query="Received defective shoes with torn stitching",
        limit=2,
    )
    assert res_damaged["success"] is True
    assert any("damaged_or_defective.md" in r["source"] for r in res_damaged["results"])

    # 5. Verify audit logging
    audit = (
        await db_session.execute(
            select(AgentAction).where(
                AgentAction.conversation_id == "conv_rag_001",
                AgentAction.tool_name == "search_policies",
            )
        )
    ).scalar_one()
    assert audit.status == AgentActionStatus.SUCCESS
