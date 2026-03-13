"""
TicketForge — Jira connector
Read-only access via the Jira Cloud REST API v3.
Docs: https://developer.atlassian.com/cloud/jira/platform/rest/v3/
Also compatible with Jira Server/Data Center v2 (same endpoints).
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

# Jira priority name → our enum string
_JIRA_PRIORITY_MAP: dict[str, str] = {
    "Highest": "critical",
    "High": "high",
    "Medium": "medium",
    "Low": "low",
    "Lowest": "low",
}


class JiraConnector:
    """Thin async client for Jira Cloud/Server REST API (read-only)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.jira_base_url:
            raise ValueError("jira_base_url is not configured")
        self._base_url = settings.jira_base_url.rstrip("/")
        token = base64.b64encode(
            f"{settings.jira_user_email}:{settings.jira_api_token}".encode()
        ).decode()
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
        }
        self._timeout = httpx.Timeout(30.0)

    async def get_issue(self, issue_key: str) -> RawTicket:
        """Fetch a single Jira issue by key (e.g. PROJ-123)."""
        url = f"{self._base_url}/rest/api/3/issue/{issue_key}"
        params = {
            "fields": "summary,description,priority,reporter,assignee,created,labels,issuetype"
        }
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout) as client:
            response = await client.get(url, params=params)
        log.debug("jira.get_issue", key=issue_key, status=response.status_code)
        response.raise_for_status()
        return self._parse_issue(response.json())

    async def search_issues(
        self,
        jql: str = "project is not EMPTY ORDER BY created DESC",
        *,
        max_results: int = 50,
    ) -> list[RawTicket]:
        """Search issues using JQL."""
        url = f"{self._base_url}/rest/api/3/search"
        payload: dict[str, Any] = {
            "jql": jql,
            "maxResults": max_results,
            "fields": [
                "summary",
                "description",
                "priority",
                "reporter",
                "assignee",
                "created",
                "labels",
                "issuetype",
            ],
        }
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout) as client:
            response = await client.post(url, json=payload)
        log.info("jira.search_issues", jql=jql, total=response.json().get("total", 0))
        response.raise_for_status()
        return [self._parse_issue(issue) for issue in response.json().get("issues", [])]

    @staticmethod
    def parse_webhook(payload: dict[str, Any]) -> RawTicket:
        """Parse a Jira Cloud/Server webhook payload."""
        issue = payload.get("issue", {})
        return JiraConnector._parse_issue(issue)

    @staticmethod
    def _parse_issue(issue: dict[str, Any]) -> RawTicket:
        fields = issue.get("fields", {})

        # Description can be Atlassian Document Format (v3) or plain string (v2)
        desc_raw = fields.get("description", "")
        description = _extract_text(desc_raw)

        reporter_obj = fields.get("reporter") or {}
        assignee_obj = fields.get("assignee") or {}

        created_str = fields.get("created", "")
        try:
            created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            created_at = datetime.now(tz=timezone.utc)

        return RawTicket(
            id=issue.get("key") or issue.get("id", "unknown"),
            source=TicketSource.jira,
            title=fields.get("summary", "No title"),
            description=description,
            reporter=reporter_obj.get("displayName") or reporter_obj.get("emailAddress", ""),
            assignee=assignee_obj.get("displayName") or assignee_obj.get("emailAddress", ""),
            created_at=created_at,
            tags=fields.get("labels", []),
            extra={
                "issuetype": (fields.get("issuetype") or {}).get("name"),
                "priority_raw": (fields.get("priority") or {}).get("name"),
            },
        )


def _extract_text(desc: Any) -> str:
    """Extract plain text from Atlassian Document Format or plain string."""
    if isinstance(desc, str):
        return desc
    if not isinstance(desc, dict):
        return ""
    # ADF: recursively collect text nodes
    parts: list[str] = []
    _walk_adf(desc, parts)
    return " ".join(parts)


def _walk_adf(node: dict[str, Any], parts: list[str]) -> None:
    if node.get("type") == "text":
        text = node.get("text", "")
        if text:
            parts.append(text)
    for child in node.get("content", []):
        _walk_adf(child, parts)
