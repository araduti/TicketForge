"""
TicketForge — PagerDuty connector
Creates incidents via PagerDuty Events API v2.
Docs: https://developer.pagerduty.com/docs/events-api-v2/trigger-events/
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

from config import Settings
from models import EnrichedTicket, EscalationResult, Priority, SLAStatus

log = structlog.get_logger(__name__)

_EVENTS_API_URL = "https://events.pagerduty.com/v2/enqueue"

_SEVERITY_MAP: dict[Priority, str] = {
    Priority.critical: "critical",
    Priority.high: "error",
    Priority.medium: "warning",
    Priority.low: "info",
}


class PagerDutyConnector:
    """Async client for PagerDuty Events API v2."""

    def __init__(self, settings: Settings) -> None:
        if not settings.pagerduty_routing_key:
            raise ValueError("pagerduty_routing_key is not configured")
        self._routing_key = settings.pagerduty_routing_key
        self._timeout = httpx.Timeout(15.0)

    async def create_incident(self, enriched: EnrichedTicket) -> EscalationResult:
        """Create a PagerDuty incident from an enriched ticket."""
        severity = _SEVERITY_MAP.get(enriched.priority.priority, "warning")
        dedup_key = f"ticketforge-{enriched.ticket_id}"

        payload: dict[str, Any] = {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "dedup_key": dedup_key,
            "payload": {
                "summary": f"[{enriched.priority.priority.value.upper()}] {enriched.summary}",
                "source": f"ticketforge/{enriched.source.value}",
                "severity": severity,
                "component": enriched.category.category,
                "group": enriched.routing.recommended_queue or "unassigned",
                "class": enriched.category.sub_category or enriched.category.category,
                "custom_details": {
                    "ticket_id": enriched.ticket_id,
                    "category": enriched.category.category,
                    "priority_score": enriched.priority.score,
                    "sentiment": enriched.sentiment.sentiment.value if enriched.sentiment else "unknown",
                    "sla_status": enriched.sla.status.value,
                    "routing_queue": enriched.routing.recommended_queue,
                    "routing_team": enriched.routing.recommended_team,
                },
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(_EVENTS_API_URL, json=payload)
            data = r.json()

            status = data.get("status", "error")
            if r.status_code == 202:
                log.info(
                    "pagerduty.incident_created",
                    ticket_id=enriched.ticket_id,
                    dedup_key=dedup_key,
                    status=status,
                )
                return EscalationResult(
                    provider="pagerduty",
                    incident_key=dedup_key,
                    status=status,
                    message=data.get("message", "Incident created"),
                )
            log.warning(
                "pagerduty.unexpected_status",
                ticket_id=enriched.ticket_id,
                http_status=r.status_code,
                response=data,
            )
            return EscalationResult(
                provider="pagerduty",
                incident_key=dedup_key,
                status="error",
                message=f"Unexpected HTTP {r.status_code}: {data.get('message', '')}",
            )
        except Exception as e:  # noqa: BLE001
            log.error(
                "pagerduty.failed",
                ticket_id=enriched.ticket_id,
                error_type=type(e).__name__,
                error=str(e),
            )
            return EscalationResult(
                provider="pagerduty",
                incident_key=dedup_key,
                status="error",
                message=str(e),
            )

    @staticmethod
    def should_escalate(enriched: EnrichedTicket) -> bool:
        """Determine whether a ticket should be auto-escalated to PagerDuty."""
        if enriched.priority.priority == Priority.critical:
            return True
        if enriched.sla.status == SLAStatus.breached:
            return True
        return False
