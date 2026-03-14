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
from fastapi.responses import JSONResponse, StreamingResponse
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
