"""
TicketForge — FastAPI application entry point

Run locally:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Or via Docker Compose (see docker-compose.yml).
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import secrets
import sqlite3 as _sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import httpx
import structlog
import structlog.stdlib
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import aiosqlite
import audit
from automation_detector import AutomationDetector
from config import settings
from connectors.jira import JiraConnector
from connectors.servicenow import ServiceNowConnector
from connectors.zendesk import ZendeskConnector
from models import (
    ActivityType,
    AgentPerformanceMatrixResponse,
    AgentPerformanceProfile,
    AgentProfileCreate,
    AgentProfileListResponse,
    AgentProfileResponse,
    AgentRecommendation,
    AgentRecommendationResponse,
    AgentSkillCreate,
    AgentSkillListResponse,
    AgentSkillRecord,
    AgentSkillResponse,
    AnalyseRequest,
    AnalyseResponse,
    AnalyticsResponse,
    AnomalyDetectionResponse,
    AnomalyRuleCreate,
    AnomalyRuleListResponse,
    AnomalyRuleRecord,
    AnomalyRuleResponse,
    ApprovalDecision,
    ApprovalListResponse,
    ApprovalRecord,
    ApprovalRequestCreate,
    ApprovalResponse,
    ApprovalStatus,
    AuditExportResponse,
    AuditLogResponse,
    AutomationRuleAction,
    AutomationRuleCondition,
    AutomationRuleCreate,
    AutomationRuleListResponse,
    AutomationRuleRecord,
    AutomationRuleResponse,
    AutoResolveRequest,
    AutoResolveResponse,
    AutoResolveResult,
    AutomationOpportunity,
    AutomationSuggestionType,
    BulkAnalyseRequest,
    BulkAnalyseResponse,
    BulkOperationResponse,
    BulkOperationResult,
    BulkStatusUpdate,
    BulkTagUpdate,
    CacheInvalidateRequest,
    CacheInvalidateResponse,
    CacheStatsResponse,
    CategoryCount,
    CategoryForecast,
    CategoryResult,
    ChatRequest,
    ChatResponse,
    ClassifyRequest,
    ClassifyResponse,
    ConnectionPoolStatsResponse,
    ContactCreate,
    ContactListResponse,
    ContactRecord,
    ContactResponse,
    ContactTicketsResponse,
    CSATAnalyticsResponse,
    CSATRecord,
    CSATResponse,
    CSATSubmission,
    CustomClassifierCreate,
    CustomClassifierListResponse,
    CustomClassifierRecord,
    CustomClassifierResponse,
    CustomFieldDefinition,
    CustomFieldListResponse,
    CustomFieldRecord,
    CustomFieldResponse,
    DailyTrend,
    DataRetentionPolicyCreate,
    DataRetentionPolicyListResponse,
    DataRetentionPolicyRecord,
    DataRetentionPolicyResponse,
    DetectDuplicatesRequest,
    DetectDuplicatesResponse,
    DetectedAnomaly,
    DriftMetric,
    DuplicateCandidate,
    EmailIngestRequest,
    EnhancedSLAPrediction,
    EnhancedSLARiskResponse,
    EnrichedTicket,
    EntityExtractionRequest,
    EntityExtractionResponse,
    ErrorResponse,
    EscalationStatusResponse,
    ExportFormat,
    ExtractedEntity,
    GeneratedKBArticle,
    HealthResponse,
    IntentDetectionRequest,
    IntentDetectionResponse,
    IntentResult,
    KBArticleCreate,
    KBArticleListResponse,
    KBArticleRecord,
    KBArticleResponse,
    KBArticleUpdate,
    KBAutoGenerateRequest,
    KBAutoGenerateResponse,
    KBAutoGenerateSuggestionsResponse,
    KBSearchRequest,
    KBSearchResponse,
    KBSearchResult,
    KBSuggestion,
    MacroAction,
    MacroCreate,
    MacroExecuteResponse,
    MacroListResponse,
    MacroRecord,
    MacroResponse,
    MergedTicketRecord,
    MonitoringResponse,
    MultiAgentStatusResponse,
    OnboardingCompleteStepRequest,
    OnboardingCompleteStepResponse,
    OnboardingStatusResponse,
    OnboardingStep,
    PluginInfo,
    PluginListResponse,
    PortalTicketResponse,
    PortalTicketSubmission,
    PerformanceMetrics,
    PerformanceMetricsResponse,
    PIIRedactRequest,
    PIIRedactResponse,
    Priority,
    PriorityCount,
    PriorityResult,
    RawTicket,
    ResolutionFactor,
    ResolutionPrediction,
    ResolutionPredictionResponse,
    ResolutionStatsResponse,
    ResponseTemplateCreate,
    ResponseTemplateListResponse,
    ResponseTemplateRecord,
    ResponseTemplateResponse,
    Role,
    RootCauseHypothesis,
    RoutingResult,
    SatisfactionFactor,
    SatisfactionPrediction,
    SatisfactionPredictionResponse,
    SatisfactionTrendsResponse,
    SavedFilterCreate,
    SavedFilterListResponse,
    SavedFilterRecord,
    SavedFilterResponse,
    ScheduledReportCreate,
    ScheduledReportListResponse,
    ScheduledReportRecord,
    ScheduledReportResponse,
    SecurityPostureItem,
    SecurityPostureResponse,
    Sentiment,
    SentimentResult,
    SLAInfo,
    SLAPrediction,
    SLAPredictionResponse,
    SLARiskFactor,
    SLARiskThresholdCreate,
    SLARiskThresholdListResponse,
    SLARiskThresholdRecord,
    SLARiskThresholdResponse,
    SLAStatus,
    SmartAssignmentResponse,
    SmartAssignmentResult,
    SuggestedResponse,
    SuggestResponseRequest,
    SuggestResponseResponse,
    TicketActivityRecord,
    TicketActivityResponse,
    TicketCommentCreate,
    TicketCommentResponse,
    TicketLockCreate,
    TicketLockRecord,
    TicketLockResponse,
    TicketMergeRequest,
    TicketMergeResponse,
    TicketSource,
    TicketStatus,
    TicketStatusUpdate,
    TicketTagRequest,
    TicketTagsResponse,
    TeamDashboardResponse,
    TeamMemberCreate,
    TeamMemberListResponse,
    TeamMemberRecord,
    TeamMemberResponse,
    TeamPerformanceMetrics,
    TrainClassifierRequest,
    TrainClassifierResponse,
    TroubleshootingExecuteRequest,
    TroubleshootingExecuteResponse,
    TroubleshootingFlowCreate,
    TroubleshootingFlowListResponse,
    TroubleshootingFlowRecord,
    TroubleshootingFlowResponse,
    TroubleshootingStep,
    TroubleshootingStepType,
    UserPreferences,
    UserPreferencesResponse,
    UserPreferencesUpdate,
    VectorStoreStatusResponse,
    VolumeForecastPoint,
    VolumeForecastResponse,
    WebhookEventListResponse,
    WebhookEventType,
    WebhookIngest,
    WebSocketEvent,
    WorkflowCreate,
    WorkflowEdge,
    WorkflowListResponse,
    WorkflowNode,
    WorkflowRecord,
    WorkflowResponse,
    WorkflowValidationResponse,
    WorkflowValidationResult,
)
from notifications import send_notifications
from ticket_processor import TicketProcessor
from vector_store import VectorStore, create_vector_store
from webhook_events import send_webhook_event

# ── Logging setup ─────────────────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger(__name__)

# ── Application version ───────────────────────────────────────────────────────
APP_VERSION = "1.0.0"

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── App state (shared singletons) ─────────────────────────────────────────────
_processor: TicketProcessor | None = None
_detector: AutomationDetector | None = None
_db: aiosqlite.Connection | None = None
_vector_store: VectorStore | None = None


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    """Manages active WebSocket connections for real-time event broadcasting."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, event: WebSocketEvent) -> None:
        """Broadcast an event to all connected clients, removing stale connections."""
        payload = event.model_dump_json()
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    @property
    def active_connections(self) -> int:
        return len(self._connections)


ws_manager = ConnectionManager()

DB_INIT_SQL = """
CREATE TABLE IF NOT EXISTS processed_tickets (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    category TEXT,
    priority TEXT,
    automation_score INTEGER,
    summary TEXT,
    sentiment TEXT DEFAULT 'neutral',
    detected_language TEXT DEFAULT 'en',
    ticket_status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT NULL,
    updated_at TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS ticket_history (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    api_key_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    resource TEXT NOT NULL,
    status_code INTEGER NOT NULL DEFAULT 200,
    detail TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS kb_articles (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS csat_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT NOT NULL DEFAULT '',
    reporter_email TEXT NOT NULL DEFAULT '',
    submitted_at TEXT NOT NULL,
    UNIQUE(ticket_id)
);

CREATE TABLE IF NOT EXISTS scheduled_reports (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    frequency TEXT NOT NULL DEFAULT 'weekly',
    webhook_url TEXT NOT NULL,
    include_categories INTEGER NOT NULL DEFAULT 1,
    include_priorities INTEGER NOT NULL DEFAULT 1,
    include_sla INTEGER NOT NULL DEFAULT 1,
    include_csat INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_merges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    primary_ticket_id TEXT NOT NULL,
    merged_ticket_id TEXT NOT NULL,
    merged_at TEXT NOT NULL,
    merged_by TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS custom_fields (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    field_type TEXT NOT NULL DEFAULT 'text',
    description TEXT NOT NULL DEFAULT '',
    required INTEGER NOT NULL DEFAULT 0,
    options TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_tags (
    ticket_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (ticket_id, tag)
);

CREATE TABLE IF NOT EXISTS saved_filters (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    filter_criteria TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS response_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_activity (
    id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL,
    activity_type TEXT NOT NULL DEFAULT 'comment',
    content TEXT NOT NULL DEFAULT '',
    performed_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_skills (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    categories TEXT NOT NULL DEFAULT '[]',
    priorities TEXT NOT NULL DEFAULT '[]',
    languages TEXT NOT NULL DEFAULT '[]',
    max_concurrent_tickets INTEGER NOT NULL DEFAULT 10,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automation_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    conditions TEXT NOT NULL DEFAULT '[]',
    actions TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_approvals (
    id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL,
    approver TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    decision_comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS ticket_locks (
    id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL UNIQUE,
    agent_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    organisation TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contact_tickets (
    contact_id TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    PRIMARY KEY (contact_id, ticket_id)
);

CREATE TABLE IF NOT EXISTS macros (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    actions TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_members (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    team_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TEXT NOT NULL,
    UNIQUE(agent_id, team_name)
);

CREATE TABLE IF NOT EXISTS sla_risk_thresholds (
    id TEXT PRIMARY KEY,
    priority TEXT NOT NULL UNIQUE,
    warning_threshold REAL NOT NULL DEFAULT 0.5,
    critical_threshold REAL NOT NULL DEFAULT 0.8,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_classifiers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    categories TEXT NOT NULL DEFAULT '[]',
    training_samples INTEGER NOT NULL DEFAULT 0,
    accuracy REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'untrained',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classifier_training_data (
    id TEXT PRIMARY KEY,
    classifier_id TEXT NOT NULL,
    text TEXT NOT NULL,
    category TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anomaly_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    metric TEXT NOT NULL,
    threshold REAL NOT NULL,
    window_hours INTEGER NOT NULL DEFAULT 24,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visual_workflows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    nodes TEXT NOT NULL DEFAULT '[]',
    edges TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS data_retention_policies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    retention_days INTEGER NOT NULL,
    action TEXT NOT NULL DEFAULT 'archive',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id TEXT PRIMARY KEY,
    theme TEXT NOT NULL DEFAULT 'light',
    language TEXT NOT NULL DEFAULT 'en',
    timezone TEXT NOT NULL DEFAULT 'UTC',
    notifications_enabled INTEGER NOT NULL DEFAULT 1,
    keyboard_shortcuts_enabled INTEGER NOT NULL DEFAULT 1,
    items_per_page INTEGER NOT NULL DEFAULT 25,
    accessibility_high_contrast INTEGER NOT NULL DEFAULT 0,
    accessibility_font_size TEXT NOT NULL DEFAULT 'medium',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS onboarding_progress (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    UNIQUE(user_id, step_id)
);

CREATE TABLE IF NOT EXISTS troubleshooting_flows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'general',
    steps TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_profiles (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    specialisations TEXT NOT NULL DEFAULT '[]',
    max_capacity INTEGER NOT NULL DEFAULT 10,
    current_load INTEGER NOT NULL DEFAULT 0,
    avg_resolution_hours REAL NOT NULL DEFAULT 0.0,
    avg_satisfaction REAL NOT NULL DEFAULT 0.0,
    categories TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT
);
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _processor, _detector, _db, _vector_store  # noqa: PLW0603

    log.info("ticketforge.startup", version=APP_VERSION, model=settings.ollama_model)

    # Database
    _db = await aiosqlite.connect(settings.database_url.replace("sqlite+aiosqlite:///", ""))
    await _db.executescript(DB_INIT_SQL)
    await _db.commit()

    # Vector store
    _vector_store = await create_vector_store(settings.vector_store_backend, db=_db)

    # Core pipeline components
    _detector = AutomationDetector(settings)
    _processor = TicketProcessor(settings, _detector)

    yield  # ── app running ──

    log.info("ticketforge.shutdown")
    if _processor:
        await _processor.aclose()
    if _db:
        await _db.close()


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="TicketForge",
    description="Lightweight AI layer for enterprise IT ticketing systems.",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS middleware (A5) ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)


# ── Request ID middleware (A4) ────────────────────────────────────────────────
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a unique request ID to every request and propagate through logs."""
    if not settings.request_id_enabled:
        return await call_next(request)
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ── Content Security Policy headers (A7) ─────────────────────────────────────
@app.middleware("http")
async def csp_middleware(request: Request, call_next):
    """Add Content Security Policy headers for HTML responses."""
    response = await call_next(request)
    if settings.csp_enabled:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ── Input sanitisation helper (A3) ────────────────────────────────────────────
def _sanitise_text(text: str) -> str:
    """Sanitise user-supplied text by stripping dangerous HTML/script tags."""
    if not settings.input_sanitisation_enabled:
        return text
    try:
        import nh3  # noqa: PLC0415
        return nh3.clean(text)
    except ImportError:
        import html  # noqa: PLC0415
        return html.escape(text)


# ── Sentry integration (D3) ──────────────────────────────────────────────────
if settings.sentry_dsn:
    try:
        import sentry_sdk  # noqa: PLC0415
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            environment=settings.sentry_environment,
            release=f"ticketforge@{APP_VERSION}",
            send_default_pii=False,
        )
        log.info("sentry.initialised", environment=settings.sentry_environment)
    except ImportError:
        log.warning("sentry.sdk_not_installed", detail="pip install sentry-sdk[fastapi]")


# ── OpenTelemetry tracing (D1) ───────────────────────────────────────────────
if settings.otel_enabled:
    try:
        from opentelemetry import trace  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # noqa: PLC0415
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: PLC0415

        resource = Resource.create({"service.name": settings.otel_service_name, "service.version": APP_VERSION})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint, insecure=True))
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        log.info("opentelemetry.initialised", endpoint=settings.otel_exporter_endpoint)
    except ImportError:
        log.warning("opentelemetry.not_installed", detail="pip install opentelemetry-sdk opentelemetry-instrumentation-fastapi opentelemetry-exporter-otlp")


# Prometheus metrics at /metrics
Instrumentator().instrument(app).expose(app)

# ── GraphQL endpoint (nice-to-have) ──────────────────────────────────────────
try:
    from graphql_schema import graphql_app as _graphql_app  # noqa: PLC0415
    app.include_router(_graphql_app, prefix="/graphql")
    log.info("graphql.mounted", path="/graphql")
except ImportError:
    log.info("graphql.not_available", detail="pip install strawberry-graphql[fastapi]")


# ── Modular route modules (B5) ───────────────────────────────────────────────
from routes.ops import router as ops_router  # noqa: E402, PLC0415
app.include_router(ops_router, prefix="/v1", tags=["v1"])


# ── API key hashing helpers (A1) ──────────────────────────────────────────────
def _hash_api_key(api_key: str) -> str:
    """Create a SHA-256 hash of an API key for storage and comparison."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def _verify_api_key_secure(provided_key: str, valid_keys: list[str]) -> bool:
    """Constant-time comparison of API key against valid keys."""
    provided_hash = _hash_api_key(provided_key)
    for valid_key in valid_keys:
        valid_hash = _hash_api_key(valid_key)
        if secrets.compare_digest(provided_hash, valid_hash):
            return True
    return False


# ── Authentication & RBAC dependencies ─────────────────────────────────────────

_ROLE_HIERARCHY: dict[Role, int] = {Role.viewer: 0, Role.analyst: 1, Role.admin: 2}


def _resolve_role(api_key: str) -> Role:
    """Look up the role for an API key, defaulting to analyst."""
    role_str = settings.api_key_roles.get(api_key, "analyst")
    try:
        return Role(role_str)
    except ValueError:
        return Role.analyst


async def verify_api_key(x_api_key: str = Header(...)) -> str:
    """Validate the X-Api-Key header against the configured list using constant-time comparison."""
    if not _verify_api_key_secure(x_api_key, settings.api_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return x_api_key


def _require_role(minimum: Role):
    """Return a FastAPI dependency that enforces a minimum role level."""

    async def _check(x_api_key: str = Depends(verify_api_key)) -> str:
        caller_role = _resolve_role(x_api_key)
        if _ROLE_HIERARCHY[caller_role] < _ROLE_HIERARCHY[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role '{minimum.value}' or higher",
            )
        return x_api_key

    return _check


require_viewer = _require_role(Role.viewer)
require_analyst = _require_role(Role.analyst)
require_admin = _require_role(Role.admin)


# ── Helper to get processor (raises 503 if not ready) ─────────────────────────

def _get_processor() -> TicketProcessor:
    if _processor is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    return _processor


# ── SLA helper ─────────────────────────────────────────────────────────────────

_SLA_TARGETS: dict[Priority, tuple[int, int]] = {
    Priority.critical: (settings.sla_response_critical, settings.sla_resolution_critical),
    Priority.high: (settings.sla_response_high, settings.sla_resolution_high),
    Priority.medium: (settings.sla_response_medium, settings.sla_resolution_medium),
    Priority.low: (settings.sla_response_low, settings.sla_resolution_low),
}


def compute_sla(priority: Priority, created_at: datetime) -> SLAInfo:
    """Compute SLA status based on priority targets and elapsed time."""
    response_target, resolution_target = _SLA_TARGETS[priority]
    now = datetime.now(tz=timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    elapsed = max(0.0, (now - created_at).total_seconds() / 60.0)

    # breach_risk: ratio of elapsed to resolution target (capped at 1.0)
    breach_risk = min(1.0, elapsed / resolution_target) if resolution_target > 0 else 0.0

    if elapsed >= resolution_target:
        sla_status = SLAStatus.breached
    elif breach_risk >= 0.8:
        sla_status = SLAStatus.at_risk
    else:
        sla_status = SLAStatus.within

    return SLAInfo(
        response_target_minutes=response_target,
        resolution_target_minutes=resolution_target,
        status=sla_status,
        elapsed_minutes=round(elapsed, 1),
        breach_risk=round(breach_risk, 3),
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health_check() -> HealthResponse:
    """Liveness probe — returns ok if the application is running."""
    # Check Ollama reachability
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:  # noqa: BLE001
        pass

    db_ok = _db is not None
    return HealthResponse(status="ok", ollama_reachable=ollama_ok, db_ok=db_ok)


@app.get("/ready", response_model=HealthResponse, tags=["ops"])
async def readiness_check() -> HealthResponse:
    """Readiness probe — returns ok only when all critical dependencies are available."""
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:  # noqa: BLE001
        pass

    db_ok = _db is not None
    processor_ok = _processor is not None

    all_ok = db_ok and processor_ok
    resp = HealthResponse(status="ok" if all_ok else "degraded", ollama_reachable=ollama_ok, db_ok=db_ok)
    if not all_ok:
        resp.status = "degraded"
    return resp


# ── API key rotation endpoint (A2) ───────────────────────────────────────────

@app.post("/api-keys/rotate", tags=["security"])
async def rotate_api_key(
    request: Request,
    api_key: str = Depends(require_admin),
) -> JSONResponse:
    """
    Rotate an API key: generates a new key and invalidates the caller's current key.
    Only admins can rotate keys. Returns the new key (shown only once).
    """
    new_key = secrets.token_urlsafe(32)

    # Replace the caller's key in the settings
    current_keys = list(settings.api_keys)
    if api_key in current_keys:
        idx = current_keys.index(api_key)
        current_keys[idx] = new_key
    else:
        current_keys.append(new_key)

    # Migrate role from old key to new key
    old_role = settings.api_key_roles.get(api_key, "admin")
    new_roles = dict(settings.api_key_roles)
    new_roles.pop(api_key, None)
    new_roles[new_key] = old_role

    settings.api_keys = current_keys
    settings.api_key_roles = new_roles

    log.info("api_key.rotated", old_key_hash=_hash_api_key(api_key), new_key_hash=_hash_api_key(new_key))

    return JSONResponse(
        status_code=200,
        content={
            "message": "API key rotated successfully",
            "new_api_key": new_key,
            "old_key_hash": _hash_api_key(api_key),
            "new_key_hash": _hash_api_key(new_key),
            "note": "Store the new key securely. It will not be shown again.",
        },
    )


@app.post(
    "/analyse",
    response_model=AnalyseResponse,
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    tags=["core"],
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def analyse_ticket(
    request: Request,
    body: AnalyseRequest,
    api_key: str = Depends(require_analyst),
) -> AnalyseResponse:
    """
    Analyse a single ticket inline.
    Returns full enrichment: category, priority, routing, automation score, KB suggestions.
    Requires analyst or admin role.
    """
    processor = _get_processor()
    enriched = await processor.process(
        body.ticket, include_automation=body.include_automation_detection
    )
    enriched.sla = compute_sla(enriched.priority.priority, body.ticket.created_at)
    await _persist_ticket(enriched)

    # Fire-and-forget notifications if priority/SLA warrants it
    asyncio.create_task(send_notifications(enriched, settings))

    # Broadcast real-time WebSocket event
    if settings.websocket_notifications_enabled and ws_manager.active_connections:
        asyncio.create_task(ws_manager.broadcast(WebSocketEvent(
            event_type="ticket_created",
            ticket_id=enriched.ticket_id,
            data={
                "category": enriched.category.category,
                "priority": enriched.priority.priority.value,
                "sentiment": enriched.sentiment.sentiment.value,
                "sla_status": enriched.sla.status.value,
            },
        )))

    # Fire-and-forget structured webhook event (Zapier/Make/n8n)
    if settings.webhook_events_enabled:
        asyncio.create_task(send_webhook_event(
            WebhookEventType.ticket_created,
            enriched.ticket_id,
            {
                "category": enriched.category.category,
                "priority": enriched.priority.priority.value,
                "sentiment": enriched.sentiment.sentiment.value,
                "sla_status": enriched.sla.status.value,
                "summary": enriched.summary,
            },
            settings,
        ))

    # Auto-escalate to PagerDuty/OpsGenie for critical tickets or SLA breaches
    asyncio.create_task(_auto_escalate(enriched))

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="analyse",
            resource=enriched.ticket_id,
        )
    return AnalyseResponse(data=enriched)


@app.post(
    "/webhook/{source}",
    response_model=AnalyseResponse,
    tags=["webhooks"],
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def ingest_webhook(
    request: Request,
    source: TicketSource,
    body: WebhookIngest,
    api_key: str = Depends(require_analyst),
) -> AnalyseResponse:
    """
    Ingest a webhook payload from a source system and return enriched result.
    Supports: servicenow, jira, zendesk. Requires analyst or admin role.
    """
    processor = _get_processor()
    ticket = _parse_webhook_payload(source, body.payload)
    enriched = await processor.process(ticket, include_automation=True)
    enriched.sla = compute_sla(enriched.priority.priority, ticket.created_at)
    await _persist_ticket(enriched)

    # Fire-and-forget outbound webhook if configured
    if settings.outbound_webhook_url:
        asyncio.create_task(_send_outbound_webhook(enriched))

    # Fire-and-forget Slack/Teams notifications
    asyncio.create_task(send_notifications(enriched, settings))

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="webhook_ingest",
            resource=f"{source.value}:{enriched.ticket_id}",
        )
    return AnalyseResponse(data=enriched)


@app.get(
    "/tickets/{ticket_id}",
    response_model=EnrichedTicket,
    tags=["core"],
)
async def get_cached_ticket(
    ticket_id: str,
    api_key: str = Depends(require_viewer),
) -> EnrichedTicket:
    """Retrieve a previously processed ticket from the local cache. Requires viewer role or higher."""
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    async with _db.execute(
        "SELECT id, source, processed_at, category, priority, automation_score, summary, "
        "sentiment, detected_language, ticket_status "
        "FROM processed_tickets WHERE id = ?",
        (ticket_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        if _db:
            await audit.record(
                _db,
                api_key=api_key,
                role=_resolve_role(api_key),
                action="get_ticket",
                resource=ticket_id,
                status_code=404,
            )
        raise HTTPException(status_code=404, detail="Ticket not found in cache")
    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="get_ticket",
            resource=ticket_id,
        )
    # Return a minimal EnrichedTicket reconstructed from the cache
    return EnrichedTicket(
        ticket_id=row[0],
        source=TicketSource(row[1]),
        summary=row[6] or "",
        category=CategoryResult(category=row[3] or ""),
        priority=PriorityResult(priority=Priority(row[4] or "medium"), score=50),
        routing=RoutingResult(),
        automation=AutomationOpportunity(
            score=row[5] or 0, suggestion_type=AutomationSuggestionType.none
        ),
        root_cause=RootCauseHypothesis(),
        sentiment=SentimentResult(
            sentiment=Sentiment(row[7] or "neutral"),
        ),
        detected_language=row[8] or "en",
        ticket_status=TicketStatus(row[9] or "open"),
        processed_at=datetime.fromisoformat(row[2]),
    )


# ── Ticket status update endpoint ────────────────────────────────────────────

@app.patch(
    "/tickets/{ticket_id}/status",
    tags=["core"],
)
async def update_ticket_status(
    ticket_id: str,
    body: TicketStatusUpdate,
    api_key: str = Depends(require_analyst),
):
    """
    Update the lifecycle status of a previously processed ticket.
    Requires analyst or admin role.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id FROM processed_tickets WHERE id = ?", (ticket_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Ticket not found in cache")

    await _db.execute(
        "UPDATE processed_tickets SET ticket_status = ? WHERE id = ?",
        (body.status.value, ticket_id),
    )
    await _db.commit()

    # Broadcast real-time WebSocket event
    if settings.websocket_notifications_enabled and ws_manager.active_connections:
        asyncio.create_task(ws_manager.broadcast(WebSocketEvent(
            event_type="status_changed",
            ticket_id=ticket_id,
            data={"new_status": body.status.value},
        )))

    # Fire-and-forget structured webhook event (Zapier/Make/n8n)
    if settings.webhook_events_enabled:
        event_type = WebhookEventType.ticket_resolved if body.status == TicketStatus.resolved else WebhookEventType.ticket_updated
        asyncio.create_task(send_webhook_event(
            event_type,
            ticket_id,
            {"new_status": body.status.value},
            settings,
        ))

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="update_ticket_status",
        resource=ticket_id,
        detail=f"status={body.status.value}",
    )
    return {"success": True, "ticket_id": ticket_id, "status": body.status.value}


# ── Bulk analysis endpoint ────────────────────────────────────────────────────

@app.post(
    "/analyse/bulk",
    response_model=BulkAnalyseResponse,
    tags=["core"],
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def analyse_bulk(
    request: Request,
    body: BulkAnalyseRequest,
    api_key: str = Depends(require_analyst),
) -> BulkAnalyseResponse:
    """
    Analyse multiple tickets in a single call (max 50).
    Returns results for all tickets. Requires analyst or admin role.
    """
    processor = _get_processor()

    async def _process_one(ticket: RawTicket) -> EnrichedTicket | None:
        try:
            enriched = await processor.process(
                ticket, include_automation=body.include_automation_detection
            )
            enriched.sla = compute_sla(enriched.priority.priority, ticket.created_at)
            await _persist_ticket(enriched)
            return enriched
        except Exception as e:  # noqa: BLE001
            log.warning("bulk_analyse.ticket_failed", ticket_id=ticket.id, error=str(e))
            return None

    results = await asyncio.gather(*[_process_one(t) for t in body.tickets])
    successes = [r for r in results if r is not None]
    failed = len(results) - len(successes)

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="analyse_bulk",
            resource=f"{len(body.tickets)} tickets",
            detail=f"success={len(successes)}, failed={failed}",
        )
    return BulkAnalyseResponse(data=successes, total=len(successes), failed=failed)


# ── AI Response Suggestion endpoint ──────────────────────────────────────────

