"""
TicketForge — Test suite for Phase 3 features
Tests for Chatbot, Model Monitoring, Plugin System, and Self-Service Portal.
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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase3.db"
os.environ["EMAIL_INGESTION_ENABLED"] = "true"
os.environ["CHATBOT_ENABLED"] = "true"
os.environ["PORTAL_ENABLED"] = "true"
os.environ["MONITORING_ENABLED"] = "true"

from main import app, lifespan  # noqa: E402
from models import (  # noqa: E402
    ChatMessage,
    ChatRequest,
    ChatResponse,
    DriftMetric,
    MonitoringResponse,
    PluginInfo,
    PluginListResponse,
    PortalTicketResponse,
    PortalTicketSubmission,
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


# ── Chatbot tests ────────────────────────────────────────────────────────────

class TestChatbot:
    """Test the POST /chat chatbot endpoint."""

    @pytest.mark.asyncio
    async def test_chat_greeting(self, client):
        """Chatbot responds to a greeting message."""
        response = await client.post(
            "/chat",
            headers={"X-Api-Key": "viewer-key"},
            json={"message": "Hello"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["session_id"] != ""
        assert len(data["reply"]) > 0
        assert data["intent"] == "general"

    @pytest.mark.asyncio
    async def test_chat_create_ticket_intent(self, client):
        """Chatbot detects create_ticket intent."""
        response = await client.post(
            "/chat",
            headers={"X-Api-Key": "viewer-key"},
            json={"message": "I want to create a ticket for my broken laptop"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "create_ticket"

    @pytest.mark.asyncio
    async def test_chat_check_status_intent(self, client):
        """Chatbot detects check_status intent."""
        response = await client.post(
            "/chat",
            headers={"X-Api-Key": "viewer-key"},
            json={"message": "Can you check the status of my ticket TF-123?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "check_status"

    @pytest.mark.asyncio
    async def test_chat_search_kb_intent(self, client):
        """Chatbot detects search_kb intent."""
        response = await client.post(
            "/chat",
            headers={"X-Api-Key": "viewer-key"},
            json={"message": "How to reset my VPN connection?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "search_kb"

    @pytest.mark.asyncio
    async def test_chat_multi_turn_session(self, client):
        """Multi-turn conversations preserve session ID."""
        # First message
        r1 = await client.post(
            "/chat",
            headers={"X-Api-Key": "viewer-key"},
            json={"message": "Hello"},
        )
        session_id = r1.json()["session_id"]
        assert session_id != ""

        # Second message with same session
        r2 = await client.post(
            "/chat",
            headers={"X-Api-Key": "viewer-key"},
            json={"message": "I need to create a ticket", "session_id": session_id},
        )
        assert r2.json()["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_chat_requires_auth(self, client):
        """Chat endpoint requires authentication."""
        response = await client.post(
            "/chat",
            json={"message": "Hello"},
        )
        assert response.status_code == 422 or response.status_code == 401

    @pytest.mark.asyncio
    async def test_chat_requires_message(self, client):
        """Chat endpoint requires a non-empty message."""
        response = await client.post(
            "/chat",
            headers={"X-Api-Key": "viewer-key"},
            json={"message": ""},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_help_intent(self, client):
        """Chatbot responds to help request."""
        response = await client.post(
            "/chat",
            headers={"X-Api-Key": "viewer-key"},
            json={"message": "help"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "general"
        assert len(data["suggested_actions"]) > 0

    @pytest.mark.asyncio
    async def test_chat_with_context(self, client):
        """Chatbot accepts optional context."""
        response = await client.post(
            "/chat",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "message": "Check the status of my ticket",
                "context": {"ticket_id": "TF-abc123"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "check_status"


class TestChatbotModels:
    """Test chatbot Pydantic models."""

    def test_chat_message_model(self):
        msg = ChatMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.timestamp is not None

    def test_chat_request_model(self):
        req = ChatRequest(message="Hello")
        assert req.message == "Hello"
        assert req.session_id == ""
        assert req.context == {}

    def test_chat_request_with_session(self):
        req = ChatRequest(message="Hello", session_id="test-123")
        assert req.session_id == "test-123"

    def test_chat_response_model(self):
        resp = ChatResponse(session_id="test-123", reply="Hi there!")
        assert resp.success is True
        assert resp.session_id == "test-123"
        assert resp.reply == "Hi there!"
        assert resp.intent == "general"
        assert resp.suggested_actions == []
        assert resp.data == {}


# ── Chatbot module unit tests ────────────────────────────────────────────────

class TestChatbotModule:
    """Test the chatbot module directly."""

    def test_detect_intent_create_ticket(self):
        from chatbot import detect_intent  # noqa: PLC0415
        assert detect_intent("I want to create a ticket") == "create_ticket"
        assert detect_intent("Something is broken") == "create_ticket"
        assert detect_intent("My printer is not working") == "create_ticket"

    def test_detect_intent_check_status(self):
        from chatbot import detect_intent  # noqa: PLC0415
        assert detect_intent("Check status of my ticket") == "check_status"
        assert detect_intent("Where is my ticket?") == "check_status"
        assert detect_intent("Any update on ticket 123?") == "check_status"

    def test_detect_intent_search_kb(self):
        from chatbot import detect_intent  # noqa: PLC0415
        assert detect_intent("How to reset my password") == "search_kb"
        assert detect_intent("Find article about VPN") == "search_kb"
        assert detect_intent("What is LDAP?") == "search_kb"

    def test_detect_intent_general(self):
        from chatbot import detect_intent  # noqa: PLC0415
        assert detect_intent("Hello there") == "general"
        assert detect_intent("Thanks for your help") == "general"

    def test_session_management(self):
        from chatbot import (  # noqa: PLC0415
            _sessions,
            add_message,
            clear_session,
            get_history,
            get_or_create_session,
        )
        sid = get_or_create_session("")
        assert sid.startswith("chat-")
        add_message(sid, "user", "Hello")
        assert len(get_history(sid)) == 1
        assert get_history(sid)[0]["role"] == "user"
        assert clear_session(sid) is True
        assert clear_session(sid) is False

    def test_generate_response_general(self):
        from chatbot import generate_response, get_or_create_session  # noqa: PLC0415
        sid = get_or_create_session("")
        result = generate_response("general", "Hello", sid)
        assert "reply" in result
        assert "intent" in result
        assert result["intent"] == "general"

    def test_generate_response_search_kb(self):
        from chatbot import generate_response, get_or_create_session  # noqa: PLC0415
        sid = get_or_create_session("")
        result = generate_response("search_kb", "How to fix VPN", sid)
        assert result["intent"] == "search_kb"
        assert "data" in result
        assert "query" in result["data"]


# ── Model monitoring tests ───────────────────────────────────────────────────

class TestModelMonitoring:
    """Test the GET /monitoring/drift endpoint."""

    @pytest.mark.asyncio
    async def test_monitoring_drift_returns_metrics(self, client):
        """Drift endpoint returns monitoring metrics."""
        response = await client.get(
            "/monitoring/drift",
            headers={"X-Api-Key": "admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "metrics" in data
        assert "overall_health" in data
        assert data["overall_health"] in ("healthy", "warning", "degraded")

    @pytest.mark.asyncio
    async def test_monitoring_drift_requires_admin(self, client):
        """Drift endpoint requires admin role."""
        response = await client.get(
            "/monitoring/drift",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_monitoring_drift_analyst_forbidden(self, client):
        """Drift endpoint forbids analyst role."""
        response = await client.get(
            "/monitoring/drift",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_monitoring_drift_no_auth(self, client):
        """Drift endpoint requires authentication."""
        response = await client.get("/monitoring/drift")
        assert response.status_code == 422 or response.status_code == 401

    @pytest.mark.asyncio
    async def test_monitoring_drift_has_fields(self, client):
        """Drift metrics include category, priority, and sentiment fields."""
        response = await client.get(
            "/monitoring/drift",
            headers={"X-Api-Key": "admin-key"},
        )
        data = response.json()
        field_names = [m["field"] for m in data["metrics"]]
        assert "category" in field_names
        assert "priority" in field_names
        assert "sentiment" in field_names


class TestMonitoringModels:
    """Test monitoring Pydantic models."""

    def test_drift_metric_model(self):
        metric = DriftMetric(field="category", drift_score=0.5, is_drifting=True)
        assert metric.field == "category"
        assert metric.drift_score == 0.5
        assert metric.is_drifting is True
        assert metric.current_distribution == {}
        assert metric.baseline_distribution == {}

    def test_monitoring_response_model(self):
        resp = MonitoringResponse()
        assert resp.success is True
        assert resp.metrics == []
        assert resp.total_tickets_analysed == 0
        assert resp.overall_health == "healthy"


class TestMonitoringModule:
    """Test the monitoring module directly."""

    def test_compute_distribution(self):
        from monitoring import compute_distribution  # noqa: PLC0415
        dist = compute_distribution(["a", "a", "b", "c"])
        assert dist["a"] == 0.5
        assert dist["b"] == 0.25
        assert dist["c"] == 0.25

    def test_compute_distribution_empty(self):
        from monitoring import compute_distribution  # noqa: PLC0415
        assert compute_distribution([]) == {}

    def test_compute_drift_score_identical(self):
        from monitoring import compute_drift_score  # noqa: PLC0415
        d = {"a": 0.5, "b": 0.5}
        assert compute_drift_score(d, d) == 0.0

    def test_compute_drift_score_completely_different(self):
        from monitoring import compute_drift_score  # noqa: PLC0415
        d1 = {"a": 1.0}
        d2 = {"b": 1.0}
        assert compute_drift_score(d1, d2) == 1.0

    def test_compute_drift_score_partial(self):
        from monitoring import compute_drift_score  # noqa: PLC0415
        d1 = {"a": 0.5, "b": 0.5}
        d2 = {"a": 0.7, "b": 0.3}
        score = compute_drift_score(d1, d2)
        assert 0.0 < score < 1.0

    def test_compute_drift_score_empty_baseline(self):
        from monitoring import compute_drift_score  # noqa: PLC0415
        assert compute_drift_score({}, {"a": 1.0}) == 1.0

    def test_compute_drift_score_both_empty(self):
        from monitoring import compute_drift_score  # noqa: PLC0415
        assert compute_drift_score({}, {}) == 0.0


# ── Plugin system tests ──────────────────────────────────────────────────────

class TestPluginSystem:
    """Test the GET /plugins endpoint."""

    @pytest.mark.asyncio
    async def test_list_plugins_empty(self, client):
        """Listing plugins returns empty list when none registered."""
        response = await client.get(
            "/plugins",
            headers={"X-Api-Key": "admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["plugins"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_plugins_requires_admin(self, client):
        """Plugins endpoint requires admin role."""
        response = await client.get(
            "/plugins",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_plugins_analyst_forbidden(self, client):
        """Plugins endpoint forbids analyst role."""
        response = await client.get(
            "/plugins",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert response.status_code == 403


class TestPluginModels:
    """Test plugin Pydantic models."""

    def test_plugin_info_model(self):
        info = PluginInfo(name="test-plugin", hook="pre_analysis")
        assert info.name == "test-plugin"
        assert info.version == "0.1.0"
        assert info.description == ""
        assert info.hook == "pre_analysis"
        assert info.enabled is True

    def test_plugin_list_response_model(self):
        resp = PluginListResponse()
        assert resp.success is True
        assert resp.plugins == []
        assert resp.total == 0


class TestPluginModule:
    """Test the plugin module directly."""

    @pytest.mark.asyncio
    async def test_plugin_registration(self):
        from plugin_system import Plugin, PluginRegistry  # noqa: PLC0415

        class TestPlugin(Plugin):
            @property
            def name(self):
                return "test-plugin"

            @property
            def hook(self):
                return "pre_analysis"

            @property
            def description(self):
                return "A test plugin"

        registry = PluginRegistry()
        plugin = TestPlugin()
        registry.register(plugin)

        plugins = registry.list_plugins()
        assert len(plugins) == 1
        assert plugins[0]["name"] == "test-plugin"
        assert plugins[0]["enabled"] is True

    @pytest.mark.asyncio
    async def test_plugin_enable_disable(self):
        from plugin_system import Plugin, PluginRegistry  # noqa: PLC0415

        class TestPlugin(Plugin):
            @property
            def name(self):
                return "toggle-plugin"

            @property
            def hook(self):
                return "post_analysis"

        registry = PluginRegistry()
        registry.register(TestPlugin())
        assert registry.is_enabled("toggle-plugin") is True

        registry.disable("toggle-plugin")
        assert registry.is_enabled("toggle-plugin") is False

        registry.enable("toggle-plugin")
        assert registry.is_enabled("toggle-plugin") is True

    @pytest.mark.asyncio
    async def test_plugin_unregister(self):
        from plugin_system import Plugin, PluginRegistry  # noqa: PLC0415

        class TestPlugin(Plugin):
            @property
            def name(self):
                return "removable-plugin"

            @property
            def hook(self):
                return "pre_analysis"

        registry = PluginRegistry()
        registry.register(TestPlugin())
        assert len(registry.list_plugins()) == 1

        assert registry.unregister("removable-plugin") is True
        assert len(registry.list_plugins()) == 0
        assert registry.unregister("nonexistent") is False

    @pytest.mark.asyncio
    async def test_plugin_hook_execution(self):
        from plugin_system import Plugin, PluginRegistry  # noqa: PLC0415

        class EnrichPlugin(Plugin):
            @property
            def name(self):
                return "enrich-plugin"

            @property
            def hook(self):
                return "post_analysis"

            async def on_post_analysis(self, data):
                data["custom_field"] = "enriched"
                return data

        registry = PluginRegistry()
        registry.register(EnrichPlugin())

        result = await registry.run_post_analysis({"ticket_id": "123"})
        assert result["custom_field"] == "enriched"
        assert result["ticket_id"] == "123"

    @pytest.mark.asyncio
    async def test_plugin_disabled_not_executed(self):
        from plugin_system import Plugin, PluginRegistry  # noqa: PLC0415

        class SkipPlugin(Plugin):
            @property
            def name(self):
                return "skip-plugin"

            @property
            def hook(self):
                return "pre_analysis"

            async def on_pre_analysis(self, data):
                data["should_not_exist"] = True
                return data

        registry = PluginRegistry()
        registry.register(SkipPlugin())
        registry.disable("skip-plugin")

        result = await registry.run_pre_analysis({"ticket_id": "123"})
        assert "should_not_exist" not in result

    @pytest.mark.asyncio
    async def test_plugin_error_isolation(self):
        from plugin_system import Plugin, PluginRegistry  # noqa: PLC0415

        class BrokenPlugin(Plugin):
            @property
            def name(self):
                return "broken-plugin"

            @property
            def hook(self):
                return "pre_analysis"

            async def on_pre_analysis(self, data):
                raise RuntimeError("Plugin crashed!")

        class GoodPlugin(Plugin):
            @property
            def name(self):
                return "good-plugin"

            @property
            def hook(self):
                return "pre_analysis"

            async def on_pre_analysis(self, data):
                data["processed"] = True
                return data

        registry = PluginRegistry()
        registry.register(BrokenPlugin())
        registry.register(GoodPlugin())

        # Broken plugin should not prevent good plugin from running
        result = await registry.run_pre_analysis({"ticket_id": "123"})
        assert result.get("processed") is True


# ── Self-Service Portal tests ────────────────────────────────────────────────

class TestPortal:
    """Test the self-service portal endpoints."""

    @pytest.mark.asyncio
    async def test_portal_html_returns_page(self, client):
        """GET /portal returns HTML page."""
        response = await client.get("/portal")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "TicketForge Portal" in response.text

    @pytest.mark.asyncio
    async def test_portal_html_contains_tabs(self, client):
        """Portal page contains all tab sections."""
        response = await client.get("/portal")
        assert "Submit Ticket" in response.text
        assert "Check Status" in response.text
        assert "Knowledge Base" in response.text
        assert "Chat Assistant" in response.text

    @pytest.mark.asyncio
    async def test_portal_submit_ticket(self, client):
        """POST /portal/tickets creates a ticket."""
        response = await client.post(
            "/portal/tickets",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "title": "My laptop won't boot",
                "description": "Laptop shows black screen after power button press.",
                "reporter_email": "user@company.com",
                "category": "Hardware",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["ticket_id"].startswith("PORTAL-")
        assert "submitted" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_portal_submit_requires_title(self, client):
        """Portal ticket submission requires a title."""
        response = await client.post(
            "/portal/tickets",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "title": "",
                "reporter_email": "user@company.com",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_portal_submit_requires_email(self, client):
        """Portal ticket submission requires reporter email."""
        response = await client.post(
            "/portal/tickets",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "title": "Test issue",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_portal_submit_requires_auth(self, client):
        """Portal ticket submission requires authentication."""
        response = await client.post(
            "/portal/tickets",
            json={
                "title": "Test",
                "reporter_email": "user@test.com",
            },
        )
        assert response.status_code == 422 or response.status_code == 401

    @pytest.mark.asyncio
    async def test_portal_ticket_can_be_looked_up(self, client):
        """Submitted portal ticket can be retrieved via /tickets/{id}."""
        # Submit a ticket
        r1 = await client.post(
            "/portal/tickets",
            headers={"X-Api-Key": "viewer-key"},
            json={
                "title": "Network issue",
                "reporter_email": "user@company.com",
            },
        )
        ticket_id = r1.json()["ticket_id"]

        # Look it up
        r2 = await client.get(
            f"/tickets/{ticket_id}",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["ticket_id"] == ticket_id
        assert data["ticket_status"] == "open"


class TestPortalModels:
    """Test portal Pydantic models."""

    def test_portal_ticket_submission_model(self):
        sub = PortalTicketSubmission(
            title="Test Issue",
            reporter_email="user@test.com",
        )
        assert sub.title == "Test Issue"
        assert sub.reporter_email == "user@test.com"
        assert sub.description == ""
        assert sub.category == ""

    def test_portal_ticket_response_model(self):
        resp = PortalTicketResponse(ticket_id="PORTAL-abc123")
        assert resp.success is True
        assert resp.ticket_id == "PORTAL-abc123"
        assert "submitted" in resp.message.lower()
        assert resp.suggested_articles == []


# ── Config tests ─────────────────────────────────────────────────────────────

class TestPhase3Config:
    """Test Phase 3 configuration settings."""

    def test_chatbot_enabled_default(self):
        from config import Settings  # noqa: PLC0415
        s = Settings(api_keys=["test"])
        assert s.chatbot_enabled is True

    def test_portal_enabled_default(self):
        from config import Settings  # noqa: PLC0415
        s = Settings(api_keys=["test"])
        assert s.portal_enabled is True

    def test_monitoring_enabled_default(self):
        from config import Settings  # noqa: PLC0415
        s = Settings(api_keys=["test"])
        assert s.monitoring_enabled is True

    def test_monitoring_baseline_days_default(self):
        from config import Settings  # noqa: PLC0415
        s = Settings(api_keys=["test"])
        assert s.monitoring_baseline_days == 30

    def test_monitoring_window_days_default(self):
        from config import Settings  # noqa: PLC0415
        s = Settings(api_keys=["test"])
        assert s.monitoring_window_days == 7

    def test_drift_threshold_default(self):
        from config import Settings  # noqa: PLC0415
        s = Settings(api_keys=["test"])
        assert s.drift_threshold == 0.3

    def test_chatbot_max_history_default(self):
        from config import Settings  # noqa: PLC0415
        s = Settings(api_keys=["test"])
        assert s.chatbot_max_history == 20
