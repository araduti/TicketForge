"""
TicketForge — OpsGenie connector
Creates alerts via OpsGenie Alert API.
Docs: https://docs.opsgenie.com/docs/alert-api
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

from config import Settings
from models import EnrichedTicket, EscalationResult, Priority, SLAStatus

log = structlog.get_logger(__name__)

_ALERT_API_URL = "https://api.opsgenie.com/v2/alerts"

_PRIORITY_MAP: dict[Priority, str] = {
    Priority.critical: "P1",
    Priority.high: "P2",
    Priority.medium: "P3",
    Priority.low: "P4",
}


class OpsGenieConnector:
    """Async client for OpsGenie Alert API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.opsgenie_api_key:
            raise ValueError("opsgenie_api_key is not configured")
        self._api_key = settings.opsgenie_api_key
        self._timeout = httpx.Timeout(15.0)

    async def create_alert(self, enriched: EnrichedTicket) -> EscalationResult:
        """Create an OpsGenie alert from an enriched ticket."""
        priority = _PRIORITY_MAP.get(enriched.priority.priority, "P3")
        alias = f"ticketforge-{enriched.ticket_id}"

        payload: dict[str, Any] = {
            "message": f"[{enriched.priority.priority.value.upper()}] {enriched.summary}",
            "alias": alias,
            "priority": priority,
            "source": f"TicketForge/{enriched.source.value}",
            "tags": [
                f"category:{enriched.category.category}",
                f"priority:{enriched.priority.priority.value}",
                f"sla:{enriched.sla.status.value}",
            ],
            "details": {
                "ticket_id": enriched.ticket_id,
                "category": enriched.category.category,
                "sub_category": enriched.category.sub_category,
                "priority_score": str(enriched.priority.score),
                "sentiment": enriched.sentiment.sentiment.value if enriched.sentiment else "unknown",
                "sla_status": enriched.sla.status.value,
                "routing_queue": enriched.routing.recommended_queue,
                "routing_team": enriched.routing.recommended_team,
                "automation_score": str(enriched.automation.score),
            },
            "entity": enriched.routing.recommended_queue or "unassigned",
        }

        if enriched.priority.rationale:
            payload["description"] = enriched.priority.rationale

        headers = {
            "Authorization": f"GenieKey {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(_ALERT_API_URL, json=payload, headers=headers)
            data = r.json()

            if r.status_code == 202:
                request_id = data.get("requestId", "")
                log.info(
                    "opsgenie.alert_created",
                    ticket_id=enriched.ticket_id,
                    alias=alias,
                    request_id=request_id,
                )
                return EscalationResult(
                    provider="opsgenie",
                    incident_key=alias,
                    status="created",
                    message=f"Alert created (requestId: {request_id})",
                )
            log.warning(
                "opsgenie.unexpected_status",
                ticket_id=enriched.ticket_id,
                http_status=r.status_code,
                response=data,
            )
            return EscalationResult(
                provider="opsgenie",
                incident_key=alias,
                status="error",
                message=f"Unexpected HTTP {r.status_code}: {data.get('message', '')}",
            )
        except Exception as e:  # noqa: BLE001
            log.error(
                "opsgenie.failed",
                ticket_id=enriched.ticket_id,
                error_type=type(e).__name__,
                error=str(e),
            )
            return EscalationResult(
                provider="opsgenie",
                incident_key=alias,
                status="error",
                message=str(e),
            )

    @staticmethod
    def should_escalate(enriched: EnrichedTicket) -> bool:
        """Determine whether a ticket should be auto-escalated to OpsGenie."""
        if enriched.priority.priority == Priority.critical:
            return True
        if enriched.sla.status == SLAStatus.breached:
            return True
        return False
