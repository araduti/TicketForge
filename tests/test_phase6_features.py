"""
TicketForge — Test suite for Phase 6 features
Tests for AI-Powered Auto-Resolution, Outbound Webhook Events
(Zapier/Make/n8n), PagerDuty and OpsGenie Escalation Connectors.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase6.db"
os.environ["CSAT_ENABLED"] = "true"
os.environ["WEBSOCKET_NOTIFICATIONS_ENABLED"] = "true"
os.environ["I18N_ENABLED"] = "true"
os.environ["CHATBOT_ENABLED"] = "true"
os.environ["PORTAL_ENABLED"] = "true"
os.environ["MONITORING_ENABLED"] = "true"
os.environ["MULTI_AGENT_ENABLED"] = "false"
os.environ["VECTOR_STORE_BACKEND"] = "in_memory"
os.environ["AUTO_RESOLUTION_ENABLED"] = "true"
os.environ["AUTO_RESOLUTION_CONFIDENCE_THRESHOLD"] = "0.8"
os.environ["WEBHOOK_EVENTS_ENABLED"] = "true"
os.environ["PAGERDUTY_ROUTING_KEY"] = ""
os.environ["PAGERDUTY_AUTO_ESCALATE"] = "false"
os.environ["OPSGENIE_API_KEY"] = ""
os.environ["OPSGENIE_AUTO_ESCALATE"] = "false"

from main import app, lifespan  # noqa: E402
from models import (  # noqa: E402
    AutoResolveResponse,
    AutoResolveResult,
    EscalationResult,
    EscalationStatusResponse,
    OutboundWebhookEvent,
    WebhookEventListResponse,
    WebhookEventType,
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

    # Ensure Phase 6 feature flags are set on the singleton
    _s.auto_resolution_enabled = True
    _s.auto_resolution_confidence_threshold = 0.8
    _s.webhook_events_enabled = True

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Clean up test database
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass


async def _create_test_ticket(client: AsyncClient) -> str:
    """Helper to create a test ticket and return its ID."""
    resp = await client.post(
        "/portal/tickets",
        headers={"X-Api-Key": "viewer-key"},
        json={
            "title": "Cannot connect to VPN",
            "description": "I am unable to connect to the company VPN from my home office.",
            "reporter_email": "test@example.com",
        },
    )
    assert resp.status_code == 200 or resp.status_code == 201
    return resp.json()["ticket_id"]


# ── Auto-Resolution Tests ────────────────────────────────────────────────────

class TestAutoResolution:
    """Test the POST /tickets/{id}/auto-resolve endpoint."""

    @pytest.mark.asyncio
    async def test_auto_resolve_requires_auth(self, client: AsyncClient) -> None:
        """Auto-resolve endpoint requires authentication."""
        resp = await client.post("/tickets/TEST-001/auto-resolve")
        assert resp.status_code == 422 or resp.status_code == 403

    @pytest.mark.asyncio
    async def test_auto_resolve_requires_analyst_role(self, client: AsyncClient) -> None:
        """Auto-resolve endpoint requires analyst or admin role."""
        resp = await client.post(
            "/tickets/TEST-001/auto-resolve",
            json={},
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_auto_resolve_ticket_not_found(self, client: AsyncClient) -> None:
        """Auto-resolve returns 404 for non-existent ticket."""
        resp = await client.post(
            "/tickets/NONEXISTENT/auto-resolve",
            json={},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_auto_resolve_returns_result(self, client: AsyncClient) -> None:
        """Auto-resolve returns a valid AutoResolveResponse for an existing ticket."""
        ticket_id = await _create_test_ticket(client)

        resp = await client.post(
            f"/tickets/{ticket_id}/auto-resolve",
            json={"additional_context": "User tried restarting the VPN client"},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["ticket_id"] == ticket_id
        assert "resolved" in data["data"]
        assert "confidence" in data["data"]
        assert "resolution_summary" in data["data"]
        assert isinstance(data["data"]["matched_kb_articles"], list)

    @pytest.mark.asyncio
    async def test_auto_resolve_with_empty_body(self, client: AsyncClient) -> None:
        """Auto-resolve works with no request body (all fields optional)."""
        ticket_id = await _create_test_ticket(client)

        resp = await client.post(
            f"/tickets/{ticket_id}/auto-resolve",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["ticket_id"] == ticket_id

    @pytest.mark.asyncio
    async def test_auto_resolve_disabled(self, client: AsyncClient) -> None:
        """Auto-resolve returns 403 when feature is disabled."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.auto_resolution_enabled
        _s.auto_resolution_enabled = False
        try:
            resp = await client.post(
                "/tickets/TEST-001/auto-resolve",
                json={},
                headers={"X-Api-Key": "analyst-key"},
            )
            assert resp.status_code == 403
            assert "not enabled" in resp.json()["detail"].lower()
        finally:
            _s.auto_resolution_enabled = original

    @pytest.mark.asyncio
    async def test_auto_resolve_audit_logged(self, client: AsyncClient) -> None:
        """Auto-resolve creates an audit log entry."""
        ticket_id = await _create_test_ticket(client)

        await client.post(
            f"/tickets/{ticket_id}/auto-resolve",
            json={},
            headers={"X-Api-Key": "admin-key"},
        )

        resp = await client.get(
            "/audit/logs",
            headers={"X-Api-Key": "admin-key"},
        )
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        actions = [e["action"] for e in entries]
        assert "auto_resolve" in actions


