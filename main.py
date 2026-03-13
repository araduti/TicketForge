"""
TicketForge — FastAPI application entry point

Run locally:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Or via Docker Compose (see docker-compose.yml).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

import httpx
import structlog
import structlog.stdlib
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import aiosqlite
from automation_detector import AutomationDetector
from config import settings
from connectors.jira import JiraConnector
from connectors.servicenow import ServiceNowConnector
from connectors.zendesk import ZendeskConnector
from models import (
    AnalyseRequest,
    AnalyseResponse,
    AutomationOpportunity,
    AutomationSuggestionType,
    CategoryResult,
    EnrichedTicket,
    ErrorResponse,
    HealthResponse,
    Priority,
    PriorityResult,
    RawTicket,
    RootCauseHypothesis,
    RoutingResult,
    TicketSource,
    WebhookIngest,
)
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
    summary TEXT
);

CREATE TABLE IF NOT EXISTS ticket_history (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
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


# ── Authentication dependency ──────────────────────────────────────────────────

async def verify_api_key(x_api_key: str = Header(...)) -> str:
    """Validate the X-Api-Key header against the configured list."""
    if x_api_key not in settings.api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return x_api_key


# ── Helper to get processor (raises 503 if not ready) ─────────────────────────

def _get_processor() -> TicketProcessor:
    if _processor is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    return _processor


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
    _: str = Depends(verify_api_key),
) -> AnalyseResponse:
    """
    Analyse a single ticket inline.
    Returns full enrichment: category, priority, routing, automation score, KB suggestions.
    """
    processor = _get_processor()
    enriched = await processor.process(
        body.ticket, include_automation=body.include_automation_detection
    )
    await _persist_ticket(enriched)
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
    _: str = Depends(verify_api_key),
) -> AnalyseResponse:
    """
    Ingest a webhook payload from a source system and return enriched result.
    Supports: servicenow, jira, zendesk.
    """
    processor = _get_processor()
    ticket = _parse_webhook_payload(source, body.payload)
    enriched = await processor.process(ticket, include_automation=True)
    await _persist_ticket(enriched)

    # Fire-and-forget outbound webhook if configured
    if settings.outbound_webhook_url:
        asyncio.create_task(_send_outbound_webhook(enriched))

    return AnalyseResponse(data=enriched)


@app.get(
    "/tickets/{ticket_id}",
    response_model=EnrichedTicket,
    tags=["core"],
)
async def get_cached_ticket(
    ticket_id: str,
    _: str = Depends(verify_api_key),
) -> EnrichedTicket:
    """Retrieve a previously processed ticket from the local cache."""
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    async with _db.execute(
        "SELECT id, source, processed_at, category, priority, automation_score, summary "
        "FROM processed_tickets WHERE id = ?",
        (ticket_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Ticket not found in cache")
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
        processed_at=datetime.fromisoformat(row[2]),
    )


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
                (id, source, processed_at, category, priority, automation_score, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                enriched.ticket_id,
                enriched.source.value,
                enriched.processed_at.isoformat(),
                enriched.category.category,
                enriched.priority.priority.value,
                enriched.automation.score,
                enriched.summary,
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
