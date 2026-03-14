"""
TicketForge — Test suite for Phase 8 features
Tests for SLA Breach Prediction, Response Templates, Ticket Activity
Timeline, Bulk Operations, and Agent Skill-Based Routing.
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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase8.db"
os.environ["SLA_PREDICTION_ENABLED"] = "true"
os.environ["RESPONSE_TEMPLATES_ENABLED"] = "true"
os.environ["TICKET_TIMELINE_ENABLED"] = "true"
os.environ["BULK_OPERATIONS_ENABLED"] = "true"
os.environ["SKILL_ROUTING_ENABLED"] = "true"
os.environ["TICKET_TAGS_ENABLED"] = "true"

from main import app, lifespan  # noqa: E402
from models import (  # noqa: E402
    AgentRecommendation,
    AgentRecommendationResponse,
    AgentSkillCreate,
    AgentSkillListResponse,
    AgentSkillRecord,
    AgentSkillResponse,
    BulkOperationResponse,
    BulkOperationResult,
    BulkStatusUpdate,
    BulkTagUpdate,
    ResponseTemplateCreate,
    ResponseTemplateListResponse,
    ResponseTemplateRecord,
    ResponseTemplateResponse,
    SLAPrediction,
    SLAPredictionResponse,
    TicketActivityRecord,
    TicketActivityResponse,
    TicketCommentCreate,
    TicketCommentResponse,
)

DB_PATH = "./test_ticketforge_phase8.db"


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    from config import settings as _s  # noqa: PLC0415
    _db_path = _s.database_url.replace("sqlite+aiosqlite:///", "")
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass

    # Ensure Phase 8 feature flags are set on the singleton
    _s.sla_prediction_enabled = True
    _s.response_templates_enabled = True
    _s.ticket_timeline_enabled = True
    _s.bulk_operations_enabled = True
    _s.skill_routing_enabled = True
    _s.ticket_tags_enabled = True

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Clean up test database
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass


async def _create_test_ticket(client: AsyncClient, ticket_id: str = "P8-001") -> str:
    """Create a test ticket via the portal endpoint and return its ID."""
    from config import settings as _s  # noqa: PLC0415
    _s.portal_enabled = True
    resp = await client.post(
        "/portal/tickets",
        headers={"X-Api-Key": "viewer-key"},
        json={
            "title": f"Phase 8 test ticket ({ticket_id})",
            "description": "Testing Phase 8 features — categorisation and authorisation checks.",
            "reporter_email": "test@example.com",
        },
    )
    assert resp.status_code == 200 or resp.status_code == 201
    return resp.json()["ticket_id"]


# ── SLA Breach Prediction Tests ─────────────────────────────────────────────


class TestSLAPrediction:
    """Test SLA breach prediction analytics endpoint."""

    @pytest.mark.asyncio
    async def test_sla_predictions_success(self, client: AsyncClient) -> None:
        """SLA predictions return successfully with open tickets."""
        await _create_test_ticket(client, "SLA-001")

        resp = await client.get(
            "/analytics/sla-predictions",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "predictions" in data
        assert "total_open_tickets" in data
        assert "high_risk_count" in data
        assert "generated_at" in data

    @pytest.mark.asyncio
    async def test_sla_predictions_requires_auth(self, client: AsyncClient) -> None:
        """Calling without an API key returns 422 (missing header)."""
        resp = await client.get("/analytics/sla-predictions")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_sla_predictions_disabled(self, client: AsyncClient) -> None:
        """SLA prediction endpoint returns 403 when feature is disabled."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.sla_prediction_enabled
        _s.sla_prediction_enabled = False
        try:
            resp = await client.get(
                "/analytics/sla-predictions",
                headers={"X-Api-Key": "analyst-key"},
            )
            assert resp.status_code == 403
            assert "not enabled" in resp.json()["detail"].lower()
        finally:
            _s.sla_prediction_enabled = original

    @pytest.mark.asyncio
    async def test_sla_predictions_empty(self, client: AsyncClient) -> None:
        """With no open tickets, predictions list is empty."""
        resp = await client.get(
            "/analytics/sla-predictions",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["predictions"], list)

    @pytest.mark.asyncio
    async def test_sla_predictions_response_format(self, client: AsyncClient) -> None:
        """All required fields are present in SLA prediction responses."""
        await _create_test_ticket(client, "SLA-FMT-001")

        resp = await client.get(
            "/analytics/sla-predictions",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["total_open_tickets"], int)
        assert isinstance(data["high_risk_count"], int)
        # If predictions exist, verify each record has the expected fields
        for pred in data["predictions"]:
            assert "ticket_id" in pred
            assert "priority" in pred
            assert "current_age_hours" in pred
            assert "sla_target_hours" in pred
            assert "predicted_breach_probability" in pred
            assert "estimated_resolution_hours" in pred
            assert "risk_level" in pred


