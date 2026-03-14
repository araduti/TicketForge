"""
TicketForge — Test suite for Phase 10b features
Tests for Custom Classifiers, Anomaly Detection, and KB Auto-Generation.
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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase10b.db"
os.environ["CUSTOM_CLASSIFIERS_ENABLED"] = "true"
os.environ["ANOMALY_DETECTION_ENABLED"] = "true"
os.environ["KB_AUTO_GENERATION_ENABLED"] = "true"

from main import app, lifespan  # noqa: E402
from models import (  # noqa: E402
    AnomalyDetectionResponse,
    AnomalyRuleCreate,
    AnomalyRuleListResponse,
    AnomalyRuleRecord,
    AnomalyRuleResponse,
    ClassifyRequest,
    ClassifyResponse,
    CustomClassifierCreate,
    CustomClassifierListResponse,
    CustomClassifierRecord,
    CustomClassifierResponse,
    DetectedAnomaly,
    GeneratedKBArticle,
    KBAutoGenerateRequest,
    KBAutoGenerateResponse,
    KBAutoGenerateSuggestionsResponse,
    KBSuggestion,
    TrainClassifierRequest,
    TrainClassifierResponse,
    TrainingSample,
)

DB_PATH = "./test_ticketforge_phase10b.db"


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    from config import settings as _s  # noqa: PLC0415

    _db_path = _s.database_url.replace("sqlite+aiosqlite:///", "")
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass

    # Ensure Phase 10b feature flags are set on the singleton
    _s.custom_classifiers_enabled = True
    _s.anomaly_detection_enabled = True
    _s.kb_auto_generation_enabled = True
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

async def _create_test_ticket(client: AsyncClient, ticket_id: str = "P10B-001") -> str:
    """Create a test ticket via the portal endpoint and return its ID."""
    from config import settings as _s  # noqa: PLC0415
    _s.portal_enabled = True
    resp = await client.post(
        "/portal/tickets",
        headers={"X-Api-Key": "viewer-key"},
        json={
            "title": f"Phase 10b test ticket ({ticket_id})",
            "description": "Testing Phase 10b features — custom classifiers and anomaly detection.",
            "reporter_email": "test@example.com",
        },
    )
    assert resp.status_code == 200 or resp.status_code == 201
    return resp.json()["ticket_id"]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CUSTOM CLASSIFIERS
# ═══════════════════════════════════════════════════════════════════════════════


class TestCustomClassifierCRUD:
    """Tests for POST/GET/DELETE /custom-classifiers endpoints."""

    @pytest.mark.asyncio
    async def test_create_custom_classifier(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/custom-classifiers",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Support Topics",
                "description": "Classify support tickets by topic",
                "categories": ["billing", "technical", "general"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["classifier"]["name"] == "Support Topics"
        assert data["classifier"]["categories"] == ["billing", "technical", "general"]
        assert data["classifier"]["status"] == "untrained"
        assert data["classifier"]["training_samples"] == 0
        assert "id" in data["classifier"]

    @pytest.mark.asyncio
    async def test_create_classifier_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/custom-classifiers",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "name": "Test",
                "categories": ["a", "b"],
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_classifier_needs_at_least_2_categories(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/custom-classifiers",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Bad Classifier",
                "categories": ["only_one"],
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_custom_classifiers(self, client: AsyncClient) -> None:
        await client.post(
            "/custom-classifiers",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "Classifier A", "categories": ["cat1", "cat2"]},
        )
        await client.post(
            "/custom-classifiers",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "Classifier B", "categories": ["x", "y", "z"]},
        )

        resp = await client.get(
            "/custom-classifiers",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total"] >= 2

    @pytest.mark.asyncio
    async def test_delete_custom_classifier(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/custom-classifiers",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "To Delete", "categories": ["a", "b"]},
        )
        classifier_id = create_resp.json()["classifier"]["id"]

        resp = await client.delete(
            f"/custom-classifiers/{classifier_id}",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify it's gone
        list_resp = await client.get(
            "/custom-classifiers",
            headers={"X-Api-Key": "viewer-key"},
        )
        ids = [c["id"] for c in list_resp.json()["classifiers"]]
        assert classifier_id not in ids

    @pytest.mark.asyncio
    async def test_delete_classifier_not_found(self, client: AsyncClient) -> None:
        resp = await client.delete(
            "/custom-classifiers/nonexistent-id",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 404


class TestCustomClassifierTraining:
    """Tests for POST /custom-classifiers/{id}/train endpoint."""

    @pytest.mark.asyncio
    async def test_train_classifier(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/custom-classifiers",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "Trainer", "categories": ["bug", "feature"]},
        )
        classifier_id = create_resp.json()["classifier"]["id"]

        resp = await client.post(
            f"/custom-classifiers/{classifier_id}/train",
            headers={"X-Api-Key": "admin-key"},
            json={
                "samples": [
                    {"text": "App crashes on login", "category": "bug"},
                    {"text": "Add dark mode please", "category": "feature"},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["samples_added"] == 2
        assert data["total_samples"] == 2
        assert data["status"] == "untrained"  # Not enough for ready

    @pytest.mark.asyncio
    async def test_train_classifier_until_ready(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/custom-classifiers",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "Full Trainer", "categories": ["bug", "feature"]},
        )
        classifier_id = create_resp.json()["classifier"]["id"]

        # Submit 10 samples to get the classifier ready
        samples = []
        for i in range(10):
            cat = "bug" if i % 2 == 0 else "feature"
            samples.append({"text": f"Sample text number {i}", "category": cat})

        resp = await client.post(
            f"/custom-classifiers/{classifier_id}/train",
            headers={"X-Api-Key": "admin-key"},
            json={"samples": samples},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["total_samples"] == 10

    @pytest.mark.asyncio
    async def test_train_classifier_invalid_category(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/custom-classifiers",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "Strict", "categories": ["billing", "support"]},
        )
        classifier_id = create_resp.json()["classifier"]["id"]

        resp = await client.post(
            f"/custom-classifiers/{classifier_id}/train",
            headers={"X-Api-Key": "admin-key"},
            json={
                "samples": [
                    {"text": "Some text", "category": "nonexistent_category"},
                ],
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_train_classifier_not_found(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/custom-classifiers/nonexistent-id/train",
            headers={"X-Api-Key": "admin-key"},
            json={
                "samples": [{"text": "text", "category": "cat"}],
            },
        )
        assert resp.status_code == 404


class TestCustomClassifierClassify:
    """Tests for POST /custom-classifiers/{id}/classify endpoint."""

    @pytest.mark.asyncio
    async def test_classify_text(self, client: AsyncClient) -> None:
        # Create and train a classifier
        create_resp = await client.post(
            "/custom-classifiers",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "Classify Me", "categories": ["bug", "feature"]},
        )
        classifier_id = create_resp.json()["classifier"]["id"]

        # Train with 10+ samples
        samples = [
            {"text": "application crashes when clicking save button", "category": "bug"},
            {"text": "error message appears on login screen", "category": "bug"},
            {"text": "system freezes during file upload", "category": "bug"},
            {"text": "database connection timeout error", "category": "bug"},
            {"text": "null pointer exception in payment module", "category": "bug"},
            {"text": "add dark mode theme to the application", "category": "feature"},
            {"text": "implement export to PDF functionality", "category": "feature"},
            {"text": "add multi-language support for users", "category": "feature"},
            {"text": "create dashboard with custom widgets", "category": "feature"},
            {"text": "integrate with slack notifications system", "category": "feature"},
        ]
        await client.post(
            f"/custom-classifiers/{classifier_id}/train",
            headers={"X-Api-Key": "admin-key"},
            json={"samples": samples},
        )

        # Now classify
        resp = await client.post(
            f"/custom-classifiers/{classifier_id}/classify",
            headers={"X-Api-Key": "viewer-key"},
            json={"text": "the application crashes on startup"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["classifier_id"] == classifier_id
        assert data["predicted_category"] in ["bug", "feature"]
        assert "confidence" in data
        assert "all_scores" in data
        assert "bug" in data["all_scores"]
        assert "feature" in data["all_scores"]

    @pytest.mark.asyncio
    async def test_classify_not_ready(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/custom-classifiers",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "Not Ready", "categories": ["a", "b"]},
        )
        classifier_id = create_resp.json()["classifier"]["id"]

        resp = await client.post(
            f"/custom-classifiers/{classifier_id}/classify",
            headers={"X-Api-Key": "viewer-key"},
            json={"text": "some text to classify"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_classify_not_found(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/custom-classifiers/nonexistent-id/classify",
            headers={"X-Api-Key": "viewer-key"},
            json={"text": "some text"},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ANOMALY DETECTION
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnomalyRuleCRUD:
    """Tests for POST/GET/DELETE /anomaly-rules endpoints."""

    @pytest.mark.asyncio
    async def test_create_anomaly_rule(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/anomaly-rules",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Volume Spike Alert",
                "metric": "volume",
                "threshold": 0.5,
                "window_hours": 24,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["rule"]["name"] == "Volume Spike Alert"
        assert data["rule"]["metric"] == "volume"
        assert data["rule"]["threshold"] == 0.5
        assert data["rule"]["window_hours"] == 24
        assert data["rule"]["enabled"] is True
        assert "id" in data["rule"]

    @pytest.mark.asyncio
    async def test_create_anomaly_rule_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/anomaly-rules",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "name": "Test Rule",
                "metric": "volume",
                "threshold": 1.0,
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_anomaly_rule_invalid_metric(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/anomaly-rules",
            headers={"X-Api-Key": "admin-key"},
            json={
                "name": "Bad Metric",
                "metric": "invalid_metric",
                "threshold": 1.0,
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_all_valid_metrics(self, client: AsyncClient) -> None:
        for metric in ["volume", "category_shift", "priority_spike", "resolution_time"]:
            resp = await client.post(
                "/anomaly-rules",
                headers={"X-Api-Key": "admin-key"},
                json={"name": f"Rule {metric}", "metric": metric, "threshold": 0.5},
            )
            assert resp.status_code == 200, f"Failed for metric {metric}"

    @pytest.mark.asyncio
    async def test_list_anomaly_rules(self, client: AsyncClient) -> None:
        await client.post(
            "/anomaly-rules",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "Rule 1", "metric": "volume", "threshold": 0.5},
        )
        await client.post(
            "/anomaly-rules",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "Rule 2", "metric": "priority_spike", "threshold": 0.3},
        )

        resp = await client.get(
            "/anomaly-rules",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total"] >= 2

    @pytest.mark.asyncio
    async def test_delete_anomaly_rule(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/anomaly-rules",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "To Delete", "metric": "volume", "threshold": 1.0},
        )
        rule_id = create_resp.json()["rule"]["id"]

        resp = await client.delete(
            f"/anomaly-rules/{rule_id}",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_delete_anomaly_rule_not_found(self, client: AsyncClient) -> None:
        resp = await client.delete(
            "/anomaly-rules/nonexistent-id",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 404


class TestAnomalyDetection:
    """Tests for GET /analytics/anomalies endpoint."""

    @pytest.mark.asyncio
    async def test_detect_anomalies_empty(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/anomalies",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total_anomalies"] == 0
        assert data["anomalies"] == []
        assert data["analysis_window_hours"] == 24

    @pytest.mark.asyncio
    async def test_detect_anomalies_with_custom_hours(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/anomalies",
            headers={"X-Api-Key": "viewer-key"},
            params={"hours": 48},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["analysis_window_hours"] == 48

    @pytest.mark.asyncio
    async def test_detect_anomalies_with_rules(self, client: AsyncClient) -> None:
        # Create a rule
        await client.post(
            "/anomaly-rules",
            headers={"X-Api-Key": "admin-key"},
            json={"name": "Vol Check", "metric": "volume", "threshold": 0.5},
        )

        # Create some test tickets
        for i in range(3):
            await _create_test_ticket(client, f"anomaly-{i}")

        resp = await client.get(
            "/analytics/anomalies",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        # We should get a result with the analysis running (may or may not find anomalies)
        assert isinstance(data["anomalies"], list)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. KB AUTO-GENERATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestKBAutoGenerate:
    """Tests for POST /kb/auto-generate endpoint."""

    @pytest.mark.asyncio
    async def test_kb_auto_generate_empty(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/kb/auto-generate",
            headers={"X-Api-Key": "admin-key"},
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total_generated"] == 0
        assert data["articles"] == []

    @pytest.mark.asyncio
    async def test_kb_auto_generate_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/kb/auto-generate",
            headers={"X-Api-Key": "viewer-key"},
            json={},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_kb_auto_generate_with_category_filter(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/kb/auto-generate",
            headers={"X-Api-Key": "admin-key"},
            json={"category": "network"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_kb_auto_generate_with_options(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/kb/auto-generate",
            headers={"X-Api-Key": "admin-key"},
            json={"min_resolved_tickets": 5, "max_articles": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestKBAutoGenerateSuggestions:
    """Tests for GET /kb/auto-generate/suggestions endpoint."""

    @pytest.mark.asyncio
    async def test_kb_suggestions_empty(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/kb/auto-generate/suggestions",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["suggestions"], list)
        assert data["total_suggestions"] >= 0

    @pytest.mark.asyncio
    async def test_kb_suggestions_with_tickets(self, client: AsyncClient) -> None:
        # Create a few tickets to generate some data
        for i in range(3):
            await _create_test_ticket(client, f"kb-sug-{i}")

        resp = await client.get(
            "/kb/auto-generate/suggestions",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 4. FEATURE FLAG INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestFeatureFlagIntegration:
    """Tests to verify feature flags correctly gate endpoints."""

    @pytest.mark.asyncio
    async def test_custom_classifiers_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.custom_classifiers_enabled = False
        try:
            resp = await client.get(
                "/custom-classifiers",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
        finally:
            _s.custom_classifiers_enabled = True

    @pytest.mark.asyncio
    async def test_anomaly_detection_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.anomaly_detection_enabled = False
        try:
            resp = await client.get(
                "/anomaly-rules",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
        finally:
            _s.anomaly_detection_enabled = True

    @pytest.mark.asyncio
    async def test_kb_auto_generation_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.kb_auto_generation_enabled = False
        try:
            resp = await client.get(
                "/kb/auto-generate/suggestions",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
        finally:
            _s.kb_auto_generation_enabled = True

    @pytest.mark.asyncio
    async def test_anomalies_endpoint_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.anomaly_detection_enabled = False
        try:
            resp = await client.get(
                "/analytics/anomalies",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 403
        finally:
            _s.anomaly_detection_enabled = True

    @pytest.mark.asyncio
    async def test_kb_auto_generate_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.kb_auto_generation_enabled = False
        try:
            resp = await client.post(
                "/kb/auto-generate",
                headers={"X-Api-Key": "admin-key"},
                json={},
            )
            assert resp.status_code == 403
        finally:
            _s.kb_auto_generation_enabled = True
