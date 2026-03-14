"""
TicketForge — Test suite for Phase 10c features
Tests for Visual Workflow Builder, Compliance & Security Hardening,
Performance & Scale Improvements, and UX Polish.
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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase10c.db"
os.environ["WORKFLOW_BUILDER_ENABLED"] = "true"
os.environ["COMPLIANCE_ENABLED"] = "true"
os.environ["PERFORMANCE_MONITORING_ENABLED"] = "true"
os.environ["UX_PREFERENCES_ENABLED"] = "true"

from main import app, lifespan
from models import (
    AuditExportResponse,
    CacheInvalidateRequest,
    CacheInvalidateResponse,
    CacheStatsResponse,
    ConnectionPoolStatsResponse,
    DataRetentionPolicyCreate,
    DataRetentionPolicyListResponse,
    DataRetentionPolicyRecord,
    DataRetentionPolicyResponse,
    OnboardingCompleteStepRequest,
    OnboardingCompleteStepResponse,
    OnboardingStatusResponse,
    OnboardingStep,
    PerformanceMetrics,
    PerformanceMetricsResponse,
    PIIRedactRequest,
    PIIRedactResponse,
    SecurityPostureItem,
    SecurityPostureResponse,
    UserPreferences,
    UserPreferencesResponse,
    UserPreferencesUpdate,
    WorkflowCreate,
    WorkflowEdge,
    WorkflowListResponse,
    WorkflowNode,
    WorkflowRecord,
    WorkflowResponse,
    WorkflowValidationResponse,
    WorkflowValidationResult,
)

DB_PATH = "./test_ticketforge_phase10c.db"


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    from config import settings as _s

    _db_path = _s.database_url.replace("sqlite+aiosqlite:///", "")
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass

    # Ensure Phase 10c feature flags are set on the singleton
    _s.workflow_builder_enabled = True
    _s.compliance_enabled = True
    _s.performance_monitoring_enabled = True
    _s.ux_preferences_enabled = True
    _s.portal_enabled = True

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Clean up test database
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass


# ── Helper: create a test ticket via the portal ──────────────────────────────


async def _create_test_ticket(client: AsyncClient, ticket_id: str = "P10C-001") -> str:
    """Create a test ticket via the portal endpoint and return its ID."""
    from config import settings as _s

    _s.portal_enabled = True
    resp = await client.post(
        "/portal/tickets",
        headers={"X-Api-Key": "viewer-key"},
        json={
            "title": f"Phase 10c test ticket ({ticket_id})",
            "description": "Testing Phase 10c features — platform maturity.",
            "reporter_email": "test@example.com",
        },
    )
    assert resp.status_code == 200 or resp.status_code == 201
    return resp.json()["ticket_id"]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. VISUAL WORKFLOW BUILDER
# ═══════════════════════════════════════════════════════════════════════════════


class TestVisualWorkflowCRUD:
    """Tests for POST/GET/DELETE /workflow-builder/workflows endpoints."""

    @pytest.mark.asyncio
    async def test_create_visual_workflow(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/workflow-builder/workflows",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Auto-Escalation Workflow",
                "description": "Escalate high-priority tickets automatically",
                "nodes": [
                    {"id": "trigger1", "type": "trigger", "label": "New ticket", "config": {}, "position_x": 0, "position_y": 0},
                    {"id": "cond1", "type": "condition", "label": "Is high priority?", "config": {"field": "priority", "value": "high"}, "position_x": 200, "position_y": 0},
                    {"id": "action1", "type": "action", "label": "Escalate", "config": {"action": "escalate"}, "position_x": 400, "position_y": 0},
                ],
                "edges": [
                    {"source_node_id": "trigger1", "target_node_id": "cond1", "label": ""},
                    {"source_node_id": "cond1", "target_node_id": "action1", "label": "yes"},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["workflow"]["name"] == "Auto-Escalation Workflow"
        assert data["workflow"]["status"] == "draft"
        assert len(data["workflow"]["nodes"]) == 3
        assert len(data["workflow"]["edges"]) == 2
        assert "id" in data["workflow"]

    @pytest.mark.asyncio
    async def test_create_workflow_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/workflow-builder/workflows",
            headers={"X-Api-Key": "viewer-key"},
            json={"name": "Test", "nodes": [], "edges": []},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_list_visual_workflows(self, client: AsyncClient) -> None:
        # Create a workflow first
        await client.post(
            "/workflow-builder/workflows",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "WF1", "nodes": [], "edges": []},
        )
        resp = await client.get(
            "/workflow-builder/workflows",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total"] >= 1
        assert len(data["workflows"]) >= 1

    @pytest.mark.asyncio
    async def test_delete_visual_workflow(self, client: AsyncClient) -> None:
        # Create
        create_resp = await client.post(
            "/workflow-builder/workflows",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "ToDelete", "nodes": [], "edges": []},
        )
        wf_id = create_resp.json()["workflow"]["id"]

        # Delete
        resp = await client.delete(
            f"/workflow-builder/workflows/{wf_id}",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["workflow"]["id"] == wf_id

        # Verify gone
        list_resp = await client.get(
            "/workflow-builder/workflows",
            headers={"X-Api-Key": "viewer-key"},
        )
        ids = [w["id"] for w in list_resp.json()["workflows"]]
        assert wf_id not in ids

    @pytest.mark.asyncio
    async def test_delete_nonexistent_workflow(self, client: AsyncClient) -> None:
        resp = await client.delete(
            "/workflow-builder/workflows/nonexistent-id",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 404


class TestVisualWorkflowPublish:
    """Tests for POST /workflow-builder/workflows/{id}/publish."""

    @pytest.mark.asyncio
    async def test_publish_workflow(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/workflow-builder/workflows",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Publish Test",
                "nodes": [{"id": "t1", "type": "trigger", "label": "Start"}],
                "edges": [],
            },
        )
        wf_id = create_resp.json()["workflow"]["id"]

        resp = await client.post(
            f"/workflow-builder/workflows/{wf_id}/publish",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow"]["status"] == "published"
        assert data["workflow"]["updated_at"] is not None

    @pytest.mark.asyncio
    async def test_publish_nonexistent_workflow(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/workflow-builder/workflows/nonexistent/publish",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 404


class TestVisualWorkflowValidation:
    """Tests for POST /workflow-builder/workflows/{id}/validate."""

    @pytest.mark.asyncio
    async def test_validate_valid_workflow(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/workflow-builder/workflows",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Valid WF",
                "nodes": [
                    {"id": "t1", "type": "trigger", "label": "Start"},
                    {"id": "a1", "type": "action", "label": "Do thing"},
                ],
                "edges": [
                    {"source_node_id": "t1", "target_node_id": "a1"},
                ],
            },
        )
        wf_id = create_resp.json()["workflow"]["id"]

        resp = await client.post(
            f"/workflow-builder/workflows/{wf_id}/validate",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["validation"]["valid"] is True
        assert len(data["validation"]["errors"]) == 0

    @pytest.mark.asyncio
    async def test_validate_empty_workflow(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/workflow-builder/workflows",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "Empty WF", "nodes": [], "edges": []},
        )
        wf_id = create_resp.json()["workflow"]["id"]

        resp = await client.post(
            f"/workflow-builder/workflows/{wf_id}/validate",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["validation"]["valid"] is False
        assert len(data["validation"]["errors"]) > 0

    @pytest.mark.asyncio
    async def test_validate_workflow_missing_trigger(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/workflow-builder/workflows",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "No Trigger",
                "nodes": [{"id": "a1", "type": "action", "label": "Act"}],
                "edges": [],
            },
        )
        wf_id = create_resp.json()["workflow"]["id"]

        resp = await client.post(
            f"/workflow-builder/workflows/{wf_id}/validate",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        assert data["validation"]["valid"] is False
        assert any("trigger" in e.lower() for e in data["validation"]["errors"])

    @pytest.mark.asyncio
    async def test_validate_workflow_bad_edge_refs(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/workflow-builder/workflows",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Bad Edges",
                "nodes": [{"id": "t1", "type": "trigger", "label": "Start"}],
                "edges": [{"source_node_id": "t1", "target_node_id": "nonexistent"}],
            },
        )
        wf_id = create_resp.json()["workflow"]["id"]

        resp = await client.post(
            f"/workflow-builder/workflows/{wf_id}/validate",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        assert data["validation"]["valid"] is False
        assert any("unknown" in e.lower() for e in data["validation"]["errors"])


class TestWorkflowBuilderFeatureFlag:
    """Tests that workflow builder endpoints return 403 when disabled."""

    @pytest.mark.asyncio
    async def test_workflow_builder_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s

        _s.workflow_builder_enabled = False
        try:
            resp = await client.get(
                "/workflow-builder/workflows",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
        finally:
            _s.workflow_builder_enabled = True


# ═══════════════════════════════════════════════════════════════════════════════
# 2. COMPLIANCE & SECURITY HARDENING
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataRetentionPolicyCRUD:
    """Tests for POST/GET/DELETE /compliance/data-retention-policies."""

    @pytest.mark.asyncio
    async def test_create_data_retention_policy(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/compliance/data-retention-policies",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Ticket Retention",
                "entity_type": "tickets",
                "retention_days": 365,
                "action": "archive",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["policy"]["name"] == "Ticket Retention"
        assert data["policy"]["entity_type"] == "tickets"
        assert data["policy"]["retention_days"] == 365
        assert data["policy"]["action"] == "archive"
        assert data["policy"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_create_policy_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/compliance/data-retention-policies",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "name": "Test",
                "entity_type": "tickets",
                "retention_days": 30,
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_policy_invalid_entity_type(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/compliance/data-retention-policies",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Bad Entity",
                "entity_type": "invalid_type",
                "retention_days": 30,
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_policy_invalid_action(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/compliance/data-retention-policies",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Bad Action",
                "entity_type": "tickets",
                "retention_days": 30,
                "action": "destroy",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_data_retention_policies(self, client: AsyncClient) -> None:
        await client.post(
            "/compliance/data-retention-policies",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Audit Log Retention",
                "entity_type": "audit_logs",
                "retention_days": 730,
                "action": "delete",
            },
        )
        resp = await client.get(
            "/compliance/data-retention-policies",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_delete_data_retention_policy(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/compliance/data-retention-policies",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "ToRemove",
                "entity_type": "contacts",
                "retention_days": 90,
            },
        )
        policy_id = create_resp.json()["policy"]["id"]

        resp = await client.delete(
            f"/compliance/data-retention-policies/{policy_id}",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["policy"]["id"] == policy_id

    @pytest.mark.asyncio
    async def test_delete_nonexistent_policy(self, client: AsyncClient) -> None:
        resp = await client.delete(
            "/compliance/data-retention-policies/nonexistent",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 404


class TestPIIRedaction:
    """Tests for POST /compliance/pii-redact."""

    @pytest.mark.asyncio
    async def test_redact_email(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/compliance/pii-redact",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "text": "Contact me at user@example.com for details.",
                "redact_types": ["email"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "[EMAIL_REDACTED]" in data["redacted_text"]
        assert "user@example.com" not in data["redacted_text"]
        assert data["redactions_applied"] == 1
        assert "email" in data["redaction_types_found"]

    @pytest.mark.asyncio
    async def test_redact_phone(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/compliance/pii-redact",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "text": "Call me at 555-123-4567 or 555.987.6543.",
                "redact_types": ["phone"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "[PHONE_REDACTED]" in data["redacted_text"]
        assert data["redactions_applied"] >= 1

    @pytest.mark.asyncio
    async def test_redact_ssn(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/compliance/pii-redact",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "text": "SSN: 123-45-6789",
                "redact_types": ["ssn"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "[SSN_REDACTED]" in data["redacted_text"]
        assert "123-45-6789" not in data["redacted_text"]

    @pytest.mark.asyncio
    async def test_redact_credit_card(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/compliance/pii-redact",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "text": "Card: 4111-1111-1111-1111",
                "redact_types": ["credit_card"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "[CREDIT_CARD_REDACTED]" in data["redacted_text"]

    @pytest.mark.asyncio
    async def test_redact_multiple_types(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/compliance/pii-redact",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "text": "Email: test@test.com, SSN: 999-88-7777",
                "redact_types": ["email", "ssn"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["redactions_applied"] == 2
        assert len(data["redaction_types_found"]) == 2

    @pytest.mark.asyncio
    async def test_redact_no_pii_found(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/compliance/pii-redact",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "text": "This text contains no PII at all.",
                "redact_types": ["email", "phone"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["redactions_applied"] == 0
        assert data["redacted_text"] == "This text contains no PII at all."


class TestAuditExport:
    """Tests for GET /compliance/audit-export."""

    @pytest.mark.asyncio
    async def test_audit_export(self, client: AsyncClient) -> None:
        # Perform an action to generate audit log
        await client.post(
            "/compliance/data-retention-policies",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "For Audit",
                "entity_type": "tickets",
                "retention_days": 30,
            },
        )

        resp = await client.get(
            "/compliance/audit-export",
            headers={"X-Api-Key": "admin-key"},
            params={"days": 7},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["export_format"] == "json"
        assert data["total_records"] >= 1

    @pytest.mark.asyncio
    async def test_audit_export_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/compliance/audit-export",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_audit_export_api_keys_masked(self, client: AsyncClient) -> None:
        # Generate an audit record
        await client.post(
            "/compliance/data-retention-policies",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Mask Test",
                "entity_type": "tickets",
                "retention_days": 30,
            },
        )
        resp = await client.get(
            "/compliance/audit-export",
            headers={"X-Api-Key": "admin-key"},
        )
        data = resp.json()
        # API key hashes should be partially masked
        for record in data["records"]:
            if record.get("api_key_hash"):
                assert "***" in record["api_key_hash"]


class TestSecurityPosture:
    """Tests for GET /compliance/security-posture."""

    @pytest.mark.asyncio
    async def test_security_posture(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/compliance/security-posture",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total_checks"] > 0
        assert data["overall_score"] > 0
        assert data["passed"] > 0
        assert isinstance(data["checks"], list)

    @pytest.mark.asyncio
    async def test_security_posture_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/compliance/security-posture",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_security_posture_checks_structure(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/compliance/security-posture",
            headers={"X-Api-Key": "admin-key"},
        )
        data = resp.json()
        for check in data["checks"]:
            assert "check" in check
            assert "status" in check
            assert check["status"] in ("pass", "warning", "fail")
            assert "severity" in check
            assert "detail" in check


class TestComplianceFeatureFlag:
    """Tests that compliance endpoints return 403 when disabled."""

    @pytest.mark.asyncio
    async def test_compliance_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s

        _s.compliance_enabled = False
        try:
            resp = await client.get(
                "/compliance/data-retention-policies",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
        finally:
            _s.compliance_enabled = True


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PERFORMANCE & SCALE IMPROVEMENTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheManagement:
    """Tests for POST /admin/cache/invalidate and GET /admin/cache/stats."""

    @pytest.mark.asyncio
    async def test_get_cache_stats(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/admin/cache/stats",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "total_entries" in data
        assert "hit_count" in data
        assert "miss_count" in data
        assert "hit_rate" in data

    @pytest.mark.asyncio
    async def test_invalidate_cache_all(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/admin/cache/invalidate",
            headers={"X-Api-Key": "admin-key"},
            json={"pattern": "*"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "invalidated_count" in data

    @pytest.mark.asyncio
    async def test_cache_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/admin/cache/stats",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403


class TestPerformanceMetrics:
    """Tests for GET /admin/performance/metrics."""

    @pytest.mark.asyncio
    async def test_get_performance_metrics(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/admin/performance/metrics",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        m = data["metrics"]
        assert "uptime_seconds" in m
        assert "total_requests" in m
        assert "avg_response_time_ms" in m
        assert "cache_entries" in m
        assert "memory_usage_mb" in m

    @pytest.mark.asyncio
    async def test_performance_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/admin/performance/metrics",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403


class TestConnectionPoolStats:
    """Tests for GET /admin/connection-pool/stats."""

    @pytest.mark.asyncio
    async def test_get_connection_pool_stats(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/admin/connection-pool/stats",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "pool_size" in data
        assert "active_connections" in data
        assert "idle_connections" in data
        assert "max_connections" in data

    @pytest.mark.asyncio
    async def test_connection_pool_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/admin/connection-pool/stats",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403


class TestPerformanceFeatureFlag:
    """Tests that performance endpoints return 403 when disabled."""

    @pytest.mark.asyncio
    async def test_performance_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s

        _s.performance_monitoring_enabled = False
        try:
            resp = await client.get(
                "/admin/performance/metrics",
                headers={"X-Api-Key": "admin-key"},
            )
            assert resp.status_code == 403
        finally:
            _s.performance_monitoring_enabled = True


# ═══════════════════════════════════════════════════════════════════════════════
# 4. UX POLISH — PREFERENCES & ONBOARDING
# ═══════════════════════════════════════════════════════════════════════════════


class TestUserPreferences:
    """Tests for GET/PUT /preferences/{user_id}."""

    @pytest.mark.asyncio
    async def test_get_default_preferences(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/preferences/user-001",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["user_id"] == "user-001"
        prefs = data["preferences"]
        assert prefs["theme"] == "light"
        assert prefs["language"] == "en"
        assert prefs["keyboard_shortcuts_enabled"] is True

    @pytest.mark.asyncio
    async def test_update_preferences_dark_mode(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/preferences/user-002",
            headers={"X-Api-Key": "viewer-key"},
            json={"theme": "dark"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["preferences"]["theme"] == "dark"
        # Other defaults should be preserved
        assert data["preferences"]["language"] == "en"

    @pytest.mark.asyncio
    async def test_update_preferences_accessibility(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/preferences/user-003",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "accessibility_high_contrast": True,
                "accessibility_font_size": "large",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["preferences"]["accessibility_high_contrast"] is True
        assert data["preferences"]["accessibility_font_size"] == "large"

    @pytest.mark.asyncio
    async def test_update_preferences_multiple_fields(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/preferences/user-004",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "theme": "system",
                "timezone": "America/New_York",
                "items_per_page": 50,
                "notifications_enabled": False,
            },
        )
        assert resp.status_code == 200
        prefs = resp.json()["preferences"]
        assert prefs["theme"] == "system"
        assert prefs["timezone"] == "America/New_York"
        assert prefs["items_per_page"] == 50
        assert prefs["notifications_enabled"] is False

    @pytest.mark.asyncio
    async def test_preferences_persist(self, client: AsyncClient) -> None:
        # Set
        await client.put(
            "/preferences/user-005",
            headers={"X-Api-Key": "viewer-key"},
            json={"theme": "dark", "language": "fr"},
        )
        # Read back
        resp = await client.get(
            "/preferences/user-005",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        prefs = resp.json()["preferences"]
        assert prefs["theme"] == "dark"
        assert prefs["language"] == "fr"


class TestOnboardingWizard:
    """Tests for GET /onboarding/status/{user_id} and POST /onboarding/complete-step."""

    @pytest.mark.asyncio
    async def test_get_onboarding_status_new_user(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/onboarding/status/new-user",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["user_id"] == "new-user"
        assert data["completed"] is False
        assert data["completion_percentage"] == 0.0
        assert data["total_steps"] == 5
        assert data["completed_steps"] == 0
        assert all(not s["completed"] for s in data["steps"])

    @pytest.mark.asyncio
    async def test_complete_onboarding_step(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/onboarding/complete-step",
            headers={"X-Api-Key": "viewer-key"},
            json={"user_id": "user-ob1", "step_id": "create_api_key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["step_id"] == "create_api_key"
        assert data["already_completed"] is False

    @pytest.mark.asyncio
    async def test_complete_step_idempotent(self, client: AsyncClient) -> None:
        # Complete once
        await client.post(
            "/onboarding/complete-step",
            headers={"X-Api-Key": "viewer-key"},
            json={"user_id": "user-ob2", "step_id": "submit_ticket"},
        )
        # Complete again
        resp = await client.post(
            "/onboarding/complete-step",
            headers={"X-Api-Key": "viewer-key"},
            json={"user_id": "user-ob2", "step_id": "submit_ticket"},
        )
        assert resp.status_code == 200
        assert resp.json()["already_completed"] is True

    @pytest.mark.asyncio
    async def test_complete_invalid_step(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/onboarding/complete-step",
            headers={"X-Api-Key": "viewer-key"},
            json={"user_id": "user-ob3", "step_id": "nonexistent_step"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_onboarding_progress_tracks(self, client: AsyncClient) -> None:
        user = "user-ob4"
        # Complete two steps
        await client.post(
            "/onboarding/complete-step",
            headers={"X-Api-Key": "viewer-key"},
            json={"user_id": user, "step_id": "create_api_key"},
        )
        await client.post(
            "/onboarding/complete-step",
            headers={"X-Api-Key": "viewer-key"},
            json={"user_id": user, "step_id": "submit_ticket"},
        )

        resp = await client.get(
            f"/onboarding/status/{user}",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        assert data["completed_steps"] == 2
        assert data["completion_percentage"] == 40.0
        assert data["completed"] is False

    @pytest.mark.asyncio
    async def test_onboarding_full_completion(self, client: AsyncClient) -> None:
        user = "user-ob5"
        step_ids = ["create_api_key", "submit_ticket", "explore_kb", "configure_sla", "setup_notifications"]
        for sid in step_ids:
            await client.post(
                "/onboarding/complete-step",
                headers={"X-Api-Key": "viewer-key"},
                json={"user_id": user, "step_id": sid},
            )

        resp = await client.get(
            f"/onboarding/status/{user}",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        assert data["completed"] is True
        assert data["completion_percentage"] == 100.0
        assert data["completed_steps"] == 5


class TestUXFeatureFlag:
    """Tests that UX preferences endpoints return 403 when disabled."""

    @pytest.mark.asyncio
    async def test_ux_preferences_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s

        _s.ux_preferences_enabled = False
        try:
            resp = await client.get(
                "/preferences/user-001",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
        finally:
            _s.ux_preferences_enabled = True

    @pytest.mark.asyncio
    async def test_onboarding_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s

        _s.ux_preferences_enabled = False
        try:
            resp = await client.get(
                "/onboarding/status/user-001",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
        finally:
            _s.ux_preferences_enabled = True
