import os
from typing import Literal
from langgraph.graph import END, START, StateGraph

from app.agent.nodes.classify import classify_intent_node
from app.agent.nodes.escalate import escalate_to_human_node
from app.agent.nodes.read_tools import read_tools_node
from app.agent.nodes.respond import respond_node
from app.agent.state import AgentState
from app.config import settings

# Configure LangSmith Tracing if enabled
if settings.langchain_tracing_v2.lower() == "true":
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    if settings.langchain_api_key:
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key


def route_intent(state: AgentState) -> Literal["read_tools", "escalate_to_human", "respond"]:
    """Conditional edge router directing workflow based on classified intent."""
    intent = state.get("intent", "other")

    if intent in ("order_status", "drop_status", "policy_question"):
        return "read_tools"
    if intent == "escalate":
        return "escalate_to_human"
    return "respond"


def create_agent_graph():
    """Build and compile the foundational LangGraph stateful workflow."""
    workflow = StateGraph(AgentState)

    # 1. Add discrete nodes
    workflow.add_node("classify_intent", classify_intent_node)
    workflow.add_node("read_tools", read_tools_node)
    workflow.add_node("respond", respond_node)
    workflow.add_node("escalate_to_human", escalate_to_human_node)

    # 2. Add edges
    workflow.add_edge(START, "classify_intent")

    # Conditional routing edge from classify_intent
    workflow.add_conditional_edges(
        "classify_intent",
        route_intent,
        {
            "read_tools": "read_tools",
            "escalate_to_human": "escalate_to_human",
            "respond": "respond",
        },
    )

    # Read tools feed directly into respond
    workflow.add_edge("read_tools", "respond")

    # Final nodes terminate at END
    workflow.add_edge("respond", END)
    workflow.add_edge("escalate_to_human", END)

    return workflow.compile()


# Singleton compiled graph instance
agent_graph = create_agent_graph()
