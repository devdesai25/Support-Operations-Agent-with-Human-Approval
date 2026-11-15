from typing import Any
import uuid
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agent.state import AgentState
from app.agent.tools.policy_rag import search_policies
from app.agent.tools.read_tools import get_drop_entry_status, get_order, list_user_orders
from app.database import async_session_factory


async def _execute_read_tools(session, state: AgentState) -> dict[str, Any]:
    intent = state.get("intent", "other")
    entities = state.get("extracted_entities") or {}
    conversation_id = str(state.get("conversation_id", "default_thread"))
    user_uuid = uuid.UUID(state["user_id"])

    # 1. Order Status
    if intent == "order_status":
        order_id_str = entities.get("order_id")
        if order_id_str:
            try:
                order_uuid = uuid.UUID(order_id_str)
                res = await get_order(session, conversation_id, user_uuid, order_uuid)
                return {
                    "order_context": res,
                    "step_count": state.get("step_count", 0) + 1,
                }
            except ValueError:
                pass

        # Fall back to listing the user's recent orders
        res = await list_user_orders(session, conversation_id, user_uuid, limit=5)
        return {
            "order_context": res,
            "step_count": state.get("step_count", 0) + 1,
        }

    # 2. Drop Entry Status
    if intent == "drop_status":
        drop_id_str = entities.get("drop_id")
        if drop_id_str:
            try:
                drop_uuid = uuid.UUID(drop_id_str)
                res = await get_drop_entry_status(session, conversation_id, user_uuid, drop_uuid)
                return {
                    "order_context": res,
                    "step_count": state.get("step_count", 0) + 1,
                }
            except ValueError:
                pass

        return {
            "order_context": {
                "success": False,
                "error": "Please provide a valid drop ID to check your entry status.",
            },
            "step_count": state.get("step_count", 0) + 1,
        }

    # 3. Policy Question (Milestone 3)
    if intent == "policy_question":
        query = entities.get("query")
        if not query:
            messages = state.get("messages", [])
            query = next(
                (m.content for m in reversed(messages) if isinstance(m, HumanMessage)),
                "store policy",
            )

        res = await search_policies(session, conversation_id, user_uuid, str(query), limit=3)
        return {
            "order_context": res,
            "step_count": state.get("step_count", 0) + 1,
        }

    return {
        "order_context": {},
        "step_count": state.get("step_count", 0) + 1,
    }


async def read_tools_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Single read-only node executing read tools based on classified intent and entities."""
    user_id_str = state.get("user_id")
    if not user_id_str:
        return {
            "order_context": {"error": "Missing authenticated user context."},
            "step_count": state.get("step_count", 0) + 1,
        }

    try:
        uuid.UUID(user_id_str)
    except ValueError:
        return {
            "order_context": {"error": f"Invalid user_id UUID: {user_id_str}"},
            "step_count": state.get("step_count", 0) + 1,
        }

    # Check if a session was supplied via LangGraph config
    configurable = config.get("configurable", {}) if config else {}
    custom_session = configurable.get("session")

    if custom_session is not None:
        return await _execute_read_tools(custom_session, state)

    async with async_session_factory() as session:
        return await _execute_read_tools(session, state)
