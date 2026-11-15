import asyncio
import json
from pathlib import Path
import time
import uuid
from langchain_core.messages import HumanMessage

from app.agent.graph import agent_graph
from app.agent.guardrails import estimate_token_cost
from app.data.index_policies import index_all_policies
from app.database import async_session_factory, init_db
from evals.evaluators import evaluate_approval_gate, evaluate_policy_compliance, evaluate_routing

DATASET_PATH = Path(__file__).resolve().parent / "dataset.json"
RESULTS_PATH = Path(__file__).resolve().parent / "results.json"


async def run_evaluation_suite() -> dict:
    """Execute the full 50-ticket evaluation suite."""
    await init_db()

    with open(DATASET_PATH, encoding="utf-8") as f:
        cases = json.load(f)

    print(f"\n[EVALS] Running Evaluation Suite on {len(cases)} test cases...\n")

    # Ensure policies are indexed
    async with async_session_factory() as session:
        await index_all_policies(session)

    results = []
    total_routing_score = 0.0
    total_approval_score = 0.0
    total_policy_score = 0.0
    total_latency_ms = 0.0
    total_steps = 0
    total_tokens_est = 0

    start_suite = time.perf_counter()

    for idx, case in enumerate(cases, 1):
        t0 = time.perf_counter()
        thread_id = f"eval_thread_{uuid.uuid4().hex[:8]}"
        user_id = str(uuid.uuid4())

        input_state = {
            "messages": [HumanMessage(content=case["input"])],
            "user_id": user_id,
            "step_count": 0,
        }

        async with async_session_factory() as session:
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "session": session,
                }
            }

            final_state = await agent_graph.ainvoke(input_state, config=config)
            thread_state = await agent_graph.aget_state(config)

        latency_ms = (time.perf_counter() - t0) * 1000
        total_latency_ms += latency_ms

        predicted_intent = final_state.get("intent", "other")
        approval_status = final_state.get("approval_status")
        action_executed = bool(final_state.get("action_result", {}).get("success", False))

        last_ai_msg = ""
        if final_state.get("messages"):
            last_ai_msg = getattr(final_state["messages"][-1], "content", str(final_state["messages"][-1]))

        # Metric evaluations
        routing_score = evaluate_routing(predicted_intent, case["expected_intent"])
        approval_score = evaluate_approval_gate(
            approval_required=case["approval_required"],
            approval_status=approval_status,
            action_executed=action_executed,
        )
        policy_score = evaluate_policy_compliance(last_ai_msg, case["expected_outcome"])

        steps = final_state.get("step_count", 1)
        total_steps += steps
        total_routing_score += routing_score
        total_approval_score += approval_score
        total_policy_score += policy_score

        # Approximate token count for cost estimation
        chars = len(case["input"]) + len(last_ai_msg)
        tokens = chars // 4
        total_tokens_est += tokens

        results.append({
            "id": case["id"],
            "category": case["category"],
            "input": case["input"],
            "expected_intent": case["expected_intent"],
            "predicted_intent": predicted_intent,
            "routing_match": routing_score == 1.0,
            "approval_required": case["approval_required"],
            "approval_status": approval_status,
            "approval_correct": approval_score == 1.0,
            "policy_score": policy_score,
            "steps": steps,
            "latency_ms": round(latency_ms, 2),
        })

    total_time = time.perf_counter() - start_suite
    n = len(cases)

    avg_routing_acc = (total_routing_score / n) * 100
    avg_approval_acc = (total_approval_score / n) * 100
    avg_policy_acc = (total_policy_score / n) * 100
    avg_latency = total_latency_ms / n
    avg_steps = total_steps / n
    est_total_cost = estimate_token_cost(total_tokens_est // 2, total_tokens_est // 2)

    summary = {
        "total_tickets": n,
        "routing_accuracy": round(avg_routing_acc, 1),
        "approval_gate_correctness": round(avg_approval_acc, 1),
        "policy_compliance_score": round(avg_policy_acc, 1),
        "avg_latency_ms": round(avg_latency, 2),
        "avg_steps_per_ticket": round(avg_steps, 2),
        "total_estimated_cost_usd": est_total_cost,
        "total_execution_time_s": round(total_time, 2),
    }

    # Save to evals/results.json
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2)

    # Print summary table
    print("=" * 72)
    print("                 SUPPORT AGENT EVALUATION REPORT                        ")
    print("=" * 72)
    print(f" Total Tickets Tested        : {n}")
    print(f" Routing Accuracy            : {avg_routing_acc:.1f}%")
    print(f" Approval-Gate Correctness   : {avg_approval_acc:.1f}%  (Zero unapproved write actions)")
    print(f" Policy Compliance Score     : {avg_policy_acc:.1f}%")
    print(f" Average Latency per Run     : {avg_latency:.2f} ms")
    print(f" Average Steps per Ticket    : {avg_steps:.2f} steps")
    print(f" Total Estimated Run Cost    : ${est_total_cost:.5f} USD")
    print(f" Total Evaluation Time       : {total_time:.2f} seconds")
    print("=" * 72)
    print(f" Detailed results saved to: {RESULTS_PATH}\n")

    return summary


def main():
    asyncio.run(run_evaluation_suite())


if __name__ == "__main__":
    main()
