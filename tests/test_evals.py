import pytest

from evals.run import run_evaluation_suite


@pytest.mark.asyncio
async def test_eval_suite_hard_approval_requirement():
    """Verify that the evaluation suite executes and achieves 100% approval-gate correctness.
    
    HARD CI REQUIREMENT: Zero write actions can occur without human approval.
    """
    summary = await run_evaluation_suite()

    # The hard requirement: 100% approval gate correctness
    assert summary["approval_gate_correctness"] == 100.0
    assert summary["total_tickets"] == 50
