"""Shared dependencies module for TicketForge route modules."""

from __future__ import annotations

import hashlib
import html
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog
from fastapi import Depends, Header, HTTPException, WebSocket, status

from config import settings
from models import Priority, Role, SLAInfo, SLAStatus, WebSocketEvent

if TYPE_CHECKING:
    import aiosqlite
    from ticket_processor import TicketProcessor
    from automation_detector import AutomationDetector
    from vector_store import VectorStore

log = structlog.get_logger(__name__)

# ── Shared singletons (set by main.lifespan) ─────────────────────────────────
db: aiosqlite.Connection | None = None
processor: TicketProcessor | None = None
detector: AutomationDetector | None = None
vector_store: VectorStore | None = None


# ── Dependency functions ──────────────────────────────────────────────────────

def get_db() -> aiosqlite.Connection:
    if db is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    return db


def get_processor() -> TicketProcessor:
    if processor is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    return processor


def get_vector_store() -> VectorStore:
    if vector_store is None:
        raise HTTPException(status_code=503, detail="Vector store not ready")
    return vector_store


# ── Auth dependencies ─────────────────────────────────────────────────────────

_ROLE_HIERARCHY: dict[Role, int] = {Role.viewer: 0, Role.analyst: 1, Role.admin: 2}


def _hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _verify_api_key_secure(provided_key: str, valid_keys: list[str]) -> bool:
    provided_hash = _hash_api_key(provided_key)
    for valid_key in valid_keys:
        valid_hash = _hash_api_key(valid_key)
        if secrets.compare_digest(provided_hash, valid_hash):
            return True
    return False


def _resolve_role(api_key: str) -> Role:
    role_str = settings.api_key_roles.get(api_key, "analyst")
    try:
        return Role(role_str)
    except ValueError:
        return Role.analyst


async def verify_api_key(x_api_key: str = Header(...)) -> str:
    if not _verify_api_key_secure(x_api_key, settings.api_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return x_api_key


def _require_role(minimum: Role):
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


# ── SLA helper ────────────────────────────────────────────────────────────────

_SLA_TARGETS: dict[Priority, tuple[int, int]] = {
    Priority.critical: (settings.sla_response_critical, settings.sla_resolution_critical),
    Priority.high: (settings.sla_response_high, settings.sla_resolution_high),
    Priority.medium: (settings.sla_response_medium, settings.sla_resolution_medium),
    Priority.low: (settings.sla_response_low, settings.sla_resolution_low),
}


def compute_sla(priority: Priority, created_at: datetime) -> SLAInfo:
    response_target, resolution_target = _SLA_TARGETS[priority]
    now = datetime.now(tz=timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    elapsed = max(0.0, (now - created_at).total_seconds() / 60.0)
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


# ── Input sanitisation helper ─────────────────────────────────────────────────

def sanitise_text(text: str) -> str:
    if not settings.input_sanitisation_enabled:
        return text
    try:
        import nh3
        return nh3.clean(text)
    except ImportError:
        return html.escape(text)


# ── WebSocket manager ─────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, event: WebSocketEvent) -> None:
        payload = event.model_dump_json()
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    @property
    def active_connections(self) -> int:
        return len(self._connections)


ws_manager = ConnectionManager()
