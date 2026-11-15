from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Support & Operations Agent"
    environment: str = "development"
    debug: bool = True
    port: int = 8000

    approval_api_key: str = "dev-approval-secret-key"

    # Default to sqlite+aiosqlite for local testing if DATABASE_URL is not set
    database_url: str = Field(
        default="sqlite+aiosqlite:///./test.db",
        description="Async SQLAlchemy database connection string",
    )

    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    langchain_tracing_v2: str = "false"
    langchain_endpoint: str = "https://api.smith.langchain.com"
    langchain_api_key: Optional[str] = None
    langchain_project: str = "support-operations-agent"


settings = Settings()
