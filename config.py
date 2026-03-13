"""
TicketForge — Configuration
Pydantic-settings based config, reads from environment variables and optional .env file.
"""
from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── API security ──────────────────────────────────────────────────────────
    api_keys: list[str] = Field(
        default=["changeme"],
        description="Comma-separated list of valid API keys (set via API_KEYS env var)",
    )

    # ── Ollama / LLM ──────────────────────────────────────────────────────────
    ollama_base_url: str = Field(
        default="http://ollama:11434",
        description="Base URL of the Ollama service",
    )
    ollama_model: str = Field(
        default="llama3.1:8b",
        description="Ollama model name (e.g. llama3.1:8b, llama3.1:70b-q4, mistral-nemo)",
    )
    ollama_timeout: float = Field(
        default=120.0,
        description="HTTP timeout (seconds) for Ollama requests",
    )
    ollama_max_retries: int = Field(
        default=3,
        description="Number of retry attempts for failed Ollama calls",
    )

    # ── Embeddings ────────────────────────────────────────────────────────────
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="HuggingFace sentence-transformers model for local embeddings",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite+aiosqlite:///./ticketforge.db",
        description="Async SQLite database URL",
    )
    db_ticket_ttl_hours: int = Field(
        default=24,
        description="How many hours to keep processed ticket data before purging",
    )

    # ── Automation detection ──────────────────────────────────────────────────
    dbscan_eps: float = Field(
        default=0.3,
        description="DBSCAN epsilon (neighbourhood distance) for pattern clustering",
    )
    dbscan_min_samples: int = Field(
        default=3,
        description="DBSCAN minimum cluster size",
    )
    automation_lookback_hours: int = Field(
        default=168,
        description="Rolling window (hours) of tickets fed into clustering (default 7 days)",
    )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_per_minute: int = Field(
        default=60,
        description="Max requests per minute per API key",
    )

    # ── ServiceNow connector ──────────────────────────────────────────────────
    servicenow_instance: str = Field(
        default="",
        description="ServiceNow instance hostname, e.g. mycompany.service-now.com",
    )
    servicenow_client_id: str = Field(default="")
    servicenow_client_secret: str = Field(default="")
    servicenow_username: str = Field(default="")
    servicenow_password: str = Field(default="")

    # ── Jira connector ────────────────────────────────────────────────────────
    jira_base_url: str = Field(
        default="",
        description="Jira base URL, e.g. https://mycompany.atlassian.net",
    )
    jira_user_email: str = Field(default="")
    jira_api_token: str = Field(default="")

    # ── Zendesk connector ─────────────────────────────────────────────────────
    zendesk_subdomain: str = Field(
        default="",
        description="Zendesk subdomain, e.g. mycompany (not full URL)",
    )
    zendesk_user_email: str = Field(default="")
    zendesk_api_token: str = Field(default="")

    # ── Outbound webhook ──────────────────────────────────────────────────────
    outbound_webhook_url: str = Field(
        default="",
        description="Optional URL to POST enriched ticket JSON back (Slack, Teams, etc.)",
    )
    outbound_webhook_secret: str = Field(
        default="",
        description="HMAC secret for signing outbound webhook payloads",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    environment: str = Field(default="production")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    @field_validator("api_keys", mode="before")
    @classmethod
    def _parse_api_keys(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return v  # type: ignore[return-value]


# Module-level singleton — import this everywhere
settings = Settings()
