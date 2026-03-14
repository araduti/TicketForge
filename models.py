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


# ── Response suggestion models ────────────────────────────────────────────────

class SuggestResponseRequest(BaseModel):
    """POST /suggest-response — generate a draft agent response for a ticket."""

    ticket_id: str = Field(..., description="ID of a previously analysed ticket")
    additional_context: str = Field(default="", description="Optional extra context for the response")


class SuggestedResponse(BaseModel):
    """AI-generated draft response for an agent."""

    ticket_id: str
    subject: str = Field(default="", description="Email-style subject line")
    body: str = Field(default="", description="Response message body")
    tone: str = Field(default="professional", description="Detected tone: empathetic, professional, urgent, informational")
    suggested_actions: list[str] = Field(default_factory=list, description="Recommended next steps")


class SuggestResponseResponse(BaseModel):
    success: bool = True
    data: SuggestedResponse


# ── Duplicate detection models ────────────────────────────────────────────────

class DuplicateCandidate(BaseModel):
    """A ticket that may be a duplicate of the query ticket."""

    ticket_id: str
    title: str = Field(default="")
    similarity_score: float = Field(ge=0.0, le=1.0, description="Cosine similarity 0.0-1.0")


class DetectDuplicatesRequest(BaseModel):
    """POST /tickets/detect-duplicates — find similar tickets."""

    ticket_id: str = Field(default="", description="ID of an existing ticket to find duplicates for")
    title: str = Field(default="", description="Title text to search for duplicates (if ticket_id not provided)")
    description: str = Field(default="", description="Description text to search for duplicates")
    threshold: float = Field(default=0.75, ge=0.0, le=1.0, description="Minimum similarity score to consider a duplicate")
    max_results: int = Field(default=5, ge=1, le=20, description="Maximum number of duplicate candidates to return")


class DetectDuplicatesResponse(BaseModel):
    success: bool = True
    query_ticket_id: str = Field(default="", description="The ticket ID being checked")
    duplicates: list[DuplicateCandidate] = Field(default_factory=list)
    total_candidates: int = 0


# ── Knowledge base models ────────────────────────────────────────────────────

class KBArticleCreate(BaseModel):
    """POST /kb/articles — create a new knowledge base article."""

    title: str = Field(..., min_length=1, max_length=500, description="Article title")
    content: str = Field(..., min_length=1, max_length=50000, description="Article body (Markdown supported)")
    category: str = Field(default="general", max_length=200, description="Article category for organisation")
    tags: list[str] = Field(default_factory=list, description="Searchable tags")


