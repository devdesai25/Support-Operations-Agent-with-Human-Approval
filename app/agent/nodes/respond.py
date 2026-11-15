from typing import Any
from langchain_core.messages import AIMessage

from app.agent.llm import get_chat_model
from app.agent.state import AgentState


def generate_deterministic_reply(intent: str, order_context: dict[str, Any]) -> str:
    """Generate structured response when LLM is unavailable."""
    if not order_context:
        return "Hello! How can I assist you with your orders, sneaker drops, or store policies today?"

    if not order_context.get("success", False) and "error" in order_context:
        return f"I couldn't complete that request: {order_context['error']}"

    if intent == "order_status":
        if "order" in order_context:
            o = order_context["order"]
            items_str = ", ".join(f"{it['product_name']} (x{it['quantity']})" for it in o.get("items", []))
            return (
                f"Order **{o['id']}** is currently **{o['status']}**.\n"
                f"Total: ${o['total_amount']} {o['currency']}\n"
                f"Items: {items_str or 'None'}"
            )
        if "orders" in order_context:
            orders = order_context["orders"]
            if not orders:
                return "You do not have any orders on file."
            lines = [f"- Order `{o['id']}`: Status **{o['status']}** (${o['total_amount']})" for o in orders]
            return "Here are your recent orders:\n" + "\n".join(lines)

    if intent == "drop_status":
        entry = order_context.get("entry", {})
        status = entry.get("status", "UNKNOWN")
        pos = entry.get("position")
        pos_str = f" at position #{pos}" if pos else ""
        return f"Your entry status for this drop is **{status}**{pos_str}."

    if intent == "policy_question":
        results = order_context.get("results", [])
        if not results:
            return "I could not find a specific policy matching your query. Please contact support for more details."
        top = results[0]
        sources = ", ".join(dict.fromkeys(r["source"] for r in results))
        all_content = "\n\n".join(r["content"] for r in results[:2])
        return (
            f"**{top['title']}**\n\n"
            f"{all_content}\n\n"
            f"*Source: {sources}*"
        )

    if intent in ("refund_request", "cancellation"):
        action_res = order_context.get("refund") or order_context
        if action_res.get("success") or "refund" in order_context or order_context.get("status") == "CANCELLED":
            if intent == "refund_request":
                amt = order_context.get("refund", {}).get("amount", "")
                return f"Good news! Your refund request has been approved and processed ({f'Amount: ${amt}' if amt else 'Processed'}). Funds will reflect in 3-5 business days."
            return "Your order has been successfully cancelled per your approved request."
        elif order_context.get("error"):
            return f"Your request could not be processed: {order_context['error']}"

        return (
            f"I have received your request regarding **{intent.replace('_', ' ')}**. "
            "A proposal has been prepared and is pending supervisor approval."
        )

    return "Thank you for reaching out. Let me know if you need any additional help!"


async def respond_node(state: AgentState) -> dict[str, Any]:
    """Generate final response to customer."""
    intent = state.get("intent", "other")
    order_context = state.get("order_context") or {}

    llm = get_chat_model()
    if llm:
        try:
            messages = state.get("messages", [])
            system_prompt = (
                "You are an expert customer operations agent for a sneaker and streetwear boutique. "
                "Answer the customer's question politely, concisely, and accurately based ONLY on the "
                "following context:\n"
                f"Intent: {intent}\n"
                f"Context Data: {order_context}\n"
                "If policy questions were asked, cite the source policy file."
            )
            response = await llm.ainvoke([
                {"role": "system", "content": system_prompt},
                *messages,
            ])
            ai_msg = response if isinstance(response, AIMessage) else AIMessage(content=str(response.content))
            return {
                "messages": [ai_msg],
                "step_count": state.get("step_count", 0) + 1,
            }
        except Exception:
            pass

    reply_text = generate_deterministic_reply(intent, order_context)
    return {
        "messages": [AIMessage(content=reply_text)],
        "step_count": state.get("step_count", 0) + 1,
    }
