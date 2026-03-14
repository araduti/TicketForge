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


# ── Phase 7: Scheduled reports ───────────────────────────────────────────────

class ReportFrequency(str, Enum):
    """Frequency options for scheduled analytics reports."""
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class ScheduledReportCreate(BaseModel):
    """POST /reports/schedules — create a new scheduled report."""
    name: str = Field(..., min_length=1, max_length=200, description="Human-readable report name")
    frequency: ReportFrequency = Field(..., description="How often the report should be generated")
    webhook_url: str = Field(..., min_length=1, max_length=2000, description="URL to deliver report payload")
    include_categories: bool = Field(default=True, description="Include category breakdown")
    include_priorities: bool = Field(default=True, description="Include priority breakdown")
    include_sla: bool = Field(default=True, description="Include SLA summary")
    include_csat: bool = Field(default=True, description="Include CSAT summary")
    enabled: bool = Field(default=True, description="Whether the schedule is active")


class ScheduledReportRecord(BaseModel):
    """Stored scheduled report configuration."""
    id: str = Field(..., description="Unique schedule ID")
    name: str = Field(..., description="Report name")
    frequency: ReportFrequency
    webhook_url: str = Field(..., description="Delivery webhook URL")
    include_categories: bool = Field(default=True)
    include_priorities: bool = Field(default=True)
    include_sla: bool = Field(default=True)
    include_csat: bool = Field(default=True)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)


class ScheduledReportResponse(BaseModel):
    success: bool = True
    data: ScheduledReportRecord


class ScheduledReportListResponse(BaseModel):
    success: bool = True
    schedules: list[ScheduledReportRecord] = Field(default_factory=list)


# ── Phase 7: Ticket merging ─────────────────────────────────────────────────

class TicketMergeRequest(BaseModel):
    """POST /tickets/merge — merge duplicate tickets."""
    primary_ticket_id: str = Field(..., description="Ticket to keep as the canonical record")
    duplicate_ticket_ids: list[str] = Field(..., min_length=1, max_length=50, description="Tickets to merge into the primary")


class MergedTicketRecord(BaseModel):
    """Record of a ticket merge operation."""
    primary_ticket_id: str
    merged_ticket_ids: list[str] = Field(default_factory=list)
    merged_at: datetime = Field(default_factory=_utcnow)
    merged_by: str = Field(default="", description="API key hash of the user who merged")


class TicketMergeResponse(BaseModel):
    success: bool = True
    data: MergedTicketRecord


# ── Phase 7: Custom fields ──────────────────────────────────────────────────

class CustomFieldType(str, Enum):
    """Supported custom field value types."""
    text = "text"
    number = "number"
    boolean = "boolean"
    select = "select"


class CustomFieldDefinition(BaseModel):
    """POST /custom-fields — define a new custom field."""
    name: str = Field(..., min_length=1, max_length=100, description="Field name (unique identifier)")
    field_type: CustomFieldType = Field(..., description="Data type of the field")
    description: str = Field(default="", max_length=500)
    required: bool = Field(default=False, description="Whether the field is required on new tickets")
    options: list[str] = Field(default_factory=list, description="Options for 'select' type fields")


class CustomFieldRecord(BaseModel):
    """Stored custom field definition."""
    id: str = Field(..., description="Unique field ID")
    name: str
    field_type: CustomFieldType
    description: str = Field(default="")
    required: bool = Field(default=False)
    options: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class CustomFieldResponse(BaseModel):
    success: bool = True
    data: CustomFieldRecord


class CustomFieldListResponse(BaseModel):
    success: bool = True
    fields: list[CustomFieldRecord] = Field(default_factory=list)


# ── Phase 7: Ticket tags ────────────────────────────────────────────────────

class TicketTagRequest(BaseModel):
    """POST /tickets/{id}/tags — add tags to a ticket."""
    tags: list[str] = Field(..., min_length=1, max_length=20, description="Tags to add")


class TicketTagsResponse(BaseModel):
    success: bool = True
    ticket_id: str = Field(default="")
    tags: list[str] = Field(default_factory=list)


# ── Phase 7: Saved filters ──────────────────────────────────────────────────

