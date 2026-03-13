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


class AnalyseResponse(BaseModel):
    success: bool = True
    data: EnrichedTicket


class WebhookIngest(BaseModel):
    """POST /webhook/{source} — ingest from source system webhook."""

    payload: dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    ollama_reachable: bool
    db_ok: bool
    version: str = "0.1.0"


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: str = ""
