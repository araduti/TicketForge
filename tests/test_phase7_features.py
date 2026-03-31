"""
TicketForge — Test suite for Phase 7 features
Tests for Scheduled Reports, Ticket Merging, Custom Fields,
Ticket Tags, and Saved Filters.
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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase7.db"
os.environ["SCHEDULED_REPORTS_ENABLED"] = "true"
os.environ["TICKET_MERGING_ENABLED"] = "true"
os.environ["CUSTOM_FIELDS_ENABLED"] = "true"
os.environ["TICKET_TAGS_ENABLED"] = "true"
os.environ["SAVED_FILTERS_ENABLED"] = "true"

from main import app, lifespan  # noqa: E402

DB_PATH = "./test_ticketforge_phase7.db"


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    from config import settings as _s  # noqa: PLC0415
    _db_path = _s.database_url.replace("sqlite+aiosqlite:///", "")
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass

    # Ensure Phase 7 feature flags are set on the singleton
    _s.scheduled_reports_enabled = True
    _s.ticket_merging_enabled = True
    _s.custom_fields_enabled = True
    _s.ticket_tags_enabled = True
    _s.saved_filters_enabled = True

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Clean up test database
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass


async def _create_test_ticket(client: AsyncClient, ticket_id: str = "MERGE-001") -> str:
    """Create a test ticket via the portal endpoint and return its ID."""
    resp = await client.post(
        "/portal/tickets",
        headers={"X-Api-Key": "viewer-key"},
        json={
            "title": f"VPN connectivity issue ({ticket_id})",
            "description": "Cannot connect to VPN from home office. Error code: 0x800.",
            "reporter_email": "test@example.com",
        },
    )
    assert resp.status_code == 200 or resp.status_code == 201
    return resp.json()["ticket_id"]


# ── Scheduled Reports Tests ─────────────────────────────────────────────────


class TestScheduledReports:
    """Test scheduled report CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_report_requires_admin(self, client: AsyncClient) -> None:
        """Creating a scheduled report requires admin role."""
        resp = await client.post(
            "/reports/schedules",
            json={"name": "Weekly Report", "frequency": "weekly", "webhook_url": "https://example.com/hook"},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_report_success(self, client: AsyncClient) -> None:
        """Admin can create a scheduled report."""
        resp = await client.post(
            "/reports/schedules",
            json={
                "name": "Weekly Analytics",
                "frequency": "weekly",
                "webhook_url": "https://example.com/webhook",
                "include_categories": True,
                "include_priorities": True,
                "include_sla": False,
                "include_csat": True,
            },
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["name"] == "Weekly Analytics"
        assert data["data"]["frequency"] == "weekly"
        assert data["data"]["webhook_url"] == "https://example.com/webhook"
        assert data["data"]["include_sla"] is False
        assert "id" in data["data"]

    @pytest.mark.asyncio
    async def test_list_reports(self, client: AsyncClient) -> None:
        """List returns created reports."""
        # Create two reports
        await client.post(
            "/reports/schedules",
            json={"name": "Daily Report", "frequency": "daily", "webhook_url": "https://example.com/d"},
            headers={"X-Api-Key": "admin-key"},
        )
        await client.post(
            "/reports/schedules",
            json={"name": "Monthly Report", "frequency": "monthly", "webhook_url": "https://example.com/m"},
            headers={"X-Api-Key": "admin-key"},
        )

        resp = await client.get(
            "/reports/schedules",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["schedules"]) >= 2

    @pytest.mark.asyncio
    async def test_delete_report(self, client: AsyncClient) -> None:
        """Admin can delete a scheduled report."""
        create_resp = await client.post(
            "/reports/schedules",
            json={"name": "Temp Report", "frequency": "weekly", "webhook_url": "https://example.com/tmp"},
            headers={"X-Api-Key": "admin-key"},
        )
        report_id = create_resp.json()["data"]["id"]

        resp = await client.delete(
            f"/reports/schedules/{report_id}",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["deleted"] == report_id

    @pytest.mark.asyncio
    async def test_delete_nonexistent_report(self, client: AsyncClient) -> None:
        """Deleting a nonexistent report returns 404."""
        resp = await client.delete(
            "/reports/schedules/nonexistent-id",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_reports_disabled(self, client: AsyncClient) -> None:
        """Reports endpoints return 403 when feature is disabled."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.scheduled_reports_enabled
        _s.scheduled_reports_enabled = False
        try:
            resp = await client.get("/reports/schedules", headers={"X-Api-Key": "viewer-key"})
            assert resp.status_code == 403
            assert "not enabled" in resp.json()["detail"].lower()
        finally:
            _s.scheduled_reports_enabled = original

    @pytest.mark.asyncio
    async def test_create_report_audit_logged(self, client: AsyncClient) -> None:
        """Creating a report generates an audit log entry."""
        await client.post(
            "/reports/schedules",
            json={"name": "Audit Test", "frequency": "daily", "webhook_url": "https://example.com/audit"},
            headers={"X-Api-Key": "admin-key"},
        )
        resp = await client.get("/audit/logs", headers={"X-Api-Key": "admin-key"})
        assert resp.status_code == 200
        actions = [e["action"] for e in resp.json()["entries"]]
        assert "create_scheduled_report" in actions

    @pytest.mark.asyncio
    async def test_create_report_validation(self, client: AsyncClient) -> None:
        """Creating a report with missing fields returns 422."""
        resp = await client.post(
            "/reports/schedules",
            json={"name": ""},
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 422


# ── Ticket Merging Tests ────────────────────────────────────────────────────


class TestTicketMerging:
    """Test ticket merge endpoint."""

    @pytest.mark.asyncio
    async def test_merge_requires_admin(self, client: AsyncClient) -> None:
        """Merging tickets requires admin role."""
        resp = await client.post(
            "/tickets/merge",
            json={"primary_ticket_id": "T1", "duplicate_ticket_ids": ["T2"]},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_merge_tickets_success(self, client: AsyncClient) -> None:
        """Admin can merge tickets."""
        tid1 = await _create_test_ticket(client, "PRIMARY-001")
        tid2 = await _create_test_ticket(client, "DUP-001")

        resp = await client.post(
            "/tickets/merge",
            json={"primary_ticket_id": tid1, "duplicate_ticket_ids": [tid2]},
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["primary_ticket_id"] == tid1
        assert tid2 in data["data"]["merged_ticket_ids"]

    @pytest.mark.asyncio
    async def test_merge_closes_duplicates(self, client: AsyncClient) -> None:
        """Merged duplicates are marked as closed."""
        tid1 = await _create_test_ticket(client, "KEEP-001")
        tid2 = await _create_test_ticket(client, "CLOSE-001")

        await client.post(
            "/tickets/merge",
            json={"primary_ticket_id": tid1, "duplicate_ticket_ids": [tid2]},
            headers={"X-Api-Key": "admin-key"},
        )

        # Check duplicate is closed
        resp = await client.get(f"/tickets/{tid2}", headers={"X-Api-Key": "viewer-key"})
        assert resp.status_code == 200
        assert resp.json()["ticket_status"] == "closed"

    @pytest.mark.asyncio
    async def test_merge_primary_not_found(self, client: AsyncClient) -> None:
        """Merging with a nonexistent primary returns 404."""
        resp = await client.post(
            "/tickets/merge",
            json={"primary_ticket_id": "NONEXISTENT", "duplicate_ticket_ids": ["T2"]},
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_merge_duplicate_not_found(self, client: AsyncClient) -> None:
        """Merging with a nonexistent duplicate returns 404."""
        tid1 = await _create_test_ticket(client, "EXISTS-001")
        resp = await client.post(
            "/tickets/merge",
            json={"primary_ticket_id": tid1, "duplicate_ticket_ids": ["NONEXISTENT"]},
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_merge_same_ticket(self, client: AsyncClient) -> None:
        """Merging a ticket with itself returns 400 (no valid duplicates)."""
        tid1 = await _create_test_ticket(client, "SELF-001")
        resp = await client.post(
            "/tickets/merge",
            json={"primary_ticket_id": tid1, "duplicate_ticket_ids": [tid1]},
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_merge_disabled(self, client: AsyncClient) -> None:
        """Merge endpoint returns 403 when feature is disabled."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.ticket_merging_enabled
        _s.ticket_merging_enabled = False
        try:
            resp = await client.post(
                "/tickets/merge",
                json={"primary_ticket_id": "T1", "duplicate_ticket_ids": ["T2"]},
                headers={"X-Api-Key": "admin-key"},
            )
            assert resp.status_code == 403
            assert "not enabled" in resp.json()["detail"].lower()
        finally:
            _s.ticket_merging_enabled = original

    @pytest.mark.asyncio
    async def test_merge_audit_logged(self, client: AsyncClient) -> None:
        """Merge operations create audit log entries."""
        tid1 = await _create_test_ticket(client, "AUDIT-PRI-001")
        tid2 = await _create_test_ticket(client, "AUDIT-DUP-001")

        await client.post(
            "/tickets/merge",
            json={"primary_ticket_id": tid1, "duplicate_ticket_ids": [tid2]},
            headers={"X-Api-Key": "admin-key"},
        )

        resp = await client.get("/audit/logs", headers={"X-Api-Key": "admin-key"})
        assert resp.status_code == 200
        actions = [e["action"] for e in resp.json()["entries"]]
        assert "merge_tickets" in actions


# ── Custom Fields Tests ──────────────────────────────────────────────────────


class TestCustomFields:
    """Test custom field CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_field_requires_admin(self, client: AsyncClient) -> None:
        """Creating a custom field requires admin role."""
        resp = await client.post(
            "/custom-fields",
            json={"name": "department", "field_type": "text"},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_field_success(self, client: AsyncClient) -> None:
        """Admin can create a custom field."""
        resp = await client.post(
            "/custom-fields",
            json={
                "name": "department",
                "field_type": "text",
                "description": "Department of the reporter",
                "required": True,
            },
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["name"] == "department"
        assert data["data"]["field_type"] == "text"
        assert data["data"]["required"] is True

    @pytest.mark.asyncio
    async def test_create_select_field(self, client: AsyncClient) -> None:
        """Admin can create a select-type field with options."""
        resp = await client.post(
            "/custom-fields",
            json={
                "name": "environment",
                "field_type": "select",
                "options": ["production", "staging", "development"],
            },
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["field_type"] == "select"
        assert "production" in data["data"]["options"]

    @pytest.mark.asyncio
    async def test_create_duplicate_field(self, client: AsyncClient) -> None:
        """Creating a field with a duplicate name returns 409."""
        await client.post(
            "/custom-fields",
            json={"name": "unique_field", "field_type": "text"},
            headers={"X-Api-Key": "admin-key"},
        )
        resp = await client.post(
            "/custom-fields",
            json={"name": "unique_field", "field_type": "number"},
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_list_fields(self, client: AsyncClient) -> None:
        """List returns all created custom fields."""
        await client.post(
            "/custom-fields",
            json={"name": "field_a", "field_type": "text"},
            headers={"X-Api-Key": "admin-key"},
        )
        await client.post(
            "/custom-fields",
            json={"name": "field_b", "field_type": "boolean"},
            headers={"X-Api-Key": "admin-key"},
        )

        resp = await client.get("/custom-fields", headers={"X-Api-Key": "viewer-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        names = [f["name"] for f in data["fields"]]
        assert "field_a" in names
        assert "field_b" in names

    @pytest.mark.asyncio
    async def test_fields_disabled(self, client: AsyncClient) -> None:
        """Custom fields endpoints return 403 when disabled."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.custom_fields_enabled
        _s.custom_fields_enabled = False
        try:
            resp = await client.get("/custom-fields", headers={"X-Api-Key": "viewer-key"})
            assert resp.status_code == 403
            assert "not enabled" in resp.json()["detail"].lower()
        finally:
            _s.custom_fields_enabled = original

    @pytest.mark.asyncio
    async def test_create_field_audit_logged(self, client: AsyncClient) -> None:
        """Creating a custom field generates an audit log entry."""
        await client.post(
            "/custom-fields",
            json={"name": "audit_test_field", "field_type": "text"},
            headers={"X-Api-Key": "admin-key"},
        )
        resp = await client.get("/audit/logs", headers={"X-Api-Key": "admin-key"})
        assert resp.status_code == 200
        actions = [e["action"] for e in resp.json()["entries"]]
        assert "create_custom_field" in actions


# ── Ticket Tags Tests ───────────────────────────────────────────────────────


class TestTicketTags:
    """Test ticket tagging endpoints."""

    @pytest.mark.asyncio
    async def test_add_tags_requires_analyst(self, client: AsyncClient) -> None:
        """Adding tags requires analyst or admin role."""
        resp = await client.post(
            "/tickets/TEST-001/tags",
            json={"tags": ["urgent"]},
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_add_tags_success(self, client: AsyncClient) -> None:
        """Analyst can add tags to a ticket."""
        tid = await _create_test_ticket(client, "TAG-001")
        resp = await client.post(
            f"/tickets/{tid}/tags",
            json={"tags": ["urgent", "VPN", "networking"]},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["ticket_id"] == tid
        assert "urgent" in data["tags"]
        assert "vpn" in data["tags"]  # normalised to lowercase
        assert "networking" in data["tags"]

    @pytest.mark.asyncio
    async def test_get_tags(self, client: AsyncClient) -> None:
        """Get tags for a ticket."""
        tid = await _create_test_ticket(client, "TAG-002")
        await client.post(
            f"/tickets/{tid}/tags",
            json={"tags": ["network", "critical"]},
            headers={"X-Api-Key": "analyst-key"},
        )

        resp = await client.get(f"/tickets/{tid}/tags", headers={"X-Api-Key": "viewer-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert "network" in data["tags"]
        assert "critical" in data["tags"]

    @pytest.mark.asyncio
    async def test_remove_tag(self, client: AsyncClient) -> None:
        """Analyst can remove a tag from a ticket."""
        tid = await _create_test_ticket(client, "TAG-003")
        await client.post(
            f"/tickets/{tid}/tags",
            json={"tags": ["removeme", "keepme"]},
            headers={"X-Api-Key": "analyst-key"},
        )

        resp = await client.delete(
            f"/tickets/{tid}/tags/removeme",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify tag was removed
        resp = await client.get(f"/tickets/{tid}/tags", headers={"X-Api-Key": "viewer-key"})
        assert "removeme" not in resp.json()["tags"]
        assert "keepme" in resp.json()["tags"]

    @pytest.mark.asyncio
    async def test_add_duplicate_tags(self, client: AsyncClient) -> None:
        """Adding duplicate tags is silently ignored."""
        tid = await _create_test_ticket(client, "TAG-004")
        await client.post(
            f"/tickets/{tid}/tags",
            json={"tags": ["dup"]},
            headers={"X-Api-Key": "analyst-key"},
        )
        resp = await client.post(
            f"/tickets/{tid}/tags",
            json={"tags": ["dup"]},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        # Should only have one instance
        assert resp.json()["tags"].count("dup") == 1

    @pytest.mark.asyncio
    async def test_tags_ticket_not_found(self, client: AsyncClient) -> None:
        """Adding tags to a nonexistent ticket returns 404."""
        resp = await client.post(
            "/tickets/NONEXISTENT/tags",
            json={"tags": ["test"]},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_remove_nonexistent_tag(self, client: AsyncClient) -> None:
        """Removing a tag that doesn't exist returns 404."""
        tid = await _create_test_ticket(client, "TAG-005")
        resp = await client.delete(
            f"/tickets/{tid}/tags/nonexistent",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_tags_disabled(self, client: AsyncClient) -> None:
        """Tags endpoints return 403 when feature is disabled."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.ticket_tags_enabled
        _s.ticket_tags_enabled = False
        try:
            resp = await client.post(
                "/tickets/T1/tags",
                json={"tags": ["test"]},
                headers={"X-Api-Key": "analyst-key"},
            )
            assert resp.status_code == 403
            assert "not enabled" in resp.json()["detail"].lower()
        finally:
            _s.ticket_tags_enabled = original

    @pytest.mark.asyncio
    async def test_tags_audit_logged(self, client: AsyncClient) -> None:
        """Tag operations create audit log entries."""
        tid = await _create_test_ticket(client, "TAG-AUDIT-001")
        await client.post(
            f"/tickets/{tid}/tags",
            json={"tags": ["audit-test"]},
            headers={"X-Api-Key": "analyst-key"},
        )
        resp = await client.get("/audit/logs", headers={"X-Api-Key": "admin-key"})
        assert resp.status_code == 200
        actions = [e["action"] for e in resp.json()["entries"]]
        assert "add_tags" in actions

    @pytest.mark.asyncio
    async def test_tag_normalisation(self, client: AsyncClient) -> None:
        """Tags are normalised to lowercase."""
        tid = await _create_test_ticket(client, "TAG-NORM-001")
        resp = await client.post(
            f"/tickets/{tid}/tags",
            json={"tags": ["UPPERCASE", "MiXeD"]},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        assert "uppercase" in resp.json()["tags"]
        assert "mixed" in resp.json()["tags"]


# ── Saved Filters Tests ──────────────────────────────────────────────────────


class TestSavedFilters:
    """Test saved filter CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_filter_requires_analyst(self, client: AsyncClient) -> None:
        """Creating a filter requires analyst or admin role."""
        resp = await client.post(
            "/filters",
            json={"name": "My Filter", "filter_criteria": {"priority": "high"}},
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_filter_success(self, client: AsyncClient) -> None:
        """Analyst can create a saved filter."""
        resp = await client.post(
            "/filters",
            json={
                "name": "Critical Open Tickets",
                "filter_criteria": {"priority": "critical", "status": "open"},
            },
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["name"] == "Critical Open Tickets"
        assert data["data"]["filter_criteria"]["priority"] == "critical"
        assert "id" in data["data"]

    @pytest.mark.asyncio
    async def test_list_filters(self, client: AsyncClient) -> None:
        """List returns all saved filters."""
        await client.post(
            "/filters",
            json={"name": "Filter A", "filter_criteria": {"category": "network"}},
            headers={"X-Api-Key": "analyst-key"},
        )
        await client.post(
            "/filters",
            json={"name": "Filter B", "filter_criteria": {"status": "closed"}},
            headers={"X-Api-Key": "analyst-key"},
        )

        resp = await client.get("/filters", headers={"X-Api-Key": "viewer-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        names = [f["name"] for f in data["filters"]]
        assert "Filter A" in names
        assert "Filter B" in names

    @pytest.mark.asyncio
    async def test_delete_filter(self, client: AsyncClient) -> None:
        """Admin can delete a saved filter."""
        create_resp = await client.post(
            "/filters",
            json={"name": "Temp Filter", "filter_criteria": {}},
            headers={"X-Api-Key": "analyst-key"},
        )
        filter_id = create_resp.json()["data"]["id"]

        resp = await client.delete(
            f"/filters/{filter_id}",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_filter(self, client: AsyncClient) -> None:
        """Deleting a nonexistent filter returns 404."""
        resp = await client.delete(
            "/filters/nonexistent-id",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_filters_disabled(self, client: AsyncClient) -> None:
        """Filter endpoints return 403 when feature is disabled."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.saved_filters_enabled
        _s.saved_filters_enabled = False
        try:
            resp = await client.get("/filters", headers={"X-Api-Key": "viewer-key"})
            assert resp.status_code == 403
            assert "not enabled" in resp.json()["detail"].lower()
        finally:
            _s.saved_filters_enabled = original

    @pytest.mark.asyncio
    async def test_filter_complex_criteria(self, client: AsyncClient) -> None:
        """Filters support complex criteria with multiple conditions."""
        resp = await client.post(
            "/filters",
            json={
                "name": "Complex Filter",
                "filter_criteria": {
                    "priority": "high",
                    "status": "open",
                    "category": "network",
                    "tags": ["vpn", "urgent"],
                    "date_from": "2024-01-01",
                },
            },
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        criteria = resp.json()["data"]["filter_criteria"]
        assert criteria["priority"] == "high"
        assert criteria["tags"] == ["vpn", "urgent"]

    @pytest.mark.asyncio
    async def test_filter_audit_logged(self, client: AsyncClient) -> None:
        """Filter operations create audit log entries."""
        await client.post(
            "/filters",
            json={"name": "Audit Filter", "filter_criteria": {}},
            headers={"X-Api-Key": "analyst-key"},
        )
        resp = await client.get("/audit/logs", headers={"X-Api-Key": "admin-key"})
        assert resp.status_code == 200
        actions = [e["action"] for e in resp.json()["entries"]]
        assert "create_saved_filter" in actions

    @pytest.mark.asyncio
    async def test_delete_filter_requires_admin(self, client: AsyncClient) -> None:
        """Deleting a saved filter requires admin role."""
        create_resp = await client.post(
            "/filters",
            json={"name": "Admin Delete Test", "filter_criteria": {}},
            headers={"X-Api-Key": "analyst-key"},
        )
        filter_id = create_resp.json()["data"]["id"]

        resp = await client.delete(
            f"/filters/{filter_id}",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 403


# ── Integration Tests ────────────────────────────────────────────────────────


class TestPhase7Integration:
    """Cross-feature integration tests for Phase 7."""

    @pytest.mark.asyncio
    async def test_merge_and_tags_integration(self, client: AsyncClient) -> None:
        """Tags persist after merge — primary ticket retains its tags."""
        tid1 = await _create_test_ticket(client, "INT-PRI-001")
        tid2 = await _create_test_ticket(client, "INT-DUP-001")

        # Tag both tickets
        await client.post(
            f"/tickets/{tid1}/tags",
            json={"tags": ["primary-tag"]},
            headers={"X-Api-Key": "analyst-key"},
        )
        await client.post(
            f"/tickets/{tid2}/tags",
            json={"tags": ["dup-tag"]},
            headers={"X-Api-Key": "analyst-key"},
        )

        # Merge
        await client.post(
            "/tickets/merge",
            json={"primary_ticket_id": tid1, "duplicate_ticket_ids": [tid2]},
            headers={"X-Api-Key": "admin-key"},
        )

        # Primary ticket's tags still accessible
        resp = await client.get(f"/tickets/{tid1}/tags", headers={"X-Api-Key": "viewer-key"})
        assert resp.status_code == 200
        assert "primary-tag" in resp.json()["tags"]

    @pytest.mark.asyncio
    async def test_all_features_enabled(self, client: AsyncClient) -> None:
        """All Phase 7 feature endpoints respond when enabled."""
        # Reports
        resp = await client.get("/reports/schedules", headers={"X-Api-Key": "viewer-key"})
        assert resp.status_code == 200

        # Custom fields
        resp = await client.get("/custom-fields", headers={"X-Api-Key": "viewer-key"})
        assert resp.status_code == 200

        # Filters
        resp = await client.get("/filters", headers={"X-Api-Key": "viewer-key"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_still_works(self, client: AsyncClient) -> None:
        """Health endpoint is unaffected by Phase 7 changes."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
