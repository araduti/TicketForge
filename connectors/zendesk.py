"""
TicketForge — Zendesk connector
Read-only access via the Zendesk Support API v2.
Docs: https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from config import Settings
from models import RawTicket, TicketSource

log = structlog.get_logger(__name__)

# Zendesk priority string → our enum string
_ZD_PRIORITY_MAP: dict[str | None, str] = {
    "urgent": "critical",
    "high": "high",
    "normal": "medium",
    "low": "low",
    None: "medium",
}


class ZendeskConnector:
    """Thin async client for the Zendesk Support REST API v2 (read-only)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.zendesk_subdomain:
            raise ValueError("zendesk_subdomain is not configured")
        self._base_url = (
            f"https://{settings.zendesk_subdomain}.zendesk.com/api/v2"
        )
        token = base64.b64encode(
            f"{settings.zendesk_user_email}/token:{settings.zendesk_api_token}".encode()
        ).decode()
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
        }
        self._timeout = httpx.Timeout(30.0)

    async def get_ticket(self, ticket_id: int | str) -> RawTicket:
        """Fetch a single Zendesk ticket by ID."""
        url = f"{self._base_url}/tickets/{ticket_id}.json"
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout) as client:
            response = await client.get(url)
        log.debug("zendesk.get_ticket", ticket_id=ticket_id, status=response.status_code)
        response.raise_for_status()
        return self._parse_ticket(response.json()["ticket"])

    async def list_tickets(
        self,
        *,
        status: str = "open",
        per_page: int = 50,
    ) -> list[RawTicket]:
        """List tickets filtered by status using the incremental export endpoint."""
        url = f"{self._base_url}/tickets.json"
        params: dict[str, Any] = {
            "status": status,
            "per_page": per_page,
            "sort_by": "created_at",
            "sort_order": "desc",
        }
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout) as client:
            response = await client.get(url, params=params)
        log.info("zendesk.list_tickets", status=status)
        response.raise_for_status()
        return [self._parse_ticket(t) for t in response.json().get("tickets", [])]

    @staticmethod
    def parse_webhook(payload: dict[str, Any]) -> RawTicket:
        """Parse a Zendesk webhook / trigger payload."""
        ticket = payload.get("ticket", payload)
        return ZendeskConnector._parse_ticket(ticket)

    @staticmethod
    def _parse_ticket(t: dict[str, Any]) -> RawTicket:
        created_str = t.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            created_at = datetime.now(tz=timezone.utc)

        # Tags are a list in Zendesk
        tags = t.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]

        subject = t.get("subject") or t.get("raw_subject") or "No title"
        description = t.get("description", "")

        requester = t.get("requester", {})
        if isinstance(requester, dict):
            reporter = requester.get("name") or requester.get("email", "")
        else:
            reporter = str(t.get("requester_id", ""))

        assignee = t.get("assignee", {})
        if isinstance(assignee, dict):
            assignee_name = assignee.get("name") or assignee.get("email", "")
        else:
            assignee_name = str(t.get("assignee_id", ""))

        return RawTicket(
            id=str(t.get("id", "unknown")),
            source=TicketSource.zendesk,
            title=subject,
            description=description,
            reporter=reporter,
            assignee=assignee_name,
            created_at=created_at,
            tags=tags,
            extra={
                "type": t.get("type"),
                "priority_raw": t.get("priority"),
                "status": t.get("status"),
            },
        )
