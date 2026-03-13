"""
TicketForge — Test suite for enterprise features
Tests for RBAC, audit logging, bulk analysis, analytics, SLA tracking, and data export.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge.db"

from main import app, lifespan, compute_sla  # noqa: E402
from models import (  # noqa: E402
    AutomationOpportunity,
    AutomationSuggestionType,
    BulkAnalyseRequest,
    CategoryResult,
    EnrichedTicket,
    ExportFormat,
    Priority,
    PriorityResult,
    Role,
    RootCauseHypothesis,
    RoutingResult,
    SLAStatus,
    TicketSource,
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
        os.remove("./test_ticketforge.db")
    except FileNotFoundError:
        pass


# ── RBAC tests ────────────────────────────────────────────────────────────────

class TestRBAC:
    """Test role-based access control."""

    @pytest.mark.asyncio
    async def test_no_api_key_returns_422(self, client):
        """Missing API key header returns 422 (unprocessable)."""
        response = await client.get("/tickets/some-id")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_401(self, client):
        """Invalid API key returns 401."""
        response = await client.get(
            "/tickets/some-id",
            headers={"X-Api-Key": "bad-key"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_viewer_can_access_tickets(self, client):
        """Viewer role can access GET /tickets/{id} (even if not found)."""
        response = await client.get(
            "/tickets/nonexistent",
            headers={"X-Api-Key": "viewer-key"},
        )
        # 404 means auth passed but ticket not found — that's correct
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_viewer_cannot_analyse(self, client):
        """Viewer role cannot access POST /analyse (requires analyst)."""
        response = await client.post(
            "/analyse",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "ticket": {
                    "id": "T1",
                    "title": "Test",
                },
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_cannot_access_audit_logs(self, client):
        """Viewer role cannot access GET /audit/logs (requires admin)."""
        response = await client.get(
            "/audit/logs",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_analyst_cannot_access_audit_logs(self, client):
        """Analyst role cannot access GET /audit/logs (requires admin)."""
        response = await client.get(
            "/audit/logs",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_access_audit_logs(self, client):
        """Admin role can access GET /audit/logs."""
        response = await client.get(
            "/audit/logs",
            headers={"X-Api-Key": "admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_viewer_can_access_analytics(self, client):
        """Viewer role can access GET /analytics."""
        response = await client.get(
            "/analytics",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_viewer_can_export(self, client):
        """Viewer role can access GET /export/tickets."""
        response = await client.get(
            "/export/tickets?format=json",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200


# ── SLA tests ─────────────────────────────────────────────────────────────────

class TestSLA:
    """Test SLA computation logic."""

    def test_sla_within(self):
        """Recently created critical ticket is within SLA."""
        now = datetime.now(tz=timezone.utc)
        sla = compute_sla(Priority.critical, now)
        assert sla.status == SLAStatus.within
        assert sla.breach_risk < 0.8
        assert sla.response_target_minutes == 15
        assert sla.resolution_target_minutes == 240

    def test_sla_breached(self):
        """Old critical ticket should be breached."""
        old = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        sla = compute_sla(Priority.critical, old)
        assert sla.status == SLAStatus.breached
        assert sla.breach_risk >= 1.0

    def test_sla_at_risk(self):
        """Ticket nearing SLA breach should be at_risk."""
        # For medium priority: resolution target = 1440 minutes (24h)
        # 80% of 1440 = 1152 minutes ≈ 19.2 hours
        nearly_breached = datetime.now(tz=timezone.utc) - timedelta(hours=20)
        sla = compute_sla(Priority.medium, nearly_breached)
        assert sla.status == SLAStatus.at_risk

    def test_sla_low_priority_defaults(self):
        """Low priority has longer SLA targets."""
        now = datetime.now(tz=timezone.utc)
        sla = compute_sla(Priority.low, now)
        assert sla.response_target_minutes == 480
        assert sla.resolution_target_minutes == 2880

    def test_sla_naive_datetime_handled(self):
        """Naive datetimes (no tzinfo) are handled gracefully."""
        naive = datetime.now() - timedelta(hours=1)
        sla = compute_sla(Priority.high, naive)
        assert sla.status in (SLAStatus.within, SLAStatus.at_risk, SLAStatus.breached)


# ── Analytics tests ───────────────────────────────────────────────────────────

class TestAnalytics:
    """Test analytics endpoint."""

    @pytest.mark.asyncio
    async def test_empty_analytics(self, client):
        """Analytics on empty DB returns zero counts."""
        response = await client.get(
            "/analytics",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_tickets"] == 0
        assert data["by_category"] == []
        assert data["by_priority"] == []
        assert data["avg_automation_score"] == 0.0

    @pytest.mark.asyncio
    async def test_analytics_with_custom_days(self, client):
        """Analytics endpoint accepts days parameter."""
        response = await client.get(
            "/analytics?days=7",
            headers={"X-Api-Key": "admin-key"},
        )
        assert response.status_code == 200
        assert response.json()["period_days"] == 7


# ── Export tests ──────────────────────────────────────────────────────────────

class TestExport:
    """Test export endpoint."""

    @pytest.mark.asyncio
    async def test_export_json_empty(self, client):
        """JSON export of empty DB returns empty list."""
        response = await client.get(
            "/export/tickets?format=json",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tickets"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_export_csv_empty(self, client):
        """CSV export of empty DB returns header row only."""
        response = await client.get(
            "/export/tickets?format=csv",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        lines = response.text.strip().split("\n")
        assert len(lines) == 1  # header only
        assert "id" in lines[0]


# ── Audit log tests ──────────────────────────────────────────────────────────

class TestAuditLog:
    """Test audit logging functionality."""

    @pytest.mark.asyncio
    async def test_audit_log_pagination(self, client):
        """Audit log supports pagination parameters."""
        response = await client.get(
            "/audit/logs?page=1&page_size=10",
            headers={"X-Api-Key": "admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    @pytest.mark.asyncio
    async def test_actions_are_audited(self, client):
        """API calls should produce audit log entries."""
        # Make a request that gets audited (get_ticket returns 404 but still audits)
        await client.get(
            "/tickets/test-audit-123",
            headers={"X-Api-Key": "admin-key"},
        )
        # Now check audit logs
        response = await client.get(
            "/audit/logs",
            headers={"X-Api-Key": "admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1


# ── Bulk analysis tests ──────────────────────────────────────────────────────

class TestBulkAnalysis:
    """Test bulk analysis endpoint."""

    @pytest.mark.asyncio
    async def test_bulk_requires_analyst_role(self, client):
        """Viewer cannot use bulk analysis."""
        response = await client.post(
            "/analyse/bulk",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "tickets": [{"id": "T1", "title": "Test"}],
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_bulk_empty_list_rejected(self, client):
        """Empty ticket list is rejected by validation."""
        response = await client.post(
            "/analyse/bulk",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "tickets": [],
            },
        )
        assert response.status_code == 422


# ── Health check test ─────────────────────────────────────────────────────────

class TestHealth:
    """Test health endpoint (no auth required)."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Health endpoint returns ok status."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["db_ok"] is True