class SavedFilterCreate(BaseModel):
    """POST /filters — create a named ticket filter."""
    name: str = Field(..., min_length=1, max_length=200, description="Filter name")
    filter_criteria: dict[str, Any] = Field(
        ...,
        description="Filter criteria: category, priority, status, tags, date_from, date_to",
    )


class SavedFilterRecord(BaseModel):
    """Stored saved filter."""
    id: str = Field(..., description="Unique filter ID")
    name: str
    filter_criteria: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    created_by: str = Field(default="", description="API key hash of the creator")


class SavedFilterResponse(BaseModel):
    success: bool = True
    data: SavedFilterRecord


class SavedFilterListResponse(BaseModel):
    success: bool = True
    filters: list[SavedFilterRecord] = Field(default_factory=list)


# ── Phase 8: SLA breach prediction ──────────────────────────────────────────


class SLAPrediction(BaseModel):
    """A single ticket's SLA breach prediction."""

    ticket_id: str = Field(..., description="Ticket ID")
    category: str = Field(default="", description="Ticket category")
    priority: str = Field(default="", description="Ticket priority")
    current_age_hours: float = Field(default=0.0, description="Hours since ticket creation")
    sla_target_hours: float = Field(default=0.0, description="SLA target in hours")
    predicted_breach_probability: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Probability of SLA breach (0.0-1.0)",
    )
    estimated_resolution_hours: float = Field(default=0.0, description="Estimated hours to resolve")
    risk_level: str = Field(default="low", description="Risk level: low, medium, high, critical")


class SLAPredictionResponse(BaseModel):
    """Response for SLA breach prediction analytics."""

    success: bool = True
    predictions: list[SLAPrediction] = Field(default_factory=list)
    total_open_tickets: int = Field(default=0)
    high_risk_count: int = Field(default=0)
    generated_at: datetime = Field(default_factory=_utcnow)


# ── Phase 8: Response templates ─────────────────────────────────────────────


class ResponseTemplateCreate(BaseModel):
    """POST /response-templates — create a response template."""

    name: str = Field(..., min_length=1, max_length=200, description="Template name")
    category: str = Field(..., min_length=1, max_length=100, description="Ticket category this template applies to")
    content: str = Field(..., min_length=1, max_length=5000, description="Template content text")
    language: str = Field(default="en", max_length=10, description="Template language code")
    tags: list[str] = Field(default_factory=list, description="Optional tags for filtering")


class ResponseTemplateRecord(BaseModel):
    """Stored response template record."""

    id: str = Field(..., description="Unique template ID")
    name: str
    category: str
    content: str
    language: str = Field(default="en")
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class ResponseTemplateResponse(BaseModel):
    success: bool = True
    data: ResponseTemplateRecord


class ResponseTemplateListResponse(BaseModel):
    success: bool = True
    templates: list[ResponseTemplateRecord] = Field(default_factory=list)


# ── Phase 8: Ticket activity timeline ───────────────────────────────────────


class ActivityType(str, Enum):
    """Types of ticket activity events."""

    comment = "comment"
    status_change = "status_change"
    tag_added = "tag_added"
    tag_removed = "tag_removed"
    merged = "merged"
    assigned = "assigned"
    created = "created"


class TicketCommentCreate(BaseModel):
    """POST /tickets/{id}/comments — add an internal comment."""

    content: str = Field(..., min_length=1, max_length=5000, description="Comment text")
    is_internal: bool = Field(default=True, description="Whether this is an internal-only comment")


class TicketActivityRecord(BaseModel):
    """A single activity entry in the ticket timeline."""

    id: str = Field(..., description="Unique activity ID")
    ticket_id: str = Field(default="")
    activity_type: ActivityType
    content: str = Field(default="", description="Activity description or comment text")
    performed_by: str = Field(default="", description="API key hash of the actor")
    created_at: datetime = Field(default_factory=_utcnow)


class TicketActivityResponse(BaseModel):
    success: bool = True
    ticket_id: str = Field(default="")
    activities: list[TicketActivityRecord] = Field(default_factory=list)


class TicketCommentResponse(BaseModel):
    success: bool = True
    data: TicketActivityRecord


# ── Phase 8: Bulk operations ───────────────────────────────────────────────


