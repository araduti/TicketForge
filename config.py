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
    api_key_roles: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "JSON mapping of API key to role (admin/analyst/viewer). "
            "Keys not listed default to 'analyst'. Set via API_KEY_ROLES env var."
        ),
    )

    # ── SLA targets (minutes) ─────────────────────────────────────────────────
    sla_response_critical: int = Field(default=15, description="Response SLA for critical (minutes)")
    sla_response_high: int = Field(default=60, description="Response SLA for high (minutes)")
    sla_response_medium: int = Field(default=240, description="Response SLA for medium (minutes)")
    sla_response_low: int = Field(default=480, description="Response SLA for low (minutes)")
    sla_resolution_critical: int = Field(default=240, description="Resolution SLA for critical (minutes)")
    sla_resolution_high: int = Field(default=480, description="Resolution SLA for high (minutes)")
    sla_resolution_medium: int = Field(default=1440, description="Resolution SLA for medium (minutes)")
    sla_resolution_low: int = Field(default=2880, description="Resolution SLA for low (minutes)")

    # ── Ollama / LLM ──────────────────────────────────────────────────────────
    llm_provider: str = Field(
        default="ollama",
        description="LLM provider: 'ollama' (local) or 'openai' (OpenAI-compatible API)",
    )
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
        description="HTTP timeout (seconds) for LLM requests",
    )
    ollama_max_retries: int = Field(
        default=3,
        description="Number of retry attempts for failed LLM calls",
    )

    # ── OpenAI-compatible provider ────────────────────────────────────────────
    openai_api_key: str = Field(
        default="",
        description="API key for OpenAI-compatible provider (leave empty for keyless endpoints like vLLM)",
    )
    openai_base_url: str = Field(
        default="https://api.openai.com",
        description="Base URL for OpenAI-compatible API (e.g. https://api.openai.com, http://localhost:8080)",
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="Model name for OpenAI-compatible provider",
    )

    # ── Embeddings ────────────────────────────────────────────────────────────
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="HuggingFace sentence-transformers model for local embeddings",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite+aiosqlite:///./ticketforge.db",
        description="Database URL. Supports SQLite (sqlite+aiosqlite:///./file.db) "
        "or PostgreSQL (postgresql://user:pass@host:5432/dbname)",
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
    llm_description_max_chars: int = Field(
        default=3000,
        description=(
            "Maximum characters of ticket description sent to the LLM. "
            "Increase if critical info is routinely truncated (increases token usage)."
        ),
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

    # ── Slack / Teams notifications ───────────────────────────────────────────
    slack_webhook_url: str = Field(
        default="",
        description="Slack incoming webhook URL for ticket notifications",
    )
    teams_webhook_url: str = Field(
        default="",
        description="Microsoft Teams incoming webhook URL for ticket notifications",
    )
    notification_min_priority: str = Field(
        default="high",
        description="Minimum priority level to trigger Slack/Teams notifications (critical, high, medium, low)",
    )
    notify_on_sla_breach: bool = Field(
        default=True,
        description="Send notification when a ticket SLA is breached or at risk",
    )

    # ── Email ingestion ───────────────────────────────────────────────────────
    email_ingestion_enabled: bool = Field(
        default=False,
        description="Enable the POST /ingest/email endpoint",
    )
    email_default_priority: str = Field(
        default="medium",
        description="Default priority for tickets created from emails",
    )

    # ── Chatbot ───────────────────────────────────────────────────────────────
    chatbot_enabled: bool = Field(
        default=True,
        description="Enable the POST /chat chatbot endpoint",
    )
    chatbot_max_history: int = Field(
        default=20,
        description="Maximum conversation messages kept per session",
    )

    # ── Self-service portal ───────────────────────────────────────────────────
    portal_enabled: bool = Field(
        default=True,
        description="Enable the GET /portal self-service endpoint",
    )

    # ── Model monitoring ──────────────────────────────────────────────────────
    monitoring_enabled: bool = Field(
        default=True,
        description="Enable the GET /monitoring/drift endpoint",
    )
    monitoring_baseline_days: int = Field(
        default=30,
        description="Baseline period in days for drift comparison",
    )
    monitoring_window_days: int = Field(
        default=7,
        description="Recent monitoring window in days",
    )
    drift_threshold: float = Field(
        default=0.3,
        description="Drift score threshold (0.0-1.0) above which a field is flagged as drifting",
    )

    # ── CSAT surveys ─────────────────────────────────────────────────────────
    csat_enabled: bool = Field(
        default=True,
        description="Enable CSAT (Customer Satisfaction) survey endpoints",
    )

    # ── WebSocket notifications ───────────────────────────────────────────────
    websocket_notifications_enabled: bool = Field(
        default=True,
        description="Enable the /ws/notifications WebSocket endpoint for real-time events",
    )

    # ── Internationalisation (i18n) ───────────────────────────────────────────
    i18n_enabled: bool = Field(
        default=True,
        description="Enable multi-language prompt templates and localised responses",
    )
    i18n_default_language: str = Field(
        default="en",
        description="Default language (ISO 639-1) when no language is detected",
    )

    # ── Multi-agent architecture ──────────────────────────────────────────────
    multi_agent_enabled: bool = Field(
        default=False,
        description="Enable multi-agent pipeline (Analyser → Classifier → Validator) instead of single LLM call",
    )

    # ── Vector store ──────────────────────────────────────────────────────────
    vector_store_backend: str = Field(
        default="in_memory",
        description="Vector store backend: 'in_memory' (default) or 'persistent' (SQLite-backed)",
    )

    # ── Auto-resolution ──────────────────────────────────────────────────────
    auto_resolution_enabled: bool = Field(
        default=False,
        description="Enable AI-powered auto-resolution endpoint POST /tickets/{id}/auto-resolve",
    )
    auto_resolution_confidence_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum confidence (0.0-1.0) for auto-resolution to proceed",
    )

    # ── Outbound webhook events (Zapier / Make / n8n) ────────────────────────
    webhook_events_enabled: bool = Field(
        default=False,
        description="Enable structured webhook event delivery for integration with Zapier/Make/n8n",
    )

    # ── PagerDuty escalation ─────────────────────────────────────────────────
    pagerduty_routing_key: str = Field(
        default="",
        description="PagerDuty Events API v2 routing key (integration key)",
    )
    pagerduty_auto_escalate: bool = Field(
        default=False,
        description="Automatically create PagerDuty incidents for critical tickets or SLA breaches",
    )

    # ── OpsGenie escalation ──────────────────────────────────────────────────
    opsgenie_api_key: str = Field(
        default="",
        description="OpsGenie Alert API key",
    )
    opsgenie_auto_escalate: bool = Field(
        default=False,
        description="Automatically create OpsGenie alerts for critical tickets or SLA breaches",
    )

    # ── Scheduled reports ────────────────────────────────────────────────────
    scheduled_reports_enabled: bool = Field(
        default=False,
        description="Enable scheduled analytics reports (POST/GET/DELETE /reports/schedules)",
    )

    # ── Ticket merging ────────────────────────────────────────────────────────
    ticket_merging_enabled: bool = Field(
        default=False,
        description="Enable ticket merging endpoint (POST /tickets/merge)",
    )

    # ── Custom fields ─────────────────────────────────────────────────────────
    custom_fields_enabled: bool = Field(
        default=False,
        description="Enable custom field definitions (POST/GET /custom-fields)",
    )

    # ── Ticket tags ───────────────────────────────────────────────────────────
    ticket_tags_enabled: bool = Field(
        default=False,
        description="Enable ticket tagging (POST/DELETE/GET /tickets/{id}/tags)",
    )

    # ── Saved filters ─────────────────────────────────────────────────────────
    saved_filters_enabled: bool = Field(
        default=False,
        description="Enable saved ticket filters (POST/GET/DELETE /filters)",
    )

    # ── Phase 8: SLA breach prediction ──────────────────────────────────────────
    sla_prediction_enabled: bool = Field(
        default=False,
        description="Enable SLA breach prediction analytics (GET /analytics/sla-predictions)",
    )

    # ── Phase 8: Response templates ─────────────────────────────────────────────
    response_templates_enabled: bool = Field(
        default=False,
        description="Enable response templates (POST/GET/DELETE /response-templates)",
    )

    # ── Phase 8: Ticket timeline ───────────────────────────────────────────────
    ticket_timeline_enabled: bool = Field(
        default=False,
        description="Enable ticket activity timeline (GET /tickets/{id}/activity, POST /tickets/{id}/comments)",
    )

    # ── Phase 8: Bulk operations ───────────────────────────────────────────────
    bulk_operations_enabled: bool = Field(
        default=False,
        description="Enable bulk ticket operations (POST /tickets/bulk/status, POST /tickets/bulk/tags)",
    )

    # ── Phase 8: Skill-based routing ───────────────────────────────────────────
    skill_routing_enabled: bool = Field(
        default=False,
        description="Enable agent skill-based routing (POST/GET /agent-skills, GET /tickets/{id}/recommended-agents)",
    )

    # ── Phase 9: Automation rules ──────────────────────────────────────────────
    automation_rules_enabled: bool = Field(
        default=False,
        description="Enable workflow automation rules (POST/GET/DELETE /automation-rules)",
    )

    # ── Phase 9: Approval workflows ────────────────────────────────────────────
    approval_workflows_enabled: bool = Field(
        default=False,
        description="Enable ticket approval workflows (POST /tickets/{id}/approval-request, POST /tickets/{id}/approve)",
    )

    # ── Phase 9: Agent collision detection ─────────────────────────────────────
    collision_detection_enabled: bool = Field(
        default=False,
        description="Enable agent collision detection (POST/DELETE/GET /tickets/{id}/lock)",
    )

    # ── Phase 9: Contact management ────────────────────────────────────────────
    contact_management_enabled: bool = Field(
        default=False,
        description="Enable customer contact management (POST/GET /contacts, GET /contacts/{id}/tickets)",
    )

    # ── Phase 9: Macros ────────────────────────────────────────────────────────
    macros_enabled: bool = Field(
        default=False,
        description="Enable macros for common ticket operations (POST/GET/DELETE /macros, POST /macros/{id}/execute)",
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

    @field_validator("api_key_roles", mode="before")
    @classmethod
    def _parse_api_key_roles(cls, v: object) -> dict[str, str]:
        if isinstance(v, str):
            import json  # noqa: PLC0415
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v  # type: ignore[return-value]


# Module-level singleton — import this everywhere
settings = Settings()