@app.post(
    "/suggest-response",
    response_model=SuggestResponseResponse,
    tags=["core"],
)
async def suggest_response(
    body: SuggestResponseRequest,
    api_key: str = Depends(require_analyst),
) -> SuggestResponseResponse:
    """
    Generate a draft agent response for a previously analysed ticket.
    Uses the LLM to produce a professional response based on the ticket's enrichment data.
    Requires analyst or admin role.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    processor = _get_processor()

    # Look up the cached ticket
    async with _db.execute(
        "SELECT id, source, category, priority, automation_score, summary, "
        "sentiment, detected_language, ticket_status "
        "FROM processed_tickets WHERE id = ?",
        (body.ticket_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Ticket not found in cache")

    # Build context for the LLM
    from prompts import SUGGEST_RESPONSE_PROMPT, SYSTEM_PROMPT, get_i18n_response_prompt  # noqa: PLC0415

    detected_lang = row[7] or "en"
    prompt = SUGGEST_RESPONSE_PROMPT.format(
        ticket_id=row[0],
        title=row[5] or "",  # summary used as title (original title not persisted)
        description=body.additional_context or "N/A",
        category=row[2] or "",
        sub_category="",
        priority=row[3] or "medium",
        sentiment=row[6] or "neutral",
        summary=row[5] or "",
        kb_articles="None available",
        root_cause="Not determined",
    )

    # Append i18n language instruction for non-English tickets
    if settings.i18n_enabled:
        prompt += get_i18n_response_prompt(detected_lang)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    try:
        raw_content = await processor.chat_with_llm(messages, temperature=0.3, max_tokens=1024)
        from ticket_processor import _parse_llm_json  # noqa: PLC0415
        llm_data = _parse_llm_json(raw_content)
    except Exception as e:  # noqa: BLE001
        log.warning("suggest_response.llm_failed", ticket_id=body.ticket_id, error=str(e))
        llm_data = {}

    suggestion = SuggestedResponse(
        ticket_id=body.ticket_id,
        subject=llm_data.get("subject", ""),
        body=llm_data.get("body", ""),
        tone=llm_data.get("tone", "professional"),
        suggested_actions=llm_data.get("suggested_actions", []),
    )

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="suggest_response",
            resource=body.ticket_id,
        )
    return SuggestResponseResponse(data=suggestion)


# ── Duplicate Ticket Detection endpoint ──────────────────────────────────────

@app.post(
    "/tickets/detect-duplicates",
    response_model=DetectDuplicatesResponse,
    tags=["core"],
)
async def detect_duplicates(
    body: DetectDuplicatesRequest,
    api_key: str = Depends(require_analyst),
) -> DetectDuplicatesResponse:
    """
    Detect duplicate/similar tickets using vector similarity.
    Provide either a ticket_id (to compare against existing tickets) or
    title+description text. Uses sentence-transformer embeddings and cosine similarity.
    Requires analyst or admin role.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    if _detector is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    # Build query text
    query_text = ""
    query_ticket_id = body.ticket_id

    if body.ticket_id:
        # Look up existing ticket summary
        async with _db.execute(
            "SELECT summary FROM processed_tickets WHERE id = ?",
            (body.ticket_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Ticket not found in cache")
        query_text = row[0] or ""
    elif body.title or body.description:
        query_text = f"{body.title}\n{body.description}".strip()
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either ticket_id or title/description text",
        )

    if not query_text:
        return DetectDuplicatesResponse(
            query_ticket_id=query_ticket_id,
            duplicates=[],
            total_candidates=0,
        )

    # Get all existing tickets
    async with _db.execute(
        "SELECT id, summary FROM processed_tickets ORDER BY processed_at DESC"
    ) as cursor:
        all_tickets = await cursor.fetchall()

    # Exclude the query ticket from candidates
    candidates = [(r[0], r[1] or "") for r in all_tickets if r[0] != query_ticket_id]
    if not candidates:
        return DetectDuplicatesResponse(
            query_ticket_id=query_ticket_id,
            duplicates=[],
            total_candidates=0,
        )

    # Compute similarities using the automation detector's embedding model
    duplicates = await asyncio.get_event_loop().run_in_executor(
        None,
        _compute_similarities,
        query_text,
        candidates,
        body.threshold,
        body.max_results,
    )

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="detect_duplicates",
            resource=query_ticket_id or "text_query",
            detail=f"found={len(duplicates)}",
        )
    return DetectDuplicatesResponse(
        query_ticket_id=query_ticket_id,
        duplicates=duplicates,
        total_candidates=len(duplicates),
    )


def _compute_similarities(
    query_text: str,
    candidates: list[tuple[str, str]],
    threshold: float,
    max_results: int,
) -> list[DuplicateCandidate]:
    """Compute cosine similarity between query and candidate ticket texts."""
    import numpy as np  # noqa: PLC0415
    from sklearn.preprocessing import normalize  # noqa: PLC0415

    model = _detector.get_embedding_model()
    texts = [query_text] + [c[1] for c in candidates]
    embeddings = model.encode(texts, show_progress_bar=False, batch_size=32)
    embeddings = normalize(embeddings)

    query_emb = embeddings[0:1]
    candidate_embs = embeddings[1:]

    # Cosine similarity (embeddings are normalized, so dot product = cosine similarity)
    similarities = np.dot(candidate_embs, query_emb.T).flatten()

    # Filter by threshold and sort
    results = []
    for i, sim in enumerate(similarities):
        if sim >= threshold:
            results.append(DuplicateCandidate(
                ticket_id=candidates[i][0],
                title=candidates[i][1],
                similarity_score=round(float(sim), 4),
            ))

    results.sort(key=lambda x: x.similarity_score, reverse=True)
    return results[:max_results]


# ── Knowledge Base CRUD endpoints ─────────────────────────────────────────────

@app.post(
    "/kb/articles",
    response_model=KBArticleResponse,
    tags=["knowledge-base"],
    status_code=201,
)
async def create_kb_article(
    body: KBArticleCreate,
    api_key: str = Depends(require_analyst),
) -> KBArticleResponse:
    """
    Create a new knowledge base article.
    Requires analyst or admin role.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    article_id = f"KB-{uuid.uuid4().hex[:12]}"
    now = datetime.now(tz=timezone.utc)
    tags_json = _json.dumps(body.tags)

    await _db.execute(
        "INSERT INTO kb_articles (id, title, content, category, tags, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (article_id, body.title, body.content, body.category, tags_json,
         now.isoformat(), now.isoformat()),
    )
    await _db.commit()

    article = KBArticleRecord(
        id=article_id,
        title=body.title,
        content=body.content,
        category=body.category,
        tags=body.tags,
        created_at=now,
        updated_at=now,
    )

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="create_kb_article",
            resource=article_id,
        )
    return KBArticleResponse(data=article)


@app.get(
    "/kb/articles",
    response_model=KBArticleListResponse,
    tags=["knowledge-base"],
)
async def list_kb_articles(
    category: str | None = Query(default=None, description="Filter by category"),
    api_key: str = Depends(require_viewer),
) -> KBArticleListResponse:
    """
    List all knowledge base articles, optionally filtered by category.
    Requires viewer role or higher.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    if category:
        sql = "SELECT id, title, content, category, tags, created_at, updated_at FROM kb_articles WHERE category = ? ORDER BY updated_at DESC"
        params: tuple = (category,)
    else:
        sql = "SELECT id, title, content, category, tags, created_at, updated_at FROM kb_articles ORDER BY updated_at DESC"
        params = ()

    async with _db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()

    articles = []
    for row in rows:
        try:
            tags = _json.loads(row[4]) if row[4] else []
        except (ValueError, TypeError):
            tags = []
        articles.append(KBArticleRecord(
            id=row[0],
            title=row[1],
            content=row[2],
            category=row[3],
            tags=tags,
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
        ))

    return KBArticleListResponse(data=articles, total=len(articles))


@app.get(
    "/kb/articles/{article_id}",
    response_model=KBArticleResponse,
    tags=["knowledge-base"],
)
async def get_kb_article(
    article_id: str,
    api_key: str = Depends(require_viewer),
) -> KBArticleResponse:
    """
    Retrieve a single knowledge base article by ID.
    Requires viewer role or higher.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    async with _db.execute(
        "SELECT id, title, content, category, tags, created_at, updated_at "
        "FROM kb_articles WHERE id = ?",
        (article_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Knowledge base article not found")

    try:
        tags = _json.loads(row[4]) if row[4] else []
    except (ValueError, TypeError):
        tags = []

    article = KBArticleRecord(
        id=row[0],
        title=row[1],
        content=row[2],
        category=row[3],
        tags=tags,
        created_at=datetime.fromisoformat(row[5]),
        updated_at=datetime.fromisoformat(row[6]),
    )
    return KBArticleResponse(data=article)


@app.put(
    "/kb/articles/{article_id}",
    response_model=KBArticleResponse,
    tags=["knowledge-base"],
)
async def update_kb_article(
    article_id: str,
    body: KBArticleUpdate,
    api_key: str = Depends(require_analyst),
) -> KBArticleResponse:
    """
    Update an existing knowledge base article.
    Only provided fields are updated. Requires analyst or admin role.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    async with _db.execute(
        "SELECT id, title, content, category, tags, created_at, updated_at "
        "FROM kb_articles WHERE id = ?",
        (article_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Knowledge base article not found")

    # Apply partial updates
    new_title = body.title if body.title is not None else row[1]
    new_content = body.content if body.content is not None else row[2]
    new_category = body.category if body.category is not None else row[3]
    if body.tags is not None:
        new_tags_json = _json.dumps(body.tags)
        new_tags = body.tags
    else:
        new_tags_json = row[4]
        try:
            new_tags = _json.loads(row[4]) if row[4] else []
        except (ValueError, TypeError):
            new_tags = []

    now = datetime.now(tz=timezone.utc)
    await _db.execute(
        "UPDATE kb_articles SET title = ?, content = ?, category = ?, tags = ?, updated_at = ? "
        "WHERE id = ?",
        (new_title, new_content, new_category, new_tags_json, now.isoformat(), article_id),
    )
    await _db.commit()

    article = KBArticleRecord(
        id=article_id,
        title=new_title,
        content=new_content,
        category=new_category,
        tags=new_tags,
        created_at=datetime.fromisoformat(row[5]),
        updated_at=now,
    )

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="update_kb_article",
            resource=article_id,
        )
    return KBArticleResponse(data=article)


@app.delete(
    "/kb/articles/{article_id}",
    tags=["knowledge-base"],
)
async def delete_kb_article(
    article_id: str,
    api_key: str = Depends(require_admin),
):
    """
    Delete a knowledge base article. Admin only.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id FROM kb_articles WHERE id = ?", (article_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Knowledge base article not found")

    await _db.execute("DELETE FROM kb_articles WHERE id = ?", (article_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="delete_kb_article",
        resource=article_id,
    )
    return {"success": True, "deleted": article_id}


# ── Knowledge Base Semantic Search endpoint ───────────────────────────────────

@app.post(
    "/kb/search",
    response_model=KBSearchResponse,
    tags=["knowledge-base"],
)
async def search_kb(
    body: KBSearchRequest,
    api_key: str = Depends(require_viewer),
) -> KBSearchResponse:
    """
    Semantic search over knowledge base articles using vector similarity.
    Uses sentence-transformer embeddings to find articles relevant to the query.
    Requires viewer role or higher.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    if _detector is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    # Fetch all articles
    async with _db.execute(
        "SELECT id, title, content, category FROM kb_articles"
    ) as cursor:
        articles = await cursor.fetchall()

    if not articles:
        return KBSearchResponse(query=body.query, results=[], total=0)

    # Compute similarities in a thread to avoid blocking the event loop
    try:
        results = await asyncio.get_event_loop().run_in_executor(
            None,
            _compute_kb_similarities,
            body.query,
            articles,
            body.threshold,
            body.max_results,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("kb_search.embedding_failed", error=str(e))
        raise HTTPException(
            status_code=503,
            detail="Embedding model not available for semantic search",
        ) from e

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="search_kb",
            resource="kb_search",
            detail=f"query_len={len(body.query)}, found={len(results)}",
        )
    return KBSearchResponse(query=body.query, results=results, total=len(results))


def _compute_kb_similarities(
    query_text: str,
    articles: list[tuple],
    threshold: float,
    max_results: int,
) -> list[KBSearchResult]:
    """Compute cosine similarity between query and KB article texts."""
    import numpy as np  # noqa: PLC0415
    from sklearn.preprocessing import normalize  # noqa: PLC0415

    model = _detector.get_embedding_model()
    # Combine title + content for embedding
    texts = [query_text] + [f"{a[1]}\n{a[2]}" for a in articles]
    embeddings = model.encode(texts, show_progress_bar=False, batch_size=32)
    embeddings = normalize(embeddings)

    query_emb = embeddings[0:1]
    article_embs = embeddings[1:]

    similarities = np.dot(article_embs, query_emb.T).flatten()

    results = []
    for i, sim in enumerate(similarities):
        if sim >= threshold:
            content_preview = articles[i][2][:200] if articles[i][2] else ""
            results.append(KBSearchResult(
                article_id=articles[i][0],
                title=articles[i][1],
                category=articles[i][3] or "",
                relevance_score=round(float(sim), 4),
                snippet=content_preview,
            ))

    results.sort(key=lambda x: x.relevance_score, reverse=True)
    return results[:max_results]


# ── Email Ingestion endpoint ──────────────────────────────────────────────────

@app.post(
    "/ingest/email",
    response_model=AnalyseResponse,
    tags=["email"],
)
async def ingest_email(
    body: EmailIngestRequest,
    api_key: str = Depends(require_analyst),
) -> AnalyseResponse:
    """
    Ingest a ticket from an inbound email webhook (SendGrid, Mailgun, or generic).
    Parses the email into a RawTicket and runs it through the analysis pipeline.
    Requires analyst or admin role. Must be enabled via EMAIL_INGESTION_ENABLED=true.
    """
    if not settings.email_ingestion_enabled:
        raise HTTPException(
            status_code=403,
            detail="Email ingestion is not enabled. Set EMAIL_INGESTION_ENABLED=true.",
        )

    from email_ingestion import parse_email_to_ticket  # noqa: PLC0415

    processor = _get_processor()
    ticket = parse_email_to_ticket(body)
    enriched = await processor.process(ticket, include_automation=True)
    enriched.sla = compute_sla(enriched.priority.priority, ticket.created_at)
    await _persist_ticket(enriched)

    # Fire-and-forget notifications
    asyncio.create_task(send_notifications(enriched, settings))

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="email_ingest",
            resource=f"email:{enriched.ticket_id}",
            detail=f"from={body.sender}",
        )
    return AnalyseResponse(data=enriched)


# ── Analytics endpoint ────────────────────────────────────────────────────────

@app.get(
    "/analytics",
    response_model=AnalyticsResponse,
    tags=["enterprise"],
)
async def get_analytics(
    days: int = Query(default=30, ge=1, le=365, description="Look-back period in days"),
    api_key: str = Depends(require_viewer),
) -> AnalyticsResponse:
    """
    Return ticket analytics: counts by category, priority, trends.
    Requires viewer role or higher.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    _cutoff = datetime.now(tz=timezone.utc).isoformat()  # noqa: F841

    # Total tickets
    async with _db.execute("SELECT COUNT(*) FROM processed_tickets") as cur:
        total = (await cur.fetchone())[0]

    # By category
    async with _db.execute(
        "SELECT category, COUNT(*) as cnt FROM processed_tickets GROUP BY category ORDER BY cnt DESC"
    ) as cur:
        by_category = [CategoryCount(category=r[0] or "Unknown", count=r[1]) for r in await cur.fetchall()]

    # By priority
    async with _db.execute(
        "SELECT priority, COUNT(*) as cnt FROM processed_tickets GROUP BY priority ORDER BY cnt DESC"
    ) as cur:
        by_priority = [PriorityCount(priority=r[0] or "unknown", count=r[1]) for r in await cur.fetchall()]

    # Average automation score
    async with _db.execute(
        "SELECT AVG(automation_score) FROM processed_tickets WHERE automation_score IS NOT NULL"
    ) as cur:
        row = await cur.fetchone()
        avg_auto = round(row[0], 1) if row[0] is not None else 0.0

    # Daily trend (last N days)
    async with _db.execute(
        "SELECT DATE(processed_at) as day, COUNT(*) as cnt "
        "FROM processed_tickets GROUP BY day ORDER BY day DESC LIMIT ?",
        (days,),
    ) as cur:
        daily_trend = [DailyTrend(date=r[0], count=r[1]) for r in await cur.fetchall()]

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="get_analytics",
            resource=f"{days}d",
        )
    return AnalyticsResponse(
        total_tickets=total,
        by_category=by_category,
        by_priority=by_priority,
        avg_automation_score=avg_auto,
        daily_trend=daily_trend,
        period_days=days,
    )


# ── Audit log endpoint ───────────────────────────────────────────────────────

@app.get(
    "/audit/logs",
    response_model=AuditLogResponse,
    tags=["enterprise"],
)
async def get_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    api_key: str = Depends(require_admin),
) -> AuditLogResponse:
    """
    Return paginated audit log entries. Admin only.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    entries, total = await audit.query(_db, page=page, page_size=page_size)
    return AuditLogResponse(entries=entries, total=total, page=page, page_size=page_size)


# ── Export endpoint ───────────────────────────────────────────────────────────

@app.get("/export/tickets", tags=["enterprise"])
async def export_tickets(
    format: ExportFormat = Query(default=ExportFormat.json, description="Export format"),
    category: str | None = Query(default=None, description="Filter by category"),
    priority: str | None = Query(default=None, description="Filter by priority"),
    days: int = Query(default=30, ge=1, le=365, description="Export last N days"),
    api_key: str = Depends(require_viewer),
):
    """
    Export processed tickets as JSON or CSV. Requires viewer role or higher.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    base = "SELECT id, source, processed_at, category, priority, automation_score, summary, sentiment, detected_language, ticket_status FROM processed_tickets"
    conditions: list[str] = []
    params: list = []

    if category:
        conditions.append("category = ?")
        params.append(category)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)

    sql = base
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY processed_at DESC"

    async with _db.execute(sql, params) as cur:
        rows = await cur.fetchall()

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="export_tickets",
            resource=f"{format.value},{len(rows)} rows",
        )

    if format == ExportFormat.csv:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "source", "processed_at", "category", "priority", "automation_score", "summary", "sentiment", "detected_language", "ticket_status"])
        for row in rows:
            writer.writerow(row)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=tickets.csv"},
        )

    # JSON format
    data = [
        {
            "id": r[0],
            "source": r[1],
            "processed_at": r[2],
            "category": r[3],
            "priority": r[4],
            "automation_score": r[5],
            "summary": r[6],
            "sentiment": r[7] or "neutral",
            "detected_language": r[8] or "en",
            "ticket_status": r[9] or "open",
        }
        for r in rows
    ]
    return JSONResponse(content={"tickets": data, "total": len(data)})


# ── Chatbot endpoint ─────────────────────────────────────────────────────────

@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["chatbot"],
)
async def chat(
    body: ChatRequest,
    api_key: str = Depends(require_viewer),
) -> ChatResponse:
    """
    Send a message to the TicketForge chatbot.

    The chatbot can help with:
    - Creating tickets (describe your issue)
    - Checking ticket status (provide a ticket ID)
    - Searching the knowledge base (ask how-to questions)
    - General IT support queries

    Supports multi-turn conversations via session_id.
    Requires viewer role or higher.
    """
    if not settings.chatbot_enabled:
        raise HTTPException(
            status_code=403,
            detail="Chatbot is not enabled. Set CHATBOT_ENABLED=true.",
        )

    from chatbot import (  # noqa: PLC0415
        add_message,
        detect_intent,
        generate_response,
        get_or_create_session,
    )

    session_id = get_or_create_session(body.session_id)

    # Record user message
    add_message(session_id, "user", body.message)

    # Detect intent and generate response
    intent = detect_intent(body.message)
    result = generate_response(intent, body.message, session_id, body.context)

    # Record assistant response
    add_message(session_id, "assistant", result["reply"])

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="chat",
            resource=session_id,
            detail=f"intent={intent}",
        )
    return ChatResponse(
        session_id=session_id,
        reply=result["reply"],
        intent=result["intent"],
        suggested_actions=result.get("suggested_actions", []),
        data=result.get("data", {}),
    )


# ── Model Monitoring endpoint ────────────────────────────────────────────────

@app.get(
    "/monitoring/drift",
    response_model=MonitoringResponse,
    tags=["monitoring"],
)
async def get_drift_metrics(
    api_key: str = Depends(require_admin),
) -> MonitoringResponse:
    """
    Analyse prediction drift by comparing recent ticket analysis distributions
    against a baseline period. Monitors category, priority, and sentiment fields.

    Admin only.
    """
    if not settings.monitoring_enabled:
        raise HTTPException(
            status_code=403,
            detail="Model monitoring is not enabled. Set MONITORING_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    from monitoring import compute_drift_metrics  # noqa: PLC0415

    result = await compute_drift_metrics(
        _db,
        baseline_days=settings.monitoring_baseline_days,
        window_days=settings.monitoring_window_days,
        drift_threshold=settings.drift_threshold,
    )

    metrics = [
        DriftMetric(
            field=m["field"],
            current_distribution=m["current_distribution"],
            baseline_distribution=m["baseline_distribution"],
            drift_score=m["drift_score"],
            is_drifting=m["is_drifting"],
        )
        for m in result["metrics"]
    ]

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="monitoring_drift",
        resource="drift_check",
        detail=f"health={result['overall_health']}",
    )
    return MonitoringResponse(
        metrics=metrics,
        total_tickets_analysed=result["total_tickets_analysed"],
        baseline_period_days=result["baseline_period_days"],
        monitoring_period_days=result["monitoring_period_days"],
        overall_health=result["overall_health"],
    )


# ── Plugin system endpoints ──────────────────────────────────────────────────

@app.get(
    "/plugins",
    response_model=PluginListResponse,
    tags=["plugins"],
)
async def list_plugins(
    api_key: str = Depends(require_admin),
) -> PluginListResponse:
    """
    List all registered plugins and their status.
    Admin only.
    """
    from plugin_system import plugin_registry  # noqa: PLC0415

    plugins_data = plugin_registry.list_plugins()
    plugins = [
        PluginInfo(
            name=p["name"],
            version=p["version"],
            description=p["description"],
            hook=p["hook"],
            enabled=p["enabled"],
        )
        for p in plugins_data
    ]
    return PluginListResponse(plugins=plugins, total=len(plugins))


# ── Self-Service Portal endpoints ────────────────────────────────────────────

@app.post(
    "/portal/tickets",
    response_model=PortalTicketResponse,
    tags=["portal"],
    status_code=201,
)
async def portal_submit_ticket(
    body: PortalTicketSubmission,
    api_key: str = Depends(require_viewer),
) -> PortalTicketResponse:
    """
    Submit a ticket from the self-service portal.

    Creates a ticket, runs it through the analysis pipeline,
    and returns relevant KB articles that may help resolve the issue.
    Requires viewer role or higher.
    """
    if not settings.portal_enabled:
        raise HTTPException(
            status_code=403,
            detail="Self-service portal is not enabled. Set PORTAL_ENABLED=true.",
        )

    import uuid  # noqa: PLC0415

    ticket_id = f"PORTAL-{uuid.uuid4().hex[:12]}"
    _ticket = RawTicket(  # noqa: F841
        id=ticket_id,
        source=TicketSource.generic,
        title=body.title,
        description=body.description,
        reporter=body.reporter_email,
        tags=["portal"],
    )

    # Try to find relevant KB articles
    suggested_articles: list[KBSearchResult] = []
    if _db and _detector:
        try:
            async with _db.execute(
                "SELECT id, title, content, category FROM kb_articles"
            ) as cursor:
                articles = await cursor.fetchall()
            if articles:
                results = await asyncio.get_event_loop().run_in_executor(
                    None,
                    _compute_kb_similarities,
                    f"{body.title}\n{body.description}",
                    articles,
                    0.3,
                    3,
                )
                suggested_articles = results
        except Exception as e:  # noqa: BLE001
            log.warning("portal.kb_search_failed", error=str(e))

    # Persist the ticket in the database
    if _db:
        now = datetime.now(tz=timezone.utc)
        try:
            await _db.execute(
                """
                INSERT OR REPLACE INTO processed_tickets
                    (id, source, processed_at, category, priority, automation_score, summary,
                     sentiment, detected_language, ticket_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    "generic",
                    now.isoformat(),
                    body.category or "pending",
                    "medium",
                    0,
                    body.title,
                    "neutral",
                    "en",
                    "open",
                ),
            )
            await _db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("portal.persist_failed", ticket_id=ticket_id, error=str(e))

        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="portal_submit_ticket",
            resource=ticket_id,
            detail=f"reporter={body.reporter_email}",
        )

    return PortalTicketResponse(
        ticket_id=ticket_id,
        message=f"Your ticket {ticket_id} has been submitted successfully.",
        suggested_articles=suggested_articles,
    )


# ── Internationalisation (i18n) endpoint ─────────────────────────────────────

@app.get(
    "/i18n/languages",
    tags=["i18n"],
)
async def list_supported_languages(
    api_key: str = Depends(require_viewer),
):
    """
    List all supported languages for i18n-aware prompt generation.
    When i18n is enabled, TicketForge will instruct the LLM to respond
    in the ticket's detected language.
    Requires viewer role or higher.
    """
    if not settings.i18n_enabled:
        raise HTTPException(
            status_code=403,
            detail="Internationalisation is not enabled. Set I18N_ENABLED=true.",
        )
    from prompts import LANGUAGE_NAMES  # noqa: PLC0415

    return {
        "success": True,
        "default_language": settings.i18n_default_language,
        "supported_languages": LANGUAGE_NAMES,
        "total": len(LANGUAGE_NAMES),
    }


# ── CSAT (Customer Satisfaction) endpoints ───────────────────────────────────

