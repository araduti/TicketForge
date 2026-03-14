"""
TicketForge — Chatbot conversation manager

Provides a simple intent-based chatbot for ticket creation, status lookup,
and knowledge base search. Conversations are tracked in-memory per session.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import structlog

log = structlog.get_logger(__name__)

# In-memory conversation store: session_id -> list of {role, content, timestamp}
_sessions: dict[str, list[dict]] = {}

# Maximum conversation history per session
MAX_HISTORY = 20


def get_or_create_session(session_id: str = "") -> str:
    """Return an existing session ID or create a new one."""
    if session_id and session_id in _sessions:
        return session_id
    new_id = session_id or f"chat-{uuid.uuid4().hex[:12]}"
    _sessions[new_id] = []
    log.info("chatbot.session_created", session_id=new_id)
    return new_id


def add_message(session_id: str, role: str, content: str) -> None:
    """Append a message to the session history."""
    if session_id not in _sessions:
        _sessions[session_id] = []
    _sessions[session_id].append({
        "role": role,
        "content": content,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    })
    # Trim old messages if history exceeds limit
    if len(_sessions[session_id]) > MAX_HISTORY:
        _sessions[session_id] = _sessions[session_id][-MAX_HISTORY:]


def get_history(session_id: str) -> list[dict]:
    """Return conversation history for a session."""
    return _sessions.get(session_id, [])


def detect_intent(message: str) -> str:
    """
    Detect user intent from message text using keyword matching.

    Returns one of: create_ticket, check_status, search_kb, general
    """
    lower = message.lower()

    # Ticket creation intent
    create_keywords = [
        "create ticket", "new ticket", "submit ticket", "open ticket",
        "report issue", "report a problem", "raise ticket", "log ticket",
        "i need help with", "i have a problem", "something is broken",
        "not working", "create a ticket",
    ]
    if any(kw in lower for kw in create_keywords):
        return "create_ticket"

    # Status check intent
    status_keywords = [
        "check status", "ticket status", "my ticket", "where is my",
        "update on", "any update", "what happened to", "track ticket",
        "status of", "check on",
    ]
    if any(kw in lower for kw in status_keywords):
        return "check_status"

    # KB search intent
    kb_keywords = [
        "how to", "how do i", "knowledge base", "help with",
        "article", "documentation", "guide", "tutorial",
        "what is", "explain", "instructions for", "steps to",
        "search for", "find article",
    ]
    if any(kw in lower for kw in kb_keywords):
        return "search_kb"

    return "general"


def generate_response(
    intent: str,
    message: str,
    session_id: str,
    context: dict | None = None,
) -> dict:
    """
    Generate a chatbot response based on detected intent.

    Returns a dict with: reply, intent, suggested_actions, data
    """
    context = context or {}

    if intent == "create_ticket":
        return _handle_create_ticket(message, session_id, context)
    elif intent == "check_status":
        return _handle_check_status(message, session_id, context)
    elif intent == "search_kb":
        return _handle_search_kb(message, session_id, context)
    else:
        return _handle_general(message, session_id, context)


def _handle_create_ticket(message: str, session_id: str, context: dict) -> dict:
    """Handle ticket creation intent."""
    # Check if we have enough information to create a ticket
    history = get_history(session_id)
    user_messages = [m for m in history if m["role"] == "user"]

    if len(user_messages) <= 1:
        # First message about creating a ticket — ask for details
        return {
            "reply": (
                "I can help you create a ticket. Could you please provide:\n"
                "1. A brief title for the issue\n"
                "2. A detailed description of what's happening\n\n"
                "You can type them in one message, or I'll guide you step by step."
            ),
            "intent": "create_ticket",
            "suggested_actions": [
                "Provide issue title and description",
                "Search knowledge base first",
            ],
            "data": {"status": "awaiting_details"},
        }

    # Extract title and description from the message
    lines = message.strip().split("\n")
    title = lines[0].strip()[:200] if lines else message[:200]
    description = "\n".join(lines[1:]).strip() if len(lines) > 1 else message

    return {
        "reply": (
            f"I've prepared your ticket:\n"
            f"- **Title**: {title}\n"
            f"- **Description**: {description[:200]}{'...' if len(description) > 200 else ''}\n\n"
            f"The ticket will be submitted for analysis. "
            f"You can use the self-service portal at /portal for a full submission form."
        ),
        "intent": "create_ticket",
        "suggested_actions": [
            "Submit via self-service portal",
            "Check ticket status later",
        ],
        "data": {
            "status": "ready",
            "title": title,
            "description": description,
        },
    }


def _handle_check_status(message: str, session_id: str, context: dict) -> dict:
    """Handle ticket status check intent."""
    # Try to extract ticket ID from message or context
    ticket_id = context.get("ticket_id", "")

    if not ticket_id:
        # Try to find a ticket ID pattern in the message
        patterns = [
            r'(?:ticket\s*(?:id)?[:\s#]*)([\w-]+)',
            r'(?:EMAIL-[\w]+)',
            r'(?:KB-[\w]+)',
            r'(?:TF-[\w]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                ticket_id = match.group(0) if match.lastindex is None else match.group(1)
                break

    if not ticket_id:
        return {
            "reply": (
                "I can help you check your ticket status. "
                "Could you please provide the ticket ID? "
                "It usually looks like 'TF-abc123' or 'EMAIL-xyz789'."
            ),
            "intent": "check_status",
            "suggested_actions": [
                "Provide ticket ID",
                "Create a new ticket",
            ],
            "data": {"status": "awaiting_ticket_id"},
        }

    return {
        "reply": (
            f"Let me look up ticket **{ticket_id}** for you. "
            f"Use `GET /tickets/{ticket_id}` with your API key to see full details."
        ),
        "intent": "check_status",
        "suggested_actions": [
            "View full ticket details via API",
            "Create a new ticket",
        ],
        "data": {"ticket_id": ticket_id, "status": "lookup_ready"},
    }


def _handle_search_kb(message: str, session_id: str, context: dict) -> dict:
    """Handle knowledge base search intent."""
    # Strip common prefixes to get the actual query
    query = message.lower()
    prefixes = [
        "how to ", "how do i ", "search for ", "find article ",
        "help with ", "guide for ", "instructions for ", "steps to ",
    ]
    for prefix in prefixes:
        if query.startswith(prefix):
            query = message[len(prefix):]
            break
    else:
        query = message

    return {
        "reply": (
            f"I'll search the knowledge base for: **{query.strip()}**\n\n"
            f"You can also use the KB search directly at `POST /kb/search` "
            f"or browse articles at the self-service portal `/portal`."
        ),
        "intent": "search_kb",
        "suggested_actions": [
            "Browse knowledge base",
            "Create a ticket if KB doesn't help",
        ],
        "data": {"query": query.strip(), "status": "search_ready"},
    }


def _handle_general(message: str, session_id: str, context: dict) -> dict:
    """Handle general conversational messages."""
    lower = message.lower().strip()

    # Greetings
    greetings = ["hello", "hi", "hey", "good morning", "good afternoon", "greetings"]
    if any(lower.startswith(g) for g in greetings):
        return {
            "reply": (
                "Hello! I'm the TicketForge assistant. I can help you with:\n"
                "- **Creating tickets** — describe your issue\n"
                "- **Checking ticket status** — provide a ticket ID\n"
                "- **Searching the knowledge base** — ask a how-to question\n\n"
                "How can I help you today?"
            ),
            "intent": "general",
            "suggested_actions": [
                "Create a new ticket",
                "Check ticket status",
                "Search knowledge base",
            ],
            "data": {},
        }

    # Help request
    if lower in ("help", "?", "menu", "options"):
        return {
            "reply": (
                "Here's what I can do:\n"
                "1. **Create a ticket** — Say 'create ticket' or describe your issue\n"
                "2. **Check status** — Say 'check status' and provide a ticket ID\n"
                "3. **Search KB** — Ask 'how to...' or 'what is...' questions\n"
                "4. **Self-service portal** — Visit /portal for a full web form\n\n"
                "What would you like to do?"
            ),
            "intent": "general",
            "suggested_actions": [
                "Create a new ticket",
                "Check ticket status",
                "Search knowledge base",
            ],
            "data": {},
        }

    # Default response
    return {
        "reply": (
            "I understand you need assistance. I can help you:\n"
            "- **Create a ticket** — describe your issue\n"
            "- **Check ticket status** — mention a ticket ID\n"
            "- **Search the knowledge base** — ask a how-to question\n\n"
            "Could you tell me more about what you need?"
        ),
        "intent": "general",
        "suggested_actions": [
            "Create a new ticket",
            "Check ticket status",
            "Search knowledge base",
        ],
        "data": {},
    }


def clear_session(session_id: str) -> bool:
    """Remove a session from memory. Returns True if session existed."""
    if session_id in _sessions:
        del _sessions[session_id]
        return True
    return False


def list_sessions() -> list[str]:
    """Return all active session IDs."""
    return list(_sessions.keys())
