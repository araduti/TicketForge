"""
TicketForge — Test suite for Phase 11 features
Tests for Conversational Intelligence (Troubleshooting Flows, Intent Detection),
Predictive Intelligence (Resolution Prediction, Satisfaction Prediction),
and Smart Assignment (Intelligent Agent Assignment).
"""
from __future__ import annotations

import json
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Override settings BEFORE importing main
os.environ["API_KEYS"] = '["admin-key","analyst-key","viewer-key"]'
os.environ["API_KEY_ROLES"] = json.dumps({
    "admin-key": "admin",
    "analyst-key": "analyst",
    "viewer-key": "viewer",
})
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase11.db"
os.environ["TROUBLESHOOTING_FLOWS_ENABLED"] = "true"
os.environ["INTENT_DETECTION_ENABLED"] = "true"
os.environ["RESOLUTION_PREDICTION_ENABLED"] = "true"
os.environ["SATISFACTION_PREDICTION_ENABLED"] = "true"
os.environ["SMART_ASSIGNMENT_ENABLED"] = "true"

from main import app, lifespan

DB_PATH = "./test_ticketforge_phase11.db"


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    from config import settings as _s

    _db_path = _s.database_url.replace("sqlite+aiosqlite:///", "")
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass

    # Ensure Phase 11 feature flags are set on the singleton
    _s.troubleshooting_flows_enabled = True
    _s.intent_detection_enabled = True
    _s.resolution_prediction_enabled = True
    _s.satisfaction_prediction_enabled = True
    _s.smart_assignment_enabled = True
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


async def _create_test_ticket(client: AsyncClient, ticket_id: str = "P11-001") -> str:
    """Create a test ticket via the portal endpoint and return its ID."""
    from config import settings as _s

    _s.portal_enabled = True
    resp = await client.post(
        "/portal/tickets",
        headers={"X-Api-Key": "viewer-key"},
        json={
            "title": f"Phase 11 test ticket ({ticket_id})",
            "description": "Testing Phase 11 features — intelligent automation.",
            "reporter_email": "test@example.com",
        },
    )
    assert resp.status_code == 200 or resp.status_code == 201
    return resp.json()["ticket_id"]


def _sample_flow_steps() -> list[dict]:
    """Return a sample set of troubleshooting flow steps."""
    return [
        {
            "id": "step1",
            "step_type": "question",
            "title": "What is the issue?",
            "content": "Select your issue type",
            "options": [],
            "next_step_id": "step2",
        },
        {
            "id": "step2",
            "step_type": "branch",
            "title": "Select category",
            "content": "",
            "options": [
                {"label": "Network", "next_step_id": "step3"},
                {"label": "Software", "next_step_id": "step3"},
            ],
            "next_step_id": None,
        },
        {
            "id": "step3",
            "step_type": "resolution",
            "title": "Resolution",
            "content": "Please restart your device and try again.",
            "options": [],
            "next_step_id": None,
        },
    ]


# ---------------------------------------------------------------------------
# 51. Troubleshooting Flows Tests
# ---------------------------------------------------------------------------


