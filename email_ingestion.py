"""
TicketForge — Email ingestion module
Parses inbound email payloads (generic, SendGrid, Mailgun) into RawTicket objects.
"""
from __future__ import annotations

import hashlib
import re

from models import EmailIngestRequest, RawTicket, TicketSource


def _strip_html(html: str) -> str:
    """Naive HTML tag removal for fallback body extraction."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _generate_ticket_id(email: EmailIngestRequest) -> str:
    """Generate a deterministic ticket ID from the email Message-ID or sender+timestamp."""
    if email.message_id:
        digest = hashlib.sha256(email.message_id.encode()).hexdigest()[:12]
    else:
        seed = f"{email.sender}:{email.timestamp.isoformat()}:{email.subject}"
        digest = hashlib.sha256(seed.encode()).hexdigest()[:12]
    return f"EMAIL-{digest}"


def parse_email_to_ticket(email: EmailIngestRequest) -> RawTicket:
    """Convert an inbound email payload into a RawTicket for the analysis pipeline."""

    # Use plain text body if available, otherwise strip HTML
    body = email.body_plain.strip()
    if not body and email.body_html:
        body = _strip_html(email.body_html)

    title = email.subject or "(no subject)"
    ticket_id = _generate_ticket_id(email)

    return RawTicket(
        id=ticket_id,
        source=TicketSource.generic,
        title=title,
        description=body,
        reporter=email.sender,
        created_at=email.timestamp,
        tags=["email"],
        extra={
            "message_id": email.message_id,
            "in_reply_to": email.in_reply_to,
            "recipient": email.recipient,
        },
    )


def parse_sendgrid_inbound(payload: dict) -> EmailIngestRequest:
    """Parse a SendGrid Inbound Parse webhook payload into EmailIngestRequest."""
    return EmailIngestRequest(
        sender=payload.get("from", payload.get("sender", "")),
        subject=payload.get("subject", ""),
        body_plain=payload.get("text", ""),
        body_html=payload.get("html", ""),
        recipient=payload.get("to", ""),
        message_id=payload.get("message_id", ""),
        in_reply_to=payload.get("in_reply_to", ""),
    )


def parse_mailgun_inbound(payload: dict) -> EmailIngestRequest:
    """Parse a Mailgun Routes webhook payload into EmailIngestRequest."""
    return EmailIngestRequest(
        sender=payload.get("sender", payload.get("from", "")),
        subject=payload.get("subject", ""),
        body_plain=payload.get("body-plain", payload.get("stripped-text", "")),
        body_html=payload.get("body-html", payload.get("stripped-html", "")),
        recipient=payload.get("recipient", payload.get("To", "")),
        message_id=payload.get("Message-Id", payload.get("message-id", "")),
        in_reply_to=payload.get("In-Reply-To", ""),
    )