class BulkStatusUpdate(BaseModel):
    """POST /tickets/bulk/status — update status for multiple tickets."""

    ticket_ids: list[str] = Field(..., min_length=1, max_length=100, description="List of ticket IDs")
    status: TicketStatus = Field(..., description="New status to apply")


class BulkTagUpdate(BaseModel):
    """POST /tickets/bulk/tags — add tags to multiple tickets."""

    ticket_ids: list[str] = Field(..., min_length=1, max_length=100, description="List of ticket IDs")
    tags: list[str] = Field(..., min_length=1, max_length=20, description="Tags to add")


class BulkOperationResult(BaseModel):
    """Result for a single ticket in a bulk operation."""

    ticket_id: str
    success: bool = True
    detail: str = Field(default="")


class BulkOperationResponse(BaseModel):
    success: bool = True
    total: int = Field(default=0)
    succeeded: int = Field(default=0)
    failed: int = Field(default=0)
    results: list[BulkOperationResult] = Field(default_factory=list)


# ── Phase 8: Agent skill-based routing ──────────────────────────────────────


class AgentSkillCreate(BaseModel):
    """POST /agent-skills — register an agent with skills."""

    agent_id: str = Field(..., min_length=1, max_length=100, description="Unique agent identifier")
    name: str = Field(..., min_length=1, max_length=200, description="Agent display name")
    categories: list[str] = Field(default_factory=list, description="Categories the agent specialises in")
    priorities: list[str] = Field(default_factory=list, description="Priority levels the agent handles")
    languages: list[str] = Field(default_factory=list, description="Languages the agent supports")
    max_concurrent_tickets: int = Field(default=10, ge=1, le=100, description="Maximum concurrent tickets")


class AgentSkillRecord(BaseModel):
    """Stored agent skill record."""

    id: str = Field(..., description="Unique record ID")
    agent_id: str
    name: str
    categories: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    max_concurrent_tickets: int = Field(default=10)
    created_at: datetime = Field(default_factory=_utcnow)


class AgentSkillResponse(BaseModel):
    success: bool = True
    data: AgentSkillRecord


class AgentSkillListResponse(BaseModel):
    success: bool = True
    agents: list[AgentSkillRecord] = Field(default_factory=list)


class AgentRecommendation(BaseModel):
    """An agent recommendation for a ticket."""

    agent_id: str
    name: str
    match_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Skill match score")
    matching_skills: list[str] = Field(default_factory=list, description="Skills that matched")


class AgentRecommendationResponse(BaseModel):
    success: bool = True
    ticket_id: str = Field(default="")
    recommendations: list[AgentRecommendation] = Field(default_factory=list)


# ── Phase 9: Automation rules ────────────────────────────────────────────────

class AutomationRuleCondition(BaseModel):
    """A single condition in an automation rule."""

    field: str = Field(..., description="Ticket field to evaluate (e.g. priority, category, sentiment)")
    operator: str = Field(..., description="Comparison operator (equals, not_equals, contains, in)")
    value: str = Field(..., description="Value to compare against")


class AutomationRuleAction(BaseModel):
    """An action to perform when rule conditions are met."""

    action_type: str = Field(..., description="Action type (set_priority, set_status, add_tag, notify_slack, escalate_pagerduty)")
    parameters: dict[str, str] = Field(default_factory=dict, description="Action parameters")


class AutomationRuleCreate(BaseModel):
    """POST /automation-rules — create a workflow automation rule."""

    name: str = Field(..., min_length=1, max_length=200, description="Rule name")
    description: str = Field(default="", max_length=1000, description="Rule description")
    conditions: list[AutomationRuleCondition] = Field(..., min_length=1, description="Conditions (all must match)")
    actions: list[AutomationRuleAction] = Field(..., min_length=1, description="Actions to execute when conditions match")
    enabled: bool = Field(default=True, description="Whether the rule is active")


class AutomationRuleRecord(BaseModel):
    """Stored automation rule record."""

    id: str = Field(..., description="Unique rule ID")
    name: str
    description: str = ""
    conditions: list[AutomationRuleCondition] = Field(default_factory=list)
    actions: list[AutomationRuleAction] = Field(default_factory=list)
    enabled: bool = True
    created_at: datetime = Field(default_factory=_utcnow)


