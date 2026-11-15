from typing import Any, Optional
from langchain_core.language_models import BaseChatModel

from app.config import settings


def get_chat_model() -> Optional[BaseChatModel]:
    """Retrieve the configured LLM based on environment variables."""
    if settings.anthropic_api_key:
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model_name="claude-3-5-sonnet-20241022",
                anthropic_api_key=settings.anthropic_api_key,
                temperature=0.0,
            )
        except Exception:
            pass

    if settings.openai_api_key:
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model_name="gpt-4o-mini",
                openai_api_key=settings.openai_api_key,
                temperature=0.0,
            )
        except Exception:
            pass

    return None
