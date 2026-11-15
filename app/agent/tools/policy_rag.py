import time
from typing import Any
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.audit import record_tool_audit
from app.data.index_policies import compute_deterministic_embedding, cosine_similarity
from app.models.agent_action import AgentActionStatus
from app.models.policy import PolicyChunk


async def search_policies(
    session: AsyncSession,
    conversation_id: str,
    user_id: uuid.UUID | None,
    query: str,
    limit: int = 3,
) -> dict[str, Any]:
    """Search operational and shop policy documents.
    
    Matches customer inquiries (e.g. return windows, cancellations, drop rules,
    damaged item protocols) against policy chunks.
    
    CRITICAL REQUIREMENT: Returns source document filenames (`source`) with each result.
    """
    start_time = time.perf_counter()
    tool_input = {"query": query, "limit": limit}

    try:
        # 1. Fetch policy chunks
        stmt = select(PolicyChunk)
        result = await session.execute(stmt)
        chunks = result.scalars().all()

        if not chunks:
            error_msg = "No policy documents currently indexed."
            await record_tool_audit(
                session=session,
                conversation_id=conversation_id,
                user_id=user_id,
                tool_name="search_policies",
                tool_input=tool_input,
                tool_output=None,
                status=AgentActionStatus.ERROR,
                start_time=start_time,
                error_message=error_msg,
            )
            return {"success": False, "error": error_msg, "results": []}

        # 2. Score chunks using embedding similarity
        query_vec = compute_deterministic_embedding(query)
        scored_results = []

        for chunk in chunks:
            chunk_vec = chunk.metadata_json.get("embedding", [])
            score = cosine_similarity(query_vec, chunk_vec) if chunk_vec else 0.0
            scored_results.append({
                "title": chunk.title,
                "source": chunk.doc_name,
                "section": chunk.metadata_json.get("section", ""),
                "content": chunk.content,
                "score": round(score, 4),
            })

        # Sort descending by relevance score
        scored_results.sort(key=lambda x: x["score"], reverse=True)
        top_results = scored_results[:limit]

        output = {
            "success": True,
            "query": query,
            "results": top_results,
        }

        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="search_policies",
            tool_input=tool_input,
            tool_output={"count": len(top_results), "top_source": top_results[0]["source"] if top_results else None},
            status=AgentActionStatus.SUCCESS,
            start_time=start_time,
        )
        return output

    except Exception as e:
        error_msg = f"Failed to search policies: {e!s}"
        await record_tool_audit(
            session=session,
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="search_policies",
            tool_input=tool_input,
            tool_output=None,
            status=AgentActionStatus.ERROR,
            start_time=start_time,
            error_message=error_msg,
        )
        return {"success": False, "error": error_msg, "results": []}
