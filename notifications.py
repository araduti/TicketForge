"""
TicketForge — Notification module

Sends ticket notifications to Slack and Microsoft Teams via incoming webhooks.
Notifications are triggered for high-priority tickets and SLA breaches.
"""
from __future__ import annotations

import httpx
import structlog

from config import Settings
from models import EnrichedTicket, Priority, SLAStatus

log = structlog.get_logger(__name__)

_PRIORITY_LEVELS: dict[Priority, int] = {
    Priority.low: 0,
    Priority.medium: 1,
    Priority.high: 2,
    Priority.critical: 3,
}

_PRIORITY_EMOJIS: dict[Priority, str] = {
    Priority.critical: "\U0001f534",  # 🔴
    Priority.high: "\U0001f7e0",      # 🟠
    Priority.medium: "\U0001f7e1",    # 🟡
    Priority.low: "\U0001f7e2",       # 🟢
}

_SLA_EMOJIS: dict[SLAStatus, str] = {
    SLAStatus.within: "\u2705",     # ✅
    SLAStatus.at_risk: "\u26a0\ufe0f",  # ⚠️
    SLAStatus.breached: "\U0001f6a8",    # 🚨
}


def should_notify(enriched: EnrichedTicket, settings: Settings) -> bool:
    """Determine whether a ticket should trigger a notification."""
    if not settings.slack_webhook_url and not settings.teams_webhook_url:
        return False

    # Check priority threshold
    try:
        min_priority = Priority(settings.notification_min_priority.lower())
    except ValueError:
        min_priority = Priority.high

    ticket_level = _PRIORITY_LEVELS.get(enriched.priority.priority, 0)
    threshold_level = _PRIORITY_LEVELS.get(min_priority, 2)

    if ticket_level >= threshold_level:
        return True

    # Check SLA breach
    if settings.notify_on_sla_breach and enriched.sla.status in (
        SLAStatus.at_risk,
        SLAStatus.breached,
    ):
        return True

    return False


def format_slack_message(enriched: EnrichedTicket) -> dict:
    """Format an enriched ticket as a Slack incoming webhook payload."""
    priority_emoji = _PRIORITY_EMOJIS.get(enriched.priority.priority, "\u2753")
    sla_emoji = _SLA_EMOJIS.get(enriched.sla.status, "")
    sentiment_text = enriched.sentiment.sentiment.value if enriched.sentiment else "unknown"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{priority_emoji} TicketForge Alert: {enriched.ticket_id}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Priority:* {enriched.priority.priority.value.title()}"},
                {"type": "mrkdwn", "text": f"*Category:* {enriched.category.category}"},
                {"type": "mrkdwn", "text": f"*Sentiment:* {sentiment_text.title()}"},
                {"type": "mrkdwn", "text": f"*SLA:* {sla_emoji} {enriched.sla.status.value.replace('_', ' ').title()}"},
                {"type": "mrkdwn", "text": f"*Queue:* {enriched.routing.recommended_queue or 'Unassigned'}"},
                {"type": "mrkdwn", "text": f"*Language:* {enriched.detected_language}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary:* {enriched.summary}"},
        },
    ]

    if enriched.automation.score > 50:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"\U0001f916 *Automation Opportunity ({enriched.automation.score}%):* {enriched.automation.suggestion}",
            },
        })

    return {"blocks": blocks}


def format_teams_message(enriched: EnrichedTicket) -> dict:
    """Format an enriched ticket as a Microsoft Teams incoming webhook payload (Adaptive Card)."""
    priority_emoji = _PRIORITY_EMOJIS.get(enriched.priority.priority, "")
    sla_emoji = _SLA_EMOJIS.get(enriched.sla.status, "")
    sentiment_text = enriched.sentiment.sentiment.value if enriched.sentiment else "unknown"

    facts = [
        {"name": "Priority", "value": f"{priority_emoji} {enriched.priority.priority.value.title()}"},
        {"name": "Category", "value": enriched.category.category},
        {"name": "Sentiment", "value": sentiment_text.title()},
        {"name": "SLA Status", "value": f"{sla_emoji} {enriched.sla.status.value.replace('_', ' ').title()}"},
        {"name": "Queue", "value": enriched.routing.recommended_queue or "Unassigned"},
        {"name": "Language", "value": enriched.detected_language},
    ]

    sections = [
        {
            "activityTitle": f"{priority_emoji} TicketForge Alert: {enriched.ticket_id}",
            "activitySubtitle": enriched.summary,
            "facts": facts,
        }
    ]

    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"TicketForge: {enriched.ticket_id}",
        "themeColor": "FF0000" if enriched.priority.priority == Priority.critical else "FFA500",
        "sections": sections,
    }


async def send_notifications(enriched: EnrichedTicket, settings: Settings) -> None:
    """Send notifications to configured Slack and/or Teams channels."""
    if not should_notify(enriched, settings):
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        if settings.slack_webhook_url:
            try:
                payload = format_slack_message(enriched)
                r = await client.post(settings.slack_webhook_url, json=payload)
                log.info(
                    "notification.slack.sent",
                    ticket_id=enriched.ticket_id,
                    status=r.status_code,
                )
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                log.error(
                    "notification.slack.failed",
                    ticket_id=enriched.ticket_id,
                    error_type=type(e).__name__,
                    error=str(e),
                )

        if settings.teams_webhook_url:
            try:
                payload = format_teams_message(enriched)
                r = await client.post(settings.teams_webhook_url, json=payload)
                log.info(
                    "notification.teams.sent",
                    ticket_id=enriched.ticket_id,
                    status=r.status_code,
                )
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                log.error(
                    "notification.teams.failed",
                    ticket_id=enriched.ticket_id,
                    error_type=type(e).__name__,
                    error=str(e),
                )
