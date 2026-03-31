"""
TicketForge — Test suite for Phase 2 features
Tests for AI response suggestions, duplicate ticket detection, and web dashboard.
"""
from __future__ import annotations

import json
import os

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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase2.db"

from main import app, lifespan  # noqa: E402
from models import (  # noqa: E402
    DetectDuplicatesRequest,
    DetectDuplicatesResponse,
    DuplicateCandidate,
    SuggestedResponse,
    SuggestResponseRequest,
    SuggestResponseResponse,
)


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Clean up test database
    try:
        os.remove("./test_ticketforge_phase2.db")
    except FileNotFoundError:
        pass


# ── AI Response Suggestion tests ─────────────────────────────────────────────

class TestSuggestResponse:
    """Test the POST /suggest-response endpoint."""

    @pytest.mark.asyncio
    async def test_suggest_response_requires_analyst(self, client):
        """Viewer cannot use suggest-response."""
        response = await client.post(
            "/suggest-response",
            headers={"X-Api-Key": "viewer-key"},
            json={"ticket_id": "T-1"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_suggest_response_ticket_not_found(self, client):
        """Suggest-response for nonexistent ticket returns 404."""
        response = await client.post(
            "/suggest-response",
            headers={"X-Api-Key": "analyst-key"},
            json={"ticket_id": "nonexistent"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_suggest_response_requires_ticket_id(self, client):
        """Missing ticket_id returns 422."""
        response = await client.post(
            "/suggest-response",
            headers={"X-Api-Key": "analyst-key"},
            json={},
        )
        assert response.status_code == 422

    def test_suggest_response_request_model(self):
        """SuggestResponseRequest model accepts valid data."""
        req = SuggestResponseRequest(
            ticket_id="T-100",
            additional_context="User called in to follow up",
        )
        assert req.ticket_id == "T-100"
        assert req.additional_context == "User called in to follow up"

    def test_suggest_response_request_defaults(self):
        """SuggestResponseRequest default additional_context is empty."""
        req = SuggestResponseRequest(ticket_id="T-100")
        assert req.additional_context == ""

    def test_suggested_response_model(self):
        """SuggestedResponse model fields work correctly."""
        resp = SuggestedResponse(
            ticket_id="T-100",
            subject="Re: VPN Connection Issue",
            body="Thank you for reaching out. We are looking into your VPN issue.",
            tone="empathetic",
            suggested_actions=["Check VPN client version", "Reset credentials"],
        )
        assert resp.ticket_id == "T-100"
        assert resp.subject == "Re: VPN Connection Issue"
        assert resp.tone == "empathetic"
        assert len(resp.suggested_actions) == 2

    def test_suggested_response_defaults(self):
        """SuggestedResponse defaults are sensible."""
        resp = SuggestedResponse(ticket_id="T-1")
        assert resp.subject == ""
        assert resp.body == ""
        assert resp.tone == "professional"
        assert resp.suggested_actions == []

    def test_suggest_response_response_model(self):
        """SuggestResponseResponse wraps SuggestedResponse."""
        inner = SuggestedResponse(ticket_id="T-1", subject="Test")
        resp = SuggestResponseResponse(data=inner)
        assert resp.success is True
        assert resp.data.ticket_id == "T-1"


# ── Duplicate Ticket Detection tests ─────────────────────────────────────────

class TestDuplicateDetection:
    """Test the POST /tickets/detect-duplicates endpoint."""

    @pytest.mark.asyncio
    async def test_detect_duplicates_requires_analyst(self, client):
        """Viewer cannot use detect-duplicates."""
        response = await client.post(
            "/tickets/detect-duplicates",
            headers={"X-Api-Key": "viewer-key"},
            json={"title": "VPN broken"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_detect_duplicates_ticket_not_found(self, client):
        """Detect-duplicates for nonexistent ticket_id returns 404."""
        response = await client.post(
            "/tickets/detect-duplicates",
            headers={"X-Api-Key": "analyst-key"},
            json={"ticket_id": "nonexistent"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_detect_duplicates_requires_input(self, client):
        """Empty request (no ticket_id or title) returns 422."""
        response = await client.post(
            "/tickets/detect-duplicates",
            headers={"X-Api-Key": "analyst-key"},
            json={},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_detect_duplicates_with_text_empty_db(self, client):
        """Detect-duplicates with text but empty DB returns no duplicates."""
        response = await client.post(
            "/tickets/detect-duplicates",
            headers={"X-Api-Key": "analyst-key"},
            json={"title": "VPN broken", "description": "Cannot connect to VPN"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["duplicates"] == []
        assert data["total_candidates"] == 0

    def test_detect_duplicates_request_model(self):
        """DetectDuplicatesRequest model accepts valid data."""
        req = DetectDuplicatesRequest(
            ticket_id="T-100",
            threshold=0.8,
            max_results=10,
        )
        assert req.ticket_id == "T-100"
        assert req.threshold == 0.8
        assert req.max_results == 10

    def test_detect_duplicates_request_defaults(self):
        """DetectDuplicatesRequest has sensible defaults."""
        req = DetectDuplicatesRequest()
        assert req.ticket_id == ""
        assert req.title == ""
        assert req.description == ""
        assert req.threshold == 0.75
        assert req.max_results == 5

    def test_duplicate_candidate_model(self):
        """DuplicateCandidate model works correctly."""
        candidate = DuplicateCandidate(
            ticket_id="T-200",
            title="VPN connection failure",
            similarity_score=0.92,
        )
        assert candidate.ticket_id == "T-200"
        assert candidate.similarity_score == 0.92

    def test_detect_duplicates_response_model(self):
        """DetectDuplicatesResponse wraps candidates."""
        resp = DetectDuplicatesResponse(
            query_ticket_id="T-100",
            duplicates=[
                DuplicateCandidate(ticket_id="T-101", similarity_score=0.95),
            ],
            total_candidates=1,
        )
        assert resp.success is True
        assert len(resp.duplicates) == 1
        assert resp.duplicates[0].ticket_id == "T-101"


# ── Dashboard tests ──────────────────────────────────────────────────────────

class TestDashboard:
    """Test the GET /dashboard endpoint."""

    @pytest.mark.asyncio
    async def test_dashboard_returns_html(self, client):
        """Dashboard endpoint returns HTML content."""
        response = await client.get("/dashboard")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_dashboard_contains_key_elements(self, client):
        """Dashboard HTML contains expected elements."""
        response = await client.get("/dashboard")
        html = response.text
        assert "TicketForge" in html
        assert "apiKey" in html
        assert "loadAll" in html
        assert "/analytics" in html
        assert "Tickets by Category" in html
        assert "Tickets by Priority" in html
        assert "Recent Tickets" in html
        assert "SLA Overview" in html

    @pytest.mark.asyncio
    async def test_dashboard_no_auth_required(self, client):
        """Dashboard is accessible without API key."""
        response = await client.get("/dashboard")
        assert response.status_code == 200