# ── Model tests ──────────────────────────────────────────────────────────────

class TestModels:
    """Test Pydantic model validation."""

    def test_role_enum(self):
        assert Role.admin.value == "admin"
        assert Role.analyst.value == "analyst"
        assert Role.viewer.value == "viewer"

    def test_sla_status_enum(self):
        assert SLAStatus.within.value == "within"
        assert SLAStatus.at_risk.value == "at_risk"
        assert SLAStatus.breached.value == "breached"

    def test_export_format_enum(self):
        assert ExportFormat.json.value == "json"
        assert ExportFormat.csv.value == "csv"

    def test_bulk_analyse_request_validation(self):
        """BulkAnalyseRequest rejects more than 50 tickets."""
        tickets = [{"id": f"T{i}", "title": f"Test {i}"} for i in range(51)]
        with pytest.raises(Exception):
            BulkAnalyseRequest(tickets=tickets)

    def test_enriched_ticket_has_sla_field(self):
        """EnrichedTicket includes SLA info by default."""
        ticket = EnrichedTicket(
            ticket_id="T1",
            source=TicketSource.generic,
            summary="Test",
            category=CategoryResult(category="Software"),
            priority=PriorityResult(priority=Priority.medium, score=50),
            routing=RoutingResult(),
            automation=AutomationOpportunity(
                score=0, suggestion_type=AutomationSuggestionType.none
            ),
            root_cause=RootCauseHypothesis(),
        )
        assert ticket.sla is not None
        assert ticket.sla.status == SLAStatus.within