class AutomationRuleResponse(BaseModel):
    success: bool = True
    data: AutomationRuleRecord


class AutomationRuleListResponse(BaseModel):
    success: bool = True
    rules: list[AutomationRuleRecord] = Field(default_factory=list)


# ── Phase 9: Approval workflows ──────────────────────────────────────────────

class ApprovalStatus(str, Enum):
    """Status of an approval request."""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ApprovalRequestCreate(BaseModel):
    """POST /tickets/{id}/approval-request — request approval for a ticket."""

    approver: str = Field(..., min_length=1, max_length=200, description="Approver identifier")
    reason: str = Field(default="", max_length=2000, description="Reason for the approval request")


class ApprovalDecision(BaseModel):
    """POST /tickets/{id}/approve — approve or reject a ticket."""

    decision: ApprovalStatus = Field(..., description="Approval decision (approved or rejected)")
    comment: str = Field(default="", max_length=2000, description="Decision comment")


class ApprovalRecord(BaseModel):
    """Stored approval record."""

    id: str = Field(..., description="Unique approval ID")
    ticket_id: str
    approver: str
    reason: str = ""
    status: ApprovalStatus = ApprovalStatus.pending
    decision_comment: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    decided_at: datetime | None = None


class ApprovalResponse(BaseModel):
    success: bool = True
    data: ApprovalRecord


class ApprovalListResponse(BaseModel):
    success: bool = True
    approvals: list[ApprovalRecord] = Field(default_factory=list)


# ── Phase 9: Agent collision detection ────────────────────────────────────────

class TicketLockCreate(BaseModel):
    """POST /tickets/{id}/lock — lock a ticket for exclusive editing."""

    agent_id: str = Field(..., min_length=1, max_length=200, description="Agent acquiring the lock")


class TicketLockRecord(BaseModel):
    """Stored ticket lock record."""

    id: str = Field(..., description="Unique lock ID")
    ticket_id: str
    agent_id: str
    acquired_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime = Field(default_factory=_utcnow)


class TicketLockResponse(BaseModel):
    success: bool = True
    data: TicketLockRecord | None = None
    locked: bool = False


# ── Phase 9: Contact management ──────────────────────────────────────────────

class ContactCreate(BaseModel):
    """POST /contacts — register a customer contact."""

    email: str = Field(..., min_length=1, max_length=300, description="Contact email address")
    name: str = Field(..., min_length=1, max_length=200, description="Contact display name")
    organisation: str = Field(default="", max_length=200, description="Organisation name")
    phone: str = Field(default="", max_length=50, description="Phone number")
    notes: str = Field(default="", max_length=2000, description="Internal notes about the contact")


class ContactRecord(BaseModel):
    """Stored contact record."""

    id: str = Field(..., description="Unique contact ID")
    email: str
    name: str
    organisation: str = ""
    phone: str = ""
    notes: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class ContactResponse(BaseModel):
    success: bool = True
    data: ContactRecord


class ContactListResponse(BaseModel):
    success: bool = True
    contacts: list[ContactRecord] = Field(default_factory=list)


class ContactTicketsResponse(BaseModel):
    success: bool = True
    contact_id: str = Field(default="")
    ticket_ids: list[str] = Field(default_factory=list)


# ── Phase 9: Macros ───────────────────────────────────────────────────────────

class MacroAction(BaseModel):
    """A single action within a macro."""

    action_type: str = Field(..., description="Action type (set_status, set_priority, add_tag, remove_tag, add_comment)")
    parameters: dict[str, str] = Field(default_factory=dict, description="Action parameters")


class MacroCreate(BaseModel):
    """POST /macros — create a reusable macro."""

    name: str = Field(..., min_length=1, max_length=200, description="Macro name")
    description: str = Field(default="", max_length=1000, description="Macro description")
    actions: list[MacroAction] = Field(..., min_length=1, description="Actions to perform")


class MacroRecord(BaseModel):
    """Stored macro record."""

    id: str = Field(..., description="Unique macro ID")
    name: str
    description: str = ""
    actions: list[MacroAction] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class MacroResponse(BaseModel):
    success: bool = True
    data: MacroRecord


