"""
TicketForge — Test suite for new competitive features
Tests for sentiment analysis, cloud LLM provider support, ticket status tracking,
language detection, and Slack/Teams notifications.
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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_new.db"

from main import app, lifespan  # noqa: E402
from models import (  # noqa: E402
    AutomationOpportunity,
    AutomationSuggestionType,
    CategoryResult,
    EnrichedTicket,
    Priority,
    PriorityResult,
    RootCauseHypothesis,
    RoutingResult,
    Sentiment,
    SentimentResult,
    SLAInfo,
    SLAStatus,
    TicketSource,
    TicketStatus,
    TicketStatusUpdate,
)
from notifications import (  # noqa: E402
    format_slack_message,
    format_teams_message,
    should_notify,
)
from config import Settings  # noqa: E402
from llm_provider import OllamaProvider, OpenAIProvider, create_llm_provider  # noqa: E402


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Clean up test database
    try:
        os.remove("./test_ticketforge_new.db")
    except FileNotFoundError:
        pass


def _make_enriched(**overrides) -> EnrichedTicket:
    """Helper to build an EnrichedTicket with sensible defaults."""
    defaults = dict(
        ticket_id="T-100",
        source=TicketSource.generic,
        summary="Test ticket summary",
        category=CategoryResult(category="Software"),
        priority=PriorityResult(priority=Priority.medium, score=50),
        routing=RoutingResult(recommended_queue="L1 Service Desk"),
        automation=AutomationOpportunity(
            score=0, suggestion_type=AutomationSuggestionType.none
        ),
        root_cause=RootCauseHypothesis(),
        sentiment=SentimentResult(sentiment=Sentiment.neutral, confidence=0.8),
        detected_language="en",
        ticket_status=TicketStatus.open,
        sla=SLAInfo(
            response_target_minutes=60,
            resolution_target_minutes=480,
            status=SLAStatus.within,
            elapsed_minutes=10.0,
            breach_risk=0.02,
        ),
    )
    defaults.update(overrides)
    return EnrichedTicket(**defaults)


# ── Sentiment model tests ────────────────────────────────────────────────────

class TestSentiment:
    """Test sentiment analysis models."""

    def test_sentiment_enum_values(self):
        assert Sentiment.positive.value == "positive"
        assert Sentiment.neutral.value == "neutral"
        assert Sentiment.negative.value == "negative"
        assert Sentiment.frustrated.value == "frustrated"

    def test_sentiment_result_defaults(self):
        result = SentimentResult()
        assert result.sentiment == Sentiment.neutral
        assert result.confidence == 0.0
        assert result.rationale == ""

    def test_sentiment_result_with_values(self):
        result = SentimentResult(
            sentiment=Sentiment.frustrated,
            confidence=0.95,
            rationale="User expressed anger about repeated failures",
        )
        assert result.sentiment == Sentiment.frustrated
        assert result.confidence == 0.95
        assert "anger" in result.rationale

    def test_enriched_ticket_has_sentiment(self):
        ticket = _make_enriched()
        assert ticket.sentiment is not None
        assert ticket.sentiment.sentiment == Sentiment.neutral

    def test_enriched_ticket_default_sentiment(self):
        """EnrichedTicket defaults to neutral sentiment."""
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
        assert ticket.sentiment.sentiment == Sentiment.neutral


# ── Ticket status tests ──────────────────────────────────────────────────────

class TestTicketStatus:
    """Test ticket lifecycle status tracking."""

    def test_ticket_status_enum_values(self):
        assert TicketStatus.open.value == "open"
        assert TicketStatus.in_progress.value == "in_progress"
        assert TicketStatus.resolved.value == "resolved"
        assert TicketStatus.closed.value == "closed"

    def test_ticket_status_update_model(self):
        update = TicketStatusUpdate(status=TicketStatus.in_progress)
        assert update.status == TicketStatus.in_progress

    def test_enriched_ticket_default_status(self):
        ticket = _make_enriched()
        assert ticket.ticket_status == TicketStatus.open

    @pytest.mark.asyncio
    async def test_status_update_requires_analyst(self, client):
        """Viewer cannot update ticket status."""
        response = await client.patch(
            "/tickets/nonexistent/status",
            headers={"X-Api-Key": "viewer-key"},
            json={"status": "in_progress"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_status_update_not_found(self, client):
        """Updating status of nonexistent ticket returns 404."""
        response = await client.patch(
            "/tickets/nonexistent/status",
            headers={"X-Api-Key": "analyst-key"},
            json={"status": "in_progress"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_status_update_invalid_status(self, client):
        """Invalid status value returns 422."""
        response = await client.patch(
            "/tickets/some-id/status",
            headers={"X-Api-Key": "analyst-key"},
            json={"status": "invalid_status"},
        )
        assert response.status_code == 422


# ── Language detection tests ─────────────────────────────────────────────────

class TestLanguageDetection:
    """Test language detection field."""

    def test_enriched_ticket_default_language(self):
        ticket = _make_enriched()
        assert ticket.detected_language == "en"

    def test_enriched_ticket_custom_language(self):
        ticket = _make_enriched(detected_language="es")
        assert ticket.detected_language == "es"


# ── LLM provider tests ──────────────────────────────────────────────────────

class TestLLMProvider:
    """Test LLM provider factory and configuration."""

    def test_default_provider_is_ollama(self):
        s = Settings(
            api_keys=["test"],
            database_url="sqlite+aiosqlite:///./test.db",
        )
        provider = create_llm_provider(s)
        assert isinstance(provider, OllamaProvider)
        assert provider.provider_name == "ollama"
        assert provider.model_name == "llama3.1:8b"

    def test_openai_provider_creation(self):
        s = Settings(
            api_keys=["test"],
            database_url="sqlite+aiosqlite:///./test.db",
            llm_provider="openai",
            openai_api_key="sk-test-key",
            openai_base_url="https://api.openai.com",
            openai_model="gpt-4o-mini",
        )
        provider = create_llm_provider(s)
        assert isinstance(provider, OpenAIProvider)
        assert provider.provider_name == "openai"
        assert provider.model_name == "gpt-4o-mini"

    def test_provider_name_case_insensitive(self):
        s = Settings(
            api_keys=["test"],
            database_url="sqlite+aiosqlite:///./test.db",
            llm_provider="OpenAI",
        )
        provider = create_llm_provider(s)
        assert isinstance(provider, OpenAIProvider)

    def test_unknown_provider_defaults_to_ollama(self):
        s = Settings(
            api_keys=["test"],
            database_url="sqlite+aiosqlite:///./test.db",
            llm_provider="unknown",
        )
        provider = create_llm_provider(s)
        assert isinstance(provider, OllamaProvider)


# ── Notification tests ───────────────────────────────────────────────────────

class TestNotifications:
    """Test Slack and Teams notification formatting and filtering."""

    def _settings_with_slack(self, **kwargs) -> Settings:
        defaults = dict(
            api_keys=["test"],
            database_url="sqlite+aiosqlite:///./test.db",
            slack_webhook_url="https://hooks.slack.com/services/test",
            notification_min_priority="high",
            notify_on_sla_breach=True,
        )
        defaults.update(kwargs)
        return Settings(**defaults)

    def test_should_notify_high_priority(self):
        """High priority ticket should trigger notification."""
        enriched = _make_enriched(
            priority=PriorityResult(priority=Priority.high, score=80),
        )
        s = self._settings_with_slack()
        assert should_notify(enriched, s) is True

    def test_should_notify_critical_priority(self):
        """Critical priority ticket should trigger notification."""
        enriched = _make_enriched(
            priority=PriorityResult(priority=Priority.critical, score=95),
        )
        s = self._settings_with_slack()
        assert should_notify(enriched, s) is True

    def test_should_not_notify_low_priority(self):
        """Low priority ticket should not trigger notification."""
        enriched = _make_enriched(
            priority=PriorityResult(priority=Priority.low, score=10),
        )
        s = self._settings_with_slack()
        assert should_notify(enriched, s) is False

    def test_should_not_notify_medium_priority(self):
        """Medium priority ticket should not trigger notification when threshold is high."""
        enriched = _make_enriched(
            priority=PriorityResult(priority=Priority.medium, score=50),
        )
        s = self._settings_with_slack()
        assert should_notify(enriched, s) is False

    def test_should_notify_sla_breach(self):
        """SLA breached ticket should trigger notification even if priority is low."""
        enriched = _make_enriched(
            priority=PriorityResult(priority=Priority.low, score=10),
            sla=SLAInfo(
                response_target_minutes=480,
                resolution_target_minutes=2880,
                status=SLAStatus.breached,
                elapsed_minutes=3000,
                breach_risk=1.0,
            ),
        )
        s = self._settings_with_slack()
        assert should_notify(enriched, s) is True

    def test_should_notify_sla_at_risk(self):
        """SLA at_risk ticket should trigger notification."""
        enriched = _make_enriched(
            priority=PriorityResult(priority=Priority.low, score=10),
            sla=SLAInfo(
                response_target_minutes=480,
                resolution_target_minutes=2880,
                status=SLAStatus.at_risk,
                elapsed_minutes=2400,
                breach_risk=0.85,
            ),
        )
        s = self._settings_with_slack()
        assert should_notify(enriched, s) is True

    def test_should_not_notify_without_webhooks(self):
        """No notification if neither Slack nor Teams is configured."""
        enriched = _make_enriched(
            priority=PriorityResult(priority=Priority.critical, score=95),
        )
        s = Settings(
            api_keys=["test"],
            database_url="sqlite+aiosqlite:///./test.db",
        )
        assert should_notify(enriched, s) is False

    def test_slack_message_format(self):
        """Slack message contains expected fields."""
        enriched = _make_enriched(
            priority=PriorityResult(priority=Priority.critical, score=95),
            sentiment=SentimentResult(sentiment=Sentiment.frustrated, confidence=0.9),
        )
        msg = format_slack_message(enriched)
        assert "blocks" in msg
        assert len(msg["blocks"]) >= 2
        # Header block
        header = msg["blocks"][0]
        assert header["type"] == "header"
        assert "T-100" in header["text"]["text"]

    def test_teams_message_format(self):
        """Teams message contains expected fields."""
        enriched = _make_enriched(
            priority=PriorityResult(priority=Priority.high, score=80),
        )
        msg = format_teams_message(enriched)
        assert msg["@type"] == "MessageCard"
        assert "sections" in msg
        assert len(msg["sections"]) > 0
        facts = msg["sections"][0]["facts"]
        fact_names = [f["name"] for f in facts]
        assert "Priority" in fact_names
        assert "Sentiment" in fact_names
        assert "Language" in fact_names

    def test_slack_message_includes_automation(self):
        """Slack message includes automation opportunity when score > 50."""
        enriched = _make_enriched(
            automation=AutomationOpportunity(
                score=75,
                suggestion_type=AutomationSuggestionType.bot,
                suggestion="Deploy a password-reset chatbot",
            ),
        )
        msg = format_slack_message(enriched)
        # Should have extra block for automation
        assert len(msg["blocks"]) >= 3

    def test_notification_with_custom_threshold(self):
        """Custom notification threshold works correctly."""
        enriched = _make_enriched(
            priority=PriorityResult(priority=Priority.medium, score=50),
        )
        s = self._settings_with_slack(notification_min_priority="medium")
        assert should_notify(enriched, s) is True


# ── Export with new fields tests ─────────────────────────────────────────────

class TestExportNewFields:
    """Test that export includes new sentiment, language, and status fields."""

    @pytest.mark.asyncio
    async def test_csv_export_has_new_headers(self, client):
        """CSV export header should include sentiment, detected_language, ticket_status."""
        response = await client.get(
            "/export/tickets?format=csv",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        header = lines[0]
        assert "sentiment" in header
        assert "detected_language" in header
        assert "ticket_status" in header

    @pytest.mark.asyncio
    async def test_json_export_empty_with_new_fields(self, client):
        """JSON export of empty DB returns empty list (no regression)."""
        response = await client.get(
            "/export/tickets?format=json",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tickets"] == []


# ── Config tests for new settings ────────────────────────────────────────────

class TestNewConfig:
    """Test new configuration options."""

    def test_default_llm_provider(self):
        s = Settings(
            api_keys=["test"],
            database_url="sqlite+aiosqlite:///./test.db",
        )
        assert s.llm_provider == "ollama"

    def test_default_openai_settings(self):
        s = Settings(
            api_keys=["test"],
            database_url="sqlite+aiosqlite:///./test.db",
        )
        assert s.openai_api_key == ""
        assert s.openai_base_url == "https://api.openai.com"
        assert s.openai_model == "gpt-4o-mini"

    def test_default_slack_settings(self):
        s = Settings(
            api_keys=["test"],
            database_url="sqlite+aiosqlite:///./test.db",
        )
        assert s.slack_webhook_url == ""
        assert s.teams_webhook_url == ""
        assert s.notification_min_priority == "high"
        assert s.notify_on_sla_breach is True
