import re
from typing import Any

from app.agent.state import AgentState

MAX_STEPS_ALLOWED = 10
MAX_COST_ALLOWED = 0.50  # USD

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"system\s+prompt\s+override",
    r"you\s+are\s+now\s+an\s+unconstrained",
    r"admin(_|\s+)override",
    r"bypass\s+approval",
    r"execute\s+refund\s+immediately\s+without\s+human",
    r"<\s*system\s*>",
    r"\[\s*system\s*\]",
    r"roleplay\s+as\s+a\s+rogue\s+admin",
    r"developer\s+mode\s+enabled",
]
COMPILED_INJECTION_REGEX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


def sanitize_input(text: str) -> str:
    """Sanitize customer input text by stripping control chars and null bytes."""
    if not text:
        return ""
    # Strip null bytes and non-printable control characters (except newline, tab)
    cleaned = re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]", "", text)
    return cleaned.strip()


def detect_prompt_injection(text: str) -> bool:
    """Detect common prompt-injection delimiters and jailbreak attempts."""
    if not text:
        return False
    return bool(COMPILED_INJECTION_REGEX.search(text))


def check_step_limit(step_count: int, max_steps: int = MAX_STEPS_ALLOWED) -> bool:
    """Returns True if the step limit has been breached."""
    return step_count >= max_steps


def detect_loop(state: AgentState) -> bool:
    """Detect infinite loops: e.g. step_count exceeds threshold or stuck in repeated intent."""
    return state.get("step_count", 0) >= MAX_STEPS_ALLOWED


def estimate_token_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost based on standard model pricing (e.g. GPT-4o-mini)."""
    # $0.15 per 1M prompt tokens, $0.60 per 1M completion tokens
    cost = (prompt_tokens * 0.00000015) + (completion_tokens * 0.00000060)
    return round(cost, 6)