class MacroListResponse(BaseModel):
    success: bool = True
    macros: list[MacroRecord] = Field(default_factory=list)


class MacroExecuteResponse(BaseModel):
    success: bool = True
    ticket_id: str = Field(default="")
    actions_performed: list[str] = Field(default_factory=list)


# ── Phase 10a: Team dashboards ────────────────────────────────────────────────

class TeamMemberCreate(BaseModel):
    """POST /teams — add an agent to a team."""

    agent_id: str = Field(..., min_length=1, max_length=200, description="Agent identifier")
    team_name: str = Field(..., min_length=1, max_length=200, description="Team name")
    role: str = Field(default="member", max_length=100, description="Role within the team (e.g. lead, member)")


class TeamMemberRecord(BaseModel):
    """Stored team member record."""

    id: str = Field(..., description="Unique record ID")
    agent_id: str
    team_name: str
    role: str = "member"
    created_at: datetime = Field(default_factory=_utcnow)


class TeamMemberResponse(BaseModel):
    success: bool = True
    data: TeamMemberRecord


class TeamMemberListResponse(BaseModel):
    success: bool = True
    members: list[TeamMemberRecord] = Field(default_factory=list)


class TeamPerformanceMetrics(BaseModel):
    """Performance metrics for a single team."""

    team_name: str = ""
    total_tickets: int = 0
    open_tickets: int = 0
    resolved_tickets: int = 0
    avg_resolution_hours: float = 0.0
    member_count: int = 0
    members: list[str] = Field(default_factory=list)


class TeamDashboardResponse(BaseModel):
    success: bool = True
    teams: list[TeamPerformanceMetrics] = Field(default_factory=list)
    total_agents: int = 0


# ── Phase 10a: Enhanced SLA prediction ────────────────────────────────────────

class SLARiskThresholdCreate(BaseModel):
    """POST /sla-risk-thresholds — configure risk thresholds per priority."""

    priority: str = Field(..., description="Priority level (critical, high, medium, low)")
    warning_threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="Warning risk threshold (0.0-1.0)")
    critical_threshold: float = Field(default=0.8, ge=0.0, le=1.0, description="Critical risk threshold (0.0-1.0)")


class SLARiskThresholdRecord(BaseModel):
    """Stored SLA risk threshold record."""

    id: str = Field(..., description="Unique threshold ID")
    priority: str
    warning_threshold: float = 0.5
    critical_threshold: float = 0.8
    created_at: datetime = Field(default_factory=_utcnow)


class SLARiskThresholdResponse(BaseModel):
    success: bool = True
    data: SLARiskThresholdRecord


class SLARiskThresholdListResponse(BaseModel):
    success: bool = True
    thresholds: list[SLARiskThresholdRecord] = Field(default_factory=list)


class SLARiskFactor(BaseModel):
    """Individual risk factor contributing to breach probability."""

    factor: str = Field(default="", description="Risk factor name")
    weight: float = Field(default=0.0, description="Weight of this factor (0.0-1.0)")
    description: str = Field(default="", description="Human-readable description")


class EnhancedSLAPrediction(BaseModel):
    """Enhanced SLA prediction with multi-factor analysis."""

    ticket_id: str = ""
    category: str = ""
    priority: str = ""
    current_age_hours: float = 0.0
    sla_target_hours: float = 0.0
    predicted_breach_probability: float = 0.0
    risk_level: str = "low"
    risk_factors: list[SLARiskFactor] = Field(default_factory=list)
    recommended_action: str = ""


class EnhancedSLARiskResponse(BaseModel):
    success: bool = True
    predictions: list[EnhancedSLAPrediction] = Field(default_factory=list)
    total_open_tickets: int = 0
    high_risk_count: int = 0
    critical_risk_count: int = 0


# ── Phase 10a: Volume forecasting ────────────────────────────────────────────

class VolumeForecastPoint(BaseModel):
    """A single forecast data point."""

    date: str = Field(default="", description="Date in YYYY-MM-DD format")
    predicted_volume: int = 0
    lower_bound: int = 0
    upper_bound: int = 0


class CategoryForecast(BaseModel):
    """Volume forecast for a specific category."""

    category: str = ""
    historical_avg: float = 0.0
    trend_direction: str = Field(default="stable", description="stable, increasing, or decreasing")
    forecast_points: list[VolumeForecastPoint] = Field(default_factory=list)