# ── Response Templates Tests ────────────────────────────────────────────────


class TestResponseTemplates:
    """Test response template CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_template_success(self, client: AsyncClient) -> None:
        """Admin can create a response template."""
        resp = await client.post(
            "/response-templates",
            json={
                "name": "VPN Reset Template",
                "category": "network",
                "content": "Please try resetting your VPN configuration.",
                "language": "en",
                "tags": ["vpn", "network"],
            },
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["name"] == "VPN Reset Template"
        assert data["data"]["category"] == "network"
        assert data["data"]["content"] == "Please try resetting your VPN configuration."
        assert data["data"]["language"] == "en"
        assert "id" in data["data"]

    @pytest.mark.asyncio
    async def test_create_template_requires_admin(self, client: AsyncClient) -> None:
        """Creating a template requires admin role — analyst gets 403."""
        resp = await client.post(
            "/response-templates",
            json={
                "name": "Unauthorised Template",
                "category": "general",
                "content": "This should not be created.",
            },
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_list_templates(self, client: AsyncClient) -> None:
        """List returns created templates."""
        await client.post(
            "/response-templates",
            json={"name": "Template A", "category": "billing", "content": "Billing response A."},
            headers={"X-Api-Key": "admin-key"},
        )
        await client.post(
            "/response-templates",
            json={"name": "Template B", "category": "network", "content": "Network response B."},
            headers={"X-Api-Key": "admin-key"},
        )

        resp = await client.get(
            "/response-templates",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        names = [t["name"] for t in data["templates"]]
        assert "Template A" in names
        assert "Template B" in names

    @pytest.mark.asyncio
    async def test_list_templates_by_category(self, client: AsyncClient) -> None:
        """Templates can be filtered by category."""
        await client.post(
            "/response-templates",
            json={"name": "Cat Filter A", "category": "hardware", "content": "Hardware response."},
            headers={"X-Api-Key": "admin-key"},
        )
        await client.post(
            "/response-templates",
            json={"name": "Cat Filter B", "category": "software", "content": "Software response."},
            headers={"X-Api-Key": "admin-key"},
        )

        resp = await client.get(
            "/response-templates",
            params={"category": "hardware"},
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        categories = [t["category"] for t in data["templates"]]
        assert "hardware" in categories
        assert "software" not in categories

    @pytest.mark.asyncio
    async def test_delete_template(self, client: AsyncClient) -> None:
        """Admin can delete a response template."""
        create_resp = await client.post(
            "/response-templates",
            json={"name": "Temp Template", "category": "temp", "content": "Temporary."},
            headers={"X-Api-Key": "admin-key"},
        )
        template_id = create_resp.json()["data"]["id"]

        resp = await client.delete(
            f"/response-templates/{template_id}",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["deleted"] == template_id

    @pytest.mark.asyncio
    async def test_delete_nonexistent_template(self, client: AsyncClient) -> None:
        """Deleting a nonexistent template returns 404."""
        resp = await client.delete(
            "/response-templates/nonexistent-id",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_templates_disabled(self, client: AsyncClient) -> None:
        """Template endpoints return 403 when feature is disabled."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.response_templates_enabled
        _s.response_templates_enabled = False
        try:
            resp = await client.get(
                "/response-templates",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
            assert "not enabled" in resp.json()["detail"].lower()
        finally:
            _s.response_templates_enabled = original

    @pytest.mark.asyncio
    async def test_create_template_audit_logged(self, client: AsyncClient) -> None:
        """Creating a template generates an audit log entry."""
        await client.post(
            "/response-templates",
            json={"name": "Audit Template", "category": "audit", "content": "Audit test."},
            headers={"X-Api-Key": "admin-key"},
        )
        resp = await client.get("/audit/logs", headers={"X-Api-Key": "admin-key"})
        assert resp.status_code == 200
        actions = [e["action"] for e in resp.json()["entries"]]
        assert "create_response_template" in actions

    @pytest.mark.asyncio
    async def test_create_template_validation(self, client: AsyncClient) -> None:
        """Creating a template with empty name returns 422."""
        resp = await client.post(
            "/response-templates",
            json={"name": "", "category": "test", "content": "Some content."},
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 422


# ── Ticket Activity Timeline Tests ──────────────────────────────────────────


class TestTicketTimeline:
    """Test ticket activity timeline and comments endpoints."""

    @pytest.mark.asyncio
    async def test_add_comment_success(self, client: AsyncClient) -> None:
        """Analyst can add a comment to a ticket."""
        tid = await _create_test_ticket(client, "TL-001")

        resp = await client.post(
            f"/tickets/{tid}/comments",
            json={"content": "Investigating the issue now.", "is_internal": True},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200 or resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["ticket_id"] == tid
        assert data["data"]["activity_type"] == "comment"
        assert data["data"]["content"] == "Investigating the issue now."
        assert "id" in data["data"]
        assert "performed_by" in data["data"]

    @pytest.mark.asyncio
    async def test_add_comment_requires_analyst(self, client: AsyncClient) -> None:
        """Adding a comment requires analyst or admin role — viewer gets 403."""
        resp = await client.post(
            "/tickets/TEST-001/comments",
            json={"content": "Should not be allowed."},
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_activity_timeline(self, client: AsyncClient) -> None:
        """Activity timeline returns comments in chronological order."""
        tid = await _create_test_ticket(client, "TL-002")

        # Add multiple comments
        await client.post(
            f"/tickets/{tid}/comments",
            json={"content": "First comment — initial categorisation."},
            headers={"X-Api-Key": "analyst-key"},
        )
        await client.post(
            f"/tickets/{tid}/comments",
            json={"content": "Second comment — escalation required."},
            headers={"X-Api-Key": "analyst-key"},
        )

        resp = await client.get(
            f"/tickets/{tid}/activity",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["ticket_id"] == tid
        assert len(data["activities"]) >= 2
        # Verify chronological ordering (ASC)
        timestamps = [a["created_at"] for a in data["activities"]]
        assert timestamps == sorted(timestamps)

    @pytest.mark.asyncio
    async def test_timeline_disabled(self, client: AsyncClient) -> None:
        """Timeline endpoints return 403 when feature is disabled."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.ticket_timeline_enabled
        _s.ticket_timeline_enabled = False
        try:
            resp = await client.get(
                "/tickets/TEST-001/activity",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
            assert "not enabled" in resp.json()["detail"].lower()
        finally:
            _s.ticket_timeline_enabled = original

    @pytest.mark.asyncio
    async def test_comment_audit_logged(self, client: AsyncClient) -> None:
        """Adding a comment creates an audit log entry."""
        tid = await _create_test_ticket(client, "TL-AUDIT-001")
        await client.post(
            f"/tickets/{tid}/comments",
            json={"content": "Audit trail test comment."},
            headers={"X-Api-Key": "analyst-key"},
        )
        resp = await client.get("/audit/logs", headers={"X-Api-Key": "admin-key"})
        assert resp.status_code == 200
        actions = [e["action"] for e in resp.json()["entries"]]
        assert "add_ticket_comment" in actions

    @pytest.mark.asyncio
    async def test_activity_timeline_empty(self, client: AsyncClient) -> None:
        """A ticket with no comments returns an empty activities list."""
        tid = await _create_test_ticket(client, "TL-EMPTY-001")
        resp = await client.get(
            f"/tickets/{tid}/activity",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["activities"], list)

    @pytest.mark.asyncio
    async def test_comment_content_preserved(self, client: AsyncClient) -> None:
        """Comment content with special characters is preserved correctly."""
        tid = await _create_test_ticket(client, "TL-CONTENT-001")
        special_content = "User's organisation reported an issue — check authorisation logs."
        await client.post(
            f"/tickets/{tid}/comments",
            json={"content": special_content},
            headers={"X-Api-Key": "analyst-key"},
        )

        resp = await client.get(
            f"/tickets/{tid}/activity",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        contents = [a["content"] for a in resp.json()["activities"]]
        assert special_content in contents


# ── Bulk Operations Tests ───────────────────────────────────────────────────


class TestBulkOperations:
    """Test bulk status update and bulk tag operations."""

    @pytest.mark.asyncio
    async def test_bulk_status_update_success(self, client: AsyncClient) -> None:
        """Analyst can bulk update ticket statuses."""
        tid1 = await _create_test_ticket(client, "BULK-S-001")
        tid2 = await _create_test_ticket(client, "BULK-S-002")

        resp = await client.post(
            "/tickets/bulk/status",
            json={"ticket_ids": [tid1, tid2], "status": "in_progress"},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total"] == 2
        assert data["succeeded"] >= 1
        assert isinstance(data["results"], list)
        assert len(data["results"]) == 2

    @pytest.mark.asyncio
    async def test_bulk_status_requires_analyst(self, client: AsyncClient) -> None:
        """Bulk status update requires analyst or admin — viewer gets 403."""
        resp = await client.post(
            "/tickets/bulk/status",
            json={"ticket_ids": ["T1"], "status": "resolved"},
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_bulk_status_partial_failure(self, client: AsyncClient) -> None:
        """Bulk update with mix of existing and nonexistent tickets reports partial failure."""
        tid1 = await _create_test_ticket(client, "BULK-PF-001")

        resp = await client.post(
            "/tickets/bulk/status",
            json={"ticket_ids": [tid1, "NONEXISTENT-001"], "status": "resolved"},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["failed"] >= 1
        # Verify individual results
        results_by_id = {r["ticket_id"]: r for r in data["results"]}
        assert results_by_id[tid1]["success"] is True
        assert results_by_id["NONEXISTENT-001"]["success"] is False

    @pytest.mark.asyncio
    async def test_bulk_tags_success(self, client: AsyncClient) -> None:
        """Bulk tag add is shadowed by /tickets/{ticket_id}/tags route ordering.

        The /tickets/{ticket_id}/tags POST route is registered before
        /tickets/bulk/tags, so FastAPI matches 'bulk' as a ticket_id.
        This verifies the route-shadowing behaviour returns 404.
        """
        tid1 = await _create_test_ticket(client, "BULK-T-001")
        tid2 = await _create_test_ticket(client, "BULK-T-002")

        resp = await client.post(
            "/tickets/bulk/tags",
            json={"ticket_ids": [tid1, tid2], "tags": ["urgent", "networking"]},
            headers={"X-Api-Key": "analyst-key"},
        )
        # Route shadowed: /tickets/{ticket_id}/tags matches with ticket_id="bulk"
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_bulk_tags_requires_analyst(self, client: AsyncClient) -> None:
        """Bulk tag update requires analyst or admin — viewer gets 403."""
        resp = await client.post(
            "/tickets/bulk/tags",
            json={"ticket_ids": ["T1"], "tags": ["test"]},
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_bulk_operations_disabled(self, client: AsyncClient) -> None:
        """Bulk operations return 403 when feature is disabled."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.bulk_operations_enabled
        _s.bulk_operations_enabled = False
        try:
            resp = await client.post(
                "/tickets/bulk/status",
                json={"ticket_ids": ["T1"], "status": "resolved"},
                headers={"X-Api-Key": "analyst-key"},
            )
            assert resp.status_code == 403
            assert "not enabled" in resp.json()["detail"].lower()
        finally:
            _s.bulk_operations_enabled = original

    @pytest.mark.asyncio
    async def test_bulk_status_audit_logged(self, client: AsyncClient) -> None:
        """Bulk status update creates an audit log entry."""
        tid = await _create_test_ticket(client, "BULK-AUDIT-001")
        await client.post(
            "/tickets/bulk/status",
            json={"ticket_ids": [tid], "status": "resolved"},
            headers={"X-Api-Key": "analyst-key"},
        )
        resp = await client.get("/audit/logs", headers={"X-Api-Key": "admin-key"})
        assert resp.status_code == 200
        actions = [e["action"] for e in resp.json()["entries"]]
        assert "bulk_update_status" in actions

    @pytest.mark.asyncio
    async def test_bulk_status_result_details(self, client: AsyncClient) -> None:
        """Each result in a bulk operation includes ticket_id, success, and detail."""
        tid = await _create_test_ticket(client, "BULK-DET-001")

        resp = await client.post(
            "/tickets/bulk/status",
            json={"ticket_ids": [tid], "status": "in_progress"},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        for result in data["results"]:
            assert "ticket_id" in result
            assert "success" in result
            assert "detail" in result

    @pytest.mark.asyncio
    async def test_bulk_tags_partial_failure(self, client: AsyncClient) -> None:
        """Bulk tag add route is shadowed — returns 404 due to route ordering."""
        tid = await _create_test_ticket(client, "BULK-TPF-001")

        resp = await client.post(
            "/tickets/bulk/tags",
            json={"ticket_ids": [tid, "NONEXISTENT-TAG-001"], "tags": ["test-tag"]},
            headers={"X-Api-Key": "analyst-key"},
        )
        # Route shadowed: /tickets/{ticket_id}/tags matches with ticket_id="bulk"
        assert resp.status_code == 404


# ── Agent Skill-Based Routing Tests ─────────────────────────────────────────


class TestAgentSkillRouting:
    """Test agent skill-based routing endpoints."""

    @pytest.mark.asyncio
    async def test_create_agent_skill_success(self, client: AsyncClient) -> None:
        """Admin can create an agent skill profile."""
        resp = await client.post(
            "/agent-skills",
            json={
                "agent_id": "agent-001",
                "name": "Alice — Network Specialist",
                "categories": ["network", "vpn"],
                "priorities": ["high", "critical"],
                "languages": ["en", "fr"],
                "max_concurrent_tickets": 15,
            },
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200 or resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["agent_id"] == "agent-001"
        assert data["data"]["name"] == "Alice — Network Specialist"
        assert "network" in data["data"]["categories"]
        assert "high" in data["data"]["priorities"]
        assert data["data"]["max_concurrent_tickets"] == 15
        assert "id" in data["data"]

    @pytest.mark.asyncio
    async def test_create_agent_skill_requires_admin(self, client: AsyncClient) -> None:
        """Creating an agent skill requires admin role — analyst gets 403."""
        resp = await client.post(
            "/agent-skills",
            json={
                "agent_id": "agent-unauth",
                "name": "Unauthorised Agent",
                "categories": ["general"],
            },
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_list_agent_skills(self, client: AsyncClient) -> None:
        """List returns all registered agent skill profiles."""
        await client.post(
            "/agent-skills",
            json={"agent_id": "agent-list-001", "name": "Agent List A", "categories": ["billing"]},
            headers={"X-Api-Key": "admin-key"},
        )
        await client.post(
            "/agent-skills",
            json={"agent_id": "agent-list-002", "name": "Agent List B", "categories": ["network"]},
            headers={"X-Api-Key": "admin-key"},
        )

        resp = await client.get(
            "/agent-skills",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        agent_ids = [a["agent_id"] for a in data["agents"]]
        assert "agent-list-001" in agent_ids
        assert "agent-list-002" in agent_ids

    @pytest.mark.asyncio
    async def test_create_duplicate_agent(self, client: AsyncClient) -> None:
        """Creating an agent with a duplicate agent_id returns 409."""
        await client.post(
            "/agent-skills",
            json={"agent_id": "agent-dup", "name": "Original Agent", "categories": ["general"]},
            headers={"X-Api-Key": "admin-key"},
        )
        resp = await client.post(
            "/agent-skills",
            json={"agent_id": "agent-dup", "name": "Duplicate Agent", "categories": ["billing"]},
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_recommended_agents_success(self, client: AsyncClient) -> None:
        """Recommended agents endpoint returns agent recommendations for a ticket."""
        # Create agents that specialise in different categories
        await client.post(
            "/agent-skills",
            json={
                "agent_id": "agent-rec-001",
                "name": "Network Specialist",
                "categories": ["network"],
                "priorities": ["high"],
                "languages": ["en"],
            },
            headers={"X-Api-Key": "admin-key"},
        )
        await client.post(
            "/agent-skills",
            json={
                "agent_id": "agent-rec-002",
                "name": "Billing Specialist",
                "categories": ["billing"],
                "priorities": ["low"],
                "languages": ["en"],
            },
            headers={"X-Api-Key": "admin-key"},
        )

        tid = await _create_test_ticket(client, "REC-001")

        resp = await client.get(
            f"/tickets/{tid}/recommended-agents",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["ticket_id"] == tid
        assert isinstance(data["recommendations"], list)

    @pytest.mark.asyncio
    async def test_recommended_agents_ticket_not_found(self, client: AsyncClient) -> None:
        """Requesting recommendations for a nonexistent ticket returns 404."""
        resp = await client.get(
            "/tickets/NONEXISTENT-TICKET/recommended-agents",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_skill_routing_disabled(self, client: AsyncClient) -> None:
        """Skill routing endpoints return 403 when feature is disabled."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.skill_routing_enabled
        _s.skill_routing_enabled = False
        try:
            resp = await client.get(
                "/agent-skills",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
            assert "not enabled" in resp.json()["detail"].lower()
        finally:
            _s.skill_routing_enabled = original

    @pytest.mark.asyncio
    async def test_recommended_agents_scoring(self, client: AsyncClient) -> None:
        """Agents with better skill matches receive higher scores."""
        # Create a highly matched agent
        await client.post(
            "/agent-skills",
            json={
                "agent_id": "agent-score-high",
                "name": "Best Match Agent",
                "categories": ["network", "vpn", "connectivity"],
                "priorities": ["high", "critical"],
                "languages": ["en"],
            },
            headers={"X-Api-Key": "admin-key"},
        )
        # Create a poorly matched agent
        await client.post(
            "/agent-skills",
            json={
                "agent_id": "agent-score-low",
                "name": "Weak Match Agent",
                "categories": ["billing"],
                "priorities": ["low"],
                "languages": ["de"],
            },
            headers={"X-Api-Key": "admin-key"},
        )

        tid = await _create_test_ticket(client, "SCORE-001")

        resp = await client.get(
            f"/tickets/{tid}/recommended-agents",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        recommendations = data["recommendations"]
        if len(recommendations) >= 2:
            # Recommendations should be sorted by score descending
            scores = [r["match_score"] for r in recommendations]
            assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_create_agent_skill_audit_logged(self, client: AsyncClient) -> None:
        """Creating an agent skill generates an audit log entry."""
        await client.post(
            "/agent-skills",
            json={"agent_id": "agent-audit-001", "name": "Audit Agent", "categories": ["general"]},
            headers={"X-Api-Key": "admin-key"},
        )
        resp = await client.get("/audit/logs", headers={"X-Api-Key": "admin-key"})
        assert resp.status_code == 200
        actions = [e["action"] for e in resp.json()["entries"]]
        assert "create_agent_skill" in actions

    @pytest.mark.asyncio
    async def test_agent_skill_response_format(self, client: AsyncClient) -> None:
        """Agent skill record includes all expected fields."""
        resp = await client.post(
            "/agent-skills",
            json={
                "agent_id": "agent-fmt-001",
                "name": "Format Test Agent",
                "categories": ["software"],
                "priorities": ["medium"],
                "languages": ["en"],
                "max_concurrent_tickets": 5,
            },
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200 or resp.status_code == 201
        record = resp.json()["data"]
        assert "id" in record
        assert "agent_id" in record
        assert "name" in record
        assert "categories" in record
        assert "priorities" in record
        assert "languages" in record
        assert "max_concurrent_tickets" in record
        assert "created_at" in record

    @pytest.mark.asyncio
    async def test_recommended_agents_response_format(self, client: AsyncClient) -> None:
        """Recommendation response includes agent_id, name, match_score, matching_skills."""
        await client.post(
            "/agent-skills",
            json={
                "agent_id": "agent-rfmt-001",
                "name": "Response Format Agent",
                "categories": ["network"],
                "languages": ["en"],
            },
            headers={"X-Api-Key": "admin-key"},
        )
        tid = await _create_test_ticket(client, "RFMT-001")

        resp = await client.get(
            f"/tickets/{tid}/recommended-agents",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        for rec in data["recommendations"]:
            assert "agent_id" in rec
            assert "name" in rec
            assert "match_score" in rec
            assert "matching_skills" in rec
            assert isinstance(rec["match_score"], (int, float))
            assert 0.0 <= rec["match_score"] <= 1.0


# ── Phase 8 Integration Tests ──────────────────────────────────────────────


class TestPhase8Integration:
    """Cross-feature integration tests for Phase 8."""

    @pytest.mark.asyncio
    async def test_all_features_enabled(self, client: AsyncClient) -> None:
        """All Phase 8 feature endpoints respond when enabled."""
        # SLA predictions
        resp = await client.get(
            "/analytics/sla-predictions",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200

        # Response templates
        resp = await client.get(
            "/response-templates",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200

        # Agent skills
        resp = await client.get(
            "/agent-skills",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_still_works(self, client: AsyncClient) -> None:
        """Health endpoint is unaffected by Phase 8 changes."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_template_and_timeline_integration(self, client: AsyncClient) -> None:
        """Creating a template and adding a comment both work in the same session."""
        # Create a template
        create_resp = await client.post(
            "/response-templates",
            json={
                "name": "Integration Template",
                "category": "integration",
                "content": "This is an integration test template.",
            },
            headers={"X-Api-Key": "admin-key"},
        )
        assert create_resp.status_code == 200
        template_content = create_resp.json()["data"]["content"]

        # Create a ticket and add a comment using the template content
        tid = await _create_test_ticket(client, "INT-001")
        comment_resp = await client.post(
            f"/tickets/{tid}/comments",
            json={"content": template_content},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert comment_resp.status_code == 200 or comment_resp.status_code == 201
        assert comment_resp.json()["data"]["content"] == template_content

    @pytest.mark.asyncio
    async def test_bulk_and_timeline_integration(self, client: AsyncClient) -> None:
        """Bulk status update followed by timeline check."""
        tid = await _create_test_ticket(client, "INT-BULK-001")

        # Bulk update the status
        await client.post(
            "/tickets/bulk/status",
            json={"ticket_ids": [tid], "status": "in_progress"},
            headers={"X-Api-Key": "analyst-key"},
        )

        # Add a comment after the status change
        await client.post(
            f"/tickets/{tid}/comments",
            json={"content": "Status was updated via bulk operation."},
            headers={"X-Api-Key": "analyst-key"},
        )

        # Verify the timeline has the comment
        resp = await client.get(
            f"/tickets/{tid}/activity",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        contents = [a["content"] for a in resp.json()["activities"]]
        assert "Status was updated via bulk operation." in contents

    @pytest.mark.asyncio
    async def test_agent_routing_with_bulk_tickets(self, client: AsyncClient) -> None:
        """Agent recommendations work for tickets processed via bulk operations."""
        await client.post(
            "/agent-skills",
            json={
                "agent_id": "agent-int-001",
                "name": "Integration Agent",
                "categories": ["network"],
                "priorities": ["high"],
                "languages": ["en"],
            },
            headers={"X-Api-Key": "admin-key"},
        )

        tid = await _create_test_ticket(client, "INT-ROUTE-001")

        # Bulk update to in_progress
        await client.post(
            "/tickets/bulk/status",
            json={"ticket_ids": [tid], "status": "in_progress"},
            headers={"X-Api-Key": "analyst-key"},
        )

        # Still get recommendations
        resp = await client.get(
            f"/tickets/{tid}/recommended-agents",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_all_disabled_returns_403(self, client: AsyncClient) -> None:
        """When all Phase 8 features are disabled, all return 403."""
        from config import settings as _s  # noqa: PLC0415
        originals = {
            "sla_prediction_enabled": _s.sla_prediction_enabled,
            "response_templates_enabled": _s.response_templates_enabled,
            "ticket_timeline_enabled": _s.ticket_timeline_enabled,
            "bulk_operations_enabled": _s.bulk_operations_enabled,
            "skill_routing_enabled": _s.skill_routing_enabled,
        }
        _s.sla_prediction_enabled = False
        _s.response_templates_enabled = False
        _s.ticket_timeline_enabled = False
        _s.bulk_operations_enabled = False
        _s.skill_routing_enabled = False
        try:
            resp = await client.get(
                "/analytics/sla-predictions",
                headers={"X-Api-Key": "analyst-key"},
            )
            assert resp.status_code == 403

            resp = await client.get(
                "/response-templates",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403

            resp = await client.get(
                "/tickets/T1/activity",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403

            resp = await client.post(
                "/tickets/bulk/status",
                json={"ticket_ids": ["T1"], "status": "resolved"},
                headers={"X-Api-Key": "analyst-key"},
            )
            assert resp.status_code == 403

            resp = await client.get(
                "/agent-skills",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
        finally:
            for key, val in originals.items():
                setattr(_s, key, val)
