"""
TicketForge — Test suite for Phase 4 features
Tests for CSAT Surveys, WebSocket Notifications, and Internationalisation (i18n).
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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase4.db"
os.environ["CSAT_ENABLED"] = "true"
os.environ["WEBSOCKET_NOTIFICATIONS_ENABLED"] = "true"
os.environ["I18N_ENABLED"] = "true"
os.environ["CHATBOT_ENABLED"] = "true"
os.environ["PORTAL_ENABLED"] = "true"
os.environ["MONITORING_ENABLED"] = "true"

from main import app, lifespan, ws_manager  # noqa: E402
from models import (  # noqa: E402
    CSATAnalyticsResponse,
    CSATRecord,
    CSATResponse,
    CSATSubmission,
    WebSocketEvent,
)


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
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


async def _create_test_ticket(client: AsyncClient, ticket_id: str = "TEST-001") -> None:
    """Insert a test ticket into the database via the portal endpoint."""
    await client.post(
        "/portal/tickets",
        headers={"X-Api-Key": "viewer-key"},
        json={
            "title": f"Test ticket {ticket_id}",
            "description": "Test description for CSAT testing",
            "reporter_email": "test@example.com",
        },
    )


# ── CSAT Survey tests ────────────────────────────────────────────────────────

class TestCSATSubmit:
    """Test the POST /tickets/{ticket_id}/csat endpoint."""

    @pytest.mark.asyncio
    async def test_submit_csat_rating(self, client):
        """Submit a CSAT rating for a resolved ticket."""
        # Create a ticket first
        portal_resp = await client.post(
            "/portal/tickets",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "title": "CSAT test ticket",
                "description": "Testing CSAT submission",
                "reporter_email": "user@example.com",
            },
        )
        ticket_id = portal_resp.json()["ticket_id"]

        response = await client.post(
            f"/tickets/{ticket_id}/csat",
            headers={"X-Api-Key": "viewer-key"},
            json={"rating": 5, "comment": "Excellent support!", "reporter_email": "user@example.com"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["ticket_id"] == ticket_id
        assert data["data"]["rating"] == 5
        assert data["data"]["comment"] == "Excellent support!"

    @pytest.mark.asyncio
    async def test_submit_csat_minimal(self, client):
        """Submit a CSAT rating with just a rating (no comment)."""
        portal_resp = await client.post(
            "/portal/tickets",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "title": "Minimal CSAT test",
                "description": "Test",
                "reporter_email": "user@example.com",
            },
        )
        ticket_id = portal_resp.json()["ticket_id"]

        response = await client.post(
            f"/tickets/{ticket_id}/csat",
            headers={"X-Api-Key": "viewer-key"},
            json={"rating": 3},
        )
        assert response.status_code == 201
        assert response.json()["data"]["rating"] == 3
        assert response.json()["data"]["comment"] == ""

    @pytest.mark.asyncio
    async def test_submit_csat_invalid_rating_too_low(self, client):
        """Reject a CSAT rating below 1."""
        portal_resp = await client.post(
            "/portal/tickets",
            headers={"X-Api-Key": "viewer-key"},
            json={"title": "Test", "description": "", "reporter_email": "u@e.com"},
        )
        ticket_id = portal_resp.json()["ticket_id"]

        response = await client.post(
            f"/tickets/{ticket_id}/csat",
            headers={"X-Api-Key": "viewer-key"},
            json={"rating": 0},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_csat_invalid_rating_too_high(self, client):
        """Reject a CSAT rating above 5."""
        portal_resp = await client.post(
            "/portal/tickets",
            headers={"X-Api-Key": "viewer-key"},
            json={"title": "Test", "description": "", "reporter_email": "u@e.com"},
        )
        ticket_id = portal_resp.json()["ticket_id"]

        response = await client.post(
            f"/tickets/{ticket_id}/csat",
            headers={"X-Api-Key": "viewer-key"},
            json={"rating": 6},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_csat_ticket_not_found(self, client):
        """Reject CSAT for a non-existent ticket."""
        response = await client.post(
            "/tickets/NONEXISTENT/csat",
            headers={"X-Api-Key": "viewer-key"},
            json={"rating": 4},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_submit_csat_requires_auth(self, client):
        """CSAT submission requires authentication."""
        response = await client.post(
            "/tickets/SOME-ID/csat",
            json={"rating": 5},
        )
        assert response.status_code == 422  # Missing header

    @pytest.mark.asyncio
    async def test_submit_csat_update_existing(self, client):
        """Submitting a second CSAT for the same ticket replaces the first."""
        portal_resp = await client.post(
            "/portal/tickets",
            headers={"X-Api-Key": "viewer-key"},
            json={"title": "Update CSAT test", "description": "", "reporter_email": "u@e.com"},
        )
        ticket_id = portal_resp.json()["ticket_id"]

        # First rating
        await client.post(
            f"/tickets/{ticket_id}/csat",
            headers={"X-Api-Key": "viewer-key"},
            json={"rating": 2, "comment": "Bad"},
        )

        # Second rating (replaces)
        response = await client.post(
            f"/tickets/{ticket_id}/csat",
            headers={"X-Api-Key": "viewer-key"},
            json={"rating": 5, "comment": "Actually great!"},
        )
        assert response.status_code == 201
        assert response.json()["data"]["rating"] == 5
        assert response.json()["data"]["comment"] == "Actually great!"


class TestCSATGet:
    """Test the GET /tickets/{ticket_id}/csat endpoint."""

    @pytest.mark.asyncio
    async def test_get_csat_existing(self, client):
        """Retrieve an existing CSAT rating."""
        portal_resp = await client.post(
            "/portal/tickets",
            headers={"X-Api-Key": "viewer-key"},
            json={"title": "Get CSAT test", "description": "", "reporter_email": "u@e.com"},
        )
        ticket_id = portal_resp.json()["ticket_id"]

        await client.post(
            f"/tickets/{ticket_id}/csat",
            headers={"X-Api-Key": "viewer-key"},
            json={"rating": 4, "comment": "Good service"},
        )

        response = await client.get(
            f"/tickets/{ticket_id}/csat",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["rating"] == 4
        assert data["data"]["comment"] == "Good service"

    @pytest.mark.asyncio
    async def test_get_csat_none_submitted(self, client):
        """Return null data when no CSAT has been submitted."""
        response = await client.get(
            "/tickets/NO-RATING-TICKET/csat",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        assert response.json()["data"] is None


class TestCSATAnalytics:
    """Test the GET /analytics/csat endpoint."""

    @pytest.mark.asyncio
    async def test_csat_analytics_empty(self, client):
        """Analytics returns zeros when no ratings exist."""
        response = await client.get(
            "/analytics/csat",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_ratings"] == 0
        assert data["average_rating"] == 0.0

    @pytest.mark.asyncio
    async def test_csat_analytics_with_data(self, client):
        """Analytics returns correct aggregates with ratings."""
        # Create tickets and submit ratings
        for i, rating in enumerate([5, 4, 3, 5, 4], start=1):
            portal_resp = await client.post(
                "/portal/tickets",
                headers={"X-Api-Key": "viewer-key"},
                json={"title": f"Analytics test {i}", "description": "", "reporter_email": "u@e.com"},
            )
            ticket_id = portal_resp.json()["ticket_id"]
            comment = f"Comment {i}" if i <= 2 else ""
            await client.post(
                f"/tickets/{ticket_id}/csat",
                headers={"X-Api-Key": "viewer-key"},
                json={"rating": rating, "comment": comment},
            )

        response = await client.get(
            "/analytics/csat",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_ratings"] == 5
        assert data["average_rating"] == 4.2
        assert data["rating_distribution"]["5"] == 2
        assert data["rating_distribution"]["4"] == 2
        assert data["rating_distribution"]["3"] == 1
        assert len(data["recent_comments"]) == 2

    @pytest.mark.asyncio
    async def test_csat_analytics_requires_analyst(self, client):
        """CSAT analytics requires analyst role."""
        response = await client.get(
            "/analytics/csat",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 403


class TestCSATFeatureGate:
    """Test CSAT feature gate when disabled."""

    @pytest.mark.asyncio
    async def test_csat_submit_disabled(self, client, monkeypatch):
        """CSAT submit returns 403 when disabled."""
        from config import settings as _s  # noqa: PLC0415
        monkeypatch.setattr(_s, "csat_enabled", False)

        response = await client.post(
            "/tickets/SOME-ID/csat",
            headers={"X-Api-Key": "viewer-key"},
            json={"rating": 5},
        )
        assert response.status_code == 403
        assert "not enabled" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_csat_get_disabled(self, client, monkeypatch):
        """CSAT get returns 403 when disabled."""
        from config import settings as _s  # noqa: PLC0415
        monkeypatch.setattr(_s, "csat_enabled", False)

        response = await client.get(
            "/tickets/SOME-ID/csat",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_csat_analytics_disabled(self, client, monkeypatch):
        """CSAT analytics returns 403 when disabled."""
        from config import settings as _s  # noqa: PLC0415
        monkeypatch.setattr(_s, "csat_enabled", False)

        response = await client.get(
            "/analytics/csat",
            headers={"X-Api-Key": "admin-key"},
        )
        assert response.status_code == 403


# ── CSAT model tests ────────────────────────────────────────────────────────

class TestCSATModels:
    """Test CSAT Pydantic models."""

    def test_csat_submission_model(self):
        """CSATSubmission validates rating range."""
        sub = CSATSubmission(rating=4, comment="Great!")
        assert sub.rating == 4
        assert sub.comment == "Great!"

    def test_csat_submission_min_rating(self):
        """CSATSubmission accepts minimum rating 1."""
        sub = CSATSubmission(rating=1)
        assert sub.rating == 1

    def test_csat_submission_max_rating(self):
        """CSATSubmission accepts maximum rating 5."""
        sub = CSATSubmission(rating=5)
        assert sub.rating == 5

    def test_csat_record_model(self):
        """CSATRecord holds full rating data."""
        rec = CSATRecord(
            id=1,
            ticket_id="T-001",
            rating=5,
            comment="Perfect!",
            reporter_email="user@example.com",
        )
        assert rec.ticket_id == "T-001"
        assert rec.rating == 5

    def test_csat_analytics_response_model(self):
        """CSATAnalyticsResponse has expected defaults."""
        resp = CSATAnalyticsResponse()
        assert resp.total_ratings == 0
        assert resp.average_rating == 0.0
        assert resp.rating_distribution == {}

    def test_websocket_event_model(self):
        """WebSocketEvent serialises correctly."""
        event = WebSocketEvent(
            event_type="ticket_created",
            ticket_id="WS-001",
            data={"priority": "high"},
        )
        assert event.event_type == "ticket_created"
        assert event.ticket_id == "WS-001"
        assert "priority" in event.data


# ── WebSocket tests ──────────────────────────────────────────────────────────

class TestWebSocketNotifications:
    """Test the /ws/notifications WebSocket endpoint."""

    @pytest.mark.asyncio
    async def test_websocket_feature_gate_config(self, client):
        """WebSocket notifications can be configured."""
        from config import settings as _s  # noqa: PLC0415
        assert _s.websocket_notifications_enabled is True

    @pytest.mark.asyncio
    async def test_websocket_endpoint_exists(self, client):
        """WebSocket endpoint is registered in the app."""
        routes = [r.path for r in app.routes]
        assert "/ws/notifications" in routes


class TestConnectionManager:
    """Test the WebSocket ConnectionManager class."""

    def test_connection_manager_initial_state(self):
        """ConnectionManager starts with zero connections."""
        from main import ConnectionManager
        mgr = ConnectionManager()
        assert mgr.active_connections == 0

    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self):
        """Broadcast with no connections does not raise."""
        from main import ConnectionManager
        mgr = ConnectionManager()
        event = WebSocketEvent(event_type="test", ticket_id="T-1")
        await mgr.broadcast(event)  # Should not raise

    def test_disconnect_missing_does_not_raise(self):
        """Disconnecting a non-existent WebSocket does not raise."""
        from main import ConnectionManager
        mgr = ConnectionManager()
        # Create a mock-like object; disconnect should safely ignore it
        mgr.disconnect(None)  # type: ignore[arg-type]
        assert mgr.active_connections == 0


# ── Internationalisation (i18n) tests ────────────────────────────────────────

class TestI18nEndpoint:
    """Test the GET /i18n/languages endpoint."""

    @pytest.mark.asyncio
    async def test_list_languages(self, client):
        """List supported languages."""
        response = await client.get(
            "/i18n/languages",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "en" in data["supported_languages"]
        assert data["supported_languages"]["en"] == "English"
        assert data["total"] > 20  # At least 20+ languages

    @pytest.mark.asyncio
    async def test_list_languages_requires_auth(self, client):
        """i18n languages endpoint requires authentication."""
        response = await client.get("/i18n/languages")
        assert response.status_code == 422  # Missing header

    @pytest.mark.asyncio
    async def test_i18n_disabled(self, client, monkeypatch):
        """i18n endpoint returns 403 when disabled."""
        from config import settings as _s  # noqa: PLC0415
        monkeypatch.setattr(_s, "i18n_enabled", False)

        response = await client.get(
            "/i18n/languages",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 403
        assert "not enabled" in response.json()["detail"].lower()


class TestI18nPrompts:
    """Test i18n prompt generation functions."""

    def test_get_language_name_known(self):
        """Known language codes return correct names."""
        from prompts import get_language_name
        assert get_language_name("en") == "English"
        assert get_language_name("fr") == "French"
        assert get_language_name("ja") == "Japanese"

    def test_get_language_name_unknown(self):
        """Unknown language codes return uppercase code."""
        from prompts import get_language_name
        assert get_language_name("xx") == "XX"

    def test_analysis_prompt_english(self):
        """English returns empty i18n instruction."""
        from prompts import get_i18n_analysis_prompt
        assert get_i18n_analysis_prompt("en") == ""

    def test_analysis_prompt_non_english(self):
        """Non-English returns language instruction."""
        from prompts import get_i18n_analysis_prompt
        result = get_i18n_analysis_prompt("fr")
        assert "French" in result
        assert "fr" in result

    def test_response_prompt_english(self):
        """English returns empty response i18n instruction."""
        from prompts import get_i18n_response_prompt
        assert get_i18n_response_prompt("en") == ""

    def test_response_prompt_non_english(self):
        """Non-English returns response language instruction."""
        from prompts import get_i18n_response_prompt
        result = get_i18n_response_prompt("de")
        assert "German" in result
        assert "de" in result

    def test_language_names_dict(self):
        """LANGUAGE_NAMES has expected entries."""
        from prompts import LANGUAGE_NAMES
        assert len(LANGUAGE_NAMES) >= 20
        assert LANGUAGE_NAMES["es"] == "Spanish"
        assert LANGUAGE_NAMES["zh"] == "Chinese"
        assert LANGUAGE_NAMES["ko"] == "Korean"


class TestI18nConfig:
    """Test i18n configuration defaults."""

    def test_i18n_enabled_default(self):
        """i18n is enabled by default."""
        from config import Settings
        s = Settings(api_keys=["test"])
        assert s.i18n_enabled is True

    def test_i18n_default_language(self):
        """Default language is English."""
        from config import Settings
        s = Settings(api_keys=["test"])
        assert s.i18n_default_language == "en"


# ── Config tests for new features ────────────────────────────────────────────

class TestPhase4Config:
    """Test configuration defaults for Phase 4 features."""

    def test_csat_enabled_default(self):
        """CSAT is enabled by default."""
        from config import Settings
        s = Settings(api_keys=["test"])
        assert s.csat_enabled is True

    def test_websocket_notifications_enabled_default(self):
        """WebSocket notifications are enabled by default."""
        from config import Settings
        s = Settings(api_keys=["test"])
        assert s.websocket_notifications_enabled is True