class VolumeForecastResponse(BaseModel):
    success: bool = True
    forecast_days: int = 7
    overall_trend: str = Field(default="stable", description="Overall volume trend")
    daily_average: float = 0.0
    category_forecasts: list[CategoryForecast] = Field(default_factory=list)
    forecast_points: list[VolumeForecastPoint] = Field(default_factory=list)


# ── Phase 10b: Custom classifiers ────────────────────────────────────────────


class CustomClassifierCreate(BaseModel):
    """POST /custom-classifiers — create a custom classifier."""

    name: str = Field(..., min_length=1, max_length=200, description="Classifier name")
    description: str = Field(default="", description="Optional description")
    categories: list[str] = Field(..., min_length=2, description="Classification categories (at least 2)")


class CustomClassifierRecord(BaseModel):
    """Stored custom classifier record."""

    id: str = Field(..., description="Unique classifier ID")
    name: str
    description: str = ""
    categories: list[str] = Field(default_factory=list)
    training_samples: int = 0
    accuracy: float = 0.0
    status: str = "untrained"
    created_at: datetime = Field(default_factory=_utcnow)


class CustomClassifierResponse(BaseModel):
    success: bool = True
    classifier: CustomClassifierRecord


class CustomClassifierListResponse(BaseModel):
    success: bool = True
    classifiers: list[CustomClassifierRecord] = Field(default_factory=list)
    total: int = 0


class TrainingSample(BaseModel):
    """A single training sample for a custom classifier."""

    text: str = Field(..., min_length=1, description="Sample text")
    category: str = Field(..., min_length=1, description="Category label")


class TrainClassifierRequest(BaseModel):
    """POST /custom-classifiers/{id}/train — submit training samples."""

    samples: list[TrainingSample] = Field(..., min_length=1, description="Training samples (at least 1)")


class TrainClassifierResponse(BaseModel):
    success: bool = True
    classifier_id: str = ""
    samples_added: int = 0
    total_samples: int = 0
    status: str = "untrained"


class ClassifyRequest(BaseModel):
    """POST /custom-classifiers/{id}/classify — classify text."""

    text: str = Field(..., min_length=1, description="Text to classify")


class ClassifyResponse(BaseModel):
    success: bool = True
    classifier_id: str = ""
    text: str = ""
    predicted_category: str = ""
    confidence: float = 0.0
    all_scores: dict[str, float] = Field(default_factory=dict)


# ── Phase 10b: Anomaly detection ─────────────────────────────────────────────


class AnomalyRuleCreate(BaseModel):
    """POST /anomaly-rules — create an anomaly detection rule."""

    name: str = Field(..., min_length=1, max_length=200, description="Rule name")
    metric: str = Field(..., description="Metric to monitor: volume, category_shift, priority_spike, resolution_time")
    threshold: float = Field(..., ge=0, description="Anomaly threshold")
    window_hours: int = Field(default=24, ge=1, le=720, description="Analysis window in hours")
    enabled: bool = Field(default=True, description="Whether the rule is active")


class AnomalyRuleRecord(BaseModel):
    """Stored anomaly rule record."""

    id: str = Field(..., description="Unique rule ID")
    name: str
    metric: str
    threshold: float
    window_hours: int = 24
    enabled: bool = True
    created_at: datetime = Field(default_factory=_utcnow)


class AnomalyRuleResponse(BaseModel):
    success: bool = True
    rule: AnomalyRuleRecord


class AnomalyRuleListResponse(BaseModel):
    success: bool = True
    rules: list[AnomalyRuleRecord] = Field(default_factory=list)
    total: int = 0


class DetectedAnomaly(BaseModel):
    """A single detected anomaly."""

    anomaly_type: str = ""
    severity: str = "low"
    metric_value: float = 0.0
    threshold: float = 0.0
    description: str = ""
    detected_at: str = ""
    window_hours: int = 24


class AnomalyDetectionResponse(BaseModel):
    success: bool = True
    anomalies: list[DetectedAnomaly] = Field(default_factory=list)
    total_anomalies: int = 0
    analysis_window_hours: int = 24


