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
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
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
    DailyTrend,
    DetectDuplicatesRequest,
    DetectDuplicatesResponse,
    DuplicateCandidate,
    EnrichedTicket,
    ErrorResponse,
    ExportFormat,
    HealthResponse,
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
    WebhookIngest,
)
from notifications import send_notifications
from ticket_processor import TicketProcessor

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

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── App state (shared singletons) ─────────────────────────────────────────────
_processor: TicketProcessor | None = None
_detector: AutomationDetector | None = None
_db: aiosqlite.Connection | None = None

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
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _processor, _detector, _db  # noqa: PLW0603

    log.info("ticketforge.startup", version="0.1.0", model=settings.ollama_model)

    # Database
    _db = await aiosqlite.connect(settings.database_url.replace("sqlite+aiosqlite:///", ""))
    await _db.executescript(DB_INIT_SQL)
    await _db.commit()

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
    version="0.1.0",
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
    from prompts import SUGGEST_RESPONSE_PROMPT, SYSTEM_PROMPT  # noqa: PLC0415

    prompt = SUGGEST_RESPONSE_PROMPT.format(
        ticket_id=row[0],
        title=row[5] or "",  # summary as title fallback
        description=body.additional_context or "N/A",
        category=row[2] or "",
        sub_category="",
        priority=row[3] or "medium",
        sentiment=row[6] or "neutral",
        summary=row[5] or "",
        kb_articles="None available",
        root_cause="Not determined",
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    try:
        raw_content = await processor._llm.chat(messages, temperature=0.3, max_tokens=1024)
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

    model = _detector._get_model()  # type: ignore[union-attr]
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


# ── Dashboard endpoint ────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse, tags=["ui"])
async def dashboard():
    """
    Serve a lightweight built-in web dashboard.
    Shows recent tickets, analytics charts, SLA overview, and status summary.
    No authentication required for the HTML shell — data is fetched via authenticated API calls.
    """
    return HTMLResponse(content=_DASHBOARD_HTML)


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
  <span class="version">v0.1.0</span>
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
  html += '<div style="font-size:.85rem;color:#666">SLA tracking is available per-ticket via the API. Use <code>GET /tickets/{id}</code> with an API key to see full SLA details.</div>';
  el.innerHTML = html;
}

function esc(s){ const d=document.createElement("div"); d.textContent=s||""; return d.innerHTML; }
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
