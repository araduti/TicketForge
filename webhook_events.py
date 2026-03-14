"""
TicketForge — Outbound webhook events module

Sends structured webhook event payloads to configured endpoints,
compatible with Zapier, Make (Integromat), n8n, and other automation platforms.
Events are sent as fire-and-forget HTTP POST requests with HMAC signing.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx
import structlog

from config import Settings
from models import OutboundWebhookEvent, WebhookEventType

log = structlog.get_logger(__name__)


async def send_webhook_event(
    event_type: WebhookEventType,
    ticket_id: str,
    payload: dict[str, Any],
    settings: Settings,
) -> None:
    """
    Send a structured webhook event to the configured outbound webhook URL.

    The event format is designed for compatibility with Zapier/Make/n8n:
    {
        "event": "ticket.created",
        "ticket_id": "TF-001",
        "timestamp": "2026-03-14T15:00:00Z",
        "payload": { ... }
    }
    """
    if not settings.webhook_events_enabled:
        return
    if not settings.outbound_webhook_url:
        return

    event = OutboundWebhookEvent(
        event=event_type,
        ticket_id=ticket_id,
        payload=payload,
    )

    event_bytes = event.model_dump_json().encode()
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-TicketForge-Event": event_type.value,
    }

    if settings.outbound_webhook_secret:
        sig = hmac.new(
            settings.outbound_webhook_secret.encode(),
            event_bytes,
            hashlib.sha256,
        ).hexdigest()
        headers["X-TicketForge-Signature"] = f"sha256={sig}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                settings.outbound_webhook_url,
                content=event_bytes,
                headers=headers,
            )
        log.info(
            "webhook_event.sent",
            event=event_type.value,
            ticket_id=ticket_id,
            status=r.status_code,
        )
    except Exception as e:  # noqa: BLE001
        log.error(
            "webhook_event.failed",
            event=event_type.value,
            ticket_id=ticket_id,
            error_type=type(e).__name__,
            error=str(e),
        )