# ── Phase 10b: KB auto-generation ────────────────────────────────────────────


class KBAutoGenerateRequest(BaseModel):
    """POST /kb/auto-generate — generate KB articles from resolved tickets."""

    category: str | None = Field(default=None, description="Optional category filter")
    min_resolved_tickets: int = Field(default=3, ge=1, description="Minimum resolved tickets per category")
    max_articles: int = Field(default=5, ge=1, le=20, description="Maximum articles to generate")


class GeneratedKBArticle(BaseModel):
    """A generated KB article."""

    title: str = ""
    content: str = ""
    category: str = ""
    source_ticket_count: int = 0
    confidence: float = 0.0
    tags: list[str] = Field(default_factory=list)


class KBAutoGenerateResponse(BaseModel):
    success: bool = True
    articles: list[GeneratedKBArticle] = Field(default_factory=list)
    total_generated: int = 0


class KBSuggestion(BaseModel):
    """A suggestion for KB article auto-generation."""

    category: str = ""
    resolved_ticket_count: int = 0
    existing_article_count: int = 0
    suggestion_score: float = 0.0
    suggested_title: str = ""


class KBAutoGenerateSuggestionsResponse(BaseModel):
    success: bool = True
    suggestions: list[KBSuggestion] = Field(default_factory=list)
    total_suggestions: int = 0


# ── Phase 10c: Visual workflow builder ───────────────────────────────────────


class WorkflowNodeType(str, Enum):
    """Types of nodes in a visual workflow."""

    trigger = "trigger"
    condition = "condition"
    action = "action"


class WorkflowNode(BaseModel):
    """A single node in a visual workflow."""

    id: str = Field(..., min_length=1)
    type: WorkflowNodeType = WorkflowNodeType.action
    label: str = Field(default="")
    config: dict[str, Any] = Field(default_factory=dict)
    position_x: float = 0.0
    position_y: float = 0.0


class WorkflowEdge(BaseModel):
    """An edge connecting two workflow nodes."""

    source_node_id: str = Field(..., min_length=1)
    target_node_id: str = Field(..., min_length=1)
    label: str = Field(default="")


