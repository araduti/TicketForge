"""
TicketForge — Audit logging service
Records every API action for compliance and traceability.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import aiosqlite
import structlog

from models import AuditEntry, Role

log = structlog.get_logger(__name__)

AUDIT_TABLE_SQL = """
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


def _hash_api_key(api_key: str) -> str:
    """Return a shortened SHA-256 hex digest (first 12 chars) for safe logging."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]


async def record(
    db: aiosqlite.Connection,
    *,
    api_key: str,
    role: Role,
    action: str,
    resource: str,
    status_code: int = 200,
    detail: str = "",
) -> None:
    """Insert an audit log entry."""
    try:
        await db.execute(
            """
            INSERT INTO audit_log (timestamp, api_key_hash, role, action, resource, status_code, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(tz=timezone.utc).isoformat(),
                _hash_api_key(api_key),
                role.value,
                action,
                resource,
                status_code,
                detail,
            ),
        )
        await db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("audit.record_failed", error=str(e))


async def query(
    db: aiosqlite.Connection,
    *,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuditEntry], int]:
    """Return paginated audit log entries (newest first) and total count."""
    async with db.execute("SELECT COUNT(*) FROM audit_log") as cur:
        total = (await cur.fetchone())[0]

    offset = (page - 1) * page_size
    async with db.execute(
        "SELECT id, timestamp, api_key_hash, role, action, resource, status_code, detail "
        "FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
        (page_size, offset),
    ) as cur:
        rows = await cur.fetchall()

    entries = [
        AuditEntry(
            id=r[0],
            timestamp=datetime.fromisoformat(r[1]),
            api_key_hash=r[2],
            role=Role(r[3]),
            action=r[4],
            resource=r[5],
            status_code=r[6],
            detail=r[7],
        )
        for r in rows
    ]
    return entries, total