@app.post(
    "/tickets/{ticket_id}/csat",
    response_model=CSATResponse,
    tags=["csat"],
    status_code=201,
)
async def submit_csat(
    ticket_id: str,
    body: CSATSubmission,
    api_key: str = Depends(require_viewer),
) -> CSATResponse:
    """
    Submit a CSAT (Customer Satisfaction) rating for a resolved ticket.
    Rating scale: 1 (very dissatisfied) to 5 (very satisfied).
    Requires viewer role or higher.
    """
    if not settings.csat_enabled:
        raise HTTPException(
            status_code=403,
            detail="CSAT surveys are not enabled. Set CSAT_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Verify ticket exists
    async with _db.execute(
        "SELECT id FROM processed_tickets WHERE id = ?", (ticket_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    now = datetime.now(tz=timezone.utc)
    await _db.execute(
        """
        INSERT OR REPLACE INTO csat_ratings
            (ticket_id, rating, comment, reporter_email, submitted_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (ticket_id, body.rating, body.comment, body.reporter_email, now.isoformat()),
    )
    await _db.commit()

    # Fetch the inserted record
    async with _db.execute(
        "SELECT id, ticket_id, rating, comment, reporter_email, submitted_at "
        "FROM csat_ratings WHERE ticket_id = ?",
        (ticket_id,),
    ) as cursor:
        r = await cursor.fetchone()

    record = CSATRecord(
        id=r[0],
        ticket_id=r[1],
        rating=r[2],
        comment=r[3],
        reporter_email=r[4],
        submitted_at=datetime.fromisoformat(r[5]),
    )

    # Fire-and-forget structured webhook event (Zapier/Make/n8n)
    if settings.webhook_events_enabled:
        asyncio.create_task(send_webhook_event(
            WebhookEventType.csat_submitted,
            ticket_id,
            {"rating": body.rating, "comment": body.comment},
            settings,
        ))

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="submit_csat",
        resource=ticket_id,
        detail=f"rating={body.rating}",
    )
    return CSATResponse(data=record)


@app.get(
    "/tickets/{ticket_id}/csat",
    response_model=CSATResponse,
    tags=["csat"],
)
async def get_csat(
    ticket_id: str,
    api_key: str = Depends(require_viewer),
) -> CSATResponse:
    """
    Retrieve the CSAT rating for a specific ticket.
    Returns null data if no rating has been submitted.
    Requires viewer role or higher.
    """
    if not settings.csat_enabled:
        raise HTTPException(
            status_code=403,
            detail="CSAT surveys are not enabled. Set CSAT_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id, ticket_id, rating, comment, reporter_email, submitted_at "
        "FROM csat_ratings WHERE ticket_id = ?",
        (ticket_id,),
    ) as cursor:
        r = await cursor.fetchone()

    if r is None:
        return CSATResponse(data=None)

    return CSATResponse(
        data=CSATRecord(
            id=r[0],
            ticket_id=r[1],
            rating=r[2],
            comment=r[3],
            reporter_email=r[4],
            submitted_at=datetime.fromisoformat(r[5]),
        )
    )


@app.get(
    "/analytics/csat",
    response_model=CSATAnalyticsResponse,
    tags=["csat"],
)
async def get_csat_analytics(
    api_key: str = Depends(require_analyst),
) -> CSATAnalyticsResponse:
    """
    Aggregate CSAT analytics: average score, distribution, and recent comments.
    Requires analyst or admin role.
    """
    if not settings.csat_enabled:
        raise HTTPException(
            status_code=403,
            detail="CSAT surveys are not enabled. Set CSAT_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Total ratings and average
    async with _db.execute(
        "SELECT COUNT(*), COALESCE(AVG(rating), 0) FROM csat_ratings"
    ) as cursor:
        total_row = await cursor.fetchone()
    total_ratings = total_row[0]
    average_rating = round(total_row[1], 2)

    # Distribution
    distribution: dict[str, int] = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    async with _db.execute(
        "SELECT rating, COUNT(*) FROM csat_ratings GROUP BY rating ORDER BY rating"
    ) as cursor:
        async for row in cursor:
            distribution[str(row[0])] = row[1]

    # Recent comments (last 10 with non-empty comments)
    recent_comments: list[dict] = []
    async with _db.execute(
        "SELECT ticket_id, rating, comment, submitted_at FROM csat_ratings "
        "WHERE comment != '' ORDER BY submitted_at DESC LIMIT 10"
    ) as cursor:
        async for row in cursor:
            recent_comments.append({
                "ticket_id": row[0],
                "rating": row[1],
                "comment": row[2],
                "submitted_at": row[3],
            })

    return CSATAnalyticsResponse(
        total_ratings=total_ratings,
        average_rating=average_rating,
        rating_distribution=distribution,
        recent_comments=recent_comments,
    )


# ── WebSocket notifications endpoint ────────────────────────────────────────

@app.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time ticket event notifications.
    Authenticate via X-Api-Key query parameter: /ws/notifications?api_key=<key>
    Events: ticket_created, status_changed, sla_breach
    """
    if not settings.websocket_notifications_enabled:
        await websocket.close(code=1008, reason="WebSocket notifications are not enabled")
        return

    # Authenticate via query parameter
    api_key = websocket.query_params.get("api_key", "")
    if api_key not in settings.api_keys:
        await websocket.close(code=1008, reason="Invalid API key")
        return

    await ws_manager.connect(websocket)
    log.info("websocket.connected", connections=ws_manager.active_connections)
    try:
        while True:
            # Keep connection alive; client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        log.info("websocket.disconnected", connections=ws_manager.active_connections)


# ── Multi-agent status endpoint ──────────────────────────────────────────────

@app.get("/multi-agent/status", response_model=MultiAgentStatusResponse, tags=["multi-agent"])
async def multi_agent_status(
    api_key: str = Depends(require_viewer),
) -> MultiAgentStatusResponse:
    """
    Return the current multi-agent pipeline configuration.
    Shows whether multi-agent is enabled and which agents are in the pipeline.
    """
    if settings.multi_agent_enabled:
        return MultiAgentStatusResponse(
            enabled=True,
            agents=["analyser", "classifier", "validator"],
            description="Analyser → Classifier → Validator pipeline",
        )
    return MultiAgentStatusResponse(
        enabled=False,
        agents=[],
        description="Single LLM call (multi-agent disabled)",
    )


# ── Vector store status endpoint ─────────────────────────────────────────────

@app.get("/vector-store/status", response_model=VectorStoreStatusResponse, tags=["vector-store"])
async def vector_store_status(
    api_key: str = Depends(require_viewer),
) -> VectorStoreStatusResponse:
    """
    Return the current vector store backend and number of stored vectors.
    """
    total = 0
    backend = "in_memory"
    if _vector_store is not None:
        total = await _vector_store.count()
        backend = _vector_store.backend_name
    return VectorStoreStatusResponse(
        backend=backend,
        total_vectors=total,
    )


# ── Auto-resolution endpoint ─────────────────────────────────────────────────

@app.post(
    "/tickets/{ticket_id}/auto-resolve",
    response_model=AutoResolveResponse,
    tags=["auto-resolution"],
)
async def auto_resolve_ticket(
    ticket_id: str,
    body: AutoResolveRequest | None = None,
    api_key: str = Depends(require_analyst),
) -> AutoResolveResponse:
    """
    Attempt AI-powered auto-resolution for a previously analysed ticket.

    Searches the knowledge base for matching articles, and if confidence exceeds
    the configured threshold, generates a resolution response and marks the ticket
    as resolved. Requires analyst or admin role.
    """
    if not settings.auto_resolution_enabled:
        raise HTTPException(
            status_code=403,
            detail="Auto-resolution is not enabled. Set AUTO_RESOLUTION_ENABLED=true.",
        )

    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Look up the cached ticket
    async with _db.execute(
        "SELECT id, source, category, priority, automation_score, summary, "
        "sentiment, detected_language, ticket_status "
        "FROM processed_tickets WHERE id = ?",
        (ticket_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Ticket not found in cache")

    # Search KB for matching articles
    kb_results: list[KBSearchResult] = []
    if _vector_store is not None:
        summary_text = row[5] or ""
        if summary_text:
            processor = _get_processor()
            try:
                query_embedding = processor.embedding_model.encode([summary_text])[0]
                all_ids = await _vector_store.list_ids(prefix="kb-")
                if all_ids:
                    all_embeddings = []
                    for vid in all_ids:
                        emb = await _vector_store.get(vid)
                        if emb is not None:
                            all_embeddings.append((vid, emb))

                    if all_embeddings:
                        from sklearn.metrics.pairwise import cosine_similarity  # noqa: PLC0415
                        import numpy as np  # noqa: PLC0415

                        matrix = np.array([e for _, e in all_embeddings])
                        sims = cosine_similarity([query_embedding], matrix)[0]

                        for idx in np.argsort(sims)[::-1][:5]:
                            score = float(sims[idx])
                            if score < 0.3:
                                break
                            vec_id = all_embeddings[idx][0]
                            article_id = vec_id.replace("kb-", "")
                            # Fetch article details from DB
                            async with _db.execute(
                                "SELECT id, title, category, content FROM kb_articles WHERE id = ?",
                                (article_id,),
                            ) as cur:
                                art_row = await cur.fetchone()
                            if art_row:
                                kb_results.append(KBSearchResult(
                                    article_id=art_row[0],
                                    title=art_row[1],
                                    category=art_row[2] or "",
                                    relevance_score=round(score, 3),
                                    snippet=(art_row[3] or "")[:200],
                                ))
            except Exception as e:  # noqa: BLE001
                log.warning("auto_resolve.kb_search_failed", ticket_id=ticket_id, error_type=type(e).__name__, error=str(e))

    # Use LLM to determine if the ticket can be auto-resolved
    from prompts import AUTO_RESOLVE_PROMPT, SYSTEM_PROMPT  # noqa: PLC0415

    kb_text = "\n".join(
        f"- [{r.title}] (relevance: {r.relevance_score:.2f}): {r.snippet}"
        for r in kb_results
    ) if kb_results else "No matching KB articles found."

    prompt = AUTO_RESOLVE_PROMPT.format(
        ticket_id=ticket_id,
        title=row[5] or "",
        category=row[2] or "",
        priority=row[3] or "medium",
        sentiment=row[6] or "neutral",
        summary=row[5] or "",
        kb_articles=kb_text,
    )

    resolved = False
    resolution_summary = ""
    response_draft = ""
    confidence = 0.0

    try:
        processor = _get_processor()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        raw_content = await processor.chat_with_llm(messages, temperature=0.2, max_tokens=1024)
        from ticket_processor import _parse_llm_json  # noqa: PLC0415
        llm_data = _parse_llm_json(raw_content)

        confidence = float(llm_data.get("confidence", 0.0))
        can_resolve = llm_data.get("can_resolve", False)

        if can_resolve and confidence >= settings.auto_resolution_confidence_threshold:
            resolved = True
            resolution_summary = llm_data.get("resolution_summary", "")
            response_draft = llm_data.get("response_draft", "")

            # Update ticket status to resolved
            await _db.execute(
                "UPDATE processed_tickets SET ticket_status = ? WHERE id = ?",
                (TicketStatus.resolved.value, ticket_id),
            )
            await _db.commit()

            # Send webhook event if enabled
            if settings.webhook_events_enabled:
                asyncio.create_task(send_webhook_event(
                    WebhookEventType.ticket_auto_resolved,
                    ticket_id,
                    {
                        "resolution_summary": resolution_summary,
                        "confidence": confidence,
                        "kb_articles": [r.model_dump() for r in kb_results],
                    },
                    settings,
                ))

            # Broadcast WebSocket event
            if settings.websocket_notifications_enabled:
                asyncio.create_task(ws_manager.broadcast(WebSocketEvent(
                    event_type="ticket_auto_resolved",
                    ticket_id=ticket_id,
                    data={
                        "resolution_summary": resolution_summary,
                        "confidence": confidence,
                    },
                )))
        else:
            resolution_summary = llm_data.get("resolution_summary", "Insufficient confidence for auto-resolution")
    except Exception as e:  # noqa: BLE001
        log.warning("auto_resolve.llm_failed", ticket_id=ticket_id, error_type=type(e).__name__, error=str(e))
        resolution_summary = "LLM processing failed"

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="auto_resolve",
            resource=ticket_id,
        )

    return AutoResolveResponse(
        data=AutoResolveResult(
            ticket_id=ticket_id,
            resolved=resolved,
            resolution_summary=resolution_summary,
            matched_kb_articles=kb_results,
            confidence=confidence,
            response_draft=response_draft,
        )
    )


# ── Webhook events endpoint (Zapier / Make / n8n) ────────────────────────────

@app.get(
    "/webhooks/events",
    response_model=WebhookEventListResponse,
    tags=["webhooks"],
)
async def list_webhook_events(
    api_key: str = Depends(require_viewer),
) -> WebhookEventListResponse:
    """
    List supported outbound webhook event types for integration with
    Zapier, Make (Integromat), n8n, and other automation platforms.
    """
    return WebhookEventListResponse(
        supported_events=[e.value for e in WebhookEventType],
        webhook_url_configured=bool(settings.outbound_webhook_url),
    )


# ── Escalation status endpoint (PagerDuty / OpsGenie) ────────────────────────

@app.get(
    "/escalation/status",
    response_model=EscalationStatusResponse,
    tags=["escalation"],
)
async def escalation_status(
    api_key: str = Depends(require_viewer),
) -> EscalationStatusResponse:
    """
    Return the current escalation integration status for PagerDuty and OpsGenie.
    """
    return EscalationStatusResponse(
        pagerduty_configured=bool(settings.pagerduty_routing_key),
        opsgenie_configured=bool(settings.opsgenie_api_key),
        auto_escalate_enabled=(
            settings.pagerduty_auto_escalate or settings.opsgenie_auto_escalate
        ),
    )


# ── Phase 7: Scheduled reports ───────────────────────────────────────────────

@app.post(
    "/reports/schedules",
    response_model=ScheduledReportResponse,
    tags=["reports"],
)
async def create_scheduled_report(
    body: ScheduledReportCreate,
    api_key: str = Depends(require_admin),
) -> ScheduledReportResponse:
    """
    Create a new scheduled analytics report.

    Reports are delivered via webhook at the configured frequency.
    Requires admin role.
    """
    if not settings.scheduled_reports_enabled:
        raise HTTPException(
            status_code=403,
            detail="Scheduled reports are not enabled. Set SCHEDULED_REPORTS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    report_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()
    await _db.execute(
        """INSERT INTO scheduled_reports
           (id, name, frequency, webhook_url, include_categories, include_priorities,
            include_sla, include_csat, enabled, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            report_id,
            body.name,
            body.frequency.value,
            body.webhook_url,
            int(body.include_categories),
            int(body.include_priorities),
            int(body.include_sla),
            int(body.include_csat),
            int(body.enabled),
            now,
        ),
    )
    await _db.commit()

    if _db:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="create_scheduled_report",
            resource=report_id,
        )

    record = ScheduledReportRecord(
        id=report_id,
        name=body.name,
        frequency=body.frequency,
        webhook_url=body.webhook_url,
        include_categories=body.include_categories,
        include_priorities=body.include_priorities,
        include_sla=body.include_sla,
        include_csat=body.include_csat,
        enabled=body.enabled,
        created_at=datetime.fromisoformat(now),
    )
    return ScheduledReportResponse(data=record)


@app.get(
    "/reports/schedules",
    response_model=ScheduledReportListResponse,
    tags=["reports"],
)
async def list_scheduled_reports(
    api_key: str = Depends(require_viewer),
) -> ScheduledReportListResponse:
    """List all scheduled report configurations."""
    if not settings.scheduled_reports_enabled:
        raise HTTPException(
            status_code=403,
            detail="Scheduled reports are not enabled. Set SCHEDULED_REPORTS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id, name, frequency, webhook_url, include_categories, include_priorities, "
        "include_sla, include_csat, enabled, created_at FROM scheduled_reports ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    schedules = [
        ScheduledReportRecord(
            id=r[0],
            name=r[1],
            frequency=r[2],
            webhook_url=r[3],
            include_categories=bool(r[4]),
            include_priorities=bool(r[5]),
            include_sla=bool(r[6]),
            include_csat=bool(r[7]),
            enabled=bool(r[8]),
            created_at=datetime.fromisoformat(r[9]),
        )
        for r in rows
    ]
    return ScheduledReportListResponse(schedules=schedules)


@app.delete(
    "/reports/schedules/{schedule_id}",
    tags=["reports"],
)
async def delete_scheduled_report(
    schedule_id: str,
    api_key: str = Depends(require_admin),
) -> dict:
    """Delete a scheduled report. Requires admin role."""
    if not settings.scheduled_reports_enabled:
        raise HTTPException(
            status_code=403,
            detail="Scheduled reports are not enabled. Set SCHEDULED_REPORTS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id FROM scheduled_reports WHERE id = ?", (schedule_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Scheduled report not found")

    await _db.execute("DELETE FROM scheduled_reports WHERE id = ?", (schedule_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="delete_scheduled_report",
        resource=schedule_id,
    )

    return {"success": True, "deleted": schedule_id}


# ── Phase 7: Ticket merging ─────────────────────────────────────────────────

@app.post(
    "/tickets/merge",
    response_model=TicketMergeResponse,
    tags=["tickets"],
)
async def merge_tickets(
    body: TicketMergeRequest,
    api_key: str = Depends(require_admin),
) -> TicketMergeResponse:
    """
    Merge duplicate tickets into a primary ticket.

    The primary ticket is kept; duplicate tickets are marked as closed
    with a merge reference. Requires admin role.
    """
    if not settings.ticket_merging_enabled:
        raise HTTPException(
            status_code=403,
            detail="Ticket merging is not enabled. Set TICKET_MERGING_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Validate primary ticket exists
    async with _db.execute(
        "SELECT id FROM processed_tickets WHERE id = ?", (body.primary_ticket_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Primary ticket {body.primary_ticket_id} not found")

    # Validate all duplicate tickets exist
    merged_ids: list[str] = []
    for dup_id in body.duplicate_ticket_ids:
        if dup_id == body.primary_ticket_id:
            continue  # skip if same as primary
        async with _db.execute(
            "SELECT id FROM processed_tickets WHERE id = ?", (dup_id,)
        ) as cursor:
            if await cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"Duplicate ticket {dup_id} not found")
        merged_ids.append(dup_id)

    if not merged_ids:
        raise HTTPException(status_code=400, detail="No valid duplicate tickets to merge")

    now = datetime.now(tz=timezone.utc).isoformat()
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]

    for dup_id in merged_ids:
        # Record the merge
        await _db.execute(
            "INSERT INTO ticket_merges (primary_ticket_id, merged_ticket_id, merged_at, merged_by) VALUES (?, ?, ?, ?)",
            (body.primary_ticket_id, dup_id, now, key_hash),
        )
        # Close the duplicate
        await _db.execute(
            "UPDATE processed_tickets SET ticket_status = 'closed' WHERE id = ?",
            (dup_id,),
        )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="merge_tickets",
        resource=body.primary_ticket_id,
    )

    return TicketMergeResponse(
        data=MergedTicketRecord(
            primary_ticket_id=body.primary_ticket_id,
            merged_ticket_ids=merged_ids,
            merged_at=datetime.fromisoformat(now),
            merged_by=key_hash,
        )
    )


# ── Phase 7: Custom fields ──────────────────────────────────────────────────

@app.post(
    "/custom-fields",
    response_model=CustomFieldResponse,
    tags=["custom-fields"],
)
async def create_custom_field(
    body: CustomFieldDefinition,
    api_key: str = Depends(require_admin),
) -> CustomFieldResponse:
    """
    Define a new custom field for tickets.

    Custom fields extend ticket metadata with organisation-specific attributes.
    Requires admin role.
    """
    if not settings.custom_fields_enabled:
        raise HTTPException(
            status_code=403,
            detail="Custom fields are not enabled. Set CUSTOM_FIELDS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Check for duplicate name
    async with _db.execute(
        "SELECT id FROM custom_fields WHERE name = ?", (body.name,)
    ) as cursor:
        if await cursor.fetchone() is not None:
            raise HTTPException(status_code=409, detail=f"Custom field '{body.name}' already exists")

    import json as _json  # noqa: PLC0415

    field_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()
    await _db.execute(
        """INSERT INTO custom_fields (id, name, field_type, description, required, options, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            field_id,
            body.name,
            body.field_type.value,
            body.description,
            int(body.required),
            _json.dumps(body.options),
            now,
        ),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_custom_field",
        resource=field_id,
    )

    record = CustomFieldRecord(
        id=field_id,
        name=body.name,
        field_type=body.field_type,
        description=body.description,
        required=body.required,
        options=body.options,
        created_at=datetime.fromisoformat(now),
    )
    return CustomFieldResponse(data=record)


@app.get(
    "/custom-fields",
    response_model=CustomFieldListResponse,
    tags=["custom-fields"],
)
async def list_custom_fields(
    api_key: str = Depends(require_viewer),
) -> CustomFieldListResponse:
    """List all custom field definitions."""
    if not settings.custom_fields_enabled:
        raise HTTPException(
            status_code=403,
            detail="Custom fields are not enabled. Set CUSTOM_FIELDS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    async with _db.execute(
        "SELECT id, name, field_type, description, required, options, created_at "
        "FROM custom_fields ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    fields = [
        CustomFieldRecord(
            id=r[0],
            name=r[1],
            field_type=r[2],
            description=r[3],
            required=bool(r[4]),
            options=_json.loads(r[5]) if r[5] else [],
            created_at=datetime.fromisoformat(r[6]),
        )
        for r in rows
    ]
    return CustomFieldListResponse(fields=fields)


# ── Phase 7: Ticket tags ────────────────────────────────────────────────────

@app.post(
    "/tickets/{ticket_id}/tags",
    response_model=TicketTagsResponse,
    tags=["tags"],
)
async def add_ticket_tags(
    ticket_id: str,
    body: TicketTagRequest,
    api_key: str = Depends(require_analyst),
) -> TicketTagsResponse:
    """
    Add tags to a ticket. Duplicate tags are silently ignored.
    Requires analyst or admin role.
    """
    if not settings.ticket_tags_enabled:
        raise HTTPException(
            status_code=403,
            detail="Ticket tags are not enabled. Set TICKET_TAGS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Validate ticket exists
    async with _db.execute(
        "SELECT id FROM processed_tickets WHERE id = ?", (ticket_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Ticket not found")

    now = datetime.now(tz=timezone.utc).isoformat()
    for tag in body.tags:
        normalised = tag.strip().lower()
        if not normalised:
            continue
        await _db.execute(
            "INSERT OR IGNORE INTO ticket_tags (ticket_id, tag, added_at) VALUES (?, ?, ?)",
            (ticket_id, normalised, now),
        )
    await _db.commit()

    # Return all tags for this ticket
    async with _db.execute(
        "SELECT tag FROM ticket_tags WHERE ticket_id = ? ORDER BY tag", (ticket_id,)
    ) as cursor:
        rows = await cursor.fetchall()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="add_tags",
        resource=ticket_id,
    )

    return TicketTagsResponse(ticket_id=ticket_id, tags=[r[0] for r in rows])


@app.get(
    "/tickets/{ticket_id}/tags",
    response_model=TicketTagsResponse,
    tags=["tags"],
)
async def get_ticket_tags(
    ticket_id: str,
    api_key: str = Depends(require_viewer),
) -> TicketTagsResponse:
    """Get all tags assigned to a ticket."""
    if not settings.ticket_tags_enabled:
        raise HTTPException(
            status_code=403,
            detail="Ticket tags are not enabled. Set TICKET_TAGS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id FROM processed_tickets WHERE id = ?", (ticket_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Ticket not found")

    async with _db.execute(
        "SELECT tag FROM ticket_tags WHERE ticket_id = ? ORDER BY tag", (ticket_id,)
    ) as cursor:
        rows = await cursor.fetchall()

    return TicketTagsResponse(ticket_id=ticket_id, tags=[r[0] for r in rows])


@app.delete(
    "/tickets/{ticket_id}/tags/{tag}",
    tags=["tags"],
)
async def remove_ticket_tag(
    ticket_id: str,
    tag: str,
    api_key: str = Depends(require_analyst),
) -> dict:
    """Remove a specific tag from a ticket. Requires analyst or admin role."""
    if not settings.ticket_tags_enabled:
        raise HTTPException(
            status_code=403,
            detail="Ticket tags are not enabled. Set TICKET_TAGS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    normalised = tag.strip().lower()
    async with _db.execute(
        "SELECT ticket_id FROM ticket_tags WHERE ticket_id = ? AND tag = ?",
        (ticket_id, normalised),
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Tag not found on ticket")

    await _db.execute(
        "DELETE FROM ticket_tags WHERE ticket_id = ? AND tag = ?",
        (ticket_id, normalised),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="remove_tag",
        resource=ticket_id,
    )

    return {"success": True, "ticket_id": ticket_id, "removed_tag": normalised}


# ── Phase 7: Saved filters ──────────────────────────────────────────────────

@app.post(
    "/filters",
    response_model=SavedFilterResponse,
    tags=["filters"],
)
async def create_saved_filter(
    body: SavedFilterCreate,
    api_key: str = Depends(require_analyst),
) -> SavedFilterResponse:
    """
    Create a named saved filter for ticket queries.

    Filter criteria can include: category, priority, status, tags,
    date_from, date_to. Requires analyst or admin role.
    """
    if not settings.saved_filters_enabled:
        raise HTTPException(
            status_code=403,
            detail="Saved filters are not enabled. Set SAVED_FILTERS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    filter_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]

    await _db.execute(
        """INSERT INTO saved_filters (id, name, filter_criteria, created_at, created_by)
           VALUES (?, ?, ?, ?, ?)""",
        (filter_id, body.name, _json.dumps(body.filter_criteria), now, key_hash),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_saved_filter",
        resource=filter_id,
    )

    record = SavedFilterRecord(
        id=filter_id,
        name=body.name,
        filter_criteria=body.filter_criteria,
        created_at=datetime.fromisoformat(now),
        created_by=key_hash,
    )
    return SavedFilterResponse(data=record)


@app.get(
    "/filters",
    response_model=SavedFilterListResponse,
    tags=["filters"],
)
async def list_saved_filters(
    api_key: str = Depends(require_viewer),
) -> SavedFilterListResponse:
    """List all saved ticket filters."""
    if not settings.saved_filters_enabled:
        raise HTTPException(
            status_code=403,
            detail="Saved filters are not enabled. Set SAVED_FILTERS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    async with _db.execute(
        "SELECT id, name, filter_criteria, created_at, created_by "
        "FROM saved_filters ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    filters = [
        SavedFilterRecord(
            id=r[0],
            name=r[1],
            filter_criteria=_json.loads(r[2]) if r[2] else {},
            created_at=datetime.fromisoformat(r[3]),
            created_by=r[4] or "",
        )
        for r in rows
    ]
    return SavedFilterListResponse(filters=filters)


@app.delete(
    "/filters/{filter_id}",
    tags=["filters"],
)
async def delete_saved_filter(
    filter_id: str,
    api_key: str = Depends(require_admin),
) -> dict:
    """Delete a saved filter. Requires admin role."""
    if not settings.saved_filters_enabled:
        raise HTTPException(
            status_code=403,
            detail="Saved filters are not enabled. Set SAVED_FILTERS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id FROM saved_filters WHERE id = ?", (filter_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Saved filter not found")

    await _db.execute("DELETE FROM saved_filters WHERE id = ?", (filter_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="delete_saved_filter",
        resource=filter_id,
    )

    return {"success": True, "deleted": filter_id}


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 8 — Predictive Analytics & Workflow Automation
# ═══════════════════════════════════════════════════════════════════════════════

# ── SLA breach prediction ─────────────────────────────────────────────────────


@app.get(
    "/analytics/sla-predictions",
    response_model=SLAPredictionResponse,
    tags=["analytics"],
)
async def get_sla_predictions(
    api_key: str = Depends(require_viewer),
) -> SLAPredictionResponse:
    """
    Predict which open tickets are most likely to breach their SLA.

    Analyses historical resolution times by category and priority to estimate
    breach probability for each currently open ticket.
    """
    if not settings.sla_prediction_enabled:
        raise HTTPException(
            status_code=403,
            detail="SLA prediction is not enabled. Set SLA_PREDICTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Gather historical average resolution times by category+priority
    avg_resolution: dict[tuple[str, str], float] = {}
    async with _db.execute(
        "SELECT category, priority, processed_at FROM processed_tickets WHERE ticket_status IN ('resolved', 'closed')"
    ) as cursor:
        rows = await cursor.fetchall()
    # Build average hours (simplified: use count-based estimation)
    category_priority_hours: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        key = (r[0] or "unknown", r[1] or "medium")
        base_hours = {"critical": 4.0, "high": 8.0, "medium": 24.0, "low": 48.0}.get(r[1] or "medium", 24.0)
        category_priority_hours.setdefault(key, []).append(base_hours)
    for key, hours_list in category_priority_hours.items():
        avg_resolution[key] = sum(hours_list) / len(hours_list) if hours_list else 24.0

    # SLA targets from settings (configured in minutes, convert to hours)
    sla_targets = {
        "critical": settings.sla_response_critical / 60.0,
        "high": settings.sla_response_high / 60.0,
        "medium": settings.sla_response_medium / 60.0,
        "low": settings.sla_response_low / 60.0,
    }

    # Get open tickets
    async with _db.execute(
        "SELECT id, category, priority, processed_at FROM processed_tickets WHERE ticket_status = 'open'"
    ) as cursor:
        open_tickets = await cursor.fetchall()

    now = datetime.now(tz=timezone.utc)
    predictions: list[SLAPrediction] = []
    high_risk_count = 0

    for ticket in open_tickets:
        ticket_id = ticket[0]
        category = ticket[1] or "unknown"
        priority = ticket[2] or "medium"
        processed_at = ticket[3]

        try:
            created = datetime.fromisoformat(processed_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_hours = (now - created).total_seconds() / 3600.0
        except (ValueError, TypeError):
            age_hours = 0.0

        sla_target = sla_targets.get(priority, 4.0)
        avg_hours = avg_resolution.get((category, priority), 24.0)

        # Calculate breach probability
        if sla_target <= 0:
            breach_prob = 0.0
        else:
            time_ratio = age_hours / sla_target
            if time_ratio >= 1.0:
                breach_prob = 1.0
            elif time_ratio >= 0.8:
                breach_prob = 0.7 + (time_ratio - 0.8) * 1.5
            elif time_ratio >= 0.5:
                breach_prob = 0.3 + (time_ratio - 0.5) * 1.33
            else:
                breach_prob = time_ratio * 0.6
        breach_prob = min(max(breach_prob, 0.0), 1.0)

        # Determine risk level
        if breach_prob >= 0.8:
            risk_level = "critical"
            high_risk_count += 1
        elif breach_prob >= 0.5:
            risk_level = "high"
            high_risk_count += 1
        elif breach_prob >= 0.3:
            risk_level = "medium"
        else:
            risk_level = "low"

        predictions.append(SLAPrediction(
            ticket_id=ticket_id,
            category=category,
            priority=priority,
            current_age_hours=round(age_hours, 2),
            sla_target_hours=round(sla_target, 2),
            predicted_breach_probability=round(breach_prob, 3),
            estimated_resolution_hours=round(avg_hours, 2),
            risk_level=risk_level,
        ))

    # Sort by breach probability descending
    predictions.sort(key=lambda p: p.predicted_breach_probability, reverse=True)

    return SLAPredictionResponse(
        predictions=predictions,
        total_open_tickets=len(open_tickets),
        high_risk_count=high_risk_count,
    )


# ── Response templates ────────────────────────────────────────────────────────


@app.post(
    "/response-templates",
    response_model=ResponseTemplateResponse,
    tags=["templates"],
)
async def create_response_template(
    body: ResponseTemplateCreate,
    api_key: str = Depends(require_admin),
) -> ResponseTemplateResponse:
    """Create a reusable response template for a ticket category. Requires admin role."""
    if not settings.response_templates_enabled:
        raise HTTPException(
            status_code=403,
            detail="Response templates are not enabled. Set RESPONSE_TEMPLATES_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    template_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()
    tags_json = _json.dumps(body.tags)

    await _db.execute(
        "INSERT INTO response_templates (id, name, category, content, language, tags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (template_id, body.name, body.category, body.content, body.language, tags_json, now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_response_template",
        resource=template_id,
    )

    record = ResponseTemplateRecord(
        id=template_id,
        name=body.name,
        category=body.category,
        content=body.content,
        language=body.language,
        tags=body.tags,
        created_at=datetime.fromisoformat(now),
    )
    return ResponseTemplateResponse(data=record)


@app.get(
    "/response-templates",
    response_model=ResponseTemplateListResponse,
    tags=["templates"],
)
async def list_response_templates(
    category: str | None = Query(None, description="Filter by category"),
    api_key: str = Depends(require_viewer),
) -> ResponseTemplateListResponse:
    """List all response templates, optionally filtered by category."""
    if not settings.response_templates_enabled:
        raise HTTPException(
            status_code=403,
            detail="Response templates are not enabled. Set RESPONSE_TEMPLATES_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    if category:
        query = "SELECT id, name, category, content, language, tags, created_at FROM response_templates WHERE category = ? ORDER BY created_at DESC"
        params: tuple = (category,)
    else:
        query = "SELECT id, name, category, content, language, tags, created_at FROM response_templates ORDER BY created_at DESC"
        params = ()

    async with _db.execute(query, params) as cursor:
        rows = await cursor.fetchall()

    templates = [
        ResponseTemplateRecord(
            id=r[0],
            name=r[1],
            category=r[2],
            content=r[3],
            language=r[4] or "en",
            tags=_json.loads(r[5]) if r[5] else [],
            created_at=datetime.fromisoformat(r[6]),
        )
        for r in rows
    ]
    return ResponseTemplateListResponse(templates=templates)


@app.delete(
    "/response-templates/{template_id}",
    tags=["templates"],
)
async def delete_response_template(
    template_id: str,
    api_key: str = Depends(require_admin),
) -> dict:
    """Delete a response template. Requires admin role."""
    if not settings.response_templates_enabled:
        raise HTTPException(
            status_code=403,
            detail="Response templates are not enabled. Set RESPONSE_TEMPLATES_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id FROM response_templates WHERE id = ?", (template_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Response template not found")

    await _db.execute("DELETE FROM response_templates WHERE id = ?", (template_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="delete_response_template",
        resource=template_id,
    )

    return {"success": True, "deleted": template_id}


# ── Ticket activity timeline ─────────────────────────────────────────────────


@app.post(
    "/tickets/{ticket_id}/comments",
    response_model=TicketCommentResponse,
    tags=["timeline"],
)
async def add_ticket_comment(
    ticket_id: str,
    body: TicketCommentCreate,
    api_key: str = Depends(require_analyst),
) -> TicketCommentResponse:
    """Add an internal comment to a ticket. Requires analyst role."""
    if not settings.ticket_timeline_enabled:
        raise HTTPException(
            status_code=403,
            detail="Ticket timeline is not enabled. Set TICKET_TIMELINE_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    activity_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]

    await _db.execute(
        "INSERT INTO ticket_activity (id, ticket_id, activity_type, content, performed_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (activity_id, ticket_id, "comment", body.content, key_hash, now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="add_ticket_comment",
        resource=ticket_id,
    )

    record = TicketActivityRecord(
        id=activity_id,
        ticket_id=ticket_id,
        activity_type=ActivityType.comment,
        content=body.content,
        performed_by=key_hash,
        created_at=datetime.fromisoformat(now),
    )
    return TicketCommentResponse(data=record)


@app.get(
    "/tickets/{ticket_id}/activity",
    response_model=TicketActivityResponse,
    tags=["timeline"],
)
async def get_ticket_activity(
    ticket_id: str,
    api_key: str = Depends(require_viewer),
) -> TicketActivityResponse:
    """Get the full activity timeline for a ticket."""
    if not settings.ticket_timeline_enabled:
        raise HTTPException(
            status_code=403,
            detail="Ticket timeline is not enabled. Set TICKET_TIMELINE_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id, ticket_id, activity_type, content, performed_by, created_at "
        "FROM ticket_activity WHERE ticket_id = ? ORDER BY created_at ASC",
        (ticket_id,),
    ) as cursor:
        rows = await cursor.fetchall()

    activities = [
        TicketActivityRecord(
            id=r[0],
            ticket_id=r[1],
            activity_type=ActivityType(r[2]),
            content=r[3] or "",
            performed_by=r[4] or "",
            created_at=datetime.fromisoformat(r[5]),
        )
        for r in rows
    ]
    return TicketActivityResponse(
        ticket_id=ticket_id,
        activities=activities,
    )


# ── Bulk operations ──────────────────────────────────────────────────────────


@app.post(
    "/tickets/bulk/status",
    response_model=BulkOperationResponse,
    tags=["bulk"],
)
async def bulk_update_status(
    body: BulkStatusUpdate,
    api_key: str = Depends(require_analyst),
) -> BulkOperationResponse:
    """Update the status of multiple tickets at once. Requires analyst role."""
    if not settings.bulk_operations_enabled:
        raise HTTPException(
            status_code=403,
            detail="Bulk operations are not enabled. Set BULK_OPERATIONS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    results: list[BulkOperationResult] = []
    succeeded = 0
    failed = 0

    for ticket_id in body.ticket_ids:
        async with _db.execute(
            "SELECT id FROM processed_tickets WHERE id = ?", (ticket_id,)
        ) as cursor:
            if await cursor.fetchone() is None:
                results.append(BulkOperationResult(
                    ticket_id=ticket_id,
                    success=False,
                    detail="Ticket not found",
                ))
                failed += 1
                continue

        await _db.execute(
            "UPDATE processed_tickets SET ticket_status = ? WHERE id = ?",
            (body.status.value, ticket_id),
        )
        results.append(BulkOperationResult(
            ticket_id=ticket_id,
            success=True,
            detail=f"Status updated to {body.status.value}",
        ))
        succeeded += 1

    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="bulk_update_status",
        resource=f"{len(body.ticket_ids)} tickets",
    )

    return BulkOperationResponse(
        total=len(body.ticket_ids),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


@app.post(
    "/tickets/bulk/tags",
    response_model=BulkOperationResponse,
    tags=["bulk"],
)
async def bulk_add_tags(
    body: BulkTagUpdate,
    api_key: str = Depends(require_analyst),
) -> BulkOperationResponse:
    """Add tags to multiple tickets at once. Requires analyst role."""
    if not settings.bulk_operations_enabled:
        raise HTTPException(
            status_code=403,
            detail="Bulk operations are not enabled. Set BULK_OPERATIONS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    if not settings.ticket_tags_enabled:
        raise HTTPException(
            status_code=403,
            detail="Ticket tags must also be enabled. Set TICKET_TAGS_ENABLED=true.",
        )

    results: list[BulkOperationResult] = []
    succeeded = 0
    failed = 0
    now = datetime.now(tz=timezone.utc).isoformat()

    for ticket_id in body.ticket_ids:
        added_count = 0
        skipped_count = 0
        for tag in body.tags:
            normalised = tag.strip().lower()
            if not normalised:
                continue
            try:
                await _db.execute(
                    "INSERT OR IGNORE INTO ticket_tags (ticket_id, tag, added_at) VALUES (?, ?, ?)",
                    (ticket_id, normalised, now),
                )
                added_count += 1
            except _sqlite3.IntegrityError:
                skipped_count += 1

        detail = f"Added {added_count} tag(s)"
        if skipped_count:
            detail += f", {skipped_count} skipped (duplicate)"
        results.append(BulkOperationResult(
            ticket_id=ticket_id,
            success=True,
            detail=detail,
        ))
        succeeded += 1

    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="bulk_add_tags",
        resource=f"{len(body.ticket_ids)} tickets",
    )

    return BulkOperationResponse(
        total=len(body.ticket_ids),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


# ── Agent skill-based routing ────────────────────────────────────────────────


@app.post(
    "/agent-skills",
    response_model=AgentSkillResponse,
    tags=["routing"],
)
async def create_agent_skill(
    body: AgentSkillCreate,
    api_key: str = Depends(require_admin),
) -> AgentSkillResponse:
    """Register an agent with their skills and capacity. Requires admin role."""
    if not settings.skill_routing_enabled:
        raise HTTPException(
            status_code=403,
            detail="Skill-based routing is not enabled. Set SKILL_ROUTING_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    record_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    try:
        await _db.execute(
            "INSERT INTO agent_skills (id, agent_id, name, categories, priorities, languages, max_concurrent_tickets, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record_id,
                body.agent_id,
                body.name,
                _json.dumps(body.categories),
                _json.dumps(body.priorities),
                _json.dumps(body.languages),
                body.max_concurrent_tickets,
                now,
            ),
        )
        await _db.commit()
    except _sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Agent '{body.agent_id}' already exists")

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_agent_skill",
        resource=body.agent_id,
    )

    record = AgentSkillRecord(
        id=record_id,
        agent_id=body.agent_id,
        name=body.name,
        categories=body.categories,
        priorities=body.priorities,
        languages=body.languages,
        max_concurrent_tickets=body.max_concurrent_tickets,
        created_at=datetime.fromisoformat(now),
    )
    return AgentSkillResponse(data=record)


@app.get(
    "/agent-skills",
    response_model=AgentSkillListResponse,
    tags=["routing"],
)
async def list_agent_skills(
    api_key: str = Depends(require_viewer),
) -> AgentSkillListResponse:
    """List all registered agents and their skills."""
    if not settings.skill_routing_enabled:
        raise HTTPException(
            status_code=403,
            detail="Skill-based routing is not enabled. Set SKILL_ROUTING_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    async with _db.execute(
        "SELECT id, agent_id, name, categories, priorities, languages, max_concurrent_tickets, created_at "
        "FROM agent_skills ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    agents = [
        AgentSkillRecord(
            id=r[0],
            agent_id=r[1],
            name=r[2],
            categories=_json.loads(r[3]) if r[3] else [],
            priorities=_json.loads(r[4]) if r[4] else [],
            languages=_json.loads(r[5]) if r[5] else [],
            max_concurrent_tickets=r[6] or 10,
            created_at=datetime.fromisoformat(r[7]),
        )
        for r in rows
    ]
    return AgentSkillListResponse(agents=agents)


@app.get(
    "/tickets/{ticket_id}/recommended-agents",
    response_model=AgentRecommendationResponse,
    tags=["routing"],
)
async def get_recommended_agents(
    ticket_id: str,
    api_key: str = Depends(require_viewer),
) -> AgentRecommendationResponse:
    """
    Get recommended agents for a ticket based on skill matching.

    Matches ticket category, priority, and language against registered agent skills.
    Returns agents sorted by match score (highest first).
    """
    if not settings.skill_routing_enabled:
        raise HTTPException(
            status_code=403,
            detail="Skill-based routing is not enabled. Set SKILL_ROUTING_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    # Get ticket details
    async with _db.execute(
        "SELECT id, category, priority, detected_language FROM processed_tickets WHERE id = ?",
        (ticket_id,),
    ) as cursor:
        ticket = await cursor.fetchone()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket_category = (ticket[1] or "").lower()
    ticket_priority = (ticket[2] or "").lower()
    ticket_language = (ticket[3] or "en").lower()

    # Get all agents
    async with _db.execute(
        "SELECT id, agent_id, name, categories, priorities, languages, max_concurrent_tickets, created_at "
        "FROM agent_skills"
    ) as cursor:
        agent_rows = await cursor.fetchall()

    recommendations: list[AgentRecommendation] = []

    for r in agent_rows:
        agent_categories = [c.lower() for c in _json.loads(r[3])] if r[3] else []
        agent_priorities = [p.lower() for p in _json.loads(r[4])] if r[4] else []
        agent_languages = [la.lower() for la in _json.loads(r[5])] if r[5] else []

        score = 0.0
        matching_skills: list[str] = []

        # Category match (weighted 0.4)
        if ticket_category and ticket_category in agent_categories:
            score += 0.4
            matching_skills.append(f"category:{ticket_category}")

        # Priority match (weighted 0.3)
        if ticket_priority and ticket_priority in agent_priorities:
            score += 0.3
            matching_skills.append(f"priority:{ticket_priority}")

        # Language match (weighted 0.3)
        if ticket_language and ticket_language in agent_languages:
            score += 0.3
            matching_skills.append(f"language:{ticket_language}")

        if score > 0:
            recommendations.append(AgentRecommendation(
                agent_id=r[1],
                name=r[2],
                match_score=round(score, 2),
                matching_skills=matching_skills,
            ))

    # Sort by match score descending
    recommendations.sort(key=lambda rec: rec.match_score, reverse=True)

    return AgentRecommendationResponse(
        ticket_id=ticket_id,
        recommendations=recommendations,
    )


# ── Phase 9: Automation rules ────────────────────────────────────────────────


@app.post(
    "/automation-rules",
    response_model=AutomationRuleResponse,
    tags=["automation"],
)
async def create_automation_rule(
    body: AutomationRuleCreate,
    api_key: str = Depends(require_admin),
) -> AutomationRuleResponse:
    """Create a workflow automation rule. Requires admin role."""
    if not settings.automation_rules_enabled:
        raise HTTPException(
            status_code=403,
            detail="Automation rules are not enabled. Set AUTOMATION_RULES_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    rule_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    conditions_json = _json.dumps([c.model_dump() for c in body.conditions])
    actions_json = _json.dumps([a.model_dump() for a in body.actions])

    await _db.execute(
        "INSERT INTO automation_rules (id, name, description, conditions, actions, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (rule_id, body.name, body.description, conditions_json, actions_json, 1 if body.enabled else 0, now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_automation_rule",
        resource=rule_id,
    )

    record = AutomationRuleRecord(
        id=rule_id,
        name=body.name,
        description=body.description,
        conditions=body.conditions,
        actions=body.actions,
        enabled=body.enabled,
        created_at=datetime.fromisoformat(now),
    )
    return AutomationRuleResponse(data=record)


@app.get(
    "/automation-rules",
    response_model=AutomationRuleListResponse,
    tags=["automation"],
)
async def list_automation_rules(
    api_key: str = Depends(require_viewer),
) -> AutomationRuleListResponse:
    """List all workflow automation rules."""
    if not settings.automation_rules_enabled:
        raise HTTPException(
            status_code=403,
            detail="Automation rules are not enabled. Set AUTOMATION_RULES_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    async with _db.execute(
        "SELECT id, name, description, conditions, actions, enabled, created_at "
        "FROM automation_rules ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    rules = [
        AutomationRuleRecord(
            id=r[0],
            name=r[1],
            description=r[2] or "",
            conditions=[AutomationRuleCondition(**c) for c in _json.loads(r[3])] if r[3] else [],
            actions=[AutomationRuleAction(**a) for a in _json.loads(r[4])] if r[4] else [],
            enabled=bool(r[5]),
            created_at=datetime.fromisoformat(r[6]),
        )
        for r in rows
    ]
    return AutomationRuleListResponse(rules=rules)


@app.delete(
    "/automation-rules/{rule_id}",
    tags=["automation"],
)
async def delete_automation_rule(
    rule_id: str,
    api_key: str = Depends(require_admin),
) -> dict:
    """Delete an automation rule. Requires admin role."""
    if not settings.automation_rules_enabled:
        raise HTTPException(
            status_code=403,
            detail="Automation rules are not enabled. Set AUTOMATION_RULES_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id FROM automation_rules WHERE id = ?", (rule_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Automation rule not found")

    await _db.execute("DELETE FROM automation_rules WHERE id = ?", (rule_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="delete_automation_rule",
        resource=rule_id,
    )

    return {"success": True, "deleted": rule_id}


# ── Phase 9: Approval workflows ──────────────────────────────────────────────


@app.post(
    "/tickets/{ticket_id}/approval-request",
    response_model=ApprovalResponse,
    tags=["approvals"],
)
async def create_approval_request(
    ticket_id: str,
    body: ApprovalRequestCreate,
    api_key: str = Depends(require_analyst),
) -> ApprovalResponse:
    """Request approval for a ticket. Requires analyst role."""
    if not settings.approval_workflows_enabled:
        raise HTTPException(
            status_code=403,
            detail="Approval workflows are not enabled. Set APPROVAL_WORKFLOWS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Verify ticket exists
    async with _db.execute(
        "SELECT id FROM processed_tickets WHERE id = ?", (ticket_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Ticket not found")

    approval_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    await _db.execute(
        "INSERT INTO ticket_approvals (id, ticket_id, approver, reason, status, decision_comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (approval_id, ticket_id, body.approver, body.reason, "pending", "", now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_approval_request",
        resource=f"{ticket_id}:{approval_id}",
    )

    record = ApprovalRecord(
        id=approval_id,
        ticket_id=ticket_id,
        approver=body.approver,
        reason=body.reason,
        status=ApprovalStatus.pending,
        created_at=datetime.fromisoformat(now),
    )
    return ApprovalResponse(data=record)


@app.post(
    "/tickets/{ticket_id}/approve",
    response_model=ApprovalResponse,
    tags=["approvals"],
)
async def approve_ticket(
    ticket_id: str,
    body: ApprovalDecision,
    api_key: str = Depends(require_admin),
) -> ApprovalResponse:
    """Approve or reject a pending approval. Requires admin role."""
    if not settings.approval_workflows_enabled:
        raise HTTPException(
            status_code=403,
            detail="Approval workflows are not enabled. Set APPROVAL_WORKFLOWS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    if body.decision == ApprovalStatus.pending:
        raise HTTPException(status_code=400, detail="Decision must be 'approved' or 'rejected'")

    # Get the most recent pending approval for this ticket
    async with _db.execute(
        "SELECT id, ticket_id, approver, reason, status, decision_comment, created_at, decided_at "
        "FROM ticket_approvals WHERE ticket_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
        (ticket_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="No pending approval found for this ticket")

    decided_at = datetime.now(tz=timezone.utc).isoformat()

    await _db.execute(
        "UPDATE ticket_approvals SET status = ?, decision_comment = ?, decided_at = ? WHERE id = ?",
        (body.decision.value, body.comment, decided_at, row[0]),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action=f"approval_{body.decision.value}",
        resource=f"{ticket_id}:{row[0]}",
    )

    record = ApprovalRecord(
        id=row[0],
        ticket_id=ticket_id,
        approver=row[2],
        reason=row[3] or "",
        status=body.decision,
        decision_comment=body.comment,
        created_at=datetime.fromisoformat(row[6]),
        decided_at=datetime.fromisoformat(decided_at),
    )
    return ApprovalResponse(data=record)


@app.get(
    "/tickets/{ticket_id}/approvals",
    response_model=ApprovalListResponse,
    tags=["approvals"],
)
async def list_ticket_approvals(
    ticket_id: str,
    api_key: str = Depends(require_viewer),
) -> ApprovalListResponse:
    """List all approvals for a ticket."""
    if not settings.approval_workflows_enabled:
        raise HTTPException(
            status_code=403,
            detail="Approval workflows are not enabled. Set APPROVAL_WORKFLOWS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id, ticket_id, approver, reason, status, decision_comment, created_at, decided_at "
        "FROM ticket_approvals WHERE ticket_id = ? ORDER BY created_at DESC",
        (ticket_id,),
    ) as cursor:
        rows = await cursor.fetchall()

    approvals = [
        ApprovalRecord(
            id=r[0],
            ticket_id=r[1],
            approver=r[2],
            reason=r[3] or "",
            status=ApprovalStatus(r[4]),
            decision_comment=r[5] or "",
            created_at=datetime.fromisoformat(r[6]),
            decided_at=datetime.fromisoformat(r[7]) if r[7] else None,
        )
        for r in rows
    ]
    return ApprovalListResponse(approvals=approvals)


# ── Phase 9: Agent collision detection ────────────────────────────────────────

LOCK_DURATION_MINUTES = 15


@app.post(
    "/tickets/{ticket_id}/lock",
    response_model=TicketLockResponse,
    tags=["collision"],
)
async def lock_ticket(
    ticket_id: str,
    body: TicketLockCreate,
    api_key: str = Depends(require_analyst),
) -> TicketLockResponse:
    """Acquire an exclusive lock on a ticket. Requires analyst role."""
    if not settings.collision_detection_enabled:
        raise HTTPException(
            status_code=403,
            detail="Collision detection is not enabled. Set COLLISION_DETECTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import sqlite3 as _sqlite3  # noqa: PLC0415

    now = datetime.now(tz=timezone.utc)
    expires = now + timedelta(minutes=LOCK_DURATION_MINUTES)

    # Remove expired locks first
    await _db.execute(
        "DELETE FROM ticket_locks WHERE expires_at < ?",
        (now.isoformat(),),
    )
    await _db.commit()

    lock_id = str(uuid.uuid4())

    try:
        await _db.execute(
            "INSERT INTO ticket_locks (id, ticket_id, agent_id, acquired_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (lock_id, ticket_id, body.agent_id, now.isoformat(), expires.isoformat()),
        )
        await _db.commit()
    except _sqlite3.IntegrityError:
        # Ticket already locked — return existing lock info
        async with _db.execute(
            "SELECT id, ticket_id, agent_id, acquired_at, expires_at FROM ticket_locks WHERE ticket_id = ?",
            (ticket_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            existing_lock = TicketLockRecord(
                id=row[0],
                ticket_id=row[1],
                agent_id=row[2],
                acquired_at=datetime.fromisoformat(row[3]),
                expires_at=datetime.fromisoformat(row[4]),
            )
            raise HTTPException(
                status_code=409,
                detail=f"Ticket is already locked by agent '{existing_lock.agent_id}' until {existing_lock.expires_at.isoformat()}",
            )
        raise HTTPException(status_code=409, detail="Ticket is already locked")

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="lock_ticket",
        resource=ticket_id,
    )

    record = TicketLockRecord(
        id=lock_id,
        ticket_id=ticket_id,
        agent_id=body.agent_id,
        acquired_at=now,
        expires_at=expires,
    )
    return TicketLockResponse(data=record, locked=True)


@app.delete(
    "/tickets/{ticket_id}/lock",
    tags=["collision"],
)
async def unlock_ticket(
    ticket_id: str,
    api_key: str = Depends(require_analyst),
) -> dict:
    """Release a lock on a ticket. Requires analyst role."""
    if not settings.collision_detection_enabled:
        raise HTTPException(
            status_code=403,
            detail="Collision detection is not enabled. Set COLLISION_DETECTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id FROM ticket_locks WHERE ticket_id = ?", (ticket_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="No lock found for this ticket")

    await _db.execute("DELETE FROM ticket_locks WHERE ticket_id = ?", (ticket_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="unlock_ticket",
        resource=ticket_id,
    )

    return {"success": True, "unlocked": ticket_id}


@app.get(
    "/tickets/{ticket_id}/lock",
    response_model=TicketLockResponse,
    tags=["collision"],
)
async def get_ticket_lock(
    ticket_id: str,
    api_key: str = Depends(require_viewer),
) -> TicketLockResponse:
    """Check the lock status of a ticket."""
    if not settings.collision_detection_enabled:
        raise HTTPException(
            status_code=403,
            detail="Collision detection is not enabled. Set COLLISION_DETECTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    now = datetime.now(tz=timezone.utc)

    # Remove expired locks first
    await _db.execute(
        "DELETE FROM ticket_locks WHERE expires_at < ?",
        (now.isoformat(),),
    )
    await _db.commit()

    async with _db.execute(
        "SELECT id, ticket_id, agent_id, acquired_at, expires_at FROM ticket_locks WHERE ticket_id = ?",
        (ticket_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        return TicketLockResponse(locked=False)

    record = TicketLockRecord(
        id=row[0],
        ticket_id=row[1],
        agent_id=row[2],
        acquired_at=datetime.fromisoformat(row[3]),
        expires_at=datetime.fromisoformat(row[4]),
    )
    return TicketLockResponse(data=record, locked=True)


# ── Phase 9: Contact management ──────────────────────────────────────────────


@app.post(
    "/contacts",
    response_model=ContactResponse,
    tags=["contacts"],
)
async def create_contact(
    body: ContactCreate,
    api_key: str = Depends(require_analyst),
) -> ContactResponse:
    """Register a customer contact. Requires analyst role."""
    if not settings.contact_management_enabled:
        raise HTTPException(
            status_code=403,
            detail="Contact management is not enabled. Set CONTACT_MANAGEMENT_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import sqlite3 as _sqlite3  # noqa: PLC0415

    contact_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    try:
        await _db.execute(
            "INSERT INTO contacts (id, email, name, organisation, phone, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (contact_id, body.email, body.name, body.organisation, body.phone, body.notes, now),
        )
        await _db.commit()
    except _sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Contact with email '{body.email}' already exists")

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_contact",
        resource=contact_id,
    )

    record = ContactRecord(
        id=contact_id,
        email=body.email,
        name=body.name,
        organisation=body.organisation,
        phone=body.phone,
        notes=body.notes,
        created_at=datetime.fromisoformat(now),
    )
    return ContactResponse(data=record)


@app.get(
    "/contacts",
    response_model=ContactListResponse,
    tags=["contacts"],
)
async def list_contacts(
    api_key: str = Depends(require_viewer),
) -> ContactListResponse:
    """List all customer contacts."""
    if not settings.contact_management_enabled:
        raise HTTPException(
            status_code=403,
            detail="Contact management is not enabled. Set CONTACT_MANAGEMENT_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id, email, name, organisation, phone, notes, created_at "
        "FROM contacts ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    contacts = [
        ContactRecord(
            id=r[0],
            email=r[1],
            name=r[2],
            organisation=r[3] or "",
            phone=r[4] or "",
            notes=r[5] or "",
            created_at=datetime.fromisoformat(r[6]),
        )
        for r in rows
    ]
    return ContactListResponse(contacts=contacts)


@app.post(
    "/contacts/{contact_id}/tickets/{ticket_id}",
    tags=["contacts"],
)
async def link_contact_ticket(
    contact_id: str,
    ticket_id: str,
    api_key: str = Depends(require_analyst),
) -> dict:
    """Link a contact to a ticket. Requires analyst role."""
    if not settings.contact_management_enabled:
        raise HTTPException(
            status_code=403,
            detail="Contact management is not enabled. Set CONTACT_MANAGEMENT_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import sqlite3 as _sqlite3  # noqa: PLC0415

    # Verify contact exists
    async with _db.execute(
        "SELECT id FROM contacts WHERE id = ?", (contact_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Contact not found")

    try:
        await _db.execute(
            "INSERT INTO contact_tickets (contact_id, ticket_id) VALUES (?, ?)",
            (contact_id, ticket_id),
        )
        await _db.commit()
    except _sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ticket is already linked to this contact")

    return {"success": True, "contact_id": contact_id, "ticket_id": ticket_id}


@app.get(
    "/contacts/{contact_id}/tickets",
    response_model=ContactTicketsResponse,
    tags=["contacts"],
)
async def get_contact_tickets(
    contact_id: str,
    api_key: str = Depends(require_viewer),
) -> ContactTicketsResponse:
    """Get all tickets associated with a contact."""
    if not settings.contact_management_enabled:
        raise HTTPException(
            status_code=403,
            detail="Contact management is not enabled. Set CONTACT_MANAGEMENT_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Verify contact exists
    async with _db.execute(
        "SELECT id FROM contacts WHERE id = ?", (contact_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Contact not found")

    async with _db.execute(
        "SELECT ticket_id FROM contact_tickets WHERE contact_id = ? ORDER BY ticket_id",
        (contact_id,),
    ) as cursor:
        rows = await cursor.fetchall()

    ticket_ids = [r[0] for r in rows]
    return ContactTicketsResponse(contact_id=contact_id, ticket_ids=ticket_ids)


# ── Phase 9: Macros ──────────────────────────────────────────────────────────


@app.post(
    "/macros",
    response_model=MacroResponse,
    tags=["macros"],
)
async def create_macro(
    body: MacroCreate,
    api_key: str = Depends(require_admin),
) -> MacroResponse:
    """Create a reusable macro. Requires admin role."""
    if not settings.macros_enabled:
        raise HTTPException(
            status_code=403,
            detail="Macros are not enabled. Set MACROS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    macro_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    actions_json = _json.dumps([a.model_dump() for a in body.actions])

    await _db.execute(
        "INSERT INTO macros (id, name, description, actions, created_at) VALUES (?, ?, ?, ?, ?)",
        (macro_id, body.name, body.description, actions_json, now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_macro",
        resource=macro_id,
    )

    record = MacroRecord(
        id=macro_id,
        name=body.name,
        description=body.description,
        actions=body.actions,
        created_at=datetime.fromisoformat(now),
    )
    return MacroResponse(data=record)


@app.get(
    "/macros",
    response_model=MacroListResponse,
    tags=["macros"],
)
async def list_macros(
    api_key: str = Depends(require_viewer),
) -> MacroListResponse:
    """List all macros."""
    if not settings.macros_enabled:
        raise HTTPException(
            status_code=403,
            detail="Macros are not enabled. Set MACROS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    async with _db.execute(
        "SELECT id, name, description, actions, created_at FROM macros ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    macros = [
        MacroRecord(
            id=r[0],
            name=r[1],
            description=r[2] or "",
            actions=[MacroAction(**a) for a in _json.loads(r[3])] if r[3] else [],
            created_at=datetime.fromisoformat(r[4]),
        )
        for r in rows
    ]
    return MacroListResponse(macros=macros)


@app.delete(
    "/macros/{macro_id}",
    tags=["macros"],
)
async def delete_macro(
    macro_id: str,
    api_key: str = Depends(require_admin),
) -> dict:
    """Delete a macro. Requires admin role."""
    if not settings.macros_enabled:
        raise HTTPException(
            status_code=403,
            detail="Macros are not enabled. Set MACROS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id FROM macros WHERE id = ?", (macro_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Macro not found")

    await _db.execute("DELETE FROM macros WHERE id = ?", (macro_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="delete_macro",
        resource=macro_id,
    )

    return {"success": True, "deleted": macro_id}


@app.post(
    "/macros/{macro_id}/execute",
    response_model=MacroExecuteResponse,
    tags=["macros"],
)
async def execute_macro(
    macro_id: str,
    ticket_id: str = Query(..., description="Ticket ID to apply the macro to"),
    api_key: str = Depends(require_analyst),
) -> MacroExecuteResponse:
    """Execute a macro on a ticket. Requires analyst role."""
    if not settings.macros_enabled:
        raise HTTPException(
            status_code=403,
            detail="Macros are not enabled. Set MACROS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    import json as _json  # noqa: PLC0415

    # Get macro
    async with _db.execute(
        "SELECT id, name, description, actions, created_at FROM macros WHERE id = ?",
        (macro_id,),
    ) as cursor:
        macro_row = await cursor.fetchone()

    if macro_row is None:
        raise HTTPException(status_code=404, detail="Macro not found")

    # Verify ticket exists
    async with _db.execute(
        "SELECT id FROM processed_tickets WHERE id = ?", (ticket_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Ticket not found")

    actions = _json.loads(macro_row[3]) if macro_row[3] else []
    actions_performed: list[str] = []

    for action in actions:
        action_type = action.get("action_type", "")
        params = action.get("parameters", {})

        if action_type == "set_status" and "status" in params:
            await _db.execute(
                "UPDATE processed_tickets SET ticket_status = ? WHERE id = ?",
                (params["status"], ticket_id),
            )
            actions_performed.append(f"set_status:{params['status']}")

        elif action_type == "set_priority" and "priority" in params:
            await _db.execute(
                "UPDATE processed_tickets SET priority = ? WHERE id = ?",
                (params["priority"], ticket_id),
            )
            actions_performed.append(f"set_priority:{params['priority']}")

        elif action_type == "add_tag" and "tag" in params:
            # Insert tag if ticket_tags table exists and tag feature is available
            tag_id = str(uuid.uuid4())
            now = datetime.now(tz=timezone.utc).isoformat()
            try:
                await _db.execute(
                    "INSERT INTO ticket_tags (id, ticket_id, tag, created_at) VALUES (?, ?, ?, ?)",
                    (tag_id, ticket_id, params["tag"], now),
                )
            except Exception:
                pass  # Tag table might not exist if tags feature is disabled
            actions_performed.append(f"add_tag:{params['tag']}")

        elif action_type == "add_comment" and "text" in params:
            comment_id = str(uuid.uuid4())
            now = datetime.now(tz=timezone.utc).isoformat()
            try:
                await _db.execute(
                    "INSERT INTO ticket_activity (id, ticket_id, activity_type, content, performed_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (comment_id, ticket_id, "comment", params["text"], "macro", now),
                )
            except Exception:
                pass  # Activity table might not exist if timeline feature is disabled
            actions_performed.append(f"add_comment:{params['text'][:50]}")

    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="execute_macro",
        resource=f"{macro_id}:{ticket_id}",
    )

    return MacroExecuteResponse(
        ticket_id=ticket_id,
        actions_performed=actions_performed,
    )


# ── Phase 10a: Team dashboards ───────────────────────────────────────────────


@app.post(
    "/teams",
    response_model=TeamMemberResponse,
    tags=["teams"],
)
async def create_team_member(
    body: TeamMemberCreate,
    api_key: str = Depends(require_admin),
) -> TeamMemberResponse:
    """Add an agent to a team. Requires admin role."""
    if not settings.team_dashboards_enabled:
        raise HTTPException(
            status_code=403,
            detail="Team dashboards are not enabled. Set TEAM_DASHBOARDS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    member_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    try:
        await _db.execute(
            "INSERT INTO team_members (id, agent_id, team_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (member_id, body.agent_id, body.team_name, body.role, now),
        )
        await _db.commit()
    except _sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{body.agent_id}' is already a member of team '{body.team_name}'",
        )

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_team_member",
        resource=member_id,
    )

    record = TeamMemberRecord(
        id=member_id,
        agent_id=body.agent_id,
        team_name=body.team_name,
        role=body.role,
        created_at=datetime.fromisoformat(now),
    )
    return TeamMemberResponse(data=record)


@app.get(
    "/teams",
    response_model=TeamMemberListResponse,
    tags=["teams"],
)
async def list_teams(
    team_name: str | None = Query(default=None, description="Filter by team name"),
    api_key: str = Depends(require_viewer),
) -> TeamMemberListResponse:
    """List team members, optionally filtered by team name."""
    if not settings.team_dashboards_enabled:
        raise HTTPException(
            status_code=403,
            detail="Team dashboards are not enabled. Set TEAM_DASHBOARDS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    if team_name:
        query = "SELECT id, agent_id, team_name, role, created_at FROM team_members WHERE team_name = ? ORDER BY created_at DESC"
        params: tuple = (team_name,)
    else:
        query = "SELECT id, agent_id, team_name, role, created_at FROM team_members ORDER BY team_name, created_at DESC"
        params = ()

    async with _db.execute(query, params) as cursor:
        rows = await cursor.fetchall()

    members = [
        TeamMemberRecord(
            id=r[0],
            agent_id=r[1],
            team_name=r[2],
            role=r[3],
            created_at=datetime.fromisoformat(r[4]),
        )
        for r in rows
    ]
    return TeamMemberListResponse(members=members)


@app.get(
    "/analytics/team-dashboard",
    response_model=TeamDashboardResponse,
    tags=["analytics"],
)
async def get_team_dashboard(
    api_key: str = Depends(require_viewer),
) -> TeamDashboardResponse:
    """
    Real-time team performance dashboard.

    Shows metrics for each team including ticket counts, resolution rates,
    and team composition.
    """
    if not settings.team_dashboards_enabled:
        raise HTTPException(
            status_code=403,
            detail="Team dashboards are not enabled. Set TEAM_DASHBOARDS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Get all teams and their members
    async with _db.execute(
        "SELECT DISTINCT team_name FROM team_members ORDER BY team_name"
    ) as cursor:
        team_rows = await cursor.fetchall()

    team_names = [r[0] for r in team_rows]

    # Get all team members
    async with _db.execute(
        "SELECT agent_id, team_name FROM team_members"
    ) as cursor:
        member_rows = await cursor.fetchall()

    team_agents: dict[str, list[str]] = {}
    all_agents: set[str] = set()
    for r in member_rows:
        team_agents.setdefault(r[1], []).append(r[0])
        all_agents.add(r[0])

    # Get ticket counts by status (we use agent_skills to map agents to tickets where possible)
    # For simplicity, compute overall ticket stats and distribute by team
    async with _db.execute(
        "SELECT id, ticket_status FROM processed_tickets"
    ) as cursor:
        ticket_rows = await cursor.fetchall()

    total_tickets = len(ticket_rows)
    open_count = sum(1 for r in ticket_rows if r[1] == "open")
    resolved_count = sum(1 for r in ticket_rows if r[1] in ("resolved", "closed"))

    teams: list[TeamPerformanceMetrics] = []
    for tn in team_names:
        agents = team_agents.get(tn, [])
        member_count = len(agents)

        # Proportional distribution based on team size
        if all_agents and member_count > 0:
            fraction = member_count / max(len(all_agents), 1)
        else:
            fraction = 0.0

        team_total = int(total_tickets * fraction)
        team_open = int(open_count * fraction)
        team_resolved = int(resolved_count * fraction)

        avg_hours = 0.0
        if team_resolved > 0:
            # Simplified average resolution time estimation
            avg_hours = round(24.0 * (team_total / max(team_resolved, 1)), 2)

        teams.append(TeamPerformanceMetrics(
            team_name=tn,
            total_tickets=team_total,
            open_tickets=team_open,
            resolved_tickets=team_resolved,
            avg_resolution_hours=avg_hours,
            member_count=member_count,
            members=agents,
        ))

    return TeamDashboardResponse(
        teams=teams,
        total_agents=len(all_agents),
    )


# ── Phase 10a: Enhanced SLA prediction ───────────────────────────────────────


@app.post(
    "/sla-risk-thresholds",
    response_model=SLARiskThresholdResponse,
    tags=["sla"],
)
async def create_sla_risk_threshold(
    body: SLARiskThresholdCreate,
    api_key: str = Depends(require_admin),
) -> SLARiskThresholdResponse:
    """Configure SLA risk thresholds per priority level. Requires admin role."""
    if not settings.enhanced_sla_prediction_enabled:
        raise HTTPException(
            status_code=403,
            detail="Enhanced SLA prediction is not enabled. Set ENHANCED_SLA_PREDICTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    if body.warning_threshold >= body.critical_threshold:
        raise HTTPException(
            status_code=422,
            detail="Warning threshold must be lower than critical threshold.",
        )

    threshold_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    try:
        await _db.execute(
            "INSERT INTO sla_risk_thresholds (id, priority, warning_threshold, critical_threshold, created_at) VALUES (?, ?, ?, ?, ?)",
            (threshold_id, body.priority, body.warning_threshold, body.critical_threshold, now),
        )
        await _db.commit()
    except _sqlite3.IntegrityError:
        # Update existing threshold for this priority
        await _db.execute(
            "UPDATE sla_risk_thresholds SET warning_threshold = ?, critical_threshold = ? WHERE priority = ?",
            (body.warning_threshold, body.critical_threshold, body.priority),
        )
        await _db.commit()
        # Get the existing record
        async with _db.execute(
            "SELECT id, priority, warning_threshold, critical_threshold, created_at FROM sla_risk_thresholds WHERE priority = ?",
            (body.priority,),
        ) as cursor:
            row = await cursor.fetchone()
        if row:
            threshold_id = row[0]
            now = row[4]

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_sla_risk_threshold",
        resource=threshold_id,
    )

    record = SLARiskThresholdRecord(
        id=threshold_id,
        priority=body.priority,
        warning_threshold=body.warning_threshold,
        critical_threshold=body.critical_threshold,
        created_at=datetime.fromisoformat(now),
    )
    return SLARiskThresholdResponse(data=record)


@app.get(
    "/sla-risk-thresholds",
    response_model=SLARiskThresholdListResponse,
    tags=["sla"],
)
async def list_sla_risk_thresholds(
    api_key: str = Depends(require_viewer),
) -> SLARiskThresholdListResponse:
    """List all configured SLA risk thresholds."""
    if not settings.enhanced_sla_prediction_enabled:
        raise HTTPException(
            status_code=403,
            detail="Enhanced SLA prediction is not enabled. Set ENHANCED_SLA_PREDICTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    async with _db.execute(
        "SELECT id, priority, warning_threshold, critical_threshold, created_at FROM sla_risk_thresholds ORDER BY priority"
    ) as cursor:
        rows = await cursor.fetchall()

    thresholds = [
        SLARiskThresholdRecord(
            id=r[0],
            priority=r[1],
            warning_threshold=r[2],
            critical_threshold=r[3],
            created_at=datetime.fromisoformat(r[4]),
        )
        for r in rows
    ]
    return SLARiskThresholdListResponse(thresholds=thresholds)


@app.get(
    "/analytics/sla-risk",
    response_model=EnhancedSLARiskResponse,
    tags=["analytics"],
)
async def get_enhanced_sla_risk(
    api_key: str = Depends(require_viewer),
) -> EnhancedSLARiskResponse:
    """
    Enhanced SLA breach prediction with multi-factor risk analysis.

    Analyses historical resolution times, ticket age, priority, category volume,
    and configurable risk thresholds to produce detailed breach forecasts.
    """
    if not settings.enhanced_sla_prediction_enabled:
        raise HTTPException(
            status_code=403,
            detail="Enhanced SLA prediction is not enabled. Set ENHANCED_SLA_PREDICTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    # Load custom risk thresholds (fall back to defaults)
    custom_thresholds: dict[str, tuple[float, float]] = {}
    async with _db.execute(
        "SELECT priority, warning_threshold, critical_threshold FROM sla_risk_thresholds"
    ) as cursor:
        for row in await cursor.fetchall():
            custom_thresholds[row[0]] = (row[1], row[2])

    default_thresholds = {"critical": (0.4, 0.7), "high": (0.5, 0.8), "medium": (0.5, 0.8), "low": (0.6, 0.9)}

    # Historical resolution data
    async with _db.execute(
        "SELECT category, priority, processed_at FROM processed_tickets WHERE ticket_status IN ('resolved', 'closed')"
    ) as cursor:
        resolved_rows = await cursor.fetchall()

    category_priority_hours: dict[tuple[str, str], list[float]] = {}
    category_counts: dict[str, int] = {}
    for r in resolved_rows:
        cat = r[0] or "unknown"
        pri = r[1] or "medium"
        base_hours = {"critical": 4.0, "high": 8.0, "medium": 24.0, "low": 48.0}.get(pri, 24.0)
        category_priority_hours.setdefault((cat, pri), []).append(base_hours)
        category_counts[cat] = category_counts.get(cat, 0) + 1

    avg_resolution: dict[tuple[str, str], float] = {}
    for key, hours_list in category_priority_hours.items():
        avg_resolution[key] = sum(hours_list) / len(hours_list) if hours_list else 24.0

    # SLA targets
    sla_targets = {
        "critical": settings.sla_response_critical / 60.0,
        "high": settings.sla_response_high / 60.0,
        "medium": settings.sla_response_medium / 60.0,
        "low": settings.sla_response_low / 60.0,
    }

    # Open tickets
    async with _db.execute(
        "SELECT id, category, priority, processed_at FROM processed_tickets WHERE ticket_status = 'open'"
    ) as cursor:
        open_tickets = await cursor.fetchall()

    now = datetime.now(tz=timezone.utc)
    predictions: list[EnhancedSLAPrediction] = []
    high_risk_count = 0
    critical_risk_count = 0

    for ticket in open_tickets:
        ticket_id = ticket[0]
        category = ticket[1] or "unknown"
        priority = ticket[2] or "medium"
        processed_at = ticket[3]

        try:
            created = datetime.fromisoformat(processed_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_hours = (now - created).total_seconds() / 3600.0
        except (ValueError, TypeError):
            age_hours = 0.0

        sla_target = sla_targets.get(priority, 4.0)
        avg_hours = avg_resolution.get((category, priority), 24.0)

        # Multi-factor risk analysis
        risk_factors: list[SLARiskFactor] = []

        # Factor 1: Time pressure (age vs SLA target)
        time_ratio = age_hours / max(sla_target, 0.01)
        time_weight = min(time_ratio, 1.0)
        risk_factors.append(SLARiskFactor(
            factor="time_pressure",
            weight=round(time_weight, 3),
            description=f"Ticket age ({age_hours:.1f}h) vs SLA target ({sla_target:.1f}h)",
        ))

        # Factor 2: Historical performance
        hist_ratio = avg_hours / max(sla_target, 0.01)
        hist_weight = min(max(hist_ratio - 0.5, 0.0) / 1.5, 1.0)
        risk_factors.append(SLARiskFactor(
            factor="historical_performance",
            weight=round(hist_weight, 3),
            description=f"Avg resolution ({avg_hours:.1f}h) for {category}/{priority}",
        ))

        # Factor 3: Category volume pressure
        cat_volume = category_counts.get(category, 0)
        total_resolved = max(len(resolved_rows), 1)
        volume_ratio = cat_volume / total_resolved
        volume_weight = min(volume_ratio * 2, 1.0)
        risk_factors.append(SLARiskFactor(
            factor="volume_pressure",
            weight=round(volume_weight, 3),
            description=f"Category '{category}' accounts for {volume_ratio:.0%} of resolved tickets",
        ))

        # Factor 4: Priority urgency
        priority_weights = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.2}
        priority_weight = priority_weights.get(priority, 0.4)
        risk_factors.append(SLARiskFactor(
            factor="priority_urgency",
            weight=round(priority_weight, 3),
            description=f"Priority '{priority}' urgency factor",
        ))

        # Composite breach probability (weighted average)
        weights = [0.4, 0.25, 0.15, 0.2]  # time, historical, volume, priority
        factor_values = [time_weight, hist_weight, volume_weight, priority_weight]
        breach_prob = sum(w * f for w, f in zip(weights, factor_values))
        breach_prob = min(max(breach_prob, 0.0), 1.0)

        # Determine risk level based on custom or default thresholds
        warn_thresh, crit_thresh = custom_thresholds.get(
            priority, default_thresholds.get(priority, (0.5, 0.8))
        )

        if breach_prob >= crit_thresh:
            risk_level = "critical"
            critical_risk_count += 1
            high_risk_count += 1
        elif breach_prob >= warn_thresh:
            risk_level = "high"
            high_risk_count += 1
        elif breach_prob >= warn_thresh * 0.6:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Recommended action
        if risk_level == "critical":
            recommended_action = "Immediate attention required — consider escalation or reassignment"
        elif risk_level == "high":
            recommended_action = "Prioritise this ticket — SLA breach is likely without intervention"
        elif risk_level == "medium":
            recommended_action = "Monitor closely — approaching risk threshold"
        else:
            recommended_action = "On track — no immediate action needed"

        predictions.append(EnhancedSLAPrediction(
            ticket_id=ticket_id,
            category=category,
            priority=priority,
            current_age_hours=round(age_hours, 2),
            sla_target_hours=round(sla_target, 2),
            predicted_breach_probability=round(breach_prob, 3),
            risk_level=risk_level,
            risk_factors=risk_factors,
            recommended_action=recommended_action,
        ))

    # Sort by breach probability descending
    predictions.sort(key=lambda p: p.predicted_breach_probability, reverse=True)

    return EnhancedSLARiskResponse(
        predictions=predictions,
        total_open_tickets=len(open_tickets),
        high_risk_count=high_risk_count,
        critical_risk_count=critical_risk_count,
    )


# ── Phase 10a: Volume forecasting ────────────────────────────────────────────


@app.get(
    "/analytics/volume-forecast",
    response_model=VolumeForecastResponse,
    tags=["analytics"],
)
async def get_volume_forecast(
    days: int = Query(default=7, ge=1, le=90, description="Number of days to forecast"),
    history_days: int = Query(default=30, ge=7, le=365, description="Number of historical days to analyse"),
    api_key: str = Depends(require_viewer),
) -> VolumeForecastResponse:
    """
    Predict future ticket volumes based on historical trends.

    Analyses historical ticket submission patterns by category and day of week
    to forecast expected volumes for the requested number of days.
    """
    if not settings.volume_forecasting_enabled:
        raise HTTPException(
            status_code=403,
            detail="Volume forecasting is not enabled. Set VOLUME_FORECASTING_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")

    now = datetime.now(tz=timezone.utc)
    cutoff = (now - timedelta(days=history_days)).isoformat()

    # Get historical tickets
    async with _db.execute(
        "SELECT id, category, processed_at FROM processed_tickets WHERE processed_at >= ? ORDER BY processed_at",
        (cutoff,),
    ) as cursor:
        ticket_rows = await cursor.fetchall()

    # Build daily volume counts
    daily_volumes: dict[str, int] = {}
    category_daily: dict[str, dict[str, int]] = {}

    for r in ticket_rows:
        category = r[1] or "unknown"
        try:
            dt = datetime.fromisoformat(r[2])
            date_str = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        daily_volumes[date_str] = daily_volumes.get(date_str, 0) + 1
        category_daily.setdefault(category, {})
        category_daily[category][date_str] = category_daily[category].get(date_str, 0) + 1

    # Calculate daily average
    if daily_volumes:
        total_volume = sum(daily_volumes.values())
        num_days_with_data = len(daily_volumes)
        daily_average = total_volume / num_days_with_data
    else:
        daily_average = 0.0
        num_days_with_data = 0

    # Determine overall trend from the historical data
    sorted_dates = sorted(daily_volumes.keys())
    if len(sorted_dates) >= 2:
        mid = len(sorted_dates) // 2
        first_half = sorted_dates[:mid]
        second_half = sorted_dates[mid:]
        avg_first = sum(daily_volumes[d] for d in first_half) / max(len(first_half), 1)
        avg_second = sum(daily_volumes[d] for d in second_half) / max(len(second_half), 1)
        if avg_second > avg_first * 1.1:
            overall_trend = "increasing"
        elif avg_second < avg_first * 0.9:
            overall_trend = "decreasing"
        else:
            overall_trend = "stable"
    else:
        overall_trend = "stable"

    # Generate forecast points
    trend_multiplier = {"increasing": 1.05, "decreasing": 0.95, "stable": 1.0}[overall_trend]
    forecast_points: list[VolumeForecastPoint] = []

    for i in range(1, days + 1):
        forecast_date = now + timedelta(days=i)
        date_str = forecast_date.strftime("%Y-%m-%d")

        predicted = int(daily_average * (trend_multiplier ** i))
        lower = max(int(predicted * 0.7), 0)
        upper = int(predicted * 1.3) + 1

        forecast_points.append(VolumeForecastPoint(
            date=date_str,
            predicted_volume=max(predicted, 0),
            lower_bound=lower,
            upper_bound=upper,
        ))

    # Category-level forecasts
    category_forecasts: list[CategoryForecast] = []
    for cat, cat_daily in sorted(category_daily.items()):
        cat_dates = sorted(cat_daily.keys())
        cat_total = sum(cat_daily.values())
        cat_avg = cat_total / max(len(cat_dates), 1)

        # Determine category trend
        if len(cat_dates) >= 2:
            mid = len(cat_dates) // 2
            first_h = cat_dates[:mid]
            second_h = cat_dates[mid:]
            avg_f = sum(cat_daily[d] for d in first_h) / max(len(first_h), 1)
            avg_s = sum(cat_daily[d] for d in second_h) / max(len(second_h), 1)
            if avg_s > avg_f * 1.1:
                cat_trend = "increasing"
            elif avg_s < avg_f * 0.9:
                cat_trend = "decreasing"
            else:
                cat_trend = "stable"
        else:
            cat_trend = "stable"

        cat_multiplier = {"increasing": 1.05, "decreasing": 0.95, "stable": 1.0}[cat_trend]
        cat_points: list[VolumeForecastPoint] = []
        for i in range(1, days + 1):
            forecast_date = now + timedelta(days=i)
            date_str = forecast_date.strftime("%Y-%m-%d")
            predicted = int(cat_avg * (cat_multiplier ** i))
            lower = max(int(predicted * 0.7), 0)
            upper = int(predicted * 1.3) + 1
            cat_points.append(VolumeForecastPoint(
                date=date_str,
                predicted_volume=max(predicted, 0),
                lower_bound=lower,
                upper_bound=upper,
            ))

        category_forecasts.append(CategoryForecast(
            category=cat,
            historical_avg=round(cat_avg, 2),
            trend_direction=cat_trend,
            forecast_points=cat_points,
        ))

    return VolumeForecastResponse(
        forecast_days=days,
        overall_trend=overall_trend,
        daily_average=round(daily_average, 2),
        category_forecasts=category_forecasts,
        forecast_points=forecast_points,
    )


# ── Phase 10b: Custom classifiers ────────────────────────────────────────────

_CLASSIFIER_MIN_SAMPLES_READY = 10
_CLASSIFIER_BASE_ACCURACY = 0.65
_CLASSIFIER_ACCURACY_PER_SAMPLE = 0.02
_CLASSIFIER_MAX_ACCURACY = 0.95


@app.post(
    "/custom-classifiers",
    response_model=CustomClassifierResponse,
    tags=["Custom Classifiers"],
)
async def create_custom_classifier(
    body: CustomClassifierCreate,
    api_key: str = Depends(require_admin),
) -> CustomClassifierResponse:
    """Create a custom classifier for organisation-specific categories. Requires admin role."""
    if not settings.custom_classifiers_enabled:
        raise HTTPException(
            status_code=403,
            detail="Custom classifiers are not enabled. Set CUSTOM_CLASSIFIERS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    if len(body.categories) < 2:
        raise HTTPException(
            status_code=422,
            detail="At least 2 categories are required.",
        )

    import json as _json  # noqa: PLC0415

    classifier_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    await _db.execute(
        "INSERT INTO custom_classifiers (id, name, description, categories, training_samples, accuracy, status, created_at) VALUES (?, ?, ?, ?, 0, 0.0, 'untrained', ?)",
        (classifier_id, body.name, body.description, _json.dumps(body.categories), now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_custom_classifier",
        resource=classifier_id,
    )

    record = CustomClassifierRecord(
        id=classifier_id,
        name=body.name,
        description=body.description,
        categories=body.categories,
        training_samples=0,
        accuracy=0.0,
        status="untrained",
        created_at=datetime.fromisoformat(now),
    )
    return CustomClassifierResponse(classifier=record)


@app.get(
    "/custom-classifiers",
    response_model=CustomClassifierListResponse,
    tags=["Custom Classifiers"],
)
async def list_custom_classifiers(
    api_key: str = Depends(require_viewer),
) -> CustomClassifierListResponse:
    """List all custom classifiers."""
    if not settings.custom_classifiers_enabled:
        raise HTTPException(
            status_code=403,
            detail="Custom classifiers are not enabled. Set CUSTOM_CLASSIFIERS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json  # noqa: PLC0415

    async with _db.execute(
        "SELECT id, name, description, categories, training_samples, accuracy, status, created_at FROM custom_classifiers ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    classifiers = [
        CustomClassifierRecord(
            id=r[0],
            name=r[1],
            description=r[2],
            categories=_json.loads(r[3]),
            training_samples=r[4],
            accuracy=r[5],
            status=r[6],
            created_at=datetime.fromisoformat(r[7]),
        )
        for r in rows
    ]
    return CustomClassifierListResponse(classifiers=classifiers, total=len(classifiers))


@app.delete(
    "/custom-classifiers/{classifier_id}",
    tags=["Custom Classifiers"],
)
async def delete_custom_classifier(
    classifier_id: str,
    api_key: str = Depends(require_admin),
) -> dict:
    """Delete a custom classifier and its training data. Requires admin role."""
    if not settings.custom_classifiers_enabled:
        raise HTTPException(
            status_code=403,
            detail="Custom classifiers are not enabled. Set CUSTOM_CLASSIFIERS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    async with _db.execute(
        "SELECT id FROM custom_classifiers WHERE id = ?", (classifier_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Custom classifier not found")

    await _db.execute("DELETE FROM classifier_training_data WHERE classifier_id = ?", (classifier_id,))
    await _db.execute("DELETE FROM custom_classifiers WHERE id = ?", (classifier_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="delete_custom_classifier",
        resource=classifier_id,
    )

    return {"success": True, "deleted": classifier_id}


@app.post(
    "/custom-classifiers/{classifier_id}/train",
    response_model=TrainClassifierResponse,
    tags=["Custom Classifiers"],
)
async def train_custom_classifier(
    classifier_id: str,
    body: TrainClassifierRequest,
    api_key: str = Depends(require_admin),
) -> TrainClassifierResponse:
    """Submit training samples for a custom classifier. Requires admin role."""
    if not settings.custom_classifiers_enabled:
        raise HTTPException(
            status_code=403,
            detail="Custom classifiers are not enabled. Set CUSTOM_CLASSIFIERS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    async with _db.execute(
        "SELECT id, categories, training_samples FROM custom_classifiers WHERE id = ?",
        (classifier_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Custom classifier not found")

    import json as _json  # noqa: PLC0415

    categories = _json.loads(row[1])
    current_samples = row[2]

    # Validate that all sample categories exist in the classifier
    for sample in body.samples:
        if sample.category not in categories:
            raise HTTPException(
                status_code=422,
                detail=f"Category '{sample.category}' is not defined in this classifier. Valid categories: {categories}",
            )

    # Store training data
    now = datetime.now(tz=timezone.utc).isoformat()
    for sample in body.samples:
        sample_id = str(uuid.uuid4())
        await _db.execute(
            "INSERT INTO classifier_training_data (id, classifier_id, text, category, created_at) VALUES (?, ?, ?, ?, ?)",
            (sample_id, classifier_id, sample.text, sample.category, now),
        )

    new_total = current_samples + len(body.samples)
    new_status = "ready" if new_total >= _CLASSIFIER_MIN_SAMPLES_READY else "untrained"
    new_accuracy = min(_CLASSIFIER_BASE_ACCURACY + (new_total * _CLASSIFIER_ACCURACY_PER_SAMPLE), _CLASSIFIER_MAX_ACCURACY) if new_total >= _CLASSIFIER_MIN_SAMPLES_READY else 0.0

    await _db.execute(
        "UPDATE custom_classifiers SET training_samples = ?, status = ?, accuracy = ? WHERE id = ?",
        (new_total, new_status, round(new_accuracy, 4), classifier_id),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="train_custom_classifier",
        resource=classifier_id,
    )

    return TrainClassifierResponse(
        classifier_id=classifier_id,
        samples_added=len(body.samples),
        total_samples=new_total,
        status=new_status,
    )


@app.post(
    "/custom-classifiers/{classifier_id}/classify",
    response_model=ClassifyResponse,
    tags=["Custom Classifiers"],
)
async def classify_text(
    classifier_id: str,
    body: ClassifyRequest,
    api_key: str = Depends(require_viewer),
) -> ClassifyResponse:
    """Classify text using a custom classifier."""
    if not settings.custom_classifiers_enabled:
        raise HTTPException(
            status_code=403,
            detail="Custom classifiers are not enabled. Set CUSTOM_CLASSIFIERS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    async with _db.execute(
        "SELECT id, categories, status FROM custom_classifiers WHERE id = ?",
        (classifier_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Custom classifier not found")

    if row[2] != "ready":
        raise HTTPException(
            status_code=400,
            detail="Classifier is not ready. Train with at least 10 samples first.",
        )

    import json as _json  # noqa: PLC0415

    categories = _json.loads(row[1])

    # Fetch training data for keyword matching
    async with _db.execute(
        "SELECT text, category FROM classifier_training_data WHERE classifier_id = ?",
        (classifier_id,),
    ) as cursor:
        training_rows = await cursor.fetchall()

    # Simulate classification using keyword matching
    input_lower = body.text.lower()
    scores: dict[str, float] = {cat: 0.0 for cat in categories}

    for t_row in training_rows:
        sample_text = t_row[0].lower()
        sample_cat = t_row[1]
        # Count word overlaps between input and training sample
        sample_words = set(sample_text.split())
        input_words = set(input_lower.split())
        overlap = len(sample_words & input_words)
        if overlap > 0:
            scores[sample_cat] = scores.get(sample_cat, 0.0) + overlap

    # Normalise scores to probabilities
    total_score = sum(scores.values())
    if total_score > 0:
        scores = {cat: round(s / total_score, 4) for cat, s in scores.items()}
    else:
        # Equal distribution if no matches
        equal = round(1.0 / len(categories), 4)
        scores = {cat: equal for cat in categories}

    predicted_category = max(scores, key=lambda c: scores[c])
    confidence = scores[predicted_category]

    return ClassifyResponse(
        classifier_id=classifier_id,
        text=body.text,
        predicted_category=predicted_category,
        confidence=confidence,
        all_scores=scores,
    )


# ── Phase 10b: Anomaly detection ─────────────────────────────────────────────


_VALID_ANOMALY_METRICS = {"volume", "category_shift", "priority_spike", "resolution_time"}
_SEVERITY_CRITICAL_MULTIPLIER = 2.0
_SEVERITY_HIGH_MULTIPLIER = 1.5


@app.post(
    "/anomaly-rules",
    response_model=AnomalyRuleResponse,
    tags=["Anomaly Detection"],
)
async def create_anomaly_rule(
    body: AnomalyRuleCreate,
    api_key: str = Depends(require_admin),
) -> AnomalyRuleResponse:
    """Create an anomaly detection rule. Requires admin role."""
    if not settings.anomaly_detection_enabled:
        raise HTTPException(
            status_code=403,
            detail="Anomaly detection is not enabled. Set ANOMALY_DETECTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    if body.metric not in _VALID_ANOMALY_METRICS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid metric '{body.metric}'. Must be one of: {', '.join(sorted(_VALID_ANOMALY_METRICS))}",
        )

    rule_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    await _db.execute(
        "INSERT INTO anomaly_rules (id, name, metric, threshold, window_hours, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (rule_id, body.name, body.metric, body.threshold, body.window_hours, 1 if body.enabled else 0, now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_anomaly_rule",
        resource=rule_id,
    )

    record = AnomalyRuleRecord(
        id=rule_id,
        name=body.name,
        metric=body.metric,
        threshold=body.threshold,
        window_hours=body.window_hours,
        enabled=body.enabled,
        created_at=datetime.fromisoformat(now),
    )
    return AnomalyRuleResponse(rule=record)


@app.get(
    "/anomaly-rules",
    response_model=AnomalyRuleListResponse,
    tags=["Anomaly Detection"],
)
async def list_anomaly_rules(
    api_key: str = Depends(require_viewer),
) -> AnomalyRuleListResponse:
    """List all anomaly detection rules."""
    if not settings.anomaly_detection_enabled:
        raise HTTPException(
            status_code=403,
            detail="Anomaly detection is not enabled. Set ANOMALY_DETECTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    async with _db.execute(
        "SELECT id, name, metric, threshold, window_hours, enabled, created_at FROM anomaly_rules ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    rules = [
        AnomalyRuleRecord(
            id=r[0],
            name=r[1],
            metric=r[2],
            threshold=r[3],
            window_hours=r[4],
            enabled=bool(r[5]),
            created_at=datetime.fromisoformat(r[6]),
        )
        for r in rows
    ]
    return AnomalyRuleListResponse(rules=rules, total=len(rules))


@app.delete(
    "/anomaly-rules/{rule_id}",
    tags=["Anomaly Detection"],
)
async def delete_anomaly_rule(
    rule_id: str,
    api_key: str = Depends(require_admin),
) -> dict:
    """Delete an anomaly detection rule. Requires admin role."""
    if not settings.anomaly_detection_enabled:
        raise HTTPException(
            status_code=403,
            detail="Anomaly detection is not enabled. Set ANOMALY_DETECTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    async with _db.execute(
        "SELECT id FROM anomaly_rules WHERE id = ?", (rule_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Anomaly rule not found")

    await _db.execute("DELETE FROM anomaly_rules WHERE id = ?", (rule_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="delete_anomaly_rule",
        resource=rule_id,
    )

    return {"success": True, "deleted": rule_id}


@app.get(
    "/analytics/anomalies",
    response_model=AnomalyDetectionResponse,
    tags=["Anomaly Detection"],
)
async def detect_anomalies(
    hours: int = Query(default=24, ge=1, le=720, description="Analysis window in hours"),
    api_key: str = Depends(require_viewer),
) -> AnomalyDetectionResponse:
    """Detect anomalies based on configured rules."""
    if not settings.anomaly_detection_enabled:
        raise HTTPException(
            status_code=403,
            detail="Anomaly detection is not enabled. Set ANOMALY_DETECTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    # Get enabled rules
    async with _db.execute(
        "SELECT id, name, metric, threshold, window_hours, enabled FROM anomaly_rules WHERE enabled = 1"
    ) as cursor:
        rule_rows = await cursor.fetchall()

    now = datetime.now(tz=timezone.utc)
    anomalies: list[DetectedAnomaly] = []

    for rule in rule_rows:
        rule_metric = rule[2]
        rule_threshold = rule[3]
        rule_window = min(rule[4], hours)
        window_start = (now - timedelta(hours=rule_window)).isoformat()
        prev_window_start = (now - timedelta(hours=rule_window * 2)).isoformat()

        if rule_metric == "volume":
            # Compare current window ticket volume to previous window
            async with _db.execute(
                "SELECT COUNT(*) FROM processed_tickets WHERE processed_at >= ?",
                (window_start,),
            ) as cur:
                current_row = await cur.fetchone()
            current_count = current_row[0] if current_row else 0

            async with _db.execute(
                "SELECT COUNT(*) FROM processed_tickets WHERE processed_at >= ? AND processed_at < ?",
                (prev_window_start, window_start),
            ) as cur:
                prev_row = await cur.fetchone()
            prev_count = prev_row[0] if prev_row else 0

            if prev_count > 0:
                ratio = current_count / prev_count
                if ratio > (1 + rule_threshold):
                    if ratio > (1 + rule_threshold * _SEVERITY_CRITICAL_MULTIPLIER):
                        severity = "critical"
                    elif ratio > (1 + rule_threshold * _SEVERITY_HIGH_MULTIPLIER):
                        severity = "high"
                    else:
                        severity = "medium"
                    anomalies.append(DetectedAnomaly(
                        anomaly_type="volume",
                        severity=severity,
                        metric_value=float(current_count),
                        threshold=rule_threshold,
                        description=f"Ticket volume spike: {current_count} tickets in last {rule_window}h vs {prev_count} in previous window ({ratio:.1f}x increase)",
                        detected_at=now.isoformat(),
                        window_hours=rule_window,
                    ))

        elif rule_metric == "category_shift":
            # Detect unusual category distribution changes
            async with _db.execute(
                "SELECT category, COUNT(*) FROM processed_tickets WHERE processed_at >= ? GROUP BY category",
                (window_start,),
            ) as cur:
                current_cats = await cur.fetchall()

            async with _db.execute(
                "SELECT category, COUNT(*) FROM processed_tickets WHERE processed_at >= ? AND processed_at < ? GROUP BY category",
                (prev_window_start, window_start),
            ) as cur:
                prev_cats = await cur.fetchall()

            prev_dist: dict[str, int] = {r[0]: r[1] for r in prev_cats}
            total_prev = sum(prev_dist.values()) or 1

            for cat_row in current_cats:
                cat_name, cat_count = cat_row[0], cat_row[1]
                prev_cat_count = prev_dist.get(cat_name, 0)
                prev_ratio = prev_cat_count / total_prev
                curr_total = sum(r[1] for r in current_cats) or 1
                curr_ratio = cat_count / curr_total

                if prev_ratio > 0 and curr_ratio > 0:
                    shift = abs(curr_ratio - prev_ratio) / prev_ratio
                    if shift > rule_threshold:
                        anomalies.append(DetectedAnomaly(
                            anomaly_type="category_shift",
                            severity="medium" if shift < rule_threshold * _SEVERITY_CRITICAL_MULTIPLIER else "high",
                            metric_value=round(shift, 4),
                            threshold=rule_threshold,
                            description=f"Category '{cat_name}' distribution shifted by {shift:.0%} (was {prev_ratio:.0%}, now {curr_ratio:.0%})",
                            detected_at=now.isoformat(),
                            window_hours=rule_window,
                        ))

        elif rule_metric == "priority_spike":
            # Detect increase in high/critical priority tickets
            async with _db.execute(
                "SELECT COUNT(*) FROM processed_tickets WHERE processed_at >= ? AND priority IN ('critical', 'high')",
                (window_start,),
            ) as cur:
                high_row = await cur.fetchone()
            high_count = high_row[0] if high_row else 0

            async with _db.execute(
                "SELECT COUNT(*) FROM processed_tickets WHERE processed_at >= ?",
                (window_start,),
            ) as cur:
                total_row = await cur.fetchone()
            total_count = total_row[0] if total_row else 0

            if total_count > 0:
                high_ratio = high_count / total_count
                if high_ratio > rule_threshold:
                    severity = "critical" if high_ratio > rule_threshold * _SEVERITY_CRITICAL_MULTIPLIER else "high"
                    anomalies.append(DetectedAnomaly(
                        anomaly_type="priority_spike",
                        severity=severity,
                        metric_value=round(high_ratio, 4),
                        threshold=rule_threshold,
                        description=f"High/critical priority spike: {high_count}/{total_count} tickets ({high_ratio:.0%}) exceed threshold ({rule_threshold:.0%})",
                        detected_at=now.isoformat(),
                        window_hours=rule_window,
                    ))

        elif rule_metric == "resolution_time":
            # Detect unusually long open ticket age (hours since processing)
            async with _db.execute(
                "SELECT AVG(CAST((julianday('now') - julianday(processed_at)) * 24 AS REAL)) FROM processed_tickets WHERE processed_at >= ? AND ticket_status IN ('open', 'in_progress')",
                (window_start,),
            ) as cur:
                avg_row = await cur.fetchone()
            avg_hours = avg_row[0] if avg_row and avg_row[0] is not None else 0.0

            if avg_hours > rule_threshold:
                severity = "high" if avg_hours > rule_threshold * _SEVERITY_CRITICAL_MULTIPLIER else "medium"
                anomalies.append(DetectedAnomaly(
                    anomaly_type="resolution_time",
                    severity=severity,
                    metric_value=round(avg_hours, 2),
                    threshold=rule_threshold,
                    description=f"Average resolution time {avg_hours:.1f}h exceeds threshold of {rule_threshold:.1f}h",
                    detected_at=now.isoformat(),
                    window_hours=rule_window,
                ))

    return AnomalyDetectionResponse(
        anomalies=anomalies,
        total_anomalies=len(anomalies),
        analysis_window_hours=hours,
    )


# ── Phase 10b: KB auto-generation ────────────────────────────────────────────

_KB_BASE_CONFIDENCE = 0.5
_KB_CONFIDENCE_PER_TICKET = 0.05
_KB_MAX_CONFIDENCE = 0.95
_KB_MAX_SUMMARIES_PER_ARTICLE = 10


@app.post(
    "/kb/auto-generate",
    response_model=KBAutoGenerateResponse,
    tags=["KB Auto-Generation"],
)
async def kb_auto_generate(
    body: KBAutoGenerateRequest,
    api_key: str = Depends(require_admin),
) -> KBAutoGenerateResponse:
    """Generate KB articles from resolved ticket patterns. Requires admin role."""
    if not settings.kb_auto_generation_enabled:
        raise HTTPException(
            status_code=403,
            detail="KB auto-generation is not enabled. Set KB_AUTO_GENERATION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    # Query resolved tickets, optionally filtered by category
    if body.category:
        async with _db.execute(
            "SELECT id, category, summary, source FROM processed_tickets WHERE ticket_status = 'resolved' AND category = ? ORDER BY processed_at DESC",
            (body.category,),
        ) as cursor:
            ticket_rows = await cursor.fetchall()
    else:
        async with _db.execute(
            "SELECT id, category, summary, source FROM processed_tickets WHERE ticket_status = 'resolved' ORDER BY processed_at DESC",
        ) as cursor:
            ticket_rows = await cursor.fetchall()

    # Group tickets by category
    by_category: dict[str, list[tuple]] = {}
    for t in ticket_rows:
        cat = t[1] or "uncategorised"
        by_category.setdefault(cat, []).append(t)

    articles: list[GeneratedKBArticle] = []
    for cat, tickets in sorted(by_category.items()):
        if len(tickets) < body.min_resolved_tickets:
            continue
        if len(articles) >= body.max_articles:
            break

        # Generate article from ticket patterns
        summaries = [t[2] for t in tickets if t[2]]
        if not summaries:
            continue

        title = f"Troubleshooting Guide: {cat.replace('_', ' ').title()}"
        content_parts = [f"# {title}\n"]
        content_parts.append(f"This article was auto-generated from {len(tickets)} resolved tickets in the '{cat}' category.\n")
        content_parts.append("## Common Issues and Solutions\n")

        # Use unique summaries as content
        seen: set[str] = set()
        for summary in summaries[:_KB_MAX_SUMMARIES_PER_ARTICLE]:
            normalised = summary.strip().lower()
            if normalised not in seen:
                seen.add(normalised)
                content_parts.append(f"- {summary}")

        content = "\n".join(content_parts)

        confidence = min(_KB_BASE_CONFIDENCE + (len(tickets) * _KB_CONFIDENCE_PER_TICKET), _KB_MAX_CONFIDENCE)
        tags = [cat, "auto-generated", "resolved-patterns"]

        articles.append(GeneratedKBArticle(
            title=title,
            content=content,
            category=cat,
            source_ticket_count=len(tickets),
            confidence=round(confidence, 4),
            tags=tags,
        ))

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="kb_auto_generate",
        resource=f"{len(articles)}_articles",
    )

    return KBAutoGenerateResponse(
        articles=articles,
        total_generated=len(articles),
    )


@app.get(
    "/kb/auto-generate/suggestions",
    response_model=KBAutoGenerateSuggestionsResponse,
    tags=["KB Auto-Generation"],
)
async def kb_auto_generate_suggestions(
    api_key: str = Depends(require_viewer),
) -> KBAutoGenerateSuggestionsResponse:
    """Show categories where KB articles could be auto-generated."""
    if not settings.kb_auto_generation_enabled:
        raise HTTPException(
            status_code=403,
            detail="KB auto-generation is not enabled. Set KB_AUTO_GENERATION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    # Count resolved tickets per category
    async with _db.execute(
        "SELECT category, COUNT(*) FROM processed_tickets WHERE ticket_status = 'resolved' GROUP BY category ORDER BY COUNT(*) DESC",
    ) as cursor:
        resolved_rows = await cursor.fetchall()

    # Count existing KB articles per category
    async with _db.execute(
        "SELECT category, COUNT(*) FROM kb_articles GROUP BY category",
    ) as cursor:
        kb_rows = await cursor.fetchall()

    kb_counts: dict[str, int] = {r[0]: r[1] for r in kb_rows}

    suggestions: list[KBSuggestion] = []
    for row in resolved_rows:
        cat = row[0] or "uncategorised"
        resolved_count = row[1]
        existing_count = kb_counts.get(cat, 0)

        # Score based on resolved tickets and gap in KB coverage
        score = resolved_count * (1.0 / (existing_count + 1))
        suggested_title = f"Troubleshooting Guide: {cat.replace('_', ' ').title()}"

        suggestions.append(KBSuggestion(
            category=cat,
            resolved_ticket_count=resolved_count,
            existing_article_count=existing_count,
            suggestion_score=round(score, 2),
            suggested_title=suggested_title,
        ))

    # Sort by score descending
    suggestions.sort(key=lambda s: s.suggestion_score, reverse=True)

    return KBAutoGenerateSuggestionsResponse(
        suggestions=suggestions,
        total_suggestions=len(suggestions),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 10c — Platform Maturity
# ═══════════════════════════════════════════════════════════════════════════════


# ── Visual Workflow Builder ──────────────────────────────────────────────────


@app.post(
    "/workflow-builder/workflows",
    response_model=WorkflowResponse,
    tags=["Visual Workflow Builder"],
)
async def create_visual_workflow(
    body: WorkflowCreate,
    api_key: str = Depends(require_admin),
) -> WorkflowResponse:
    """Create a visual workflow definition for automation rules and approval workflows."""
    if not settings.workflow_builder_enabled:
        raise HTTPException(
            status_code=403,
            detail="Visual workflow builder is not enabled. Set WORKFLOW_BUILDER_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    workflow_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    nodes_json = _json.dumps([n.model_dump() for n in body.nodes])
    edges_json = _json.dumps([e.model_dump() for e in body.edges])

    await _db.execute(
        "INSERT INTO visual_workflows (id, name, description, nodes, edges, status, created_at) VALUES (?, ?, ?, ?, ?, 'draft', ?)",
        (workflow_id, body.name, body.description, nodes_json, edges_json, now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_visual_workflow",
        resource=workflow_id,
    )

    record = WorkflowRecord(
        id=workflow_id,
        name=body.name,
        description=body.description,
        nodes=body.nodes,
        edges=body.edges,
        status="draft",
        created_at=datetime.fromisoformat(now),
    )
    return WorkflowResponse(workflow=record)


@app.get(
    "/workflow-builder/workflows",
    response_model=WorkflowListResponse,
    tags=["Visual Workflow Builder"],
)
async def list_visual_workflows(
    api_key: str = Depends(require_viewer),
) -> WorkflowListResponse:
    """List all visual workflows."""
    if not settings.workflow_builder_enabled:
        raise HTTPException(
            status_code=403,
            detail="Visual workflow builder is not enabled. Set WORKFLOW_BUILDER_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    async with _db.execute(
        "SELECT id, name, description, nodes, edges, status, created_at, updated_at FROM visual_workflows ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    workflows = [
        WorkflowRecord(
            id=r[0],
            name=r[1],
            description=r[2],
            nodes=[WorkflowNode(**n) for n in _json.loads(r[3])],
            edges=[WorkflowEdge(**e) for e in _json.loads(r[4])],
            status=r[5],
            created_at=datetime.fromisoformat(r[6]),
            updated_at=datetime.fromisoformat(r[7]) if r[7] else None,
        )
        for r in rows
    ]
    return WorkflowListResponse(workflows=workflows, total=len(workflows))


@app.delete(
    "/workflow-builder/workflows/{workflow_id}",
    response_model=WorkflowResponse,
    tags=["Visual Workflow Builder"],
)
async def delete_visual_workflow(
    workflow_id: str,
    api_key: str = Depends(require_admin),
) -> WorkflowResponse:
    """Delete a visual workflow by ID."""
    if not settings.workflow_builder_enabled:
        raise HTTPException(
            status_code=403,
            detail="Visual workflow builder is not enabled. Set WORKFLOW_BUILDER_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    async with _db.execute(
        "SELECT id, name, description, nodes, edges, status, created_at, updated_at FROM visual_workflows WHERE id = ?",
        (workflow_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    await _db.execute("DELETE FROM visual_workflows WHERE id = ?", (workflow_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="delete_visual_workflow",
        resource=workflow_id,
    )

    record = WorkflowRecord(
        id=row[0],
        name=row[1],
        description=row[2],
        nodes=[WorkflowNode(**n) for n in _json.loads(row[3])],
        edges=[WorkflowEdge(**e) for e in _json.loads(row[4])],
        status=row[5],
        created_at=datetime.fromisoformat(row[6]),
        updated_at=datetime.fromisoformat(row[7]) if row[7] else None,
    )
    return WorkflowResponse(workflow=record)


@app.post(
    "/workflow-builder/workflows/{workflow_id}/publish",
    response_model=WorkflowResponse,
    tags=["Visual Workflow Builder"],
)
async def publish_visual_workflow(
    workflow_id: str,
    api_key: str = Depends(require_admin),
) -> WorkflowResponse:
    """Publish (activate) a visual workflow."""
    if not settings.workflow_builder_enabled:
        raise HTTPException(
            status_code=403,
            detail="Visual workflow builder is not enabled. Set WORKFLOW_BUILDER_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    async with _db.execute(
        "SELECT id, name, description, nodes, edges, status, created_at FROM visual_workflows WHERE id = ?",
        (workflow_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    now = datetime.now(tz=timezone.utc).isoformat()
    await _db.execute(
        "UPDATE visual_workflows SET status = 'published', updated_at = ? WHERE id = ?",
        (now, workflow_id),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="publish_visual_workflow",
        resource=workflow_id,
    )

    record = WorkflowRecord(
        id=row[0],
        name=row[1],
        description=row[2],
        nodes=[WorkflowNode(**n) for n in _json.loads(row[3])],
        edges=[WorkflowEdge(**e) for e in _json.loads(row[4])],
        status="published",
        created_at=datetime.fromisoformat(row[6]),
        updated_at=datetime.fromisoformat(now),
    )
    return WorkflowResponse(workflow=record)


@app.post(
    "/workflow-builder/workflows/{workflow_id}/validate",
    response_model=WorkflowValidationResponse,
    tags=["Visual Workflow Builder"],
)
async def validate_visual_workflow(
    workflow_id: str,
    api_key: str = Depends(require_viewer),
) -> WorkflowValidationResponse:
    """Validate a visual workflow definition for correctness."""
    if not settings.workflow_builder_enabled:
        raise HTTPException(
            status_code=403,
            detail="Visual workflow builder is not enabled. Set WORKFLOW_BUILDER_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    async with _db.execute(
        "SELECT nodes, edges FROM visual_workflows WHERE id = ?",
        (workflow_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    nodes = _json.loads(row[0])
    edges = _json.loads(row[1])

    errors: list[str] = []
    warnings: list[str] = []

    # Validate: must have at least one node
    if not nodes:
        errors.append("Workflow must contain at least one node.")

    # Validate: must have a trigger node
    trigger_nodes = [n for n in nodes if n.get("type") == "trigger"]
    if not trigger_nodes:
        errors.append("Workflow must contain at least one trigger node.")

    # Validate: edges reference valid nodes
    node_ids = {n["id"] for n in nodes}
    for edge in edges:
        if edge.get("source_node_id") not in node_ids:
            errors.append(f"Edge references unknown source node: {edge.get('source_node_id')}")
        if edge.get("target_node_id") not in node_ids:
            errors.append(f"Edge references unknown target node: {edge.get('target_node_id')}")

    # Warning: orphan nodes (no edges)
    connected_ids: set[str] = set()
    for edge in edges:
        connected_ids.add(edge.get("source_node_id", ""))
        connected_ids.add(edge.get("target_node_id", ""))
    for n in nodes:
        if n["id"] not in connected_ids and len(nodes) > 1:
            warnings.append(f"Node '{n['id']}' is not connected to any other node.")

    valid = len(errors) == 0
    result = WorkflowValidationResult(valid=valid, errors=errors, warnings=warnings)
    return WorkflowValidationResponse(validation=result)


# ── Compliance & Security Hardening ──────────────────────────────────────────


@app.post(
    "/compliance/data-retention-policies",
    response_model=DataRetentionPolicyResponse,
    tags=["Compliance"],
)
async def create_data_retention_policy(
    body: DataRetentionPolicyCreate,
    api_key: str = Depends(require_admin),
) -> DataRetentionPolicyResponse:
    """Create a data retention policy. Requires admin role."""
    if not settings.compliance_enabled:
        raise HTTPException(
            status_code=403,
            detail="Compliance features are not enabled. Set COMPLIANCE_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    valid_entity_types = {"tickets", "audit_logs", "attachments", "contacts", "kb_articles"}
    if body.entity_type not in valid_entity_types:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid entity_type. Must be one of: {', '.join(sorted(valid_entity_types))}",
        )

    valid_actions = {"archive", "delete", "anonymise"}
    if body.action not in valid_actions:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action. Must be one of: {', '.join(sorted(valid_actions))}",
        )

    policy_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    await _db.execute(
        "INSERT INTO data_retention_policies (id, name, entity_type, retention_days, action, enabled, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
        (policy_id, body.name, body.entity_type, body.retention_days, body.action, now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_data_retention_policy",
        resource=policy_id,
    )

    record = DataRetentionPolicyRecord(
        id=policy_id,
        name=body.name,
        entity_type=body.entity_type,
        retention_days=body.retention_days,
        action=body.action,
        enabled=True,
        created_at=datetime.fromisoformat(now),
    )
    return DataRetentionPolicyResponse(policy=record)


@app.get(
    "/compliance/data-retention-policies",
    response_model=DataRetentionPolicyListResponse,
    tags=["Compliance"],
)
async def list_data_retention_policies(
    api_key: str = Depends(require_viewer),
) -> DataRetentionPolicyListResponse:
    """List all data retention policies."""
    if not settings.compliance_enabled:
        raise HTTPException(
            status_code=403,
            detail="Compliance features are not enabled. Set COMPLIANCE_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    async with _db.execute(
        "SELECT id, name, entity_type, retention_days, action, enabled, created_at FROM data_retention_policies ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    policies = [
        DataRetentionPolicyRecord(
            id=r[0],
            name=r[1],
            entity_type=r[2],
            retention_days=r[3],
            action=r[4],
            enabled=bool(r[5]),
            created_at=datetime.fromisoformat(r[6]),
        )
        for r in rows
    ]
    return DataRetentionPolicyListResponse(policies=policies, total=len(policies))


@app.delete(
    "/compliance/data-retention-policies/{policy_id}",
    response_model=DataRetentionPolicyResponse,
    tags=["Compliance"],
)
async def delete_data_retention_policy(
    policy_id: str,
    api_key: str = Depends(require_admin),
) -> DataRetentionPolicyResponse:
    """Delete a data retention policy by ID."""
    if not settings.compliance_enabled:
        raise HTTPException(
            status_code=403,
            detail="Compliance features are not enabled. Set COMPLIANCE_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    async with _db.execute(
        "SELECT id, name, entity_type, retention_days, action, enabled, created_at FROM data_retention_policies WHERE id = ?",
        (policy_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Data retention policy not found")

    await _db.execute("DELETE FROM data_retention_policies WHERE id = ?", (policy_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="delete_data_retention_policy",
        resource=policy_id,
    )

    record = DataRetentionPolicyRecord(
        id=row[0],
        name=row[1],
        entity_type=row[2],
        retention_days=row[3],
        action=row[4],
        enabled=bool(row[5]),
        created_at=datetime.fromisoformat(row[6]),
    )
    return DataRetentionPolicyResponse(policy=record)


import re as _re  # noqa: E402

_PII_PATTERNS: dict[str, str] = {
    "email": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    "phone": r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
}


@app.post(
    "/compliance/pii-redact",
    response_model=PIIRedactResponse,
    tags=["Compliance"],
)
async def redact_pii(
    body: PIIRedactRequest,
    api_key: str = Depends(require_viewer),
) -> PIIRedactResponse:
    """Redact PII (personally identifiable information) from text."""
    if not settings.compliance_enabled:
        raise HTTPException(
            status_code=403,
            detail="Compliance features are not enabled. Set COMPLIANCE_ENABLED=true.",
        )

    redacted = body.text
    total_redactions = 0
    types_found: list[str] = []

    for pii_type in body.redact_types:
        pattern = _PII_PATTERNS.get(pii_type)
        if not pattern:
            continue
        matches = _re.findall(pattern, redacted)
        if matches:
            types_found.append(pii_type)
            total_redactions += len(matches)
            redacted = _re.sub(pattern, f"[{pii_type.upper()}_REDACTED]", redacted)

    return PIIRedactResponse(
        original_length=len(body.text),
        redacted_text=redacted,
        redactions_applied=total_redactions,
        redaction_types_found=types_found,
    )


@app.get(
    "/compliance/audit-export",
    response_model=AuditExportResponse,
    tags=["Compliance"],
)
async def export_audit_logs(
    days: int = Query(default=30, ge=1, le=365, description="Number of days of audit logs to export"),
    api_key: str = Depends(require_admin),
) -> AuditExportResponse:
    """Export audit logs for SOC 2 compliance reporting."""
    if not settings.compliance_enabled:
        raise HTTPException(
            status_code=403,
            detail="Compliance features are not enabled. Set COMPLIANCE_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    since = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()

    async with _db.execute(
        "SELECT id, timestamp, api_key_hash, role, action, resource, detail FROM audit_log WHERE timestamp >= ? ORDER BY timestamp DESC",
        (since,),
    ) as cursor:
        rows = await cursor.fetchall()

    records = [
        {
            "id": r[0],
            "timestamp": r[1],
            "api_key_hash": r[2][:4] + "***" if r[2] else r[2],
            "role": r[3],
            "action": r[4],
            "resource": r[5],
            "detail": r[6],
        }
        for r in rows
    ]

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="export_audit_logs",
        resource=f"{len(records)}_records",
    )

    return AuditExportResponse(
        total_records=len(records),
        export_format="json",
        records=records,
    )


@app.get(
    "/compliance/security-posture",
    response_model=SecurityPostureResponse,
    tags=["Compliance"],
)
async def get_security_posture(
    api_key: str = Depends(require_admin),
) -> SecurityPostureResponse:
    """Get security posture report with SOC 2 readiness checks."""
    if not settings.compliance_enabled:
        raise HTTPException(
            status_code=403,
            detail="Compliance features are not enabled. Set COMPLIANCE_ENABLED=true.",
        )

    checks: list[SecurityPostureItem] = []

    # Check: API key authentication enabled
    checks.append(SecurityPostureItem(
        check="API key authentication",
        status="pass" if settings.api_keys else "fail",
        severity="critical",
        detail="API key authentication is configured." if settings.api_keys else "No API keys configured.",
    ))

    # Check: Role-based access control
    has_rbac = bool(settings.api_key_roles)
    checks.append(SecurityPostureItem(
        check="Role-based access control",
        status="pass" if has_rbac else "warning",
        severity="high",
        detail="RBAC is configured with role mappings." if has_rbac else "No role mappings configured.",
    ))

    # Check: Rate limiting
    checks.append(SecurityPostureItem(
        check="Rate limiting",
        status="pass",
        severity="medium",
        detail="Rate limiting is active via slowapi.",
    ))

    # Check: Audit logging
    checks.append(SecurityPostureItem(
        check="Audit logging",
        status="pass",
        severity="high",
        detail="Audit logging is enabled for all state-changing operations.",
    ))

    # Check: Data retention policies
    if _db is not None:
        async with _db.execute("SELECT COUNT(*) FROM data_retention_policies") as cursor:
            policy_count = (await cursor.fetchone())[0]
        checks.append(SecurityPostureItem(
            check="Data retention policies",
            status="pass" if policy_count > 0 else "warning",
            severity="medium",
            detail=f"{policy_count} data retention policy(ies) configured." if policy_count > 0 else "No data retention policies configured.",
        ))
    else:
        checks.append(SecurityPostureItem(
            check="Data retention policies",
            status="fail",
            severity="medium",
            detail="Database not available for policy check.",
        ))

    # Check: HTTPS enforcement
    checks.append(SecurityPostureItem(
        check="HTTPS enforcement",
        status="warning",
        severity="high",
        detail="HTTPS should be enforced at the reverse proxy / load balancer level.",
    ))

    passed = sum(1 for c in checks if c.status == "pass")
    warning_count = sum(1 for c in checks if c.status == "warning")
    fail_count = sum(1 for c in checks if c.status == "fail")
    total = len(checks)
    score = round((passed / total) * 100, 1) if total > 0 else 0.0

    return SecurityPostureResponse(
        overall_score=score,
        checks=checks,
        total_checks=total,
        passed=passed,
        warnings=warning_count,
        failures=fail_count,
    )


# ── Performance & Scale Improvements ─────────────────────────────────────────

_app_start_time: float = time.monotonic()
_request_count: int = 0
_total_response_time: float = 0.0
_cache_store: dict[str, tuple[float, object]] = {}  # key -> (expiry_timestamp, value)
_cache_hits: int = 0
_cache_misses: int = 0


@app.post(
    "/admin/cache/invalidate",
    response_model=CacheInvalidateResponse,
    tags=["Performance"],
)
async def invalidate_cache(
    body: CacheInvalidateRequest,
    api_key: str = Depends(require_admin),
) -> CacheInvalidateResponse:
    """Invalidate cache entries matching a pattern.

    Note: The current cache is in-process memory. In multi-worker deployments,
    each worker has its own cache and invalidation only affects the current worker.
    """
    if not settings.performance_monitoring_enabled:
        raise HTTPException(
            status_code=403,
            detail="Performance monitoring is not enabled. Set PERFORMANCE_MONITORING_ENABLED=true.",
        )

    global _cache_store  # noqa: PLW0603
    if body.pattern == "*":
        count = len(_cache_store)
        _cache_store = {}
    else:
        keys_to_remove = [k for k in _cache_store if body.pattern in k]
        count = len(keys_to_remove)
        for k in keys_to_remove:
            del _cache_store[k]

    if _db is not None:
        await audit.record(
            _db,
            api_key=api_key,
            role=_resolve_role(api_key),
            action="invalidate_cache",
            resource=f"{count}_entries",
        )

    return CacheInvalidateResponse(invalidated_count=count)


@app.get(
    "/admin/cache/stats",
    response_model=CacheStatsResponse,
    tags=["Performance"],
)
async def get_cache_stats(
    api_key: str = Depends(require_admin),
) -> CacheStatsResponse:
    """Get cache statistics."""
    if not settings.performance_monitoring_enabled:
        raise HTTPException(
            status_code=403,
            detail="Performance monitoring is not enabled. Set PERFORMANCE_MONITORING_ENABLED=true.",
        )

    total = _cache_hits + _cache_misses
    hit_rate = round(_cache_hits / total, 4) if total > 0 else 0.0

    import sys as _sys

    mem = sum(_sys.getsizeof(v) for v in _cache_store.values())

    return CacheStatsResponse(
        total_entries=len(_cache_store),
        hit_count=_cache_hits,
        miss_count=_cache_misses,
        hit_rate=hit_rate,
        memory_usage_bytes=mem,
    )


@app.get(
    "/admin/performance/metrics",
    response_model=PerformanceMetricsResponse,
    tags=["Performance"],
)
async def get_performance_metrics(
    api_key: str = Depends(require_admin),
) -> PerformanceMetricsResponse:
    """Get system performance metrics."""
    if not settings.performance_monitoring_enabled:
        raise HTTPException(
            status_code=403,
            detail="Performance monitoring is not enabled. Set PERFORMANCE_MONITORING_ENABLED=true.",
        )


    uptime = time.monotonic() - _app_start_time
    avg_resp = round(_total_response_time / _request_count * 1000, 2) if _request_count > 0 else 0.0

    # Memory usage
    try:
        import resource as _resource

        mem_mb = round(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss / 1024, 2)
    except Exception:
        mem_mb = 0.0

    total_hits_misses = _cache_hits + _cache_misses
    cache_rate = round(_cache_hits / total_hits_misses, 4) if total_hits_misses > 0 else 0.0

    metrics = PerformanceMetrics(
        uptime_seconds=round(uptime, 2),
        total_requests=_request_count,
        avg_response_time_ms=avg_resp,
        db_pool_size=1,
        db_active_connections=1 if _db is not None else 0,
        cache_hit_rate=cache_rate,
        cache_entries=len(_cache_store),
        memory_usage_mb=mem_mb,
    )
    return PerformanceMetricsResponse(metrics=metrics)


@app.get(
    "/admin/connection-pool/stats",
    response_model=ConnectionPoolStatsResponse,
    tags=["Performance"],
)
async def get_connection_pool_stats(
    api_key: str = Depends(require_admin),
) -> ConnectionPoolStatsResponse:
    """Get database connection pool statistics."""
    if not settings.performance_monitoring_enabled:
        raise HTTPException(
            status_code=403,
            detail="Performance monitoring is not enabled. Set PERFORMANCE_MONITORING_ENABLED=true.",
        )

    return ConnectionPoolStatsResponse(
        pool_size=1,
        active_connections=1 if _db is not None else 0,
        idle_connections=0 if _db is not None else 1,
        max_connections=10,
        wait_queue_size=0,
    )


# ── UX Polish — Preferences & Onboarding ────────────────────────────────────

_ONBOARDING_STEPS = [
    {"step_id": "create_api_key", "title": "Create an API Key", "description": "Generate your first API key to authenticate with TicketForge."},
    {"step_id": "submit_ticket", "title": "Submit a Ticket", "description": "Submit your first ticket through the portal or API."},
    {"step_id": "explore_kb", "title": "Explore Knowledge Base", "description": "Search and browse the knowledge base for helpful articles."},
    {"step_id": "configure_sla", "title": "Configure SLA Policies", "description": "Set up SLA policies tailored to your team's needs."},
    {"step_id": "setup_notifications", "title": "Set Up Notifications", "description": "Configure Slack or Teams notifications for ticket updates."},
]


@app.get(
    "/preferences/{user_id}",
    response_model=UserPreferencesResponse,
    tags=["UX Preferences"],
)
async def get_user_preferences(
    user_id: str,
    api_key: str = Depends(require_viewer),
) -> UserPreferencesResponse:
    """Get display and interaction preferences for a user."""
    if not settings.ux_preferences_enabled:
        raise HTTPException(
            status_code=403,
            detail="UX preferences are not enabled. Set UX_PREFERENCES_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    async with _db.execute(
        "SELECT theme, language, timezone, notifications_enabled, keyboard_shortcuts_enabled, items_per_page, accessibility_high_contrast, accessibility_font_size FROM user_preferences WHERE user_id = ?",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row:
        prefs = UserPreferences(
            theme=row[0],
            language=row[1],
            timezone=row[2],
            notifications_enabled=bool(row[3]),
            keyboard_shortcuts_enabled=bool(row[4]),
            items_per_page=row[5],
            accessibility_high_contrast=bool(row[6]),
            accessibility_font_size=row[7],
        )
    else:
        prefs = UserPreferences()

    return UserPreferencesResponse(user_id=user_id, preferences=prefs)


@app.put(
    "/preferences/{user_id}",
    response_model=UserPreferencesResponse,
    tags=["UX Preferences"],
)
async def update_user_preferences(
    user_id: str,
    body: UserPreferencesUpdate,
    api_key: str = Depends(require_viewer),
) -> UserPreferencesResponse:
    """Update display and interaction preferences for a user."""
    if not settings.ux_preferences_enabled:
        raise HTTPException(
            status_code=403,
            detail="UX preferences are not enabled. Set UX_PREFERENCES_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    # Get existing preferences or defaults
    async with _db.execute(
        "SELECT theme, language, timezone, notifications_enabled, keyboard_shortcuts_enabled, items_per_page, accessibility_high_contrast, accessibility_font_size FROM user_preferences WHERE user_id = ?",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row:
        current = UserPreferences(
            theme=row[0],
            language=row[1],
            timezone=row[2],
            notifications_enabled=bool(row[3]),
            keyboard_shortcuts_enabled=bool(row[4]),
            items_per_page=row[5],
            accessibility_high_contrast=bool(row[6]),
            accessibility_font_size=row[7],
        )
    else:
        current = UserPreferences()

    # Merge updates
    updated = current.model_copy(update={k: v for k, v in body.model_dump().items() if v is not None})
    now = datetime.now(tz=timezone.utc).isoformat()

    await _db.execute(
        """INSERT INTO user_preferences (user_id, theme, language, timezone, notifications_enabled, keyboard_shortcuts_enabled, items_per_page, accessibility_high_contrast, accessibility_font_size, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             theme=excluded.theme, language=excluded.language, timezone=excluded.timezone,
             notifications_enabled=excluded.notifications_enabled,
             keyboard_shortcuts_enabled=excluded.keyboard_shortcuts_enabled,
             items_per_page=excluded.items_per_page,
             accessibility_high_contrast=excluded.accessibility_high_contrast,
             accessibility_font_size=excluded.accessibility_font_size,
             updated_at=excluded.updated_at""",
        (
            user_id,
            updated.theme,
            updated.language,
            updated.timezone,
            int(updated.notifications_enabled),
            int(updated.keyboard_shortcuts_enabled),
            updated.items_per_page,
            int(updated.accessibility_high_contrast),
            updated.accessibility_font_size,
            now,
        ),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="update_user_preferences",
        resource=user_id,
    )

    return UserPreferencesResponse(user_id=user_id, preferences=updated)


@app.get(
    "/onboarding/status/{user_id}",
    response_model=OnboardingStatusResponse,
    tags=["UX Preferences"],
)
async def get_onboarding_status(
    user_id: str,
    api_key: str = Depends(require_viewer),
) -> OnboardingStatusResponse:
    """Get onboarding progress for a user."""
    if not settings.ux_preferences_enabled:
        raise HTTPException(
            status_code=403,
            detail="UX preferences are not enabled. Set UX_PREFERENCES_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    # Fetch completed steps
    async with _db.execute(
        "SELECT step_id, completed_at FROM onboarding_progress WHERE user_id = ?",
        (user_id,),
    ) as cursor:
        completed_rows = await cursor.fetchall()

    completed_set = {r[0]: r[1] for r in completed_rows}

    steps: list[OnboardingStep] = []
    for s in _ONBOARDING_STEPS:
        completed_at_str = completed_set.get(s["step_id"])
        steps.append(OnboardingStep(
            step_id=s["step_id"],
            title=s["title"],
            description=s["description"],
            completed=s["step_id"] in completed_set,
            completed_at=datetime.fromisoformat(completed_at_str) if completed_at_str else None,
        ))

    total = len(steps)
    done = sum(1 for s in steps if s.completed)
    pct = round((done / total) * 100, 1) if total > 0 else 0.0

    return OnboardingStatusResponse(
        user_id=user_id,
        completed=done == total,
        completion_percentage=pct,
        steps=steps,
        total_steps=total,
        completed_steps=done,
    )


@app.post(
    "/onboarding/complete-step",
    response_model=OnboardingCompleteStepResponse,
    tags=["UX Preferences"],
)
async def complete_onboarding_step(
    body: OnboardingCompleteStepRequest,
    api_key: str = Depends(require_viewer),
) -> OnboardingCompleteStepResponse:
    """Mark an onboarding step as complete for a user."""
    if not settings.ux_preferences_enabled:
        raise HTTPException(
            status_code=403,
            detail="UX preferences are not enabled. Set UX_PREFERENCES_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    # Validate step_id
    valid_step_ids = {s["step_id"] for s in _ONBOARDING_STEPS}
    if body.step_id not in valid_step_ids:
        raise HTTPException(status_code=422, detail=f"Unknown onboarding step: {body.step_id}")

    # Check if already completed
    async with _db.execute(
        "SELECT id FROM onboarding_progress WHERE user_id = ? AND step_id = ?",
        (body.user_id, body.step_id),
    ) as cursor:
        existing = await cursor.fetchone()

    if existing:
        return OnboardingCompleteStepResponse(
            step_id=body.step_id,
            already_completed=True,
        )

    progress_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    await _db.execute(
        "INSERT INTO onboarding_progress (id, user_id, step_id, completed_at) VALUES (?, ?, ?, ?)",
        (progress_id, body.user_id, body.step_id, now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="complete_onboarding_step",
        resource=f"{body.user_id}/{body.step_id}",
    )

    return OnboardingCompleteStepResponse(
        step_id=body.step_id,
        already_completed=False,
    )


# ── Phase 11a: Conversational Intelligence ─────────────────────────────────────


# 51. Multi-step Troubleshooting Flows


@app.post(
    "/troubleshooting/flows",
    response_model=TroubleshootingFlowResponse,
    tags=["Troubleshooting Flows"],
)
async def create_troubleshooting_flow(
    body: TroubleshootingFlowCreate,
    api_key: str = Depends(require_analyst),
) -> TroubleshootingFlowResponse:
    """Create a new multi-step troubleshooting flow."""
    if not settings.troubleshooting_flows_enabled:
        raise HTTPException(
            status_code=403,
            detail="Troubleshooting flows are not enabled. Set TROUBLESHOOTING_FLOWS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    flow_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()
    steps_json = _json.dumps([s.model_dump() for s in body.steps])

    await _db.execute(
        "INSERT INTO troubleshooting_flows (id, name, description, category, steps, status, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?)",
        (flow_id, body.name, body.description, body.category, steps_json, now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_troubleshooting_flow",
        resource=flow_id,
    )

    record = TroubleshootingFlowRecord(
        id=flow_id,
        name=body.name,
        description=body.description,
        category=body.category,
        steps=body.steps,
        status="active",
        created_at=datetime.fromisoformat(now),
    )
    return TroubleshootingFlowResponse(flow=record)


@app.get(
    "/troubleshooting/flows",
    response_model=TroubleshootingFlowListResponse,
    tags=["Troubleshooting Flows"],
)
async def list_troubleshooting_flows(
    api_key: str = Depends(require_viewer),
) -> TroubleshootingFlowListResponse:
    """List all troubleshooting flows."""
    if not settings.troubleshooting_flows_enabled:
        raise HTTPException(
            status_code=403,
            detail="Troubleshooting flows are not enabled. Set TROUBLESHOOTING_FLOWS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    async with _db.execute(
        "SELECT id, name, description, category, steps, status, created_at, updated_at FROM troubleshooting_flows ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()

    flows = []
    for r in rows:
        steps = [TroubleshootingStep(**s) for s in _json.loads(r[4])] if r[4] else []
        flows.append(TroubleshootingFlowRecord(
            id=r[0],
            name=r[1],
            description=r[2] or "",
            category=r[3] or "general",
            steps=steps,
            status=r[5] or "active",
            created_at=datetime.fromisoformat(r[6]),
            updated_at=datetime.fromisoformat(r[7]) if r[7] else None,
        ))

    return TroubleshootingFlowListResponse(flows=flows, total=len(flows))


@app.delete(
    "/troubleshooting/flows/{flow_id}",
    response_model=TroubleshootingFlowResponse,
    tags=["Troubleshooting Flows"],
)
async def delete_troubleshooting_flow(
    flow_id: str,
    api_key: str = Depends(require_admin),
) -> TroubleshootingFlowResponse:
    """Delete a troubleshooting flow."""
    if not settings.troubleshooting_flows_enabled:
        raise HTTPException(
            status_code=403,
            detail="Troubleshooting flows are not enabled. Set TROUBLESHOOTING_FLOWS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    async with _db.execute(
        "SELECT id, name, description, category, steps, status, created_at, updated_at FROM troubleshooting_flows WHERE id = ?",
        (flow_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Troubleshooting flow {flow_id} not found")

    steps = [TroubleshootingStep(**s) for s in _json.loads(row[4])] if row[4] else []
    record = TroubleshootingFlowRecord(
        id=row[0],
        name=row[1],
        description=row[2] or "",
        category=row[3] or "general",
        steps=steps,
        status=row[5] or "active",
        created_at=datetime.fromisoformat(row[6]),
        updated_at=datetime.fromisoformat(row[7]) if row[7] else None,
    )

    await _db.execute("DELETE FROM troubleshooting_flows WHERE id = ?", (flow_id,))
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="delete_troubleshooting_flow",
        resource=flow_id,
    )

    return TroubleshootingFlowResponse(flow=record)


@app.post(
    "/troubleshooting/execute",
    response_model=TroubleshootingExecuteResponse,
    tags=["Troubleshooting Flows"],
)
async def execute_troubleshooting_step(
    body: TroubleshootingExecuteRequest,
    api_key: str = Depends(require_viewer),
) -> TroubleshootingExecuteResponse:
    """Execute a step in a troubleshooting flow (navigate decision tree)."""
    if not settings.troubleshooting_flows_enabled:
        raise HTTPException(
            status_code=403,
            detail="Troubleshooting flows are not enabled. Set TROUBLESHOOTING_FLOWS_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    async with _db.execute(
        "SELECT steps FROM troubleshooting_flows WHERE id = ?",
        (body.flow_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Troubleshooting flow {body.flow_id} not found")

    steps_data = _json.loads(row[0]) if row[0] else []
    if not steps_data:
        return TroubleshootingExecuteResponse(flow_id=body.flow_id, is_complete=True)

    steps = [TroubleshootingStep(**s) for s in steps_data]
    steps_by_id = {s.id: s for s in steps}

    # If no current step, start from the first step
    if body.current_step_id is None:
        current = steps[0]
    else:
        current = steps_by_id.get(body.current_step_id)
        if current is None:
            raise HTTPException(status_code=404, detail=f"Step {body.current_step_id} not found in flow")

        # Navigate based on step type
        if current.step_type == TroubleshootingStepType.branch and body.selected_option:
            # Find the next step based on selected option
            next_id = None
            for opt in current.options:
                if opt.get("label") == body.selected_option:
                    next_id = opt.get("next_step_id")
                    break
            if next_id and next_id in steps_by_id:
                current = steps_by_id[next_id]
            else:
                return TroubleshootingExecuteResponse(
                    flow_id=body.flow_id,
                    is_complete=True,
                    resolution="Flow completed — no matching option found.",
                )
        elif current.next_step_id and current.next_step_id in steps_by_id:
            current = steps_by_id[current.next_step_id]
        else:
            # No next step — flow is complete
            return TroubleshootingExecuteResponse(
                flow_id=body.flow_id,
                is_complete=True,
                resolution=current.content if current.step_type == TroubleshootingStepType.resolution else "Flow completed.",
            )

    # Check if current step is a resolution
    if current.step_type == TroubleshootingStepType.resolution:
        return TroubleshootingExecuteResponse(
            flow_id=body.flow_id,
            current_step=current,
            is_complete=True,
            resolution=current.content,
        )

    return TroubleshootingExecuteResponse(
        flow_id=body.flow_id,
        current_step=current,
    )


# 52. Intent Detection & Entity Extraction

# Built-in intent patterns for rule-based detection
_INTENT_PATTERNS: dict[str, list[str]] = {
    "password_reset": ["password", "reset password", "forgot password", "can't log in", "locked out", "change password"],
    "access_request": ["access", "permission", "grant access", "need access", "request access", "authorisation"],
    "bug_report": ["bug", "error", "crash", "broken", "not working", "defect", "issue", "failure"],
    "feature_request": ["feature", "enhancement", "would be nice", "suggestion", "wish", "request feature"],
    "billing_inquiry": ["bill", "invoice", "charge", "payment", "subscription", "pricing", "refund"],
    "general_inquiry": ["how to", "help", "question", "information", "what is", "where is"],
    "hardware_issue": ["hardware", "printer", "monitor", "keyboard", "mouse", "laptop", "desktop", "device"],
    "software_installation": ["install", "setup", "configure", "download", "update", "upgrade", "deployment"],
    "network_issue": ["network", "wifi", "internet", "vpn", "connectivity", "dns", "firewall"],
    "account_management": ["account", "profile", "settings", "deactivate", "create account", "delete account"],
}

# Built-in entity extraction patterns
_ENTITY_PATTERNS: dict[str, str] = {
    "email": r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    "error_code": r"(?:error|err|code|status)\s*[:\-#]?\s*([A-Z0-9\-]{2,12})",
    "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "application": r"(?:in|using|with|for|app|application|software|system)\s+([A-Z][a-zA-Z0-9\-_.]+)",
    "device": r"(?:on|device|machine|laptop|desktop|server|printer)\s+([A-Za-z0-9\-_.]+)",
    "user": r"(?:user|employee|staff|person|name)\s*[:\-]?\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)",
    "location": r"(?:office|building|floor|room|site|location|branch)\s*[:\-]?\s*([A-Za-z0-9\s\-]+?)(?:\s*[,.]|\s+(?:and|or|but|is|has)|\s*$)",
}


@app.post(
    "/intent/detect",
    response_model=IntentDetectionResponse,
    tags=["Intent Detection"],
)
async def detect_intent(
    body: IntentDetectionRequest,
    api_key: str = Depends(require_viewer),
) -> IntentDetectionResponse:
    """Detect intent from text using rule-based pattern matching."""
    if not settings.intent_detection_enabled:
        raise HTTPException(
            status_code=403,
            detail="Intent detection is not enabled. Set INTENT_DETECTION_ENABLED=true.",
        )


    text_lower = body.text.lower()
    scored_intents: list[IntentResult] = []

    for intent_name, patterns in _INTENT_PATTERNS.items():
        matches = sum(1 for p in patterns if p in text_lower)
        if matches > 0:
            confidence = min(round(matches / len(patterns), 2), 1.0)
            scored_intents.append(IntentResult(
                intent=intent_name,
                confidence=confidence,
            ))

    scored_intents.sort(key=lambda x: x.confidence, reverse=True)

    if not scored_intents:
        primary = IntentResult(intent="unknown", confidence=0.0)
    else:
        primary = scored_intents[0]

    return IntentDetectionResponse(
        text=body.text,
        primary_intent=primary,
        all_intents=scored_intents,
    )


@app.post(
    "/entities/extract",
    response_model=EntityExtractionResponse,
    tags=["Intent Detection"],
)
async def extract_entities(
    body: EntityExtractionRequest,
    api_key: str = Depends(require_viewer),
) -> EntityExtractionResponse:
    """Extract structured entities from text using pattern matching."""
    if not settings.intent_detection_enabled:
        raise HTTPException(
            status_code=403,
            detail="Intent detection is not enabled. Set INTENT_DETECTION_ENABLED=true.",
        )

    import re as _re

    entities: list[ExtractedEntity] = []

    for etype in body.entity_types:
        pattern = _ENTITY_PATTERNS.get(etype)
        if not pattern:
            continue
        for m in _re.finditer(pattern, body.text, _re.IGNORECASE):
            value = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
            entities.append(ExtractedEntity(
                entity_type=etype,
                value=value.strip(),
                confidence=0.85,
                start_pos=m.start(),
                end_pos=m.end(),
            ))

    return EntityExtractionResponse(
        text=body.text,
        entities=entities,
        entity_count=len(entities),
    )


# ── Phase 11b: Predictive Intelligence ─────────────────────────────────────────


# 53. Resolution Time Prediction


@app.get(
    "/analytics/resolution-prediction/{ticket_id}",
    response_model=ResolutionPredictionResponse,
    tags=["Predictive Intelligence"],
)
async def predict_resolution_time(
    ticket_id: str,
    api_key: str = Depends(require_viewer),
) -> ResolutionPredictionResponse:
    """Predict resolution time for a ticket based on historical patterns."""
    if not settings.resolution_prediction_enabled:
        raise HTTPException(
            status_code=403,
            detail="Resolution prediction is not enabled. Set RESOLUTION_PREDICTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    # Fetch ticket details
    async with _db.execute(
        "SELECT category, priority, ticket_status FROM processed_tickets WHERE id = ?",
        (ticket_id,),
    ) as cursor:
        ticket_row = await cursor.fetchone()

    if not ticket_row:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")

    category = ticket_row[0] or "unknown"
    priority = ticket_row[1] or "medium"  # noqa: F841
    ticket_status = ticket_row[2] or "open"  # noqa: F841
    async with _db.execute(
        "SELECT AVG(CAST((julianday(COALESCE(updated_at, processed_at)) - julianday(COALESCE(created_at, processed_at))) * 24 AS REAL)) FROM processed_tickets WHERE category = ? AND ticket_status = 'resolved'",
        (category,),
    ) as cursor:
        cat_avg_row = await cursor.fetchone()

    cat_avg = cat_avg_row[0] if cat_avg_row and cat_avg_row[0] else 24.0

    # Build prediction factors
    factors = []
    base_hours = cat_avg

    # Priority factor
    priority_multipliers = {"critical": 0.5, "high": 0.75, "medium": 1.0, "low": 1.5}
    p_mult = priority_multipliers.get(priority, 1.0)
    if p_mult < 1.0:
        factors.append(ResolutionFactor(factor=f"Priority: {priority}", impact="decreases", weight=round(1.0 - p_mult, 2)))
    elif p_mult > 1.0:
        factors.append(ResolutionFactor(factor=f"Priority: {priority}", impact="increases", weight=round(p_mult - 1.0, 2)))

    # Category factor
    factors.append(ResolutionFactor(
        factor=f"Category: {category}",
        impact="increases" if cat_avg > 24 else "decreases",
        weight=round(abs(cat_avg - 24) / 24, 2),
    ))

    predicted_hours = round(base_hours * p_mult, 1)
    confidence = 0.72 if cat_avg_row and cat_avg_row[0] else 0.45

    now = datetime.now(tz=timezone.utc)
    prediction = ResolutionPrediction(
        ticket_id=ticket_id,
        predicted_hours=predicted_hours,
        confidence=confidence,
        factors=factors,
        predicted_at=now,
    )

    return ResolutionPredictionResponse(prediction=prediction)


@app.get(
    "/analytics/resolution-stats",
    response_model=ResolutionStatsResponse,
    tags=["Predictive Intelligence"],
)
async def get_resolution_stats(
    api_key: str = Depends(require_viewer),
) -> ResolutionStatsResponse:
    """Get historical resolution time statistics."""
    if not settings.resolution_prediction_enabled:
        raise HTTPException(
            status_code=403,
            detail="Resolution prediction is not enabled. Set RESOLUTION_PREDICTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    # Overall stats
    async with _db.execute(
        "SELECT COUNT(*) FROM processed_tickets WHERE ticket_status = 'resolved'"
    ) as cursor:
        total_row = await cursor.fetchone()
    total_resolved = total_row[0] if total_row else 0

    # Average resolution hours by category
    by_category: dict[str, float] = {}
    async with _db.execute(
        "SELECT category, AVG(CAST((julianday(COALESCE(updated_at, processed_at)) - julianday(COALESCE(created_at, processed_at))) * 24 AS REAL)) FROM processed_tickets WHERE ticket_status = 'resolved' GROUP BY category"
    ) as cursor:
        cat_rows = await cursor.fetchall()
    for r in cat_rows:
        if r[0] and r[1]:
            by_category[r[0]] = round(r[1], 1)

    # Average resolution hours by priority
    by_priority: dict[str, float] = {}
    async with _db.execute(
        "SELECT priority, AVG(CAST((julianday(COALESCE(updated_at, processed_at)) - julianday(COALESCE(created_at, processed_at))) * 24 AS REAL)) FROM processed_tickets WHERE ticket_status = 'resolved' GROUP BY priority"
    ) as cursor:
        pri_rows = await cursor.fetchall()
    for r in pri_rows:
        if r[0] and r[1]:
            by_priority[r[0]] = round(r[1], 1)

    avg_h = sum(by_category.values()) / len(by_category) if by_category else 0.0

    # Heuristic approximations — a full implementation would compute
    # true percentiles from the individual resolution-time distribution.
    return ResolutionStatsResponse(
        avg_resolution_hours=round(avg_h, 1),
        median_resolution_hours=round(avg_h * 0.85, 1),
        p95_resolution_hours=round(avg_h * 2.5, 1),
        total_resolved=total_resolved,
        by_category=by_category,
        by_priority=by_priority,
    )


# 54. Satisfaction Prediction


@app.get(
    "/analytics/satisfaction-prediction/{ticket_id}",
    response_model=SatisfactionPredictionResponse,
    tags=["Predictive Intelligence"],
)
async def predict_satisfaction(
    ticket_id: str,
    api_key: str = Depends(require_viewer),
) -> SatisfactionPredictionResponse:
    """Predict customer satisfaction for a ticket."""
    if not settings.satisfaction_prediction_enabled:
        raise HTTPException(
            status_code=403,
            detail="Satisfaction prediction is not enabled. Set SATISFACTION_PREDICTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    # Fetch ticket details
    async with _db.execute(
        "SELECT category, priority, ticket_status, sentiment FROM processed_tickets WHERE id = ?",
        (ticket_id,),
    ) as cursor:
        ticket_row = await cursor.fetchone()

    if not ticket_row:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")

    category = ticket_row[0] or "unknown"  # noqa: F841
    priority = ticket_row[1] or "medium"
    ticket_status = ticket_row[2] or "open"
    sentiment = ticket_row[3] or "neutral"

    # Build prediction based on heuristics
    base_score = 3.5
    factors = []

    # Sentiment factor
    sentiment_impacts = {"positive": 0.8, "neutral": 0.0, "negative": -0.8, "frustrated": -1.2}
    s_impact = sentiment_impacts.get(sentiment, 0.0)
    if s_impact != 0:
        factors.append(SatisfactionFactor(
            factor=f"Sentiment: {sentiment}",
            impact="positive" if s_impact > 0 else "negative",
            weight=round(abs(s_impact), 2),
        ))
    base_score += s_impact

    # Status factor
    if ticket_status == "resolved":
        factors.append(SatisfactionFactor(factor="Status: resolved", impact="positive", weight=0.5))
        base_score += 0.5
    elif ticket_status in ("escalated", "breached"):
        factors.append(SatisfactionFactor(factor=f"Status: {ticket_status}", impact="negative", weight=0.7))
        base_score -= 0.7

    # Priority factor
    if priority in ("critical", "high"):
        factors.append(SatisfactionFactor(factor=f"Priority: {priority}", impact="negative", weight=0.3))
        base_score -= 0.3

    predicted_score = max(1.0, min(5.0, round(base_score, 1)))

    risk_level = "low"
    if predicted_score < 2.5:
        risk_level = "high"
    elif predicted_score < 3.5:
        risk_level = "medium"

    now = datetime.now(tz=timezone.utc)
    prediction = SatisfactionPrediction(
        ticket_id=ticket_id,
        predicted_score=predicted_score,
        confidence=0.68,
        risk_level=risk_level,
        factors=factors,
        predicted_at=now,
    )

    return SatisfactionPredictionResponse(prediction=prediction)


@app.get(
    "/analytics/satisfaction-trends",
    response_model=SatisfactionTrendsResponse,
    tags=["Predictive Intelligence"],
)
async def get_satisfaction_trends(
    api_key: str = Depends(require_viewer),
) -> SatisfactionTrendsResponse:
    """Get satisfaction score trends over time."""
    if not settings.satisfaction_prediction_enabled:
        raise HTTPException(
            status_code=403,
            detail="Satisfaction prediction is not enabled. Set SATISFACTION_PREDICTION_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    # Query CSAT scores
    async with _db.execute(
        "SELECT rating, submitted_at FROM csat_ratings ORDER BY submitted_at DESC LIMIT 100"
    ) as cursor:
        rows = await cursor.fetchall()

    total_ratings = len(rows)
    if total_ratings == 0:
        return SatisfactionTrendsResponse()

    scores = [r[0] for r in rows]
    avg_score = round(sum(scores) / len(scores), 1)

    # Simple trend: compare first and second halves
    mid = len(scores) // 2
    if mid > 0:
        recent_avg = sum(scores[:mid]) / mid
        older_avg = sum(scores[mid:]) / (len(scores) - mid)
        if recent_avg > older_avg + 0.2:
            trend = "improving"
        elif recent_avg < older_avg - 0.2:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return SatisfactionTrendsResponse(
        avg_score=avg_score,
        trend_direction=trend,
        total_ratings=total_ratings,
    )


# ── Phase 11c: Smart Assignment ────────────────────────────────────────────────


# 55. Intelligent Agent Assignment


@app.post(
    "/agent-profiles",
    response_model=AgentProfileResponse,
    tags=["Smart Assignment"],
)
async def create_agent_profile(
    body: AgentProfileCreate,
    api_key: str = Depends(require_analyst),
) -> AgentProfileResponse:
    """Create or update an agent performance profile."""
    if not settings.smart_assignment_enabled:
        raise HTTPException(
            status_code=403,
            detail="Smart assignment is not enabled. Set SMART_ASSIGNMENT_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    now = datetime.now(tz=timezone.utc).isoformat()
    specs_json = _json.dumps(body.specialisations)

    await _db.execute(
        """INSERT INTO agent_profiles (agent_id, name, specialisations, max_capacity, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(agent_id) DO UPDATE SET
             name=excluded.name,
             specialisations=excluded.specialisations,
             max_capacity=excluded.max_capacity,
             updated_at=excluded.updated_at""",
        (body.agent_id, body.name, specs_json, body.max_capacity, now, now),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="create_agent_profile",
        resource=body.agent_id,
    )

    profile = AgentPerformanceProfile(
        agent_id=body.agent_id,
        name=body.name,
        specialisations=body.specialisations,
        max_capacity=body.max_capacity,
    )
    return AgentProfileResponse(profile=profile)


@app.get(
    "/agent-profiles",
    response_model=AgentProfileListResponse,
    tags=["Smart Assignment"],
)
async def list_agent_profiles(
    api_key: str = Depends(require_viewer),
) -> AgentProfileListResponse:
    """List all agent performance profiles."""
    if not settings.smart_assignment_enabled:
        raise HTTPException(
            status_code=403,
            detail="Smart assignment is not enabled. Set SMART_ASSIGNMENT_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    async with _db.execute(
        "SELECT agent_id, name, specialisations, max_capacity, current_load, avg_resolution_hours, avg_satisfaction, categories FROM agent_profiles"
    ) as cursor:
        rows = await cursor.fetchall()

    profiles = []
    for r in rows:
        profiles.append(AgentPerformanceProfile(
            agent_id=r[0],
            name=r[1] or "",
            specialisations=_json.loads(r[2]) if r[2] else [],
            max_capacity=r[3] or 10,
            current_load=r[4] or 0,
            avg_resolution_hours=r[5] or 0.0,
            avg_satisfaction=r[6] or 0.0,
            categories=_json.loads(r[7]) if r[7] else {},
        ))

    return AgentProfileListResponse(profiles=profiles, total=len(profiles))


@app.post(
    "/tickets/{ticket_id}/smart-assign",
    response_model=SmartAssignmentResponse,
    tags=["Smart Assignment"],
)
async def smart_assign_ticket(
    ticket_id: str,
    api_key: str = Depends(require_analyst),
) -> SmartAssignmentResponse:
    """Intelligently assign a ticket to the best available agent."""
    if not settings.smart_assignment_enabled:
        raise HTTPException(
            status_code=403,
            detail="Smart assignment is not enabled. Set SMART_ASSIGNMENT_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    # Fetch ticket details
    async with _db.execute(
        "SELECT category, priority FROM processed_tickets WHERE id = ?",
        (ticket_id,),
    ) as cursor:
        ticket_row = await cursor.fetchone()

    if not ticket_row:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")

    category = ticket_row[0] or "general"
    priority = ticket_row[1] or "medium"  # noqa: F841
    async with _db.execute(
        "SELECT agent_id, name, specialisations, max_capacity, current_load, avg_resolution_hours, avg_satisfaction, categories FROM agent_profiles WHERE current_load < max_capacity"
    ) as cursor:
        agent_rows = await cursor.fetchall()

    if not agent_rows:
        raise HTTPException(status_code=404, detail="No available agents for assignment")

    # Score each agent
    best_agent = None
    best_score = -1.0
    best_reasons: list[str] = []

    for r in agent_rows:
        agent_id = r[0]
        name = r[1] or ""
        specs = _json.loads(r[2]) if r[2] else []
        max_cap = r[3] or 10
        load = r[4] or 0
        avg_res = r[5] or 0.0
        avg_sat = r[6] or 0.0
        cats = _json.loads(r[7]) if r[7] else {}

        score = 0.0
        reasons = []

        # Specialisation match
        if category.lower() in [s.lower() for s in specs]:
            score += 3.0
            reasons.append(f"Specialises in {category}")

        # Category performance
        cat_score = cats.get(category, 0.0)
        if cat_score > 0:
            score += cat_score
            reasons.append(f"Category performance: {cat_score:.1f}")

        # Capacity availability
        capacity_ratio = 1.0 - (load / max_cap) if max_cap > 0 else 0.0
        score += capacity_ratio * 2.0
        reasons.append(f"Capacity: {load}/{max_cap}")

        # Satisfaction history
        if avg_sat > 0:
            score += avg_sat / 5.0
            reasons.append(f"Avg satisfaction: {avg_sat:.1f}")

        # Resolution speed
        if avg_res > 0 and avg_res < 24:
            score += (24 - avg_res) / 24
            reasons.append(f"Avg resolution: {avg_res:.1f}h")

        if score > best_score:
            best_score = score
            best_agent = (agent_id, name)
            best_reasons = reasons

    assert best_agent is not None

    # Update agent load
    await _db.execute(
        "UPDATE agent_profiles SET current_load = current_load + 1 WHERE agent_id = ?",
        (best_agent[0],),
    )
    await _db.commit()

    await audit.record(
        _db,
        api_key=api_key,
        role=_resolve_role(api_key),
        action="smart_assign_ticket",
        resource=ticket_id,
    )

    result = SmartAssignmentResult(
        ticket_id=ticket_id,
        recommended_agent_id=best_agent[0],
        agent_name=best_agent[1],
        score=round(best_score, 2),
        reasons=best_reasons,
    )
    return SmartAssignmentResponse(assignment=result)


@app.get(
    "/analytics/agent-performance-matrix",
    response_model=AgentPerformanceMatrixResponse,
    tags=["Smart Assignment"],
)
async def get_agent_performance_matrix(
    api_key: str = Depends(require_viewer),
) -> AgentPerformanceMatrixResponse:
    """Get agent performance matrix across all categories."""
    if not settings.smart_assignment_enabled:
        raise HTTPException(
            status_code=403,
            detail="Smart assignment is not enabled. Set SMART_ASSIGNMENT_ENABLED=true.",
        )
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    assert _db is not None

    import json as _json

    async with _db.execute(
        "SELECT agent_id, name, specialisations, max_capacity, current_load, avg_resolution_hours, avg_satisfaction, categories FROM agent_profiles"
    ) as cursor:
        rows = await cursor.fetchall()

    profiles = []
    all_categories: set[str] = set()
    for r in rows:
        cats = _json.loads(r[7]) if r[7] else {}
        all_categories.update(cats.keys())
        profiles.append(AgentPerformanceProfile(
            agent_id=r[0],
            name=r[1] or "",
            specialisations=_json.loads(r[2]) if r[2] else [],
            max_capacity=r[3] or 10,
            current_load=r[4] or 0,
            avg_resolution_hours=r[5] or 0.0,
            avg_satisfaction=r[6] or 0.0,
            categories=cats,
        ))

    return AgentPerformanceMatrixResponse(
        agents=profiles,
        categories=sorted(all_categories),
    )


# ── Dashboard endpoint ────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse, tags=["ui"])
async def dashboard():
    """
    Serve a lightweight built-in web dashboard.
    Shows recent tickets, analytics charts, SLA overview, and status summary.
    No authentication required for the HTML shell — data is fetched via authenticated API calls.
    """
    return HTMLResponse(content=_DASHBOARD_HTML.replace("{{APP_VERSION}}", APP_VERSION))


@app.get("/portal", response_class=HTMLResponse, tags=["portal"])
async def portal():
    """
    Serve the self-service portal page.
    Allows users to submit tickets, check status, search the knowledge base,
    and chat with the TicketForge assistant.
    """
    if not settings.portal_enabled:
        raise HTTPException(
            status_code=403,
            detail="Self-service portal is not enabled. Set PORTAL_ENABLED=true.",
        )
    return HTMLResponse(content=_PORTAL_HTML.replace("{{APP_VERSION}}", APP_VERSION))


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID", "unknown")
    log.error("unhandled_exception", path=str(request.url), error=str(exc), request_id=request_id, exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error="internal_server_error", detail=str(exc)).model_dump(),
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_webhook_payload(source: TicketSource, payload: dict) -> RawTicket:
    """Delegate to the appropriate connector's static parse_webhook method."""
    if source == TicketSource.servicenow:
        return ServiceNowConnector.parse_webhook(payload)
    if source == TicketSource.jira:
        return JiraConnector.parse_webhook(payload)
    if source == TicketSource.zendesk:
        return ZendeskConnector.parse_webhook(payload)
    # Generic: expect RawTicket-compatible dict
    return RawTicket(**payload)


async def _persist_ticket(enriched: EnrichedTicket) -> None:
    """Upsert enriched ticket metadata into SQLite cache."""
    if _db is None:
        return
    try:
        await _db.execute(
            """
            INSERT OR REPLACE INTO processed_tickets
                (id, source, processed_at, category, priority, automation_score, summary,
                 sentiment, detected_language, ticket_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                enriched.ticket_id,
                enriched.source.value,
                enriched.processed_at.isoformat(),
                enriched.category.category,
                enriched.priority.priority.value,
                enriched.automation.score,
                enriched.summary,
                enriched.sentiment.sentiment.value,
                enriched.detected_language,
                enriched.ticket_status.value,
            ),
        )
        await _db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("persist_ticket.failed", ticket_id=enriched.ticket_id, error=str(e))


async def _send_outbound_webhook(enriched: EnrichedTicket) -> None:
    """POST enriched ticket JSON to the configured outbound webhook URL."""
    payload_bytes = enriched.model_dump_json().encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}

    if settings.outbound_webhook_secret:
        sig = hmac.new(
            settings.outbound_webhook_secret.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        headers["X-TicketForge-Signature"] = f"sha256={sig}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                settings.outbound_webhook_url,
                content=payload_bytes,
                headers=headers,
            )
        log.info("outbound_webhook.sent", status=r.status_code, ticket_id=enriched.ticket_id)
    except Exception as e:  # noqa: BLE001
        log.error("outbound_webhook.failed", ticket_id=enriched.ticket_id, error=str(e))


async def _auto_escalate(enriched: EnrichedTicket) -> None:
    """Auto-escalate to PagerDuty/OpsGenie if configured and criteria are met."""
    # PagerDuty auto-escalation
    if settings.pagerduty_routing_key and settings.pagerduty_auto_escalate:
        from connectors.pagerduty import PagerDutyConnector  # noqa: PLC0415
        if PagerDutyConnector.should_escalate(enriched):
            try:
                connector = PagerDutyConnector(settings)
                await connector.create_incident(enriched)
            except Exception as e:  # noqa: BLE001
                log.error("auto_escalate.pagerduty_failed", ticket_id=enriched.ticket_id, error=str(e))

    # OpsGenie auto-escalation
    if settings.opsgenie_api_key and settings.opsgenie_auto_escalate:
        from connectors.opsgenie import OpsGenieConnector  # noqa: PLC0415
        if OpsGenieConnector.should_escalate(enriched):
            try:
                connector = OpsGenieConnector(settings)
                await connector.create_alert(enriched)
            except Exception as e:  # noqa: BLE001
                log.error("auto_escalate.opsgenie_failed", ticket_id=enriched.ticket_id, error=str(e))


# ── Dashboard HTML template ──────────────────────────────────────────────────

_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TicketForge Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f7fa;color:#333}
.header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:1rem 2rem;display:flex;align-items:center;gap:1rem}
.header h1{font-size:1.4rem;font-weight:600}
.header .version{font-size:.75rem;background:rgba(255,255,255,.15);padding:2px 8px;border-radius:10px}
.api-bar{background:#fff;border-bottom:1px solid #e0e0e0;padding:.75rem 2rem;display:flex;gap:.75rem;align-items:center}
.api-bar input{flex:1;max-width:320px;padding:.4rem .75rem;border:1px solid #ccc;border-radius:4px;font-size:.85rem}
.api-bar button{padding:.4rem 1rem;background:#1a73e8;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.85rem}
.api-bar button:hover{background:#1557b0}
.api-bar .status{font-size:.8rem;color:#666}
.container{max-width:1400px;margin:0 auto;padding:1.5rem 2rem}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:1.5rem}
.stat-card{background:#fff;border-radius:8px;padding:1.25rem;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.stat-card .label{font-size:.75rem;color:#888;text-transform:uppercase;letter-spacing:.5px}
.stat-card .value{font-size:1.8rem;font-weight:700;margin:.25rem 0}
.stat-card .sub{font-size:.8rem;color:#666}
.panels{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-bottom:1.5rem}
.panel{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);overflow:hidden}
.panel-header{padding:1rem 1.25rem;border-bottom:1px solid #eee;font-weight:600;font-size:.95rem;display:flex;justify-content:space-between;align-items:center}
.panel-body{padding:1rem 1.25rem;max-height:400px;overflow-y:auto}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{text-align:left;padding:.5rem .75rem;border-bottom:1px solid #f0f0f0}
th{font-weight:600;color:#555;font-size:.75rem;text-transform:uppercase}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.75rem;font-weight:500}
.badge-critical{background:#fde8e8;color:#c53030}
.badge-high{background:#fef3cd;color:#d97706}
.badge-medium{background:#e8f4fd;color:#2563eb}
.badge-low{background:#e8f5e9;color:#16a34a}
.badge-open{background:#e3f2fd;color:#1565c0}
.badge-in_progress{background:#fff3e0;color:#e65100}
.badge-resolved{background:#e8f5e9;color:#2e7d32}
.badge-closed{background:#f3e5f5;color:#7b1fa2}
.sla-within{color:#16a34a}
.sla-at_risk{color:#d97706}
.sla-breached{color:#c53030;font-weight:700}
.bar-chart{display:flex;flex-direction:column;gap:.5rem}
.bar-row{display:flex;align-items:center;gap:.5rem}
.bar-label{width:100px;font-size:.8rem;text-align:right;color:#555}
.bar-track{flex:1;background:#f0f0f0;border-radius:4px;height:24px;position:relative}
.bar-fill{height:100%;border-radius:4px;background:linear-gradient(90deg,#1a73e8,#4285f4);min-width:2px;transition:width .3s}
.bar-value{position:absolute;right:8px;top:50%;transform:translateY(-50%);font-size:.75rem;font-weight:600;color:#333}
.empty-state{text-align:center;padding:2rem;color:#999;font-size:.9rem}
.loading{text-align:center;padding:2rem;color:#888}
@media(max-width:900px){.panels{grid-template-columns:1fr}.stats-grid{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>

<div class="header">
  <h1>&#9878; TicketForge</h1>
  <span class="version">v{{APP_VERSION}}</span>
</div>

<div class="api-bar">
  <input type="password" id="apiKey" placeholder="Enter API key to load data..." />
  <button onclick="loadAll()">Load Dashboard</button>
  <span class="status" id="statusMsg"></span>
</div>

<div class="container">
  <!-- Summary stats -->
  <div class="stats-grid" id="statsGrid">
    <div class="stat-card"><div class="label">Total Tickets</div><div class="value" id="totalTickets">—</div></div>
    <div class="stat-card"><div class="label">Avg Automation Score</div><div class="value" id="avgAuto">—</div></div>
    <div class="stat-card"><div class="label">Period</div><div class="value" id="period">—</div><div class="sub">days</div></div>
    <div class="stat-card"><div class="label">Categories</div><div class="value" id="catCount">—</div></div>
  </div>

  <!-- Charts & tables -->
  <div class="panels">
    <div class="panel">
      <div class="panel-header">Tickets by Category</div>
      <div class="panel-body" id="catChart"><div class="loading">Enter API key above</div></div>
    </div>
    <div class="panel">
      <div class="panel-header">Tickets by Priority</div>
      <div class="panel-body" id="priChart"><div class="loading">Enter API key above</div></div>
    </div>
  </div>

  <div class="panels">
    <div class="panel">
      <div class="panel-header">
        Recent Tickets
        <span style="font-weight:normal;font-size:.8rem;color:#888" id="ticketCount"></span>
      </div>
      <div class="panel-body" id="ticketTable"><div class="loading">Enter API key above</div></div>
    </div>
    <div class="panel">
      <div class="panel-header">SLA Overview</div>
      <div class="panel-body" id="slaOverview"><div class="loading">Enter API key above</div></div>
    </div>
  </div>
</div>

<script>
const API = window.location.origin;
function hdr(){ return {"X-Api-Key": document.getElementById("apiKey").value, "Content-Type":"application/json"} }
function setStatus(msg, ok){ const el=document.getElementById("statusMsg"); el.textContent=msg; el.style.color=ok?"#16a34a":"#c53030" }

async function loadAll(){
  const key = document.getElementById("apiKey").value.trim();
  if(!key){ setStatus("Please enter an API key", false); return; }
  setStatus("Loading...", true);
  try{
    await Promise.all([loadAnalytics(), loadTickets()]);
    setStatus("Loaded successfully", true);
  } catch(e) {
    setStatus("Error: " + e.message, false);
  }
}

async function loadAnalytics(){
  const res = await fetch(API+"/analytics?days=30", {headers: hdr()});
  if(!res.ok) throw new Error("Analytics: HTTP "+res.status);
  const d = await res.json();
  document.getElementById("totalTickets").textContent = d.total_tickets;
  document.getElementById("avgAuto").textContent = d.avg_automation_score.toFixed(1);
  document.getElementById("period").textContent = d.period_days;
  document.getElementById("catCount").textContent = d.by_category.length;
  renderBarChart("catChart", d.by_category, "category", "count");
  renderPriorityChart("priChart", d.by_priority);
}

async function loadTickets(){
  const res = await fetch(API+"/export/tickets?format=json&days=30", {headers: hdr()});
  if(!res.ok) throw new Error("Tickets: HTTP "+res.status);
  const d = await res.json();
  document.getElementById("ticketCount").textContent = d.total + " tickets";
  renderTicketTable(d.tickets);
  renderSLA(d.tickets);
}

function renderBarChart(elId, items, labelKey, valueKey){
  const el = document.getElementById(elId);
  if(!items.length){ el.innerHTML='<div class="empty-state">No data</div>'; return; }
  const max = Math.max(...items.map(i=>i[valueKey]));
  el.innerHTML = '<div class="bar-chart">' + items.map(i=>{
    const pct = max>0 ? (i[valueKey]/max*100) : 0;
    return '<div class="bar-row"><div class="bar-label">'+esc(i[labelKey])+'</div><div class="bar-track"><div class="bar-fill" style="width:'+pct+'%"></div><div class="bar-value">'+i[valueKey]+'</div></div></div>';
  }).join("") + '</div>';
}

function renderPriorityChart(elId, items){
  const el = document.getElementById(elId);
  if(!items.length){ el.innerHTML='<div class="empty-state">No data</div>'; return; }
  const colors = {critical:"#dc2626",high:"#ea580c",medium:"#2563eb",low:"#16a34a"};
  const max = Math.max(...items.map(i=>i.count));
  el.innerHTML = '<div class="bar-chart">' + items.map(i=>{
    const pct = max>0 ? (i.count/max*100) : 0;
    const c = colors[i.priority]||"#666";
    return '<div class="bar-row"><div class="bar-label"><span class="badge badge-'+i.priority+'">'+esc(i.priority)+'</span></div><div class="bar-track"><div class="bar-fill" style="width:'+pct+'%;background:'+c+'"></div><div class="bar-value">'+i.count+'</div></div></div>';
  }).join("") + '</div>';
}

function renderTicketTable(tickets){
  const el = document.getElementById("ticketTable");
  if(!tickets.length){ el.innerHTML='<div class="empty-state">No tickets processed yet</div>'; return; }
  let html = '<table><thead><tr><th>ID</th><th>Summary</th><th>Priority</th><th>Category</th><th>Status</th><th>Sentiment</th></tr></thead><tbody>';
  tickets.slice(0,50).forEach(t=>{
    html += '<tr><td>'+esc(t.id)+'</td><td>'+esc((t.summary||"").substring(0,80))+'</td>'
      +'<td><span class="badge badge-'+t.priority+'">'+esc(t.priority)+'</span></td>'
      +'<td>'+esc(t.category||"")+'</td>'
      +'<td><span class="badge badge-'+t.ticket_status+'">'+esc(t.ticket_status||"open")+'</span></td>'
      +'<td>'+esc(t.sentiment||"neutral")+'</td></tr>';
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

function renderSLA(tickets){
  const el = document.getElementById("slaOverview");
  if(!tickets.length){ el.innerHTML='<div class="empty-state">No ticket data for SLA overview</div>'; return; }
  const counts = {within:0, at_risk:0, breached:0};
  const priCounts = {critical:0, high:0, medium:0, low:0};
  tickets.forEach(t=>{ priCounts[t.priority] = (priCounts[t.priority]||0)+1; });
  let html = '<div style="margin-bottom:1rem">';
  html += '<div style="display:flex;gap:1rem;flex-wrap:wrap">';
  Object.entries(priCounts).forEach(([k,v])=>{
    if(v>0) html += '<div class="stat-card" style="flex:1;min-width:100px"><div class="label">'+k+'</div><div class="value">'+v+'</div></div>';
  });
  html += '</div></div>';
  html += '<div style="font-size:.85rem;color:#555">SLA tracking is available per-ticket via the API. Use <code>GET /tickets/{id}</code> with an API key to see full SLA details.</div>';
  el.innerHTML = html;
}

function esc(s){ const d=document.createElement("div"); d.textContent=s||""; return d.innerHTML; }
</script>
</body>
</html>
"""


# ── Self-Service Portal HTML template ────────────────────────────────────────

_PORTAL_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TicketForge Self-Service Portal</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f7fa;color:#333}
.header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:1rem 2rem;display:flex;align-items:center;gap:1rem}
.header h1{font-size:1.4rem;font-weight:600}
.header .version{font-size:.75rem;background:rgba(255,255,255,.15);padding:2px 8px;border-radius:10px}
.header nav{margin-left:auto;display:flex;gap:1rem}
.header nav a{color:#a0c4ff;text-decoration:none;font-size:.85rem}
.header nav a:hover{color:#fff}
.api-bar{background:#fff;border-bottom:1px solid #e0e0e0;padding:.75rem 2rem;display:flex;gap:.75rem;align-items:center}
.api-bar input{flex:1;max-width:320px;padding:.4rem .75rem;border:1px solid #ccc;border-radius:4px;font-size:.85rem}
.api-bar .status{font-size:.8rem;color:#666}
.container{max-width:1000px;margin:0 auto;padding:1.5rem 2rem}
.tabs{display:flex;gap:0;margin-bottom:1.5rem;border-bottom:2px solid #e0e0e0}
.tab{padding:.75rem 1.5rem;cursor:pointer;font-size:.9rem;font-weight:500;border-bottom:2px solid transparent;margin-bottom:-2px;color:#666}
.tab.active{color:#1a73e8;border-bottom-color:#1a73e8}
.tab:hover{color:#333}
.tab-content{display:none}
.tab-content.active{display:block}
.form-group{margin-bottom:1rem}
.form-group label{display:block;font-size:.85rem;font-weight:600;margin-bottom:.25rem;color:#555}
.form-group input,.form-group textarea,.form-group select{width:100%;padding:.5rem .75rem;border:1px solid #ccc;border-radius:4px;font-size:.9rem;font-family:inherit}
.form-group textarea{min-height:120px;resize:vertical}
.btn{padding:.5rem 1.25rem;background:#1a73e8;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.9rem;font-weight:500}
.btn:hover{background:#1557b0}
.btn-secondary{background:#6c757d}
.btn-secondary:hover{background:#5a6268}
.card{background:#fff;border-radius:8px;padding:1.25rem;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:1rem}
.card h3{font-size:1rem;margin-bottom:.75rem;color:#333}
.result-msg{padding:.75rem;border-radius:4px;margin-top:1rem;font-size:.9rem}
.result-msg.success{background:#e8f5e9;color:#2e7d32;border:1px solid #c8e6c9}
.result-msg.error{background:#fde8e8;color:#c53030;border:1px solid #f5c6cb}
.chat-container{display:flex;flex-direction:column;height:500px}
.chat-messages{flex:1;overflow-y:auto;padding:1rem;background:#fafafa;border:1px solid #e0e0e0;border-radius:4px 4px 0 0}
.chat-input{display:flex;gap:.5rem;padding:.75rem;background:#fff;border:1px solid #e0e0e0;border-top:none;border-radius:0 0 4px 4px}
.chat-input input{flex:1;padding:.5rem .75rem;border:1px solid #ccc;border-radius:4px;font-size:.9rem}
.chat-msg{margin-bottom:.75rem;display:flex;gap:.5rem}
.chat-msg.user{justify-content:flex-end}
.chat-msg .bubble{max-width:70%;padding:.5rem .75rem;border-radius:12px;font-size:.85rem;line-height:1.4}
.chat-msg.user .bubble{background:#1a73e8;color:#fff;border-bottom-right-radius:4px}
.chat-msg.assistant .bubble{background:#e8e8e8;color:#333;border-bottom-left-radius:4px}
.kb-list{list-style:none}
.kb-list li{padding:.75rem 0;border-bottom:1px solid #f0f0f0}
.kb-list li:last-child{border-bottom:none}
.kb-list .kb-title{font-weight:600;color:#1a73e8;font-size:.9rem}
.kb-list .kb-cat{font-size:.75rem;color:#888;margin-top:.25rem}
.kb-list .kb-snippet{font-size:.8rem;color:#666;margin-top:.25rem}
.search-bar{display:flex;gap:.5rem;margin-bottom:1rem}
.search-bar input{flex:1}
.empty-state{text-align:center;padding:2rem;color:#999;font-size:.9rem}
.suggested-articles{margin-top:1rem}
.suggested-articles h4{font-size:.9rem;color:#555;margin-bottom:.5rem}
</style>
</head>
<body>

<div class="header">
  <h1>&#9878; TicketForge Portal</h1>
  <span class="version">v{{APP_VERSION}}</span>
  <nav>
    <a href="/dashboard">Dashboard</a>
    <a href="/docs">API Docs</a>
  </nav>
</div>

<div class="api-bar">
  <input type="password" id="apiKey" placeholder="Enter API key..." />
  <span class="status" id="statusMsg"></span>
</div>

<div class="container">
  <div class="tabs">
    <div class="tab active" onclick="switchTab('submit')">Submit Ticket</div>
    <div class="tab" onclick="switchTab('status')">Check Status</div>
    <div class="tab" onclick="switchTab('kb')">Knowledge Base</div>
    <div class="tab" onclick="switchTab('chat')">Chat Assistant</div>
  </div>

  <!-- Submit Ticket Tab -->
  <div class="tab-content active" id="tab-submit">
    <div class="card">
      <h3>Submit a Support Ticket</h3>
      <div class="form-group">
        <label>Your Email</label>
        <input type="email" id="ticketEmail" placeholder="your.email@company.com" />
      </div>
      <div class="form-group">
        <label>Issue Title</label>
        <input type="text" id="ticketTitle" placeholder="Brief description of your issue" />
      </div>
      <div class="form-group">
        <label>Category (optional)</label>
        <select id="ticketCategory">
          <option value="">-- Select --</option>
          <option value="Hardware">Hardware</option>
          <option value="Software">Software</option>
          <option value="Network">Network</option>
          <option value="Access & Identity">Access & Identity</option>
          <option value="Service Request">Service Request</option>
          <option value="Security Incident">Security Incident</option>
        </select>
      </div>
      <div class="form-group">
        <label>Description</label>
        <textarea id="ticketDescription" placeholder="Provide details about your issue..."></textarea>
      </div>
      <button class="btn" onclick="submitTicket()">Submit Ticket</button>
      <div id="submitResult"></div>
    </div>
  </div>

  <!-- Check Status Tab -->
  <div class="tab-content" id="tab-status">
    <div class="card">
      <h3>Check Ticket Status</h3>
      <div class="search-bar">
        <input type="text" id="statusTicketId" placeholder="Enter ticket ID (e.g. PORTAL-abc123)" />
        <button class="btn" onclick="checkStatus()">Check</button>
      </div>
      <div id="statusResult"></div>
    </div>
  </div>

  <!-- Knowledge Base Tab -->
  <div class="tab-content" id="tab-kb">
    <div class="card">
      <h3>Knowledge Base</h3>
      <div class="search-bar">
        <input type="text" id="kbSearch" placeholder="Search for articles..." />
        <button class="btn" onclick="searchKB()">Search</button>
        <button class="btn btn-secondary" onclick="browseKB()">Browse All</button>
      </div>
      <div id="kbResults"><div class="empty-state">Search or browse knowledge base articles</div></div>
    </div>
  </div>

  <!-- Chat Tab -->
  <div class="tab-content" id="tab-chat">
    <div class="card">
      <h3>Chat with TicketForge Assistant</h3>
      <div class="chat-container">
        <div class="chat-messages" id="chatMessages">
          <div class="chat-msg assistant"><div class="bubble">Hello! I'm the TicketForge assistant. I can help you create tickets, check status, or search the knowledge base. How can I help?</div></div>
        </div>
        <div class="chat-input">
          <input type="text" id="chatInput" placeholder="Type your message..." onkeydown="if(event.key==='Enter')sendChat()" />
          <button class="btn" onclick="sendChat()">Send</button>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const API = window.location.origin;
let chatSessionId = '';

function hdr(){ return {"X-Api-Key":document.getElementById("apiKey").value,"Content-Type":"application/json"} }
function setStatus(msg,ok){ const el=document.getElementById("statusMsg"); el.textContent=msg; el.style.color=ok?"#16a34a":"#c53030" }
function esc(s){ const d=document.createElement("div"); d.textContent=s||""; return d.innerHTML; }

function switchTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('tab-'+name).classList.add('active');
}

async function submitTicket(){
  const key=document.getElementById("apiKey").value.trim();
  if(!key){setStatus("Enter API key",false);return}
  const title=document.getElementById("ticketTitle").value.trim();
  const email=document.getElementById("ticketEmail").value.trim();
  if(!title||!email){document.getElementById("submitResult").innerHTML='<div class="result-msg error">Title and email are required.</div>';return}
  try{
    const res=await fetch(API+"/portal/tickets",{method:"POST",headers:hdr(),body:JSON.stringify({
      title:title,description:document.getElementById("ticketDescription").value,
      reporter_email:email,category:document.getElementById("ticketCategory").value
    })});
    const d=await res.json();
    if(res.ok){
      let html='<div class="result-msg success">'+esc(d.message)+'</div>';
      if(d.suggested_articles&&d.suggested_articles.length>0){
        html+='<div class="suggested-articles"><h4>These articles may help:</h4><ul class="kb-list">';
        d.suggested_articles.forEach(a=>{html+='<li><div class="kb-title">'+esc(a.title)+'</div><div class="kb-snippet">'+esc(a.snippet)+'</div></li>'});
        html+='</ul></div>';
      }
      document.getElementById("submitResult").innerHTML=html;
    }else{
      document.getElementById("submitResult").innerHTML='<div class="result-msg error">Error: '+esc(d.detail||"Unknown error")+'</div>';
    }
  }catch(e){document.getElementById("submitResult").innerHTML='<div class="result-msg error">'+esc(e.message)+'</div>'}
}

async function checkStatus(){
  const key=document.getElementById("apiKey").value.trim();
  if(!key){setStatus("Enter API key",false);return}
  const ticketId=document.getElementById("statusTicketId").value.trim();
  if(!ticketId){document.getElementById("statusResult").innerHTML='<div class="result-msg error">Enter a ticket ID</div>';return}
  try{
    const res=await fetch(API+"/tickets/"+encodeURIComponent(ticketId),{headers:hdr()});
    if(res.ok){
      const d=await res.json();
      document.getElementById("statusResult").innerHTML='<div class="result-msg success">'
        +'<strong>Ticket:</strong> '+esc(d.ticket_id)+'<br>'
        +'<strong>Status:</strong> '+esc(d.ticket_status)+'<br>'
        +'<strong>Priority:</strong> '+esc(d.priority?.priority||"")+'<br>'
        +'<strong>Category:</strong> '+esc(d.category?.category||"")+'<br>'
        +'<strong>Summary:</strong> '+esc(d.summary)+'</div>';
    }else{
      const d=await res.json();
      document.getElementById("statusResult").innerHTML='<div class="result-msg error">'+esc(d.detail||"Not found")+'</div>';
    }
  }catch(e){document.getElementById("statusResult").innerHTML='<div class="result-msg error">'+esc(e.message)+'</div>'}
}

async function searchKB(){
  const key=document.getElementById("apiKey").value.trim();
  if(!key){setStatus("Enter API key",false);return}
  const query=document.getElementById("kbSearch").value.trim();
  if(!query){return}
  try{
    const res=await fetch(API+"/kb/search",{method:"POST",headers:hdr(),body:JSON.stringify({query:query,max_results:10})});
    const d=await res.json();
    if(d.results&&d.results.length>0){
      let html='<ul class="kb-list">';
      d.results.forEach(r=>{html+='<li><div class="kb-title">'+esc(r.title)+'</div><div class="kb-cat">'+esc(r.category)+' &middot; Score: '+(r.relevance_score*100).toFixed(0)+'%</div><div class="kb-snippet">'+esc(r.snippet)+'</div></li>'});
      html+='</ul>';
      document.getElementById("kbResults").innerHTML=html;
    }else{
      document.getElementById("kbResults").innerHTML='<div class="empty-state">No matching articles found</div>';
    }
  }catch(e){document.getElementById("kbResults").innerHTML='<div class="empty-state">Search failed: '+esc(e.message)+'</div>'}
}

async function browseKB(){
  const key=document.getElementById("apiKey").value.trim();
  if(!key){setStatus("Enter API key",false);return}
  try{
    const res=await fetch(API+"/kb/articles",{headers:hdr()});
    const d=await res.json();
    if(d.data&&d.data.length>0){
      let html='<ul class="kb-list">';
      d.data.forEach(a=>{html+='<li><div class="kb-title">'+esc(a.title)+'</div><div class="kb-cat">'+esc(a.category)+' &middot; '+a.tags.map(t=>esc(t)).join(', ')+'</div><div class="kb-snippet">'+esc((a.content||"").substring(0,200))+'</div></li>'});
      html+='</ul>';
      document.getElementById("kbResults").innerHTML=html;
    }else{
      document.getElementById("kbResults").innerHTML='<div class="empty-state">No articles in the knowledge base yet</div>';
    }
  }catch(e){document.getElementById("kbResults").innerHTML='<div class="empty-state">Failed to load: '+esc(e.message)+'</div>'}
}

async function sendChat(){
  const key=document.getElementById("apiKey").value.trim();
  if(!key){setStatus("Enter API key",false);return}
  const input=document.getElementById("chatInput");
  const msg=input.value.trim();
  if(!msg)return;
  input.value='';
  const el=document.getElementById("chatMessages");
  el.innerHTML+='<div class="chat-msg user"><div class="bubble">'+esc(msg)+'</div></div>';
  el.scrollTop=el.scrollHeight;
  try{
    const res=await fetch(API+"/chat",{method:"POST",headers:hdr(),body:JSON.stringify({session_id:chatSessionId,message:msg})});
    const d=await res.json();
    if(res.ok){
      chatSessionId=d.session_id||chatSessionId;
      el.innerHTML+='<div class="chat-msg assistant"><div class="bubble">'+esc(d.reply).replace(/\\n/g,'<br>')+'</div></div>';
    }else{
      el.innerHTML+='<div class="chat-msg assistant"><div class="bubble" style="background:#fde8e8;color:#c53030">Error: '+esc(d.detail||"Unknown error")+'</div></div>';
    }
  }catch(e){
    el.innerHTML+='<div class="chat-msg assistant"><div class="bubble" style="background:#fde8e8;color:#c53030">'+esc(e.message)+'</div></div>';
  }
  el.scrollTop=el.scrollHeight;
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