class WorkflowCreate(BaseModel):
    """POST /workflow-builder/workflows — create a visual workflow."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)


class WorkflowRecord(BaseModel):
    """Stored visual workflow record."""

    id: str
    name: str
    description: str = ""
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    status: str = "draft"
    created_at: datetime
    updated_at: datetime | None = None


class WorkflowResponse(BaseModel):
    success: bool = True
    workflow: WorkflowRecord


class WorkflowListResponse(BaseModel):
    success: bool = True
    workflows: list[WorkflowRecord] = Field(default_factory=list)
    total: int = 0


class WorkflowValidationResult(BaseModel):
    """Result of validating a workflow definition."""

    valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WorkflowValidationResponse(BaseModel):
    success: bool = True
    validation: WorkflowValidationResult


# ── Phase 10c: Compliance & security hardening ───────────────────────────────


class DataRetentionPolicyCreate(BaseModel):
    """POST /compliance/data-retention-policies — create a data retention policy."""

    name: str = Field(..., min_length=1, max_length=200)
    entity_type: str = Field(..., description="Entity type (tickets, audit_logs, attachments)")
    retention_days: int = Field(..., ge=1, le=3650, description="Days to retain data")
    action: str = Field(default="archive", description="Action on expiry (archive, delete, anonymise)")


class DataRetentionPolicyRecord(BaseModel):
    """Stored data retention policy."""

    id: str
    name: str
    entity_type: str
    retention_days: int
    action: str = "archive"
    enabled: bool = True
    created_at: datetime


class DataRetentionPolicyResponse(BaseModel):
    success: bool = True
    policy: DataRetentionPolicyRecord


class DataRetentionPolicyListResponse(BaseModel):
    success: bool = True
    policies: list[DataRetentionPolicyRecord] = Field(default_factory=list)
    total: int = 0


class PIIRedactRequest(BaseModel):
    """POST /compliance/pii-redact — redact PII from text."""

    text: str = Field(..., min_length=1)
    redact_types: list[str] = Field(
        default_factory=lambda: ["email", "phone", "ssn", "credit_card"],
        description="Types of PII to redact",
    )


class PIIRedactResponse(BaseModel):
    success: bool = True
    original_length: int = 0
    redacted_text: str = ""
    redactions_applied: int = 0
    redaction_types_found: list[str] = Field(default_factory=list)


class AuditExportResponse(BaseModel):
    success: bool = True
    total_records: int = 0
    export_format: str = "json"
    records: list[dict[str, Any]] = Field(default_factory=list)


class SecurityPostureItem(BaseModel):
    """A single security posture check."""

    check: str = ""
    status: str = "pass"
    severity: str = "info"
    detail: str = ""


class SecurityPostureResponse(BaseModel):
    success: bool = True
    overall_score: float = 0.0
    checks: list[SecurityPostureItem] = Field(default_factory=list)
    total_checks: int = 0
    passed: int = 0
    warnings: int = 0
    failures: int = 0


# ── Phase 10c: Performance & scale improvements ─────────────────────────────


class PerformanceMetrics(BaseModel):
    """System performance metrics."""

    uptime_seconds: float = 0.0
    total_requests: int = 0
    avg_response_time_ms: float = 0.0
    db_pool_size: int = 1
    db_active_connections: int = 0
    cache_hit_rate: float = 0.0
    cache_entries: int = 0
    memory_usage_mb: float = 0.0


class PerformanceMetricsResponse(BaseModel):
    success: bool = True
    metrics: PerformanceMetrics


class CacheStatsResponse(BaseModel):
    success: bool = True
    total_entries: int = 0
    hit_count: int = 0
    miss_count: int = 0
    hit_rate: float = 0.0
    memory_usage_bytes: int = 0


class CacheInvalidateRequest(BaseModel):
    """POST /admin/cache/invalidate — invalidate cache entries."""

    pattern: str = Field(default="*", description="Pattern to match cache keys (* for all)")


class CacheInvalidateResponse(BaseModel):
    success: bool = True
    invalidated_count: int = 0


class ConnectionPoolStatsResponse(BaseModel):
    success: bool = True
    pool_size: int = 1
    active_connections: int = 0
    idle_connections: int = 1
    max_connections: int = 10
    wait_queue_size: int = 0


# ── Phase 10c: UX polish ────────────────────────────────────────────────────


class UserPreferences(BaseModel):
    """User display and interaction preferences."""

    theme: str = Field(default="light", description="UI theme (light, dark, system)")
    language: str = Field(default="en", description="Preferred language code")
    timezone: str = Field(default="UTC", description="Display timezone")
    notifications_enabled: bool = Field(default=True)
    keyboard_shortcuts_enabled: bool = Field(default=True)
    items_per_page: int = Field(default=25, ge=5, le=100)
    accessibility_high_contrast: bool = Field(default=False)
    accessibility_font_size: str = Field(default="medium", description="Font size (small, medium, large)")


class UserPreferencesUpdate(BaseModel):
    """PUT /preferences — update user preferences."""

    theme: str | None = None
    language: str | None = None
    timezone: str | None = None
    notifications_enabled: bool | None = None
    keyboard_shortcuts_enabled: bool | None = None
    items_per_page: int | None = Field(default=None, ge=5, le=100)
    accessibility_high_contrast: bool | None = None
    accessibility_font_size: str | None = None


class UserPreferencesResponse(BaseModel):
    success: bool = True
    user_id: str = ""
    preferences: UserPreferences


class OnboardingStep(BaseModel):
    """A single onboarding step."""

    step_id: str = ""
    title: str = ""
    description: str = ""
    completed: bool = False
    completed_at: datetime | None = None


class OnboardingStatusResponse(BaseModel):
    success: bool = True
    user_id: str = ""
    completed: bool = False
    completion_percentage: float = 0.0
    steps: list[OnboardingStep] = Field(default_factory=list)
    total_steps: int = 0
    completed_steps: int = 0


class OnboardingCompleteStepRequest(BaseModel):
    """POST /onboarding/complete-step — mark a step as complete."""

    user_id: str = Field(..., min_length=1)
    step_id: str = Field(..., min_length=1)


class OnboardingCompleteStepResponse(BaseModel):
    success: bool = True
    step_id: str = ""
    already_completed: bool = False

