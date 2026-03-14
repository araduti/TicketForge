"""
TicketForge — Test suite for Phase 10a features
Tests for Team Dashboards, Enhanced SLA Prediction, and Volume Forecasting.
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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase10.db"
os.environ["TEAM_DASHBOARDS_ENABLED"] = "true"
os.environ["ENHANCED_SLA_PREDICTION_ENABLED"] = "true"
os.environ["VOLUME_FORECASTING_ENABLED"] = "true"

from main import app, lifespan  # noqa: E402
from models import (  # noqa: E402
    CategoryForecast,
    EnhancedSLAPrediction,
    EnhancedSLARiskResponse,
    SLARiskFactor,
    SLARiskThresholdCreate,
    SLARiskThresholdListResponse,
    SLARiskThresholdRecord,
    SLARiskThresholdResponse,
    TeamDashboardResponse,
    TeamMemberCreate,
    TeamMemberListResponse,
    TeamMemberRecord,
    TeamMemberResponse,
    TeamPerformanceMetrics,
    VolumeForecastPoint,
    VolumeForecastResponse,
)

DB_PATH = "./test_ticketforge_phase10.db"


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    from config import settings as _s  # noqa: PLC0415

    _db_path = _s.database_url.replace("sqlite+aiosqlite:///", "")
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass

    # Ensure Phase 10a feature flags are set on the singleton
    _s.team_dashboards_enabled = True
    _s.enhanced_sla_prediction_enabled = True
    _s.volume_forecasting_enabled = True
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

async def _create_test_ticket(client: AsyncClient, ticket_id: str = "P10-001") -> str:
    """Create a test ticket via the portal endpoint and return its ID."""
    from config import settings as _s  # noqa: PLC0415
    _s.portal_enabled = True
    resp = await client.post(
        "/portal/tickets",
        headers={"X-Api-Key": "viewer-key"},
        json={
            "title": f"Phase 10 test ticket ({ticket_id})",
            "description": "Testing Phase 10 features — categorisation and performance analysis.",
            "reporter_email": "test@example.com",
        },
    )
    assert resp.status_code == 200 or resp.status_code == 201
    return resp.json()["ticket_id"]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TEAM DASHBOARDS
# ═══════════════════════════════════════════════════════════════════════════════


class TestTeamMemberCRUD:
    """Tests for POST/GET /teams endpoints."""

    @pytest.mark.asyncio
    async def test_create_team_member(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "agent-1", "team_name": "Support", "role": "lead"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["agent_id"] == "agent-1"
        assert data["data"]["team_name"] == "Support"
        assert data["data"]["role"] == "lead"
        assert "id" in data["data"]

    @pytest.mark.asyncio
    async def test_create_team_member_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/teams",
            headers={"X-Api-Key": "analyst-key"},
            json={"agent_id": "agent-2", "team_name": "Support"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_team_member_viewer_denied(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/teams",
            headers={"X-Api-Key": "viewer-key"},
            json={"agent_id": "agent-3", "team_name": "Support"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_duplicate_team_member(self, client: AsyncClient) -> None:
        await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "agent-dup", "team_name": "Ops"},
        )
        resp = await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "agent-dup", "team_name": "Ops"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_agent_can_be_in_multiple_teams(self, client: AsyncClient) -> None:
        resp1 = await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "agent-multi", "team_name": "TeamA"},
        )
        resp2 = await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "agent-multi", "team_name": "TeamB"},
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200

    @pytest.mark.asyncio
    async def test_list_teams(self, client: AsyncClient) -> None:
        await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "agent-list-1", "team_name": "Engineering"},
        )
        await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "agent-list-2", "team_name": "Engineering"},
        )

        resp = await client.get(
            "/teams",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["members"]) >= 2

    @pytest.mark.asyncio
    async def test_list_teams_filter_by_name(self, client: AsyncClient) -> None:
        await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "agent-f1", "team_name": "Alpha"},
        )
        await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "agent-f2", "team_name": "Beta"},
        )

        resp = await client.get(
            "/teams",
            headers={"X-Api-Key": "viewer-key"},
            params={"team_name": "Alpha"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(m["team_name"] == "Alpha" for m in data["members"])

    @pytest.mark.asyncio
    async def test_create_team_member_default_role(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "agent-default", "team_name": "Defaults"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["role"] == "member"


class TestTeamDashboard:
    """Tests for GET /analytics/team-dashboard."""

    @pytest.mark.asyncio
    async def test_team_dashboard_empty(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/team-dashboard",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["teams"] == []
        assert data["total_agents"] == 0

    @pytest.mark.asyncio
    async def test_team_dashboard_with_teams(self, client: AsyncClient) -> None:
        # Create teams
        await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "dash-agent-1", "team_name": "Frontend"},
        )
        await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "dash-agent-2", "team_name": "Frontend"},
        )
        await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "dash-agent-3", "team_name": "Backend"},
        )

        resp = await client.get(
            "/analytics/team-dashboard",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["teams"]) == 2
        assert data["total_agents"] == 3

        team_names = [t["team_name"] for t in data["teams"]]
        assert "Frontend" in team_names
        assert "Backend" in team_names

    @pytest.mark.asyncio
    async def test_team_dashboard_metrics_structure(self, client: AsyncClient) -> None:
        await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "metrics-agent", "team_name": "Metrics"},
        )

        resp = await client.get(
            "/analytics/team-dashboard",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        team = data["teams"][0]

        assert "team_name" in team
        assert "total_tickets" in team
        assert "open_tickets" in team
        assert "resolved_tickets" in team
        assert "avg_resolution_hours" in team
        assert "member_count" in team
        assert "members" in team
        assert team["member_count"] == 1
        assert "metrics-agent" in team["members"]

    @pytest.mark.asyncio
    async def test_team_dashboard_with_tickets(self, client: AsyncClient) -> None:
        # Create a ticket first
        await _create_test_ticket(client, "dash-ticket")

        # Create a team
        await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "ticket-agent", "team_name": "TicketTeam"},
        )

        resp = await client.get(
            "/analytics/team-dashboard",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_team_dashboard_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.team_dashboards_enabled = False

        resp = await client.get(
            "/analytics/team-dashboard",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403

        _s.team_dashboards_enabled = True


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ENHANCED SLA PREDICTION
# ═══════════════════════════════════════════════════════════════════════════════


class TestSLARiskThresholds:
    """Tests for POST/GET /sla-risk-thresholds."""

    @pytest.mark.asyncio
    async def test_create_risk_threshold(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "admin-key"},
            json={"priority": "critical", "warning_threshold": 0.3, "critical_threshold": 0.6},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["priority"] == "critical"
        assert data["data"]["warning_threshold"] == 0.3
        assert data["data"]["critical_threshold"] == 0.6

    @pytest.mark.asyncio
    async def test_create_risk_threshold_requires_admin(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "analyst-key"},
            json={"priority": "high", "warning_threshold": 0.4, "critical_threshold": 0.7},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_risk_threshold_invalid_range(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "admin-key"},
            json={"priority": "medium", "warning_threshold": 0.8, "critical_threshold": 0.5},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_risk_threshold_equal_values(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "admin-key"},
            json={"priority": "low", "warning_threshold": 0.5, "critical_threshold": 0.5},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_existing_threshold(self, client: AsyncClient) -> None:
        await client.post(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "admin-key"},
            json={"priority": "high", "warning_threshold": 0.4, "critical_threshold": 0.7},
        )
        # Re-create with same priority should update
        resp = await client.post(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "admin-key"},
            json={"priority": "high", "warning_threshold": 0.3, "critical_threshold": 0.6},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["warning_threshold"] == 0.3

    @pytest.mark.asyncio
    async def test_list_risk_thresholds(self, client: AsyncClient) -> None:
        await client.post(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "admin-key"},
            json={"priority": "critical", "warning_threshold": 0.3, "critical_threshold": 0.6},
        )
        await client.post(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "admin-key"},
            json={"priority": "high", "warning_threshold": 0.4, "critical_threshold": 0.7},
        )

        resp = await client.get(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["thresholds"]) >= 2

    @pytest.mark.asyncio
    async def test_list_risk_thresholds_empty(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["thresholds"] == []

    @pytest.mark.asyncio
    async def test_risk_threshold_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.enhanced_sla_prediction_enabled = False

        resp = await client.post(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "admin-key"},
            json={"priority": "low", "warning_threshold": 0.5, "critical_threshold": 0.8},
        )
        assert resp.status_code == 403

        _s.enhanced_sla_prediction_enabled = True


class TestEnhancedSLARisk:
    """Tests for GET /analytics/sla-risk."""

    @pytest.mark.asyncio
    async def test_sla_risk_empty(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/sla-risk",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["predictions"] == []
        assert data["total_open_tickets"] == 0

    @pytest.mark.asyncio
    async def test_sla_risk_with_tickets(self, client: AsyncClient) -> None:
        await _create_test_ticket(client, "sla-risk-1")

        resp = await client.get(
            "/analytics/sla-risk",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total_open_tickets"] >= 1

        if data["predictions"]:
            pred = data["predictions"][0]
            assert "ticket_id" in pred
            assert "risk_factors" in pred
            assert "recommended_action" in pred
            assert "risk_level" in pred
            assert pred["risk_level"] in ("low", "medium", "high", "critical")

    @pytest.mark.asyncio
    async def test_sla_risk_factors_present(self, client: AsyncClient) -> None:
        await _create_test_ticket(client, "sla-factors")

        resp = await client.get(
            "/analytics/sla-risk",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        if data["predictions"]:
            pred = data["predictions"][0]
            factor_names = [f["factor"] for f in pred["risk_factors"]]
            assert "time_pressure" in factor_names
            assert "historical_performance" in factor_names
            assert "volume_pressure" in factor_names
            assert "priority_urgency" in factor_names

    @pytest.mark.asyncio
    async def test_sla_risk_with_custom_thresholds(self, client: AsyncClient) -> None:
        # Set custom thresholds first
        await client.post(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "admin-key"},
            json={"priority": "medium", "warning_threshold": 0.2, "critical_threshold": 0.4},
        )

        await _create_test_ticket(client, "sla-custom")

        resp = await client.get(
            "/analytics/sla-risk",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_sla_risk_recommended_actions(self, client: AsyncClient) -> None:
        await _create_test_ticket(client, "sla-action")

        resp = await client.get(
            "/analytics/sla-risk",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        if data["predictions"]:
            pred = data["predictions"][0]
            assert isinstance(pred["recommended_action"], str)
            assert len(pred["recommended_action"]) > 0

    @pytest.mark.asyncio
    async def test_sla_risk_breach_probability_range(self, client: AsyncClient) -> None:
        await _create_test_ticket(client, "sla-prob")

        resp = await client.get(
            "/analytics/sla-risk",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        for pred in data["predictions"]:
            assert 0.0 <= pred["predicted_breach_probability"] <= 1.0

    @pytest.mark.asyncio
    async def test_sla_risk_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.enhanced_sla_prediction_enabled = False

        resp = await client.get(
            "/analytics/sla-risk",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403

        _s.enhanced_sla_prediction_enabled = True

    @pytest.mark.asyncio
    async def test_sla_risk_sorted_by_probability(self, client: AsyncClient) -> None:
        await _create_test_ticket(client, "sla-sort-1")
        await _create_test_ticket(client, "sla-sort-2")

        resp = await client.get(
            "/analytics/sla-risk",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        probs = [p["predicted_breach_probability"] for p in data["predictions"]]
        assert probs == sorted(probs, reverse=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. VOLUME FORECASTING
# ═══════════════════════════════════════════════════════════════════════════════


class TestVolumeForecast:
    """Tests for GET /analytics/volume-forecast."""

    @pytest.mark.asyncio
    async def test_volume_forecast_empty(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["overall_trend"] == "stable"
        assert data["daily_average"] == 0.0

    @pytest.mark.asyncio
    async def test_volume_forecast_default_days(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["forecast_days"] == 7
        assert len(data["forecast_points"]) == 7

    @pytest.mark.asyncio
    async def test_volume_forecast_custom_days(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
            params={"days": 14},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["forecast_days"] == 14
        assert len(data["forecast_points"]) == 14

    @pytest.mark.asyncio
    async def test_volume_forecast_with_tickets(self, client: AsyncClient) -> None:
        # Create multiple tickets
        for i in range(3):
            await _create_test_ticket(client, f"vol-{i}")

        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["daily_average"] > 0

    @pytest.mark.asyncio
    async def test_volume_forecast_points_structure(self, client: AsyncClient) -> None:
        await _create_test_ticket(client, "vol-struct")

        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        for point in data["forecast_points"]:
            assert "date" in point
            assert "predicted_volume" in point
            assert "lower_bound" in point
            assert "upper_bound" in point
            assert point["lower_bound"] <= point["predicted_volume"] <= point["upper_bound"]

    @pytest.mark.asyncio
    async def test_volume_forecast_category_breakdown(self, client: AsyncClient) -> None:
        await _create_test_ticket(client, "vol-cat")

        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        if data["category_forecasts"]:
            cat = data["category_forecasts"][0]
            assert "category" in cat
            assert "historical_avg" in cat
            assert "trend_direction" in cat
            assert cat["trend_direction"] in ("stable", "increasing", "decreasing")
            assert "forecast_points" in cat

    @pytest.mark.asyncio
    async def test_volume_forecast_trend_values(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        assert data["overall_trend"] in ("stable", "increasing", "decreasing")

    @pytest.mark.asyncio
    async def test_volume_forecast_history_days_param(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
            params={"history_days": 60},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_volume_forecast_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.volume_forecasting_enabled = False

        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403

        _s.volume_forecasting_enabled = True

    @pytest.mark.asyncio
    async def test_volume_forecast_min_days(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
            params={"days": 1},
        )
        assert resp.status_code == 200
        assert len(resp.json()["forecast_points"]) == 1

    @pytest.mark.asyncio
    async def test_volume_forecast_max_days(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
            params={"days": 90},
        )
        assert resp.status_code == 200
        assert len(resp.json()["forecast_points"]) == 90

    @pytest.mark.asyncio
    async def test_volume_forecast_invalid_days(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
            params={"days": 0},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_volume_forecast_dates_are_future(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        for point in data["forecast_points"]:
            assert point["date"] >= today

    @pytest.mark.asyncio
    async def test_volume_forecast_non_negative_values(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
        )
        data = resp.json()
        for point in data["forecast_points"]:
            assert point["predicted_volume"] >= 0
            assert point["lower_bound"] >= 0
            assert point["upper_bound"] >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. FEATURE FLAG INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestFeatureFlagIntegration:
    """Verify that all Phase 10a endpoints respect feature flags."""

    @pytest.mark.asyncio
    async def test_teams_disabled_post(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.team_dashboards_enabled = False
        resp = await client.post(
            "/teams",
            headers={"X-Api-Key": "admin-key"},
            json={"agent_id": "x", "team_name": "X"},
        )
        assert resp.status_code == 403
        _s.team_dashboards_enabled = True

    @pytest.mark.asyncio
    async def test_teams_disabled_get(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.team_dashboards_enabled = False
        resp = await client.get(
            "/teams",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403
        _s.team_dashboards_enabled = True

    @pytest.mark.asyncio
    async def test_sla_risk_thresholds_disabled_post(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.enhanced_sla_prediction_enabled = False
        resp = await client.post(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "admin-key"},
            json={"priority": "high", "warning_threshold": 0.4, "critical_threshold": 0.7},
        )
        assert resp.status_code == 403
        _s.enhanced_sla_prediction_enabled = True

    @pytest.mark.asyncio
    async def test_sla_risk_thresholds_disabled_get(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.enhanced_sla_prediction_enabled = False
        resp = await client.get(
            "/sla-risk-thresholds",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403
        _s.enhanced_sla_prediction_enabled = True

    @pytest.mark.asyncio
    async def test_volume_forecast_disabled(self, client: AsyncClient) -> None:
        from config import settings as _s  # noqa: PLC0415
        _s.volume_forecasting_enabled = False
        resp = await client.get(
            "/analytics/volume-forecast",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403
        _s.volume_forecasting_enabled = True
