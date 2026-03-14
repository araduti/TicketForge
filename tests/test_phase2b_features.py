"""
TicketForge — Test suite for Phase 2 remaining features
Tests for Knowledge Base module, Email Ingestion, and PostgreSQL config.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Override settings BEFORE importing main so the app uses test config
os.environ["API_KEYS"] = '["admin-key","analyst-key","viewer-key"]'
os.environ["API_KEY_ROLES"] = json.dumps({
    "admin-key": "admin",
    "analyst-key": "analyst",
    "viewer-key": "viewer",
})
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase2b.db"
os.environ["EMAIL_INGESTION_ENABLED"] = "true"

from main import app, lifespan  # noqa: E402
from models import (  # noqa: E402
    EmailIngestRequest,
    KBArticleCreate,
    KBArticleListResponse,
    KBArticleRecord,
    KBArticleResponse,
    KBArticleUpdate,
    KBSearchRequest,
    KBSearchResponse,
    KBSearchResult,
)


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    # Pre-clean database file to avoid state leaking between tests
    from config import settings as _s  # noqa: PLC0415
    _db_path = _s.database_url.replace("sqlite+aiosqlite:///", "")
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Clean up test database
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass


# ── Knowledge Base CRUD tests ────────────────────────────────────────────────

class TestKBArticleCRUD:
    """Test the Knowledge Base CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_kb_article(self, client):
        """Create a new KB article returns 201 with article data."""
        response = await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "title": "How to Reset VPN",
                "content": "Step 1: Open VPN client. Step 2: Click Reset.",
                "category": "networking",
                "tags": ["vpn", "reset"],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["title"] == "How to Reset VPN"
        assert data["data"]["category"] == "networking"
        assert data["data"]["tags"] == ["vpn", "reset"]
        assert data["data"]["id"].startswith("KB-")

    @pytest.mark.asyncio
    async def test_create_kb_article_requires_analyst(self, client):
        """Viewer cannot create KB articles."""
        response = await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "viewer-key"},
            json={"title": "Test", "content": "Body text"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_kb_article_validation(self, client):
        """KB article requires title and content."""
        response = await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={"title": ""},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_list_kb_articles_empty(self, client):
        """List KB articles when none exist returns empty list."""
        response = await client.get(
            "/kb/articles",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_kb_articles_with_data(self, client):
        """List KB articles returns created articles."""
        # Create two articles
        await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={"title": "Article 1", "content": "Content 1", "category": "general"},
        )
        await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={"title": "Article 2", "content": "Content 2", "category": "networking"},
        )

        response = await client.get(
            "/kb/articles",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_list_kb_articles_filter_category(self, client):
        """List KB articles can filter by category."""
        await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={"title": "Art A", "content": "Content A", "category": "hardware"},
        )
        await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={"title": "Art B", "content": "Content B", "category": "software"},
        )

        response = await client.get(
            "/kb/articles?category=hardware",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["data"][0]["category"] == "hardware"

    @pytest.mark.asyncio
    async def test_get_kb_article(self, client):
        """Get a single KB article by ID."""
        create_resp = await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={"title": "My Article", "content": "Full content here"},
        )
        article_id = create_resp.json()["data"]["id"]

        response = await client.get(
            f"/kb/articles/{article_id}",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["id"] == article_id
        assert data["data"]["title"] == "My Article"

    @pytest.mark.asyncio
    async def test_get_kb_article_not_found(self, client):
        """Get a nonexistent KB article returns 404."""
        response = await client.get(
            "/kb/articles/KB-nonexistent",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_kb_article(self, client):
        """Update a KB article with partial data."""
        create_resp = await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={"title": "Original Title", "content": "Original content", "category": "general"},
        )
        article_id = create_resp.json()["data"]["id"]

        response = await client.put(
            f"/kb/articles/{article_id}",
            headers={"X-Api-Key": "analyst-key"},
            json={"title": "Updated Title"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["title"] == "Updated Title"
        assert data["data"]["content"] == "Original content"  # unchanged

    @pytest.mark.asyncio
    async def test_update_kb_article_not_found(self, client):
        """Update a nonexistent KB article returns 404."""
        response = await client.put(
            "/kb/articles/KB-nonexistent",
            headers={"X-Api-Key": "analyst-key"},
            json={"title": "New Title"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_kb_article_requires_analyst(self, client):
        """Viewer cannot update KB articles."""
        response = await client.put(
            "/kb/articles/KB-test",
            headers={"X-Api-Key": "viewer-key"},
            json={"title": "Nope"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_kb_article(self, client):
        """Delete a KB article (admin only)."""
        create_resp = await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={"title": "To Delete", "content": "Bye"},
        )
        article_id = create_resp.json()["data"]["id"]

        response = await client.delete(
            f"/kb/articles/{article_id}",
            headers={"X-Api-Key": "admin-key"},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Confirm it's gone
        get_resp = await client.get(
            f"/kb/articles/{article_id}",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_kb_article_requires_admin(self, client):
        """Analyst cannot delete KB articles."""
        response = await client.delete(
            "/kb/articles/KB-test",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_kb_article_not_found(self, client):
        """Delete a nonexistent KB article returns 404."""
        response = await client.delete(
            "/kb/articles/KB-nonexistent",
            headers={"X-Api-Key": "admin-key"},
        )
        assert response.status_code == 404


class TestKBArticleModels:
    """Test KB article Pydantic models."""

    def test_kb_article_create_model(self):
        """KBArticleCreate model accepts valid data."""
        article = KBArticleCreate(
            title="Test Article",
            content="Full content here",
            category="networking",
            tags=["vpn", "setup"],
        )
        assert article.title == "Test Article"
        assert article.category == "networking"
        assert len(article.tags) == 2

    def test_kb_article_create_defaults(self):
        """KBArticleCreate has sensible defaults."""
        article = KBArticleCreate(title="Test", content="Body")
        assert article.category == "general"
        assert article.tags == []

    def test_kb_article_update_model(self):
        """KBArticleUpdate allows partial updates."""
        update = KBArticleUpdate(title="New Title")
        assert update.title == "New Title"
        assert update.content is None
        assert update.category is None
        assert update.tags is None

    def test_kb_article_record_model(self):
        """KBArticleRecord model works correctly."""
        record = KBArticleRecord(
            id="KB-abc123",
            title="Test",
            content="Body",
            category="general",
            tags=["test"],
        )
        assert record.id == "KB-abc123"
        assert record.tags == ["test"]

    def test_kb_article_response_model(self):
        """KBArticleResponse wraps KBArticleRecord."""
        record = KBArticleRecord(id="KB-1", title="T", content="C")
        resp = KBArticleResponse(data=record)
        assert resp.success is True
        assert resp.data.id == "KB-1"

    def test_kb_article_list_response_model(self):
        """KBArticleListResponse wraps list of records."""
        resp = KBArticleListResponse(
            data=[KBArticleRecord(id="KB-1", title="T", content="C")],
            total=1,
        )
        assert resp.total == 1
        assert len(resp.data) == 1

    def test_kb_search_request_model(self):
        """KBSearchRequest model accepts valid data."""
        req = KBSearchRequest(query="VPN not working", max_results=3, threshold=0.5)
        assert req.query == "VPN not working"
        assert req.max_results == 3
        assert req.threshold == 0.5

    def test_kb_search_request_defaults(self):
        """KBSearchRequest has sensible defaults."""
        req = KBSearchRequest(query="help")
        assert req.max_results == 5
        assert req.threshold == 0.3

    def test_kb_search_result_model(self):
        """KBSearchResult model works correctly."""
        result = KBSearchResult(
            article_id="KB-1",
            title="VPN Guide",
            category="networking",
            relevance_score=0.85,
            snippet="Step 1: Connect...",
        )
        assert result.relevance_score == 0.85
        assert result.snippet.startswith("Step 1")

    def test_kb_search_response_model(self):
        """KBSearchResponse wraps search results."""
        resp = KBSearchResponse(
            query="vpn",
            results=[KBSearchResult(article_id="KB-1", title="VPN", relevance_score=0.9)],
            total=1,
        )
        assert resp.success is True
        assert resp.total == 1


class TestKBSearch:
    """Test the POST /kb/search endpoint."""

    @pytest.mark.asyncio
    async def test_kb_search_empty(self, client):
        """KB search with no articles returns empty results."""
        response = await client.post(
            "/kb/search",
            headers={"X-Api-Key": "viewer-key"},
            json={"query": "VPN connection issues"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_kb_search_requires_query(self, client):
        """KB search requires a query string."""
        response = await client.post(
            "/kb/search",
            headers={"X-Api-Key": "viewer-key"},
            json={},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_kb_search_with_articles(self, client):
        """KB search returns relevant articles after adding them."""
        # Create articles
        await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "title": "VPN Troubleshooting Guide",
                "content": "If your VPN connection is failing, try these steps: restart the VPN client, check network settings, verify credentials.",
                "category": "networking",
            },
        )
        await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "title": "Password Reset Procedure",
                "content": "To reset your password, go to the self-service portal and click Forgot Password.",
                "category": "account",
            },
        )

        # Search for VPN-related content — may fail if embedding model not cached
        response = await client.post(
            "/kb/search",
            headers={"X-Api-Key": "viewer-key"},
            json={"query": "VPN connection not working", "threshold": 0.1},
        )
        if response.status_code == 503:
            pytest.skip("Embedding model not available in this environment")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total"] >= 1
        # VPN article should be most relevant
        assert any("VPN" in r["title"] for r in data["results"])


# ── Email Ingestion tests ────────────────────────────────────────────────────

class TestEmailIngestion:
    """Test the POST /ingest/email endpoint."""

    @pytest.mark.asyncio
    async def test_email_ingest_requires_analyst(self, client):
        """Viewer cannot use email ingestion."""
        response = await client.post(
            "/ingest/email",
            headers={"X-Api-Key": "viewer-key"},
            json={"sender": "user@example.com", "subject": "Help"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_email_ingest_requires_sender(self, client):
        """Email ingest requires sender field."""
        response = await client.post(
            "/ingest/email",
            headers={"X-Api-Key": "analyst-key"},
            json={"subject": "Help"},
        )
        assert response.status_code == 422


class TestEmailIngestionModels:
    """Test email ingestion Pydantic models and parsing."""

    def test_email_ingest_request_model(self):
        """EmailIngestRequest model accepts valid data."""
        req = EmailIngestRequest(
            sender="user@example.com",
            subject="VPN is broken",
            body_plain="I can't connect to VPN since this morning.",
            recipient="support@company.com",
            message_id="<abc123@mail.example.com>",
        )
        assert req.sender == "user@example.com"
        assert req.subject == "VPN is broken"
        assert req.message_id == "<abc123@mail.example.com>"

    def test_email_ingest_request_defaults(self):
        """EmailIngestRequest has sensible defaults."""
        req = EmailIngestRequest(sender="user@example.com")
        assert req.subject == ""
        assert req.body_plain == ""
        assert req.body_html == ""
        assert req.headers == {}

    def test_email_to_ticket_conversion(self):
        """parse_email_to_ticket converts email to RawTicket."""
        from email_ingestion import parse_email_to_ticket

        email = EmailIngestRequest(
            sender="user@example.com",
            subject="VPN is broken",
            body_plain="I can't connect to the corporate VPN.",
            message_id="<msg-001@mail.example.com>",
        )
        ticket = parse_email_to_ticket(email)
        assert ticket.id.startswith("EMAIL-")
        assert ticket.title == "VPN is broken"
        assert ticket.description == "I can't connect to the corporate VPN."
        assert ticket.reporter == "user@example.com"
        assert "email" in ticket.tags

    def test_email_to_ticket_no_subject(self):
        """Email without subject uses fallback title."""
        from email_ingestion import parse_email_to_ticket

        email = EmailIngestRequest(
            sender="user@example.com",
            body_plain="Something is wrong.",
        )
        ticket = parse_email_to_ticket(email)
        assert ticket.title == "(no subject)"

    def test_email_to_ticket_html_fallback(self):
        """Email with only HTML body strips tags for description."""
        from email_ingestion import parse_email_to_ticket

        email = EmailIngestRequest(
            sender="user@example.com",
            subject="Help",
            body_html="<p>My <b>printer</b> is not working</p>",
        )
        ticket = parse_email_to_ticket(email)
        assert "printer" in ticket.description
        assert "<p>" not in ticket.description

    def test_sendgrid_payload_parsing(self):
        """parse_sendgrid_inbound converts SendGrid payload."""
        from email_ingestion import parse_sendgrid_inbound

        payload = {
            "from": "user@example.com",
            "subject": "Need help with printer",
            "text": "My printer won't print.",
            "to": "support@company.com",
            "message_id": "<sg-123@sendgrid.net>",
        }
        email = parse_sendgrid_inbound(payload)
        assert email.sender == "user@example.com"
        assert email.subject == "Need help with printer"
        assert email.body_plain == "My printer won't print."

    def test_mailgun_payload_parsing(self):
        """parse_mailgun_inbound converts Mailgun payload."""
        from email_ingestion import parse_mailgun_inbound

        payload = {
            "sender": "user@example.com",
            "subject": "Password issue",
            "body-plain": "I forgot my password.",
            "recipient": "support@company.com",
            "Message-Id": "<mg-456@mailgun.org>",
        }
        email = parse_mailgun_inbound(payload)
        assert email.sender == "user@example.com"
        assert email.body_plain == "I forgot my password."
        assert email.message_id == "<mg-456@mailgun.org>"


# ── PostgreSQL config tests ──────────────────────────────────────────────────

class TestDatabaseConfig:
    """Test database configuration for PostgreSQL support."""

    def test_default_database_url_is_sqlite(self):
        """Default database URL is SQLite."""
        from config import Settings
        s = Settings(api_keys=["test"])
        assert "sqlite" in s.database_url

    def test_database_url_accepts_postgresql(self):
        """Database URL can be set to PostgreSQL."""
        from config import Settings
        pg_url = "postgresql://user:pass@localhost:5432/ticketforge"
        s = Settings(api_keys=["test"], database_url=pg_url)
        assert s.database_url == pg_url
        assert "postgresql" in s.database_url

    def test_email_ingestion_default_disabled(self):
        """Email ingestion is disabled by default when env var is not set."""
        from config import Settings
        # Temporarily remove the env var set at module level
        old_val = os.environ.pop("EMAIL_INGESTION_ENABLED", None)
        try:
            s = Settings(api_keys=["test"])
            assert s.email_ingestion_enabled is False
        finally:
            if old_val is not None:
                os.environ["EMAIL_INGESTION_ENABLED"] = old_val

    def test_email_ingestion_can_be_enabled(self):
        """Email ingestion can be enabled via settings."""
        from config import Settings
        s = Settings(api_keys=["test"], email_ingestion_enabled=True)
        assert s.email_ingestion_enabled is True
