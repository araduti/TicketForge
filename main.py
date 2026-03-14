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
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

import httpx
import structlog
import structlog.stdlib
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
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
    AnalyseRequest,
    AnalyseResponse,
    AnalyticsResponse,
    AuditLogResponse,
    AutomationOpportunity,
    AutomationSuggestionType,
    BulkAnalyseRequest,
    BulkAnalyseResponse,
    CategoryCount,
    CategoryResult,
    ChatRequest,
    ChatResponse,
    CSATAnalyticsResponse,
    CSATRecord,
    CSATResponse,
    CSATSubmission,
    DailyTrend,
    DetectDuplicatesRequest,
    DetectDuplicatesResponse,
    DriftMetric,
    DuplicateCandidate,
    EmailIngestRequest,
    EnrichedTicket,
    ErrorResponse,
    ExportFormat,
    HealthResponse,
    KBArticleCreate,
    KBArticleListResponse,
    KBArticleRecord,
    KBArticleResponse,
    KBArticleUpdate,
    KBSearchRequest,
    KBSearchResponse,
    KBSearchResult,
    MonitoringResponse,
    MultiAgentStatusResponse,
    PluginInfo,
    PluginListResponse,
    PortalTicketResponse,
    PortalTicketSubmission,
    Priority,
    PriorityCount,
    PriorityResult,
    RawTicket,
    Role,
    RootCauseHypothesis,
    RoutingResult,
    Sentiment,
    SentimentResult,
    SLAInfo,
    SLAStatus,
    SuggestedResponse,
    SuggestResponseRequest,
    SuggestResponseResponse,
    TicketSource,
    TicketStatus,
    TicketStatusUpdate,
    VectorStoreStatusResponse,
    WebhookIngest,
    WebSocketEvent,
)
from notifications import send_notifications
from ticket_processor import TicketProcessor
from vector_store import VectorStore, create_vector_store

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
APP_VERSION = "0.1.0"

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
    ticket_status TEXT DEFAULT 'open'
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

# Prometheus metrics at /metrics
Instrumentator().instrument(app).expose(app)


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
    """Validate the X-Api-Key header against the configured list."""
    if x_api_key not in settings.api_keys:
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
    """Liveness / readiness probe."""
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

    cutoff = datetime.now(tz=timezone.utc).isoformat()

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
    ticket = RawTicket(
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
    log.error("unhandled_exception", path=str(request.url), error=str(exc), exc_info=True)
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