class TestTroubleshootingFlows:
    """Tests for Troubleshooting Flows CRUD and execution."""

    @pytest.mark.asyncio
    async def test_create_troubleshooting_flow(self, client: AsyncClient) -> None:
        """POST /troubleshooting/flows — create a flow with 3 steps."""
        steps = _sample_flow_steps()
        resp = await client.post(
            "/troubleshooting/flows",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "name": "Device Troubleshooting",
                "description": "Standard device troubleshooting flow",
                "category": "hardware",
                "steps": steps,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        flow = data["flow"]
        assert "id" in flow
        assert flow["name"] == "Device Troubleshooting"
        assert len(flow["steps"]) == 3

    @pytest.mark.asyncio
    async def test_list_troubleshooting_flows(self, client: AsyncClient) -> None:
        """Create a flow then GET /troubleshooting/flows — verify list."""
        await client.post(
            "/troubleshooting/flows",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "name": "List Test Flow",
                "description": "Flow for listing test",
                "category": "general",
                "steps": _sample_flow_steps(),
            },
        )
        resp = await client.get(
            "/troubleshooting/flows",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["flows"]) >= 1

    @pytest.mark.asyncio
    async def test_delete_troubleshooting_flow(self, client: AsyncClient) -> None:
        """Create a flow then DELETE /troubleshooting/flows/{id}."""
        create_resp = await client.post(
            "/troubleshooting/flows",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "name": "Delete Me Flow",
                "description": "To be deleted",
                "category": "general",
                "steps": _sample_flow_steps(),
            },
        )
        flow_id = create_resp.json()["flow"]["id"]
        resp = await client.delete(
            f"/troubleshooting/flows/{flow_id}",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_execute_troubleshooting_start(self, client: AsyncClient) -> None:
        """POST /troubleshooting/execute with no current_step_id — returns first step."""
        create_resp = await client.post(
            "/troubleshooting/flows",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "name": "Exec Start Flow",
                "description": "Execution test",
                "category": "general",
                "steps": _sample_flow_steps(),
            },
        )
        flow_id = create_resp.json()["flow"]["id"]
        resp = await client.post(
            "/troubleshooting/execute",
            headers={"X-Api-Key": "viewer-key"},
            json={"flow_id": flow_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"]["id"] == "step1"
        assert data["current_step"]["step_type"] == "question"

    @pytest.mark.asyncio
    async def test_execute_troubleshooting_branch(self, client: AsyncClient) -> None:
        """Execute to a branch step then select an option to navigate."""
        create_resp = await client.post(
            "/troubleshooting/flows",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "name": "Branch Nav Flow",
                "description": "Branch navigation test",
                "category": "general",
                "steps": _sample_flow_steps(),
            },
        )
        flow_id = create_resp.json()["flow"]["id"]

        # Navigate to step2 (branch) via step1
        resp = await client.post(
            "/troubleshooting/execute",
            headers={"X-Api-Key": "viewer-key"},
            json={"flow_id": flow_id, "current_step_id": "step1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"]["id"] == "step2"
        assert data["current_step"]["step_type"] == "branch"

        # Select "Network" option to go to step3
        resp = await client.post(
            "/troubleshooting/execute",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "flow_id": flow_id,
                "current_step_id": "step2",
                "selected_option": "Network",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"]["id"] == "step3"

    @pytest.mark.asyncio
    async def test_execute_troubleshooting_resolution(
        self, client: AsyncClient
    ) -> None:
        """Execute through to the resolution step — verify is_complete."""
        create_resp = await client.post(
            "/troubleshooting/flows",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "name": "Resolution Flow",
                "description": "Resolution test",
                "category": "general",
                "steps": _sample_flow_steps(),
            },
        )
        flow_id = create_resp.json()["flow"]["id"]

        # Navigate to step2 then to step3 (resolution)
        await client.post(
            "/troubleshooting/execute",
            headers={"X-Api-Key": "viewer-key"},
            json={"flow_id": flow_id, "current_step_id": "step1"},
        )
        resp = await client.post(
            "/troubleshooting/execute",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "flow_id": flow_id,
                "current_step_id": "step2",
                "selected_option": "Network",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"]["step_type"] == "resolution"
        assert data["is_complete"] is True
        assert "restart your device" in data["current_step"]["content"].lower()

    @pytest.mark.asyncio
    async def test_troubleshooting_flow_not_found(
        self, client: AsyncClient
    ) -> None:
        """POST /troubleshooting/execute with non-existent flow_id — 404."""
        resp = await client.post(
            "/troubleshooting/execute",
            headers={"X-Api-Key": "viewer-key"},
            json={"flow_id": "nonexistent-flow-id"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_troubleshooting_rbac_viewer_cannot_create(
        self, client: AsyncClient
    ) -> None:
        """POST /troubleshooting/flows with viewer-key — 403."""
        resp = await client.post(
            "/troubleshooting/flows",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "name": "Viewer Flow",
                "description": "Should fail",
                "category": "general",
                "steps": [],
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_troubleshooting_feature_flag_disabled(
        self, client: AsyncClient
    ) -> None:
        """Disable troubleshooting flag — POST /troubleshooting/flows returns 403."""
        from config import settings as _s

        _s.troubleshooting_flows_enabled = False
        resp = await client.post(
            "/troubleshooting/flows",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "name": "Flag Test",
                "description": "Should be blocked",
                "category": "general",
                "steps": [],
            },
        )
        assert resp.status_code == 403
        _s.troubleshooting_flows_enabled = True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_flow(self, client: AsyncClient) -> None:
        """DELETE /troubleshooting/flows/nonexistent — 404."""
        resp = await client.delete(
            "/troubleshooting/flows/nonexistent",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 52. Intent Detection Tests
# ---------------------------------------------------------------------------


class TestIntentDetection:
    """Tests for intent detection and entity extraction endpoints."""

    @pytest.mark.asyncio
    async def test_detect_intent_password_reset(
        self, client: AsyncClient
    ) -> None:
        """POST /intent/detect — password reset intent."""
        resp = await client.post(
            "/intent/detect",
            headers={"X-Api-Key": "viewer-key"},
            json={"text": "I forgot my password and can't log in"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["primary_intent"]["intent"] == "password_reset"
        assert data["primary_intent"]["confidence"] > 0

    @pytest.mark.asyncio
    async def test_detect_intent_bug_report(self, client: AsyncClient) -> None:
        """POST /intent/detect — bug report intent."""
        resp = await client.post(
            "/intent/detect",
            headers={"X-Api-Key": "viewer-key"},
            json={"text": "There is a bug causing the app to crash"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["primary_intent"]["intent"] == "bug_report"

    @pytest.mark.asyncio
    async def test_detect_intent_unknown(self, client: AsyncClient) -> None:
        """POST /intent/detect — unknown intent for gibberish."""
        resp = await client.post(
            "/intent/detect",
            headers={"X-Api-Key": "viewer-key"},
            json={"text": "xyz abc 12345"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["primary_intent"]["intent"] == "unknown"

    @pytest.mark.asyncio
    async def test_detect_intent_multiple(self, client: AsyncClient) -> None:
        """POST /intent/detect — multiple intent signals."""
        resp = await client.post(
            "/intent/detect",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "text": (
                    "I forgot my password and the app crashes with a bug "
                    "every time I try to reset it"
                )
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["all_intents"]) >= 2

    @pytest.mark.asyncio
    async def test_extract_entities_email(self, client: AsyncClient) -> None:
        """POST /entities/extract — extract email entity."""
        resp = await client.post(
            "/entities/extract",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "text": "Please contact support@example.com for help",
                "entity_types": ["email"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        entity_types = [e["entity_type"] for e in data["entities"]]
        assert "email" in entity_types

    @pytest.mark.asyncio
    async def test_extract_entities_error_code(
        self, client: AsyncClient
    ) -> None:
        """POST /entities/extract — extract error code entity."""
        resp = await client.post(
            "/entities/extract",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "text": "I am seeing error code: ERR-404 on the page",
                "entity_types": ["error_code"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        entity_types = [e["entity_type"] for e in data["entities"]]
        assert "error_code" in entity_types

    @pytest.mark.asyncio
    async def test_extract_entities_multiple(self, client: AsyncClient) -> None:
        """POST /entities/extract — multiple entities (email + error code)."""
        resp = await client.post(
            "/entities/extract",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "text": (
                    "Contact admin@example.com about error code: ERR-500 "
                    "on the dashboard"
                ),
                "entity_types": ["email", "error_code"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_count"] >= 2

    @pytest.mark.asyncio
    async def test_intent_feature_flag_disabled(
        self, client: AsyncClient
    ) -> None:
        """Disable intent detection flag — POST /intent/detect returns 403."""
        from config import settings as _s

        _s.intent_detection_enabled = False
        resp = await client.post(
            "/intent/detect",
            headers={"X-Api-Key": "viewer-key"},
            json={"text": "test"},
        )
        assert resp.status_code == 403
        _s.intent_detection_enabled = True


# ---------------------------------------------------------------------------
# 53. Resolution Prediction Tests
# ---------------------------------------------------------------------------


class TestResolutionPrediction:
    """Tests for resolution time prediction and stats."""

    @pytest.mark.asyncio
    async def test_predict_resolution_time(self, client: AsyncClient) -> None:
        """GET /analytics/resolution-prediction/{id} — 200 with prediction."""
        ticket_id = await _create_test_ticket(client, "RP-001")
        resp = await client.get(
            f"/analytics/resolution-prediction/{ticket_id}",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        prediction = data["prediction"]
        assert "predicted_hours" in prediction
        assert "confidence" in prediction
        assert "factors" in prediction

    @pytest.mark.asyncio
    async def test_predict_resolution_ticket_not_found(
        self, client: AsyncClient
    ) -> None:
        """GET /analytics/resolution-prediction/nonexistent — 404."""
        resp = await client.get(
            "/analytics/resolution-prediction/nonexistent",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_resolution_stats(self, client: AsyncClient) -> None:
        """GET /analytics/resolution-stats — 200 with stats."""
        resp = await client.get(
            "/analytics/resolution-stats",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "avg_resolution_hours" in data
        assert "total_resolved" in data

    @pytest.mark.asyncio
    async def test_resolution_prediction_feature_flag_disabled(
        self, client: AsyncClient
    ) -> None:
        """Disable resolution prediction flag — endpoint returns 403."""
        from config import settings as _s

        ticket_id = await _create_test_ticket(client, "RP-FLAG")
        _s.resolution_prediction_enabled = False
        resp = await client.get(
            f"/analytics/resolution-prediction/{ticket_id}",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403
        _s.resolution_prediction_enabled = True

    @pytest.mark.asyncio
    async def test_resolution_prediction_factors(
        self, client: AsyncClient
    ) -> None:
        """Verify prediction includes a factors list."""
        ticket_id = await _create_test_ticket(client, "RP-FACT")
        resp = await client.get(
            f"/analytics/resolution-prediction/{ticket_id}",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        factors = resp.json()["prediction"]["factors"]
        assert isinstance(factors, list)

    @pytest.mark.asyncio
    async def test_resolution_stats_structure(self, client: AsyncClient) -> None:
        """Verify resolution stats response has by_category and by_priority."""
        resp = await client.get(
            "/analytics/resolution-stats",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "by_category" in data
        assert "by_priority" in data
        assert isinstance(data["by_category"], dict)
        assert isinstance(data["by_priority"], dict)


# ---------------------------------------------------------------------------
# 54. Satisfaction Prediction Tests
# ---------------------------------------------------------------------------


class TestSatisfactionPrediction:
    """Tests for satisfaction prediction and trends."""

    @pytest.mark.asyncio
    async def test_predict_satisfaction(self, client: AsyncClient) -> None:
        """GET /analytics/satisfaction-prediction/{id} — 200 with prediction."""
        ticket_id = await _create_test_ticket(client, "SP-001")
        resp = await client.get(
            f"/analytics/satisfaction-prediction/{ticket_id}",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        prediction = data["prediction"]
        assert "predicted_score" in prediction
        assert "confidence" in prediction
        assert "risk_level" in prediction

    @pytest.mark.asyncio
    async def test_predict_satisfaction_ticket_not_found(
        self, client: AsyncClient
    ) -> None:
        """GET /analytics/satisfaction-prediction/nonexistent — 404."""
        resp = await client.get(
            "/analytics/satisfaction-prediction/nonexistent",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_satisfaction_trends(self, client: AsyncClient) -> None:
        """GET /analytics/satisfaction-trends — 200 with trends."""
        resp = await client.get(
            "/analytics/satisfaction-trends",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "avg_score" in data
        assert "trend_direction" in data
        assert "total_ratings" in data

    @pytest.mark.asyncio
    async def test_satisfaction_prediction_feature_flag_disabled(
        self, client: AsyncClient
    ) -> None:
        """Disable satisfaction prediction flag — endpoint returns 403."""
        from config import settings as _s

        ticket_id = await _create_test_ticket(client, "SP-FLAG")
        _s.satisfaction_prediction_enabled = False
        resp = await client.get(
            f"/analytics/satisfaction-prediction/{ticket_id}",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403
        _s.satisfaction_prediction_enabled = True

    @pytest.mark.asyncio
    async def test_satisfaction_prediction_factors(
        self, client: AsyncClient
    ) -> None:
        """Verify prediction includes a factors list."""
        ticket_id = await _create_test_ticket(client, "SP-FACT")
        resp = await client.get(
            f"/analytics/satisfaction-prediction/{ticket_id}",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        factors = resp.json()["prediction"]["factors"]
        assert isinstance(factors, list)

    @pytest.mark.asyncio
    async def test_satisfaction_risk_level(self, client: AsyncClient) -> None:
        """Verify risk_level is one of low / medium / high."""
        ticket_id = await _create_test_ticket(client, "SP-RISK")
        resp = await client.get(
            f"/analytics/satisfaction-prediction/{ticket_id}",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        risk = resp.json()["prediction"]["risk_level"]
        assert risk in ("low", "medium", "high")


# ---------------------------------------------------------------------------
# 55. Smart Assignment Tests
# ---------------------------------------------------------------------------


class TestSmartAssignment:
    """Tests for agent profiles, smart assignment, and performance matrix."""

    @pytest.mark.asyncio
    async def test_smart_assign_no_agents(self, client: AsyncClient) -> None:
        """POST /tickets/{id}/smart-assign with no agent profiles — 404."""
        ticket_id = await _create_test_ticket(client, "SA-NONE")
        resp = await client.post(
            f"/tickets/{ticket_id}/smart-assign",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_agent_profile(self, client: AsyncClient) -> None:
        """POST /agent-profiles — create an agent profile."""
        resp = await client.post(
            "/agent-profiles",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "agent_id": "agent-001",
                "name": "Alice Smith",
                "specialisations": ["network", "hardware"],
                "max_capacity": 10,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile"]["agent_id"] == "agent-001"

    @pytest.mark.asyncio
    async def test_list_agent_profiles(self, client: AsyncClient) -> None:
        """Create profile then GET /agent-profiles — verify listing."""
        await client.post(
            "/agent-profiles",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "agent_id": "agent-list-001",
                "name": "Bob Builder",
                "specialisations": ["software"],
                "max_capacity": 5,
            },
        )
        resp = await client.get(
            "/agent-profiles",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_create_agent_profile_upsert(
        self, client: AsyncClient
    ) -> None:
        """POST /agent-profiles twice with same agent_id — upsert, no error."""
        payload = {
            "agent_id": "agent-upsert",
            "name": "Upsert Agent",
            "specialisations": ["general"],
            "max_capacity": 8,
        }
        resp1 = await client.post(
            "/agent-profiles",
            headers={"X-Api-Key": "analyst-key"},
            json=payload,
        )
        assert resp1.status_code == 200

        payload["name"] = "Upsert Agent Updated"
        resp2 = await client.post(
            "/agent-profiles",
            headers={"X-Api-Key": "analyst-key"},
            json=payload,
        )
        assert resp2.status_code == 200
        assert resp2.json()["profile"]["name"] == "Upsert Agent Updated"

    @pytest.mark.asyncio
    async def test_smart_assign_ticket(self, client: AsyncClient) -> None:
        """Create agent + ticket, POST /tickets/{id}/smart-assign — 200."""
        await client.post(
            "/agent-profiles",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "agent_id": "agent-assign",
                "name": "Assign Agent",
                "specialisations": ["general", "hardware"],
                "max_capacity": 10,
            },
        )
        ticket_id = await _create_test_ticket(client, "SA-001")
        resp = await client.post(
            f"/tickets/{ticket_id}/smart-assign",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assignment = data["assignment"]
        assert "recommended_agent_id" in assignment
        assert assignment["score"] > 0
        assert isinstance(assignment["reasons"], list)

    @pytest.mark.asyncio
    async def test_smart_assign_ticket_not_found(
        self, client: AsyncClient
    ) -> None:
        """POST /tickets/nonexistent/smart-assign — 404."""
        resp = await client.post(
            "/tickets/nonexistent/smart-assign",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_agent_performance_matrix(self, client: AsyncClient) -> None:
        """Create agent profiles, GET /analytics/agent-performance-matrix."""
        await client.post(
            "/agent-profiles",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "agent_id": "agent-perf-001",
                "name": "Performance Agent",
                "specialisations": ["network"],
                "max_capacity": 10,
            },
        )
        resp = await client.get(
            "/analytics/agent-performance-matrix",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert isinstance(data["agents"], list)

    @pytest.mark.asyncio
    async def test_smart_assignment_rbac_viewer_cannot_create(
        self, client: AsyncClient
    ) -> None:
        """POST /agent-profiles with viewer-key — 403."""
        resp = await client.post(
            "/agent-profiles",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "agent_id": "agent-viewer",
                "name": "Viewer Agent",
                "specialisations": [],
                "max_capacity": 5,
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_smart_assignment_feature_flag_disabled(
        self, client: AsyncClient
    ) -> None:
        """Disable smart assignment flag — POST /agent-profiles returns 403."""
        from config import settings as _s

        _s.smart_assignment_enabled = False
        resp = await client.post(
            "/agent-profiles",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "agent_id": "agent-flag",
                "name": "Flag Agent",
                "specialisations": [],
                "max_capacity": 5,
            },
        )
        assert resp.status_code == 403
        _s.smart_assignment_enabled = True

    @pytest.mark.asyncio
    async def test_smart_assign_specialisation_match(
        self, client: AsyncClient
    ) -> None:
        """Agent with matching specialisation gets a score for the ticket."""
        await client.post(
            "/agent-profiles",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "agent_id": "agent-spec-match",
                "name": "Specialist Agent",
                "specialisations": ["general", "software", "hardware"],
                "max_capacity": 10,
            },
        )
        ticket_id = await _create_test_ticket(client, "SA-SPEC")
        resp = await client.post(
            f"/tickets/{ticket_id}/smart-assign",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        assignment = resp.json()["assignment"]
        assert assignment["score"] > 0
        assert assignment["recommended_agent_id"] == "agent-spec-match"
