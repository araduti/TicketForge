"""
TicketForge — ServiceNow connector
Read-only access using the ServiceNow Table API (REST v2).
Docs: https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from config import Settings
from models import Priority, RawTicket, TicketSource

log = structlog.get_logger(__name__)

# Map ServiceNow urgency/impact matrix to our priority enum
_SN_PRIORITY_MAP: dict[str, Priority] = {
    "1": Priority.critical,
    "2": Priority.high,
    "3": Priority.medium,
    "4": Priority.low,
    "5": Priority.low,
}


class ServiceNowConnector:
    """Thin async client for ServiceNow Table API (read-only)."""

    BASE_PATH = "/api/now/v2/table"

    def __init__(self, settings: Settings) -> None:
        if not settings.servicenow_instance:
            raise ValueError("servicenow_instance is not configured")
        self._base_url = f"https://{settings.servicenow_instance}{self.BASE_PATH}"
        # Prefer OAuth client credentials if available, else Basic auth
        credentials = base64.b64encode(
            f"{settings.servicenow_username}:{settings.servicenow_password}".encode()
        ).decode()
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {credentials}",
        }
        self._timeout = httpx.Timeout(30.0)

    async def get_incident(self, sys_id: str) -> RawTicket:
        """Fetch a single incident by sys_id."""
        url = f"{self._base_url}/incident/{sys_id}"
        params = {
            "sysparm_fields": (
                "sys_id,number,short_description,description,"
                "priority,caller_id,assigned_to,sys_created_on,sys_tags"
            ),
            "sysparm_display_value": "true",
        }
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout) as client:
            response = await client.get(url, params=params)
        log.debug("servicenow.get_incident", sys_id=sys_id, status=response.status_code)
        response.raise_for_status()
        return self._parse_incident(response.json()["result"])

    async def list_incidents(
        self,
        *,
        limit: int = 50,
        query: str = "active=true",
    ) -> list[RawTicket]:
        """List incidents with optional encoded query filter."""
        url = f"{self._base_url}/incident"
        params: dict[str, Any] = {
            "sysparm_limit": limit,
            "sysparm_query": query,
            "sysparm_fields": (
                "sys_id,number,short_description,description,"
                "priority,caller_id,assigned_to,sys_created_on,sys_tags"
            ),
            "sysparm_display_value": "true",
        }
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout) as client:
            response = await client.get(url, params=params)
        log.info("servicenow.list_incidents", count=len(response.json().get("result", [])))
        response.raise_for_status()
        return [self._parse_incident(r) for r in response.json().get("result", [])]

    @staticmethod
    def parse_webhook(payload: dict[str, Any]) -> RawTicket:
        """Parse a ServiceNow Business Rule / Flow webhook payload."""
        rec = payload.get("data", payload)
        return ServiceNowConnector._parse_incident(rec)

    @staticmethod
    def _parse_incident(r: dict[str, Any]) -> RawTicket:
        raw_created = r.get("sys_created_on", "")
        try:
            created_at = datetime.strptime(raw_created, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            created_at = datetime.now(tz=timezone.utc)

        tags_raw = r.get("sys_tags", "")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

        return RawTicket(
            id=r.get("sys_id") or r.get("number", "unknown"),
            source=TicketSource.servicenow,
            title=r.get("short_description", "No title"),
            description=r.get("description", ""),
            reporter=r.get("caller_id", ""),
            assignee=r.get("assigned_to", ""),
            created_at=created_at,
            tags=tags,
            extra={
                "number": r.get("number"),
                "priority_raw": r.get("priority"),
            },
        )
