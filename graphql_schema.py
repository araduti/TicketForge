"""Strawberry-GraphQL schema exposing TicketForge data.

Mount on the FastAPI app via::

    from graphql_schema import graphql_app
    app.include_router(graphql_app, prefix="/graphql")
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.types import Info

import aiosqlite

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db() -> aiosqlite.Connection:
    """Return the shared *aiosqlite* connection owned by ``main._db``.

    Raises :class:`RuntimeError` (surfaced as a GraphQL error) when the
    database is not yet initialised.
    """
    from main import _db  # noqa: PLC0415

    if _db is None:
        raise RuntimeError("Database connection is not available")
    return _db


# ---------------------------------------------------------------------------
# Strawberry types
# ---------------------------------------------------------------------------


@strawberry.type
class Ticket:
    id: str
    source: str
    processed_at: str
    category: Optional[str]
    priority: Optional[str]
    automation_score: Optional[int]
    summary: Optional[str]
    sentiment: Optional[str]
    detected_language: Optional[str]
    ticket_status: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


@strawberry.type
class KBArticle:
    id: str
    title: str
    content: str
    category: str
    tags: list[str]
    created_at: str
    updated_at: str


@strawberry.type
class CategoryCount:
    category: str
    count: int


@strawberry.type
class PriorityCount:
    priority: str
    count: int


@strawberry.type
class AnalyticsSummary:
    total_tickets: int
    avg_automation_score: float
    period_days: int
    by_category: list[CategoryCount]
    by_priority: list[PriorityCount]


@strawberry.type
class HealthStatus:
    status: str
    ollama_reachable: bool
    db_ok: bool


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


@strawberry.type
class Query:
    @strawberry.field
    async def tickets(
        self,
        info: Info,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Ticket]:
        db = _get_db()
        async with db.execute(
            "SELECT id, source, processed_at, category, priority, "
            "automation_score, summary, sentiment, detected_language, "
            "ticket_status, created_at, updated_at "
            "FROM processed_tickets ORDER BY processed_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [
            Ticket(
                id=r[0],
                source=r[1],
                processed_at=r[2],
                category=r[3],
                priority=r[4],
                automation_score=r[5],
                summary=r[6],
                sentiment=r[7],
                detected_language=r[8],
                ticket_status=r[9],
                created_at=r[10],
                updated_at=r[11],
            )
            for r in rows
        ]

    @strawberry.field
    async def ticket(self, info: Info, id: str) -> Optional[Ticket]:
        db = _get_db()
        async with db.execute(
            "SELECT id, source, processed_at, category, priority, "
            "automation_score, summary, sentiment, detected_language, "
            "ticket_status, created_at, updated_at "
            "FROM processed_tickets WHERE id = ?",
            (id,),
        ) as cur:
            r = await cur.fetchone()
        if r is None:
            return None
        return Ticket(
            id=r[0],
            source=r[1],
            processed_at=r[2],
            category=r[3],
            priority=r[4],
            automation_score=r[5],
            summary=r[6],
            sentiment=r[7],
            detected_language=r[8],
            ticket_status=r[9],
            created_at=r[10],
            updated_at=r[11],
        )

    @strawberry.field
    async def kb_articles(self, info: Info, limit: int = 50) -> list[KBArticle]:
        db = _get_db()
        async with db.execute(
            "SELECT id, title, content, category, tags, created_at, updated_at "
            "FROM kb_articles ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        articles: list[KBArticle] = []
        for r in rows:
            try:
                tags = json.loads(r[4]) if r[4] else []
            except (json.JSONDecodeError, TypeError):
                tags = []
            articles.append(
                KBArticle(
                    id=r[0],
                    title=r[1],
                    content=r[2],
                    category=r[3],
                    tags=tags,
                    created_at=r[5],
                    updated_at=r[6],
                )
            )
        return articles

    @strawberry.field
    async def analytics(self, info: Info, days: int = 30) -> AnalyticsSummary:
        db = _get_db()

        async with db.execute("SELECT COUNT(*) FROM processed_tickets") as cur:
            total = (await cur.fetchone())[0]  # type: ignore[index]

        async with db.execute(
            "SELECT category, COUNT(*) AS cnt FROM processed_tickets "
            "GROUP BY category ORDER BY cnt DESC",
        ) as cur:
            by_category = [
                CategoryCount(category=r[0] or "Unknown", count=r[1])
                for r in await cur.fetchall()
            ]

        async with db.execute(
            "SELECT priority, COUNT(*) AS cnt FROM processed_tickets "
            "GROUP BY priority ORDER BY cnt DESC",
        ) as cur:
            by_priority = [
                PriorityCount(priority=r[0] or "unknown", count=r[1])
                for r in await cur.fetchall()
            ]

        async with db.execute(
            "SELECT AVG(automation_score) FROM processed_tickets "
            "WHERE automation_score IS NOT NULL",
        ) as cur:
            row = await cur.fetchone()
            avg_auto = round(row[0], 1) if row and row[0] is not None else 0.0  # type: ignore[index]

        return AnalyticsSummary(
            total_tickets=total,
            avg_automation_score=avg_auto,
            period_days=days,
            by_category=by_category,
            by_priority=by_priority,
        )

    @strawberry.field
    async def health(self, info: Info) -> HealthStatus:
        import httpx  # noqa: PLC0415

        from config import settings  # noqa: PLC0415

        ollama_ok = False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{settings.ollama_base_url}/api/tags")
                ollama_ok = r.status_code == 200
        except Exception:  # noqa: BLE001
            pass

        from main import _db  # noqa: PLC0415

        return HealthStatus(
            status="ok",
            ollama_reachable=ollama_ok,
            db_ok=_db is not None,
        )


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_kb_article(
        self,
        info: Info,
        title: str,
        content: str,
        category: str = "general",
        tags: Optional[list[str]] = None,
    ) -> KBArticle:
        db = _get_db()
        article_id = f"KB-{uuid.uuid4().hex[:12]}"
        now = datetime.now(tz=timezone.utc).isoformat()
        tags_list = tags if tags is not None else []
        tags_json = json.dumps(tags_list)

        await db.execute(
            "INSERT INTO kb_articles (id, title, content, category, tags, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (article_id, title, content, category, tags_json, now, now),
        )
        await db.commit()

        return KBArticle(
            id=article_id,
            title=title,
            content=content,
            category=category,
            tags=tags_list,
            created_at=now,
            updated_at=now,
        )


# ---------------------------------------------------------------------------
# Router to mount on FastAPI
# ---------------------------------------------------------------------------

schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_app = GraphQLRouter(schema)
