import os
from typing import Any, Literal
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.guardrails import check_step_limit
from app.agent.nodes.approval_gate import approval_gate_node
from app.agent.nodes.classify import classify_intent_node
from app.agent.nodes.escalate import escalate_to_human_node
from app.agent.nodes.execute_action import execute_action_node
from app.agent.nodes.read_tools import read_tools_node
from app.agent.nodes.refund_flow import refund_flow_node
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


def route_intent(state: AgentState) -> Literal["read_tools", "refund_flow", "escalate_to_human", "respond"]:
    """Conditional edge router directing workflow based on classified intent and guardrails."""
    # Guardrail check: Max steps
    if check_step_limit(state.get("step_count", 0)):
        return "escalate_to_human"

    intent = state.get("intent", "other")

    if intent in ("order_status", "drop_status", "policy_question"):
        return "read_tools"
    if intent in ("refund_request", "cancellation"):
        return "refund_flow"
    if intent == "escalate":
        return "escalate_to_human"
    return "respond"


def route_after_refund_flow(state: AgentState) -> Literal["approval_gate", "respond"]:
    """Route to approval gate if action proposal is pending, otherwise to respond."""
    if state.get("approval_status") == "pending" and state.get("proposed_action"):
        return "approval_gate"
    return "respond"


def route_after_approval_gate(state: AgentState) -> Literal["execute_action", "respond"]:
    """Only route to execute_action if explicitly approved by supervisor."""
    if state.get("approval_status") == "approved":
        return "execute_action"
    return "respond"


def create_agent_graph(checkpointer: Any = None):
    """Build and compile the complete Human-in-the-Loop LangGraph workflow."""
    workflow = StateGraph(AgentState)

    # 1. Register all discrete nodes
    workflow.add_node("classify_intent", classify_intent_node)
    workflow.add_node("read_tools", read_tools_node)
    workflow.add_node("refund_flow", refund_flow_node)
    workflow.add_node("approval_gate", approval_gate_node)
    workflow.add_node("execute_action", execute_action_node)
    workflow.add_node("respond", respond_node)
    workflow.add_node("escalate_to_human", escalate_to_human_node)

    # 2. Add edges & conditional routing
    workflow.add_edge(START, "classify_intent")

    # Entry conditional edge
    workflow.add_conditional_edges(
        "classify_intent",
        route_intent,
        {
            "read_tools": "read_tools",
            "refund_flow": "refund_flow",
            "escalate_to_human": "escalate_to_human",
            "respond": "respond",
        },
    )

    # Read tools route directly to respond
    workflow.add_edge("read_tools", "respond")

    # Refund flow routes to approval gate (if proposed) or respond (if ineligible)
    workflow.add_conditional_edges(
        "refund_flow",
        route_after_refund_flow,
        {
            "approval_gate": "approval_gate",
            "respond": "respond",
        },
    )

    # Approval gate routes to execute_action (if approved) or respond (if rejected)
    workflow.add_conditional_edges(
        "approval_gate",
        route_after_approval_gate,
        {
            "execute_action": "execute_action",
            "respond": "respond",
        },
    )

    # After execute_action, format final customer response
    workflow.add_edge("execute_action", "respond")

    # Termination edges
    workflow.add_edge("respond", END)
    workflow.add_edge("escalate_to_human", END)

    # MemorySaver by default if no checkpointer provided
    cp = checkpointer if checkpointer is not None else MemorySaver()
    return workflow.compile(checkpointer=cp)


# Singleton compiled graph instance
agent_graph = create_agent_graph()