class KBArticleUpdate(BaseModel):
    """PUT /kb/articles/{id} — update an existing knowledge base article."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=50000)
    category: str | None = Field(default=None, max_length=200)
    tags: list[str] | None = Field(default=None)


class KBArticleRecord(BaseModel):
    """Knowledge base article as stored in the database."""

    id: str = Field(..., description="Unique article identifier")
    title: str
    content: str
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class KBArticleResponse(BaseModel):
    success: bool = True
    data: KBArticleRecord


class KBArticleListResponse(BaseModel):
    success: bool = True
    data: list[KBArticleRecord] = Field(default_factory=list)
    total: int = 0


class KBSearchRequest(BaseModel):
    """POST /kb/search — semantic search over knowledge base articles."""

    query: str = Field(..., min_length=1, max_length=2000, description="Search query text")
    max_results: int = Field(default=5, ge=1, le=20, description="Maximum results to return")
    threshold: float = Field(default=0.3, ge=0.0, le=1.0, description="Minimum similarity score")


class KBSearchResult(BaseModel):
    """A knowledge base article matched by semantic search."""

    article_id: str
    title: str
    category: str = ""
    relevance_score: float = Field(ge=0.0, le=1.0, description="Cosine similarity 0.0-1.0")
    snippet: str = Field(default="", description="Content preview (first 200 chars)")


class KBSearchResponse(BaseModel):
    success: bool = True
    query: str = ""
    results: list[KBSearchResult] = Field(default_factory=list)
    total: int = 0


# ── Email ingestion models ───────────────────────────────────────────────────

class EmailIngestRequest(BaseModel):
    """POST /ingest/email — ingest a ticket from an email webhook (SendGrid, Mailgun, generic)."""

    sender: str = Field(..., min_length=1, description="Sender email address")
    subject: str = Field(default="", max_length=2000, description="Email subject line")
    body_plain: str = Field(default="", max_length=50000, description="Plain-text email body")
    body_html: str = Field(default="", max_length=100000, description="HTML email body (fallback)")
    recipient: str = Field(default="", description="Recipient/to email address")
    message_id: str = Field(default="", description="Email Message-ID header")
    in_reply_to: str = Field(default="", description="In-Reply-To header for threading")
    timestamp: datetime = Field(default_factory=_utcnow, description="Email received timestamp")
    headers: dict[str, str] = Field(default_factory=dict, description="Additional email headers")


# ── Chatbot models ───────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    """A single message in a chatbot conversation."""

    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., min_length=1, max_length=5000, description="Message content")
    timestamp: datetime = Field(default_factory=_utcnow)


class ChatRequest(BaseModel):
    """POST /chat — send a message to the TicketForge chatbot."""

    session_id: str = Field(default="", description="Session ID for multi-turn conversations (auto-generated if empty)")
    message: str = Field(..., min_length=1, max_length=5000, description="User message")
    context: dict[str, Any] = Field(default_factory=dict, description="Optional context (e.g. ticket_id for status lookup)")


class ChatResponse(BaseModel):
    """Response from the chatbot."""

    success: bool = True
    session_id: str = Field(..., description="Session ID for continuing the conversation")
    reply: str = Field(..., description="Assistant response message")
    intent: str = Field(default="general", description="Detected intent: create_ticket, check_status, search_kb, general")
    suggested_actions: list[str] = Field(default_factory=list, description="Suggested follow-up actions")
    data: dict[str, Any] = Field(default_factory=dict, description="Structured data returned (e.g. ticket info, KB results)")


# ── Model monitoring models ──────────────────────────────────────────────────

class DriftMetric(BaseModel):
    """A single drift metric for a prediction field."""

    field: str = Field(..., description="Field being monitored (e.g. 'category', 'priority', 'sentiment')")
    current_distribution: dict[str, float] = Field(default_factory=dict, description="Current distribution percentages")
    baseline_distribution: dict[str, float] = Field(default_factory=dict, description="Baseline distribution percentages")
    drift_score: float = Field(ge=0.0, le=1.0, default=0.0, description="Drift score 0.0=identical, 1.0=completely different")
    is_drifting: bool = Field(default=False, description="True if drift exceeds threshold")


class MonitoringResponse(BaseModel):
    """GET /monitoring/drift — model prediction drift analysis."""

    success: bool = True
    metrics: list[DriftMetric] = Field(default_factory=list)
    total_tickets_analysed: int = 0
    baseline_period_days: int = Field(default=30, description="Baseline comparison period")
    monitoring_period_days: int = Field(default=7, description="Recent period being monitored")
    overall_health: str = Field(default="healthy", description="Overall model health: healthy, warning, degraded")


# ── Plugin system models ─────────────────────────────────────────────────────

class PluginInfo(BaseModel):
    """Metadata about a registered plugin."""

    name: str = Field(..., description="Unique plugin name")
    version: str = Field(default="0.1.0", description="Plugin version")
    description: str = Field(default="", description="Human-readable description")
    hook: str = Field(..., description="Hook point: pre_analysis, post_analysis, custom_enrichment")
    enabled: bool = Field(default=True, description="Whether the plugin is active")


class PluginListResponse(BaseModel):
    """GET /plugins — list registered plugins."""

    success: bool = True
    plugins: list[PluginInfo] = Field(default_factory=list)
    total: int = 0


# ── Self-service portal models ───────────────────────────────────────────────

class PortalTicketSubmission(BaseModel):
    """POST /portal/tickets — submit a ticket from the self-service portal."""

    title: str = Field(..., min_length=1, max_length=2000, description="Issue title")
    description: str = Field(default="", max_length=20000, description="Detailed issue description")
    reporter_email: str = Field(..., min_length=1, description="Reporter email address")
    category: str = Field(default="", description="Optional category hint from the user")


class PortalTicketResponse(BaseModel):
    """Response after submitting a ticket through the portal."""

    success: bool = True
    ticket_id: str = Field(..., description="Assigned ticket ID")
    message: str = Field(default="Your ticket has been submitted successfully.", description="Confirmation message")
    suggested_articles: list[KBSearchResult] = Field(default_factory=list, description="Relevant KB articles that may help")


# ── CSAT (Customer Satisfaction) models ──────────────────────────────────────

class CSATSubmission(BaseModel):
    """POST /tickets/{ticket_id}/csat — submit a customer satisfaction rating."""

    rating: int = Field(..., ge=1, le=5, description="Satisfaction rating 1 (very dissatisfied) to 5 (very satisfied)")
    comment: str = Field(default="", max_length=2000, description="Optional free-text feedback")
    reporter_email: str = Field(default="", description="Email of the person submitting the rating")


class CSATRecord(BaseModel):
    """A stored CSAT rating record."""

    id: int = Field(..., description="Unique rating record ID")
    ticket_id: str = Field(..., description="Ticket this rating belongs to")
    rating: int = Field(ge=1, le=5, description="Satisfaction rating 1-5")
    comment: str = Field(default="")
    reporter_email: str = Field(default="")
    submitted_at: datetime = Field(default_factory=_utcnow)


class CSATResponse(BaseModel):
    """Response for a single CSAT rating lookup."""

    success: bool = True
    data: CSATRecord | None = Field(default=None, description="CSAT rating record, or null if none submitted")


class CSATAnalyticsResponse(BaseModel):
    """GET /analytics/csat — aggregate CSAT statistics."""

    success: bool = True
    total_ratings: int = Field(default=0, description="Total number of CSAT ratings collected")
    average_rating: float = Field(default=0.0, description="Mean satisfaction score (1.0-5.0)")
    rating_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Count of ratings per score level (1-5)",
    )
    recent_comments: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Most recent feedback comments with ticket IDs",
    )


# ── WebSocket notification models ────────────────────────────────────────────

class WebSocketEvent(BaseModel):
    """Real-time event broadcast via WebSocket."""

    event_type: str = Field(..., description="Event type: ticket_created, status_changed, sla_breach")
    ticket_id: str = Field(default="", description="Related ticket ID")
    data: dict[str, Any] = Field(default_factory=dict, description="Event-specific payload")
    timestamp: datetime = Field(default_factory=_utcnow)


# ── Multi-agent architecture models ─────────────────────────────────────────

class AgentStepResult(BaseModel):
    """Result from a single agent in the multi-agent pipeline."""

    agent: str = Field(..., description="Agent name: analyser, classifier, validator")
    output: dict[str, Any] = Field(default_factory=dict, description="Raw agent output")


class MultiAgentResult(BaseModel):
    """Metadata about a multi-agent pipeline execution."""

    enabled: bool = Field(default=False, description="Whether multi-agent was used for this ticket")
    agent_count: int = Field(default=0, description="Number of agents in the pipeline")
    validated: bool = Field(default=False, description="Whether the validator approved the result")
    corrections: list[str] = Field(default_factory=list, description="Corrections made by the validator")


class MultiAgentStatusResponse(BaseModel):
    """GET /multi-agent/status — current multi-agent configuration."""

    success: bool = True
    enabled: bool = Field(default=False)
    agents: list[str] = Field(default_factory=list, description="Agents in the pipeline")
    description: str = Field(default="", description="Pipeline description")


# ── Vector store models ──────────────────────────────────────────────────────

class VectorStoreStatusResponse(BaseModel):
    """GET /vector-store/status — current vector store status."""

    success: bool = True
    backend: str = Field(default="in_memory", description="Active backend: in_memory or persistent")
    total_vectors: int = Field(default=0, description="Number of stored vectors")


# ── Auto-resolution models ───────────────────────────────────────────────────

class AutoResolveRequest(BaseModel):
    """POST /tickets/{ticket_id}/auto-resolve — attempt AI-powered auto-resolution."""

    additional_context: str = Field(default="", max_length=5000, description="Optional extra context for resolution")


class AutoResolveResult(BaseModel):
    """Result of an AI auto-resolution attempt."""

    ticket_id: str = Field(..., description="Ticket that was auto-resolved")
    resolved: bool = Field(default=False, description="Whether the ticket was successfully auto-resolved")
    resolution_summary: str = Field(default="", description="Summary of the resolution applied")
    matched_kb_articles: list[KBSearchResult] = Field(default_factory=list, description="KB articles used for resolution")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0, description="Confidence in the auto-resolution")
    response_draft: str = Field(default="", description="Draft response sent to the ticket reporter")


class AutoResolveResponse(BaseModel):
    success: bool = True
    data: AutoResolveResult


# ── Webhook event models (Zapier / Make / n8n) ──────────────────────────────

class WebhookEventType(str, Enum):
    """Event types for outbound structured webhook events."""
    ticket_created = "ticket.created"
    ticket_updated = "ticket.updated"
    ticket_resolved = "ticket.resolved"
    ticket_auto_resolved = "ticket.auto_resolved"
    sla_breach = "sla.breach"
    csat_submitted = "csat.submitted"


class OutboundWebhookEvent(BaseModel):
    """Structured event sent to outbound webhook endpoints (Zapier/Make/n8n compatible)."""

    event: WebhookEventType = Field(..., description="Event type identifier")
    ticket_id: str = Field(default="", description="Related ticket ID")
    timestamp: datetime = Field(default_factory=_utcnow)
    payload: dict[str, Any] = Field(default_factory=dict, description="Event-specific data")


class WebhookEventListResponse(BaseModel):
    """GET /webhooks/events — list supported webhook event types."""

    success: bool = True
    supported_events: list[str] = Field(default_factory=list, description="Supported event type strings")
    webhook_url_configured: bool = Field(default=False, description="Whether an outbound webhook URL is set")


# ── PagerDuty / OpsGenie escalation models ───────────────────────────────────

class EscalationResult(BaseModel):
    """Result of an escalation to PagerDuty or OpsGenie."""

    provider: str = Field(..., description="Escalation provider: pagerduty or opsgenie")
    incident_key: str = Field(default="", description="Unique incident/alert key")
    status: str = Field(default="", description="Escalation status: created, deduplicated, error")
    message: str = Field(default="", description="Human-readable status message")


class EscalationStatusResponse(BaseModel):
    """GET /escalation/status — escalation integration status."""

    success: bool = True
    pagerduty_configured: bool = Field(default=False, description="Whether PagerDuty is configured")
    opsgenie_configured: bool = Field(default=False, description="Whether OpsGenie is configured")
    auto_escalate_enabled: bool = Field(default=False, description="Whether auto-escalation on SLA breach is enabled")