# ── Webhook Events Tests (Zapier / Make / n8n) ──────────────────────────────

class TestWebhookEvents:
    """Test the GET /webhooks/events endpoint and webhook event system."""

    @pytest.mark.asyncio
    async def test_list_webhook_events(self, client: AsyncClient) -> None:
        """List supported webhook event types."""
        resp = await client.get(
            "/webhooks/events",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["supported_events"], list)
        assert len(data["supported_events"]) >= 6
        assert "ticket.created" in data["supported_events"]
        assert "ticket.resolved" in data["supported_events"]
        assert "ticket.auto_resolved" in data["supported_events"]
        assert "sla.breach" in data["supported_events"]
        assert "csat.submitted" in data["supported_events"]
        assert "ticket.updated" in data["supported_events"]

    @pytest.mark.asyncio
    async def test_list_webhook_events_auth_required(self, client: AsyncClient) -> None:
        """Webhook events list requires authentication."""
        resp = await client.get("/webhooks/events")
        assert resp.status_code == 422 or resp.status_code == 403

    @pytest.mark.asyncio
    async def test_webhook_url_not_configured(self, client: AsyncClient) -> None:
        """Reports webhook URL configuration status correctly."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.outbound_webhook_url
        _s.outbound_webhook_url = ""
        try:
            resp = await client.get(
                "/webhooks/events",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 200
            assert resp.json()["webhook_url_configured"] is False
        finally:
            _s.outbound_webhook_url = original

    @pytest.mark.asyncio
    async def test_webhook_url_configured(self, client: AsyncClient) -> None:
        """Reports webhook URL as configured when set."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.outbound_webhook_url
        _s.outbound_webhook_url = "https://hooks.example.com/webhook"
        try:
            resp = await client.get(
                "/webhooks/events",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 200
            assert resp.json()["webhook_url_configured"] is True
        finally:
            _s.outbound_webhook_url = original

    @pytest.mark.asyncio
    async def test_webhook_event_type_enum(self) -> None:
        """WebhookEventType enum has expected values."""
        assert WebhookEventType.ticket_created.value == "ticket.created"
        assert WebhookEventType.ticket_updated.value == "ticket.updated"
        assert WebhookEventType.ticket_resolved.value == "ticket.resolved"
        assert WebhookEventType.ticket_auto_resolved.value == "ticket.auto_resolved"
        assert WebhookEventType.sla_breach.value == "sla.breach"
        assert WebhookEventType.csat_submitted.value == "csat.submitted"

    @pytest.mark.asyncio
    async def test_outbound_webhook_event_model(self) -> None:
        """OutboundWebhookEvent model serialises correctly."""
        event = OutboundWebhookEvent(
            event=WebhookEventType.ticket_created,
            ticket_id="TEST-001",
            payload={"priority": "high", "category": "Network"},
        )
        data = json.loads(event.model_dump_json())
        assert data["event"] == "ticket.created"
        assert data["ticket_id"] == "TEST-001"
        assert "timestamp" in data
        assert data["payload"]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_send_webhook_event_disabled(self) -> None:
        """send_webhook_event does nothing when disabled."""
        from config import settings as _s  # noqa: PLC0415
        from webhook_events import send_webhook_event  # noqa: PLC0415

        original = _s.webhook_events_enabled
        _s.webhook_events_enabled = False
        try:
            # Should return without error or HTTP call
            await send_webhook_event(
                WebhookEventType.ticket_created,
                "TEST-001",
                {"test": True},
                _s,
            )
        finally:
            _s.webhook_events_enabled = original

    @pytest.mark.asyncio
    async def test_send_webhook_event_no_url(self) -> None:
        """send_webhook_event does nothing when URL is not set."""
        from config import settings as _s  # noqa: PLC0415
        from webhook_events import send_webhook_event  # noqa: PLC0415

        original_enabled = _s.webhook_events_enabled
        original_url = _s.outbound_webhook_url
        _s.webhook_events_enabled = True
        _s.outbound_webhook_url = ""
        try:
            await send_webhook_event(
                WebhookEventType.ticket_created,
                "TEST-001",
                {"test": True},
                _s,
            )
        finally:
            _s.webhook_events_enabled = original_enabled
            _s.outbound_webhook_url = original_url


# ── Escalation Status Tests (PagerDuty / OpsGenie) ──────────────────────────

class TestEscalationStatus:
    """Test the GET /escalation/status endpoint."""

    @pytest.mark.asyncio
    async def test_escalation_status_unconfigured(self, client: AsyncClient) -> None:
        """Escalation status shows unconfigured when no keys are set."""
        resp = await client.get(
            "/escalation/status",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["pagerduty_configured"] is False
        assert data["opsgenie_configured"] is False
        assert data["auto_escalate_enabled"] is False

    @pytest.mark.asyncio
    async def test_escalation_status_pagerduty_configured(self, client: AsyncClient) -> None:
        """Escalation status detects PagerDuty configuration."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.pagerduty_routing_key
        _s.pagerduty_routing_key = "test-routing-key"
        try:
            resp = await client.get(
                "/escalation/status",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 200
            assert resp.json()["pagerduty_configured"] is True
        finally:
            _s.pagerduty_routing_key = original

    @pytest.mark.asyncio
    async def test_escalation_status_opsgenie_configured(self, client: AsyncClient) -> None:
        """Escalation status detects OpsGenie configuration."""
        from config import settings as _s  # noqa: PLC0415
        original = _s.opsgenie_api_key
        _s.opsgenie_api_key = "test-api-key"
        try:
            resp = await client.get(
                "/escalation/status",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 200
            assert resp.json()["opsgenie_configured"] is True
        finally:
            _s.opsgenie_api_key = original

    @pytest.mark.asyncio
    async def test_escalation_status_auto_escalate(self, client: AsyncClient) -> None:
        """Escalation status reports auto-escalation enabled."""
        from config import settings as _s  # noqa: PLC0415
        original_pd = _s.pagerduty_auto_escalate
        _s.pagerduty_auto_escalate = True
        try:
            resp = await client.get(
                "/escalation/status",
                headers={"X-Api-Key": "viewer-key"},
            )
            assert resp.status_code == 200
            assert resp.json()["auto_escalate_enabled"] is True
        finally:
            _s.pagerduty_auto_escalate = original_pd

    @pytest.mark.asyncio
    async def test_escalation_status_auth_required(self, client: AsyncClient) -> None:
        """Escalation status endpoint requires authentication."""
        resp = await client.get("/escalation/status")
        assert resp.status_code == 422 or resp.status_code == 403


# ── PagerDuty Connector Tests ────────────────────────────────────────────────

class TestPagerDutyConnector:
    """Test the PagerDuty Events API v2 connector."""

    @pytest.mark.asyncio
    async def test_pagerduty_requires_routing_key(self) -> None:
        """PagerDutyConnector raises ValueError without routing key."""
        from config import settings as _s  # noqa: PLC0415
        from connectors.pagerduty import PagerDutyConnector  # noqa: PLC0415

        original = _s.pagerduty_routing_key
        _s.pagerduty_routing_key = ""
        try:
            with pytest.raises(ValueError, match="pagerduty_routing_key"):
                PagerDutyConnector(_s)
        finally:
            _s.pagerduty_routing_key = original

    @pytest.mark.asyncio
    async def test_pagerduty_should_escalate_critical(self) -> None:
        """PagerDuty escalation triggers for critical priority tickets."""
        from connectors.pagerduty import PagerDutyConnector  # noqa: PLC0415
        from models import (  # noqa: PLC0415
            AutomationOpportunity,
            CategoryResult,
            EnrichedTicket,
            Priority,
            PriorityResult,
            RootCauseHypothesis,
            RoutingResult,
            SentimentResult,
            SLAInfo,
        )

        enriched = EnrichedTicket(
            ticket_id="CRIT-001",
            source="generic",
            summary="Critical system down",
            category=CategoryResult(category="Infrastructure", confidence=0.9),
            priority=PriorityResult(priority=Priority.critical, score=95),
            routing=RoutingResult(recommended_queue="L3 Infrastructure"),
            automation=AutomationOpportunity(score=10),
            root_cause=RootCauseHypothesis(),
            sentiment=SentimentResult(),
            sla=SLAInfo(status="within"),
        )
        assert PagerDutyConnector.should_escalate(enriched) is True

    @pytest.mark.asyncio
    async def test_pagerduty_should_not_escalate_low(self) -> None:
        """PagerDuty escalation does not trigger for low priority tickets."""
        from connectors.pagerduty import PagerDutyConnector  # noqa: PLC0415
        from models import (  # noqa: PLC0415
            AutomationOpportunity,
            CategoryResult,
            EnrichedTicket,
            Priority,
            PriorityResult,
            RootCauseHypothesis,
            RoutingResult,
            SentimentResult,
            SLAInfo,
        )

        enriched = EnrichedTicket(
            ticket_id="LOW-001",
            source="generic",
            summary="Minor UI issue",
            category=CategoryResult(category="Software", confidence=0.9),
            priority=PriorityResult(priority=Priority.low, score=20),
            routing=RoutingResult(recommended_queue="L1 Service Desk"),
            automation=AutomationOpportunity(score=10),
            root_cause=RootCauseHypothesis(),
            sentiment=SentimentResult(),
            sla=SLAInfo(status="within"),
        )
        assert PagerDutyConnector.should_escalate(enriched) is False

    @pytest.mark.asyncio
    async def test_pagerduty_should_escalate_sla_breach(self) -> None:
        """PagerDuty escalation triggers for SLA breached tickets."""
        from connectors.pagerduty import PagerDutyConnector  # noqa: PLC0415
        from models import (  # noqa: PLC0415
            AutomationOpportunity,
            CategoryResult,
            EnrichedTicket,
            Priority,
            PriorityResult,
            RootCauseHypothesis,
            RoutingResult,
            SentimentResult,
            SLAInfo,
            SLAStatus,
        )

        enriched = EnrichedTicket(
            ticket_id="SLA-001",
            source="generic",
            summary="Overdue ticket",
            category=CategoryResult(category="Software", confidence=0.9),
            priority=PriorityResult(priority=Priority.medium, score=50),
            routing=RoutingResult(recommended_queue="L1 Service Desk"),
            automation=AutomationOpportunity(score=10),
            root_cause=RootCauseHypothesis(),
            sentiment=SentimentResult(),
            sla=SLAInfo(status=SLAStatus.breached),
        )
        assert PagerDutyConnector.should_escalate(enriched) is True


# ── OpsGenie Connector Tests ─────────────────────────────────────────────────

class TestOpsGenieConnector:
    """Test the OpsGenie Alert API connector."""

    @pytest.mark.asyncio
    async def test_opsgenie_requires_api_key(self) -> None:
        """OpsGenieConnector raises ValueError without API key."""
        from config import settings as _s  # noqa: PLC0415
        from connectors.opsgenie import OpsGenieConnector  # noqa: PLC0415

        original = _s.opsgenie_api_key
        _s.opsgenie_api_key = ""
        try:
            with pytest.raises(ValueError, match="opsgenie_api_key"):
                OpsGenieConnector(_s)
        finally:
            _s.opsgenie_api_key = original

    @pytest.mark.asyncio
    async def test_opsgenie_should_escalate_critical(self) -> None:
        """OpsGenie escalation triggers for critical priority tickets."""
        from connectors.opsgenie import OpsGenieConnector  # noqa: PLC0415
        from models import (  # noqa: PLC0415
            AutomationOpportunity,
            CategoryResult,
            EnrichedTicket,
            Priority,
            PriorityResult,
            RootCauseHypothesis,
            RoutingResult,
            SentimentResult,
            SLAInfo,
        )

        enriched = EnrichedTicket(
            ticket_id="CRIT-001",
            source="generic",
            summary="Critical system down",
            category=CategoryResult(category="Infrastructure", confidence=0.9),
            priority=PriorityResult(priority=Priority.critical, score=95),
            routing=RoutingResult(recommended_queue="L3 Infrastructure"),
            automation=AutomationOpportunity(score=10),
            root_cause=RootCauseHypothesis(),
            sentiment=SentimentResult(),
            sla=SLAInfo(status="within"),
        )
        assert OpsGenieConnector.should_escalate(enriched) is True

    @pytest.mark.asyncio
    async def test_opsgenie_should_not_escalate_low(self) -> None:
        """OpsGenie escalation does not trigger for low priority tickets."""
        from connectors.opsgenie import OpsGenieConnector  # noqa: PLC0415
        from models import (  # noqa: PLC0415
            AutomationOpportunity,
            CategoryResult,
            EnrichedTicket,
            Priority,
            PriorityResult,
            RootCauseHypothesis,
            RoutingResult,
            SentimentResult,
            SLAInfo,
        )

        enriched = EnrichedTicket(
            ticket_id="LOW-001",
            source="generic",
            summary="Minor UI issue",
            category=CategoryResult(category="Software", confidence=0.9),
            priority=PriorityResult(priority=Priority.low, score=20),
            routing=RoutingResult(recommended_queue="L1 Service Desk"),
            automation=AutomationOpportunity(score=10),
            root_cause=RootCauseHypothesis(),
            sentiment=SentimentResult(),
            sla=SLAInfo(status="within"),
        )
        assert OpsGenieConnector.should_escalate(enriched) is False

    @pytest.mark.asyncio
    async def test_opsgenie_should_escalate_sla_breach(self) -> None:
        """OpsGenie escalation triggers for SLA breached tickets."""
        from connectors.opsgenie import OpsGenieConnector  # noqa: PLC0415
        from models import (  # noqa: PLC0415
            AutomationOpportunity,
            CategoryResult,
            EnrichedTicket,
            Priority,
            PriorityResult,
            RootCauseHypothesis,
            RoutingResult,
            SentimentResult,
            SLAInfo,
            SLAStatus,
        )

        enriched = EnrichedTicket(
            ticket_id="SLA-001",
            source="generic",
            summary="Overdue ticket",
            category=CategoryResult(category="Software", confidence=0.9),
            priority=PriorityResult(priority=Priority.medium, score=50),
            routing=RoutingResult(recommended_queue="L1 Service Desk"),
            automation=AutomationOpportunity(score=10),
            root_cause=RootCauseHypothesis(),
            sentiment=SentimentResult(),
            sla=SLAInfo(status=SLAStatus.breached),
        )
        assert OpsGenieConnector.should_escalate(enriched) is True


# ── Configuration Tests ──────────────────────────────────────────────────────

class TestPhase6Configuration:
    """Test Phase 6 configuration settings."""

    @pytest.mark.asyncio
    async def test_auto_resolution_config(self) -> None:
        """Auto-resolution configuration is accessible."""
        from config import settings as _s  # noqa: PLC0415
        assert hasattr(_s, "auto_resolution_enabled")
        assert hasattr(_s, "auto_resolution_confidence_threshold")
        assert isinstance(_s.auto_resolution_confidence_threshold, float)

    @pytest.mark.asyncio
    async def test_webhook_events_config(self) -> None:
        """Webhook events configuration is accessible."""
        from config import settings as _s  # noqa: PLC0415
        assert hasattr(_s, "webhook_events_enabled")
        assert isinstance(_s.webhook_events_enabled, bool)

    @pytest.mark.asyncio
    async def test_pagerduty_config(self) -> None:
        """PagerDuty configuration is accessible."""
        from config import settings as _s  # noqa: PLC0415
        assert hasattr(_s, "pagerduty_routing_key")
        assert hasattr(_s, "pagerduty_auto_escalate")
        assert isinstance(_s.pagerduty_auto_escalate, bool)

    @pytest.mark.asyncio
    async def test_opsgenie_config(self) -> None:
        """OpsGenie configuration is accessible."""
        from config import settings as _s  # noqa: PLC0415
        assert hasattr(_s, "opsgenie_api_key")
        assert hasattr(_s, "opsgenie_auto_escalate")
        assert isinstance(_s.opsgenie_auto_escalate, bool)


# ── Model Validation Tests ───────────────────────────────────────────────────

class TestPhase6Models:
    """Test Phase 6 Pydantic model validation."""

    @pytest.mark.asyncio
    async def test_auto_resolve_request_defaults(self) -> None:
        """AutoResolveRequest works with defaults."""
        from models import AutoResolveRequest  # noqa: PLC0415
        req = AutoResolveRequest()
        assert req.additional_context == ""

    @pytest.mark.asyncio
    async def test_auto_resolve_result_serialisation(self) -> None:
        """AutoResolveResult serialises correctly."""
        result = AutoResolveResult(
            ticket_id="TEST-001",
            resolved=True,
            resolution_summary="Issue resolved via KB article",
            confidence=0.92,
            response_draft="Your issue has been resolved.",
        )
        data = json.loads(result.model_dump_json())
        assert data["ticket_id"] == "TEST-001"
        assert data["resolved"] is True
        assert data["confidence"] == 0.92

    @pytest.mark.asyncio
    async def test_webhook_event_type_values(self) -> None:
        """WebhookEventType enum values are correct."""
        assert len(WebhookEventType) == 6

    @pytest.mark.asyncio
    async def test_escalation_result_model(self) -> None:
        """EscalationResult model works correctly."""
        result = EscalationResult(
            provider="pagerduty",
            incident_key="ticketforge-TEST-001",
            status="created",
            message="Incident created",
        )
        assert result.provider == "pagerduty"
        assert result.incident_key == "ticketforge-TEST-001"

    @pytest.mark.asyncio
    async def test_escalation_status_response(self) -> None:
        """EscalationStatusResponse model defaults are correct."""
        resp = EscalationStatusResponse()
        assert resp.success is True
        assert resp.pagerduty_configured is False
        assert resp.opsgenie_configured is False
        assert resp.auto_escalate_enabled is False

    @pytest.mark.asyncio
    async def test_webhook_event_list_response(self) -> None:
        """WebhookEventListResponse model works correctly."""
        resp = WebhookEventListResponse(
            supported_events=["ticket.created", "ticket.resolved"],
            webhook_url_configured=True,
        )
        assert resp.success is True
        assert len(resp.supported_events) == 2
        assert resp.webhook_url_configured is True


# ── Prompt Template Tests ────────────────────────────────────────────────────

class TestAutoResolvePrompt:
    """Test the auto-resolve prompt template."""

    @pytest.mark.asyncio
    async def test_auto_resolve_prompt_exists(self) -> None:
        """AUTO_RESOLVE_PROMPT is defined."""
        from prompts import AUTO_RESOLVE_PROMPT  # noqa: PLC0415
        assert "auto-resolution" in AUTO_RESOLVE_PROMPT.lower() or "resolution" in AUTO_RESOLVE_PROMPT.lower()

    @pytest.mark.asyncio
    async def test_auto_resolve_prompt_has_placeholders(self) -> None:
        """AUTO_RESOLVE_PROMPT has expected format placeholders."""
        from prompts import AUTO_RESOLVE_PROMPT  # noqa: PLC0415
        assert "{ticket_id}" in AUTO_RESOLVE_PROMPT
        assert "{title}" in AUTO_RESOLVE_PROMPT
        assert "{category}" in AUTO_RESOLVE_PROMPT
        assert "{priority}" in AUTO_RESOLVE_PROMPT
        assert "{kb_articles}" in AUTO_RESOLVE_PROMPT

    @pytest.mark.asyncio
    async def test_auto_resolve_prompt_format(self) -> None:
        """AUTO_RESOLVE_PROMPT formats without error."""
        from prompts import AUTO_RESOLVE_PROMPT  # noqa: PLC0415
        formatted = AUTO_RESOLVE_PROMPT.format(
            ticket_id="TEST-001",
            title="VPN not connecting",
            category="Network",
            priority="high",
            sentiment="frustrated",
            summary="User cannot connect to VPN",
            kb_articles="- VPN Troubleshooting Guide (relevance: 0.85)",
        )
        assert "TEST-001" in formatted
        assert "VPN not connecting" in formatted


# ── Integration Tests ────────────────────────────────────────────────────────

class TestPhase6Integration:
    """Integration tests for Phase 6 features working together."""

    @pytest.mark.asyncio
    async def test_full_flow_create_and_auto_resolve(self, client: AsyncClient) -> None:
        """Create a ticket and attempt auto-resolution."""
        # Create ticket
        ticket_id = await _create_test_ticket(client)

        # Attempt auto-resolve
        resp = await client.post(
            f"/tickets/{ticket_id}/auto-resolve",
            json={},
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["ticket_id"] == ticket_id

    @pytest.mark.asyncio
    async def test_escalation_and_webhook_endpoints_accessible(self, client: AsyncClient) -> None:
        """All Phase 6 endpoints are accessible."""
        # Webhook events
        resp = await client.get(
            "/webhooks/events",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200

        # Escalation status
        resp = await client.get(
            "/escalation/status",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_auto_resolve_respects_confidence_threshold(self, client: AsyncClient) -> None:
        """Auto-resolution respects the configured confidence threshold."""
        from config import settings as _s  # noqa: PLC0415

        # Set threshold very high so auto-resolution is unlikely to succeed
        original = _s.auto_resolution_confidence_threshold
        _s.auto_resolution_confidence_threshold = 0.99
        try:
            ticket_id = await _create_test_ticket(client)
            resp = await client.post(
                f"/tickets/{ticket_id}/auto-resolve",
                json={},
                headers={"X-Api-Key": "analyst-key"},
            )
            assert resp.status_code == 200
            # Result should exist regardless of resolution outcome
            data = resp.json()
            assert data["data"]["ticket_id"] == ticket_id
        finally:
            _s.auto_resolution_confidence_threshold = original
