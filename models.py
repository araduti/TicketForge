"""
TicketForge — Pydantic models / schemas
All input/output shapes for the API and internal processing pipeline.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Enumerations ──────────────────────────────────────────────────────────────

class TicketSource(str, Enum):
    servicenow = "servicenow"
    jira = "jira"
    zendesk = "zendesk"
    generic = "generic"


class Priority(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class AutomationSuggestionType(str, Enum):
    bot = "bot"
    script = "script"
    form = "form"
    kb_article = "kb_article"
    self_service = "self_service"
    none = "none"


class Role(str, Enum):
    """RBAC roles — higher roles inherit lower permissions."""
    admin = "admin"
    analyst = "analyst"
    viewer = "viewer"


class SLAStatus(str, Enum):
    within = "within"
    at_risk = "at_risk"
    breached = "breached"


class Sentiment(str, Enum):
    """User/customer sentiment detected in the ticket."""
    positive = "positive"
    neutral = "neutral"
    negative = "negative"
    frustrated = "frustrated"


class TicketStatus(str, Enum):
    """Ticket lifecycle status."""
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


# ── Inbound ticket payload ────────────────────────────────────────────────────

class RawTicket(BaseModel):
    """Raw ticket as received from source system or webhook."""

    id: str = Field(..., description="Unique ticket identifier from source system")
    source: TicketSource = Field(default=TicketSource.generic)
    title: str = Field(..., min_length=1, max_length=2000)
    description: str = Field(default="", max_length=20000)
    reporter: str = Field(default="", description="User who created the ticket")
    assignee: str = Field(default="", description="Currently assigned agent/team")
    created_at: datetime = Field(default_factory=_utcnow)
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-system-specific fields passed through unchanged",
    )


# ── Enrichment output ─────────────────────────────────────────────────────────

class CategoryResult(BaseModel):
    category: str = Field(..., description="Top-level ITIL-style category")
    sub_category: str = Field(default="", description="More specific sub-category")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class PriorityResult(BaseModel):
    priority: Priority
    score: int = Field(ge=1, le=100, description="Numeric priority score 1=lowest")
    rationale: str = Field(default="")


class RoutingResult(BaseModel):
    recommended_queue: str = Field(default="")
    recommended_team: str = Field(default="")
    rationale: str = Field(default="")


class AutomationOpportunity(BaseModel):
    score: int = Field(ge=0, le=100, description="Automation opportunity score 0=none,100=perfect")
    suggestion_type: AutomationSuggestionType = Field(default=AutomationSuggestionType.none)
    suggestion: str = Field(default="", description="Concrete one-line fix recommendation")
    pattern_count: int = Field(
        default=0, description="How many similar tickets were found in the rolling window"
    )


class KBArticle(BaseModel):
    title: str
    url: str = Field(default="")
    relevance_score: float = Field(ge=0.0, le=1.0, default=0.0)


class RootCauseHypothesis(BaseModel):
    hypothesis: str = Field(default="")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    included: bool = Field(
        default=False,
        description="True only when confidence >= threshold to avoid hallucination",
    )


class SentimentResult(BaseModel):
    """Sentiment detected in the ticket text."""
    sentiment: Sentiment = Field(default=Sentiment.neutral)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    rationale: str = Field(default="", description="Brief explanation of why this sentiment was detected")


class SLAInfo(BaseModel):
    """SLA status for a ticket based on its priority."""
    response_target_minutes: int = Field(default=0, description="Target response time in minutes")
    resolution_target_minutes: int = Field(default=0, description="Target resolution time in minutes")
    status: SLAStatus = Field(default=SLAStatus.within)
    elapsed_minutes: float = Field(default=0.0, description="Minutes since ticket creation")
    breach_risk: float = Field(ge=0.0, le=1.0, default=0.0, description="Risk ratio: <0.8=within, >=0.8=at_risk, >=1.0=breached")


class EnrichedTicket(BaseModel):
    """Full enrichment result returned to the caller."""

    ticket_id: str
    source: TicketSource
    summary: str = Field(..., description="One-sentence human-readable summary")
    category: CategoryResult
    priority: PriorityResult
    routing: RoutingResult
    automation: AutomationOpportunity
    kb_articles: list[KBArticle] = Field(default_factory=list, max_length=3)
    root_cause: RootCauseHypothesis
    sentiment: SentimentResult = Field(default_factory=SentimentResult, description="Detected user sentiment")
    detected_language: str = Field(default="en", description="ISO 639-1 language code detected in the ticket")
    ticket_status: TicketStatus = Field(default=TicketStatus.open, description="Current ticket lifecycle status")
    sla: SLAInfo = Field(default_factory=SLAInfo, description="SLA tracking information")
    processed_at: datetime = Field(default_factory=_utcnow)
    processing_time_ms: float = Field(default=0.0)


# ── API request / response wrappers ──────────────────────────────────────────

class AnalyseRequest(BaseModel):
    """POST /analyse — analyse a single ticket inline."""

    ticket: RawTicket
    include_automation_detection: bool = Field(
        default=True,
        description="Set false to skip (slower) DBSCAN clustering step",
    )


class BulkAnalyseRequest(BaseModel):
    """POST /analyse/bulk — analyse multiple tickets in a single call."""

    tickets: list[RawTicket] = Field(..., min_length=1, max_length=50)
    include_automation_detection: bool = Field(default=True)


class BulkAnalyseResponse(BaseModel):
    success: bool = True
    data: list[EnrichedTicket]
    total: int
    failed: int = 0


class AnalyseResponse(BaseModel):
    success: bool = True
    data: EnrichedTicket


class WebhookIngest(BaseModel):
    """POST /webhook/{source} — ingest from source system webhook."""

    payload: dict[str, Any]


class TicketStatusUpdate(BaseModel):
    """PATCH /tickets/{id}/status — update ticket lifecycle status."""

    status: TicketStatus


class HealthResponse(BaseModel):
    status: str
    ollama_reachable: bool
    db_ok: bool
    version: str = "0.1.0"


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: str = ""


# ── Analytics models ──────────────────────────────────────────────────────────

class CategoryCount(BaseModel):
    category: str
    count: int


class PriorityCount(BaseModel):
    priority: str
    count: int


class DailyTrend(BaseModel):
    date: str
    count: int


class AnalyticsResponse(BaseModel):
    """GET /analytics — ticket statistics and trends."""
    total_tickets: int = 0
    by_category: list[CategoryCount] = Field(default_factory=list)
    by_priority: list[PriorityCount] = Field(default_factory=list)
    avg_automation_score: float = 0.0
    daily_trend: list[DailyTrend] = Field(default_factory=list)
    period_days: int = 30


# ── Audit log models ─────────────────────────────────────────────────────────

class AuditEntry(BaseModel):
    """Single audit log record."""
    id: int
    timestamp: datetime
    api_key_hash: str = Field(description="SHA-256 prefix of the API key used")
    role: Role
    action: str
    resource: str
    status_code: int
    detail: str = ""


class AuditLogResponse(BaseModel):
    """GET /audit/logs — paginated audit entries."""
    entries: list[AuditEntry]
    total: int
    page: int
    page_size: int


# ── Export models ─────────────────────────────────────────────────────────────

class ExportFormat(str, Enum):
    json = "json"
    csv = "csv"
