"""
TicketForge — Test suite for Phase 9 features
Tests for Workflow Automation Rules, Approval Workflows, Agent Collision
Detection, Customer Contact Management, and Macros.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase9.db"
os.environ["AUTOMATION_RULES_ENABLED"] = "true"
os.environ["APPROVAL_WORKFLOWS_ENABLED"] = "true"
os.environ["COLLISION_DETECTION_ENABLED"] = "true"
os.environ["CONTACT_MANAGEMENT_ENABLED"] = "true"
os.environ["MACROS_ENABLED"] = "true"
os.environ["TICKET_TAGS_ENABLED"] = "true"
os.environ["TICKET_TIMELINE_ENABLED"] = "true"

from main import app, lifespan  # noqa: E402
from models import (  # noqa: E402
    ApprovalDecision,
    ApprovalListResponse,
    ApprovalRecord,
    ApprovalRequestCreate,
    ApprovalResponse,
    ApprovalStatus,
    AutomationRuleAction,
    AutomationRuleCondition,
    AutomationRuleCreate,
    AutomationRuleListResponse,
    AutomationRuleRecord,
    AutomationRuleResponse,
    ContactCreate,
    ContactListResponse,
    ContactRecord,
    ContactResponse,
    ContactTicketsResponse,
    MacroAction,
    MacroCreate,
    MacroExecuteResponse,
    MacroListResponse,
    MacroRecord,
    MacroResponse,
    TicketLockCreate,
    TicketLockRecord,
    TicketLockResponse,
)

DB_PATH = "./test_ticketforge_phase9.db"


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    from config import settings as _s  # noqa: PLC0415

    _db_path = _s.database_url.replace("sqlite+aiosqlite:///", "")
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass

    # Ensure Phase 9 feature flags are set on the singleton
    _s.automation_rules_enabled = True
    _s.approval_workflows_enabled = True
    _s.collision_detection_enabled = True
    _s.contact_management_enabled = True
    _s.macros_enabled = True
    _s.ticket_tags_enabled = True
    _s.ticket_timeline_enabled = True
    _s.portal_enabled = True

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Clean up test database
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass


# ── Helper: create a test ticket via the portal ──────────────────────────────

async def _create_test_ticket(client: AsyncClient, ticket_id: str = "P9-001") -> str:
    """Create a test ticket via the portal endpoint and return its ID."""
    from config import settings as _s  # noqa: PLC0415
    _s.portal_enabled = True
    resp = await client.post(
        "/portal/tickets",
        headers={"X-Api-Key": "viewer-key"},
        json={
            "title": f"Phase 9 test ticket ({ticket_id})",
            "description": "Testing Phase 9 features — categorisation and authorisation checks.",
            "reporter_email": "test@example.com",
        },
    )
    assert resp.status_code == 200 or resp.status_code == 201
    return resp.json()["ticket_id"]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. AUTOMATION RULES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_automation_rule(client):
    """Admin can create an automation rule."""
    resp = await client.post(
        "/automation-rules",
        json={
            "name": "Escalate critical security tickets",
            "description": "Auto-escalate critical security tickets",
            "conditions": [
                {"field": "priority", "operator": "equals", "value": "critical"},
                {"field": "category", "operator": "equals", "value": "security"},
            ],
            "actions": [
                {"action_type": "set_status", "parameters": {"status": "in_progress"}},
                {"action_type": "notify_slack", "parameters": {"channel": "#security"}},
            ],
        },
        headers={"X-Api-Key": "admin-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Escalate critical security tickets"
    assert len(data["data"]["conditions"]) == 2
    assert len(data["data"]["actions"]) == 2
    assert data["data"]["enabled"] is True


@pytest.mark.asyncio
async def test_list_automation_rules(client):
    """Can list all automation rules."""
    # Create two rules
    for name in ["Rule A", "Rule B"]:
        await client.post(
            "/automation-rules",
            json={
                "name": name,
                "conditions": [{"field": "priority", "operator": "equals", "value": "high"}],
                "actions": [{"action_type": "set_status", "parameters": {"status": "in_progress"}}],
            },
            headers={"X-Api-Key": "admin-key"},
        )

    resp = await client.get(
        "/automation-rules",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["rules"]) == 2


@pytest.mark.asyncio
async def test_delete_automation_rule(client):
    """Admin can delete an automation rule."""
    # Create
    create_resp = await client.post(
        "/automation-rules",
        json={
            "name": "Temp rule",
            "conditions": [{"field": "priority", "operator": "equals", "value": "low"}],
            "actions": [{"action_type": "set_status", "parameters": {"status": "closed"}}],
        },
        headers={"X-Api-Key": "admin-key"},
    )
    rule_id = create_resp.json()["data"]["id"]

    # Delete
    resp = await client.delete(
        f"/automation-rules/{rule_id}",
        headers={"X-Api-Key": "admin-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == rule_id

    # Verify it's gone
    list_resp = await client.get(
        "/automation-rules",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert len(list_resp.json()["rules"]) == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_automation_rule(client):
    """Deleting a nonexistent rule returns 404."""
    resp = await client.delete(
        "/automation-rules/nonexistent-id",
        headers={"X-Api-Key": "admin-key"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_automation_rule_rbac_create(client):
    """Only admins can create automation rules."""
    resp = await client.post(
        "/automation-rules",
        json={
            "name": "Unauthorized rule",
            "conditions": [{"field": "priority", "operator": "equals", "value": "high"}],
            "actions": [{"action_type": "set_status", "parameters": {"status": "closed"}}],
        },
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_automation_rule_disabled(client):
    """Feature flag gating works."""
    from config import settings as _s  # noqa: PLC0415

    _s.automation_rules_enabled = False
    resp = await client.get(
        "/automation-rules",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403
    _s.automation_rules_enabled = True


@pytest.mark.asyncio
async def test_create_automation_rule_validation(client):
    """Automation rule requires at least one condition and one action."""
    resp = await client.post(
        "/automation-rules",
        json={
            "name": "Invalid rule",
            "conditions": [],
            "actions": [{"action_type": "set_status", "parameters": {"status": "closed"}}],
        },
        headers={"X-Api-Key": "admin-key"},
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 2. APPROVAL WORKFLOWS
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_approval_request(client):
    """Analyst can request approval for a ticket."""
    ticket_id = await _create_test_ticket(client)

    resp = await client.post(
        f"/tickets/{ticket_id}/approval-request",
        json={"approver": "manager-1", "reason": "Needs change approval"},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["ticket_id"] == ticket_id
    assert data["data"]["approver"] == "manager-1"
    assert data["data"]["status"] == "pending"


@pytest.mark.asyncio
async def test_approve_ticket(client):
    """Admin can approve a pending approval."""
    ticket_id = await _create_test_ticket(client)

    # Request approval
    await client.post(
        f"/tickets/{ticket_id}/approval-request",
        json={"approver": "manager-1", "reason": "Change approval needed"},
        headers={"X-Api-Key": "analyst-key"},
    )

    # Approve
    resp = await client.post(
        f"/tickets/{ticket_id}/approve",
        json={"decision": "approved", "comment": "Looks good"},
        headers={"X-Api-Key": "admin-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["status"] == "approved"
    assert data["data"]["decision_comment"] == "Looks good"
    assert data["data"]["decided_at"] is not None


@pytest.mark.asyncio
async def test_reject_ticket(client):
    """Admin can reject a pending approval."""
    ticket_id = await _create_test_ticket(client)

    await client.post(
        f"/tickets/{ticket_id}/approval-request",
        json={"approver": "manager-1", "reason": "Risky change"},
        headers={"X-Api-Key": "analyst-key"},
    )

    resp = await client.post(
        f"/tickets/{ticket_id}/approve",
        json={"decision": "rejected", "comment": "Too risky, needs more review"},
        headers={"X-Api-Key": "admin-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "rejected"


@pytest.mark.asyncio
async def test_approve_nonexistent_approval(client):
    """Approving a ticket with no pending approval returns 404."""
    ticket_id = await _create_test_ticket(client)

    resp = await client.post(
        f"/tickets/{ticket_id}/approve",
        json={"decision": "approved", "comment": ""},
        headers={"X-Api-Key": "admin-key"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_ticket_approvals(client):
    """Can list all approvals for a ticket."""
    ticket_id = await _create_test_ticket(client)

    # Create two approval requests
    await client.post(
        f"/tickets/{ticket_id}/approval-request",
        json={"approver": "manager-1", "reason": "First review"},
        headers={"X-Api-Key": "analyst-key"},
    )
    await client.post(
        f"/tickets/{ticket_id}/approval-request",
        json={"approver": "manager-2", "reason": "Second review"},
        headers={"X-Api-Key": "analyst-key"},
    )

    resp = await client.get(
        f"/tickets/{ticket_id}/approvals",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["approvals"]) == 2


@pytest.mark.asyncio
async def test_approval_request_nonexistent_ticket(client):
    """Requesting approval for a nonexistent ticket returns 404."""
    resp = await client.post(
        "/tickets/NONEXISTENT/approval-request",
        json={"approver": "manager-1", "reason": "Test"},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approval_rbac(client):
    """Only admins can approve/reject."""
    ticket_id = await _create_test_ticket(client)

    await client.post(
        f"/tickets/{ticket_id}/approval-request",
        json={"approver": "manager-1", "reason": "Test"},
        headers={"X-Api-Key": "analyst-key"},
    )

    resp = await client.post(
        f"/tickets/{ticket_id}/approve",
        json={"decision": "approved", "comment": ""},
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approval_disabled(client):
    """Feature flag gating works."""
    from config import settings as _s  # noqa: PLC0415

    _s.approval_workflows_enabled = False
    resp = await client.get(
        "/tickets/ANY/approvals",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403
    _s.approval_workflows_enabled = True


@pytest.mark.asyncio
async def test_approval_pending_decision_invalid(client):
    """Sending 'pending' as a decision is rejected."""
    ticket_id = await _create_test_ticket(client)

    await client.post(
        f"/tickets/{ticket_id}/approval-request",
        json={"approver": "manager-1", "reason": "Test"},
        headers={"X-Api-Key": "analyst-key"},
    )

    resp = await client.post(
        f"/tickets/{ticket_id}/approve",
        json={"decision": "pending", "comment": ""},
        headers={"X-Api-Key": "admin-key"},
    )
    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AGENT COLLISION DETECTION
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_lock_ticket(client):
    """Analyst can lock a ticket."""
    ticket_id = await _create_test_ticket(client)

    resp = await client.post(
        f"/tickets/{ticket_id}/lock",
        json={"agent_id": "agent-alice"},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["locked"] is True
    assert data["data"]["agent_id"] == "agent-alice"
    assert data["data"]["ticket_id"] == ticket_id


@pytest.mark.asyncio
async def test_lock_already_locked_ticket(client):
    """Locking an already-locked ticket returns 409."""
    ticket_id = await _create_test_ticket(client)

    await client.post(
        f"/tickets/{ticket_id}/lock",
        json={"agent_id": "agent-alice"},
        headers={"X-Api-Key": "analyst-key"},
    )

    resp = await client.post(
        f"/tickets/{ticket_id}/lock",
        json={"agent_id": "agent-bob"},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_unlock_ticket(client):
    """Analyst can unlock a ticket."""
    ticket_id = await _create_test_ticket(client)

    await client.post(
        f"/tickets/{ticket_id}/lock",
        json={"agent_id": "agent-alice"},
        headers={"X-Api-Key": "analyst-key"},
    )

    resp = await client.delete(
        f"/tickets/{ticket_id}/lock",
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["unlocked"] == ticket_id


@pytest.mark.asyncio
async def test_unlock_no_lock(client):
    """Unlocking a ticket with no lock returns 404."""
    resp = await client.delete(
        "/tickets/NONEXISTENT/lock",
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_lock_status_locked(client):
    """Can check lock status of a locked ticket."""
    ticket_id = await _create_test_ticket(client)

    await client.post(
        f"/tickets/{ticket_id}/lock",
        json={"agent_id": "agent-alice"},
        headers={"X-Api-Key": "analyst-key"},
    )

    resp = await client.get(
        f"/tickets/{ticket_id}/lock",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["locked"] is True
    assert data["data"]["agent_id"] == "agent-alice"


@pytest.mark.asyncio
async def test_get_lock_status_unlocked(client):
    """Lock status returns false for unlocked ticket."""
    resp = await client.get(
        "/tickets/UNLOCKED/lock",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["locked"] is False


@pytest.mark.asyncio
async def test_relock_after_unlock(client):
    """Can relock a ticket after unlocking it."""
    ticket_id = await _create_test_ticket(client)

    # Lock
    await client.post(
        f"/tickets/{ticket_id}/lock",
        json={"agent_id": "agent-alice"},
        headers={"X-Api-Key": "analyst-key"},
    )
    # Unlock
    await client.delete(
        f"/tickets/{ticket_id}/lock",
        headers={"X-Api-Key": "analyst-key"},
    )
    # Relock with different agent
    resp = await client.post(
        f"/tickets/{ticket_id}/lock",
        json={"agent_id": "agent-bob"},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["agent_id"] == "agent-bob"


@pytest.mark.asyncio
async def test_collision_detection_disabled(client):
    """Feature flag gating works."""
    from config import settings as _s  # noqa: PLC0415

    _s.collision_detection_enabled = False
    resp = await client.get(
        "/tickets/ANY/lock",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403
    _s.collision_detection_enabled = True


@pytest.mark.asyncio
async def test_lock_rbac(client):
    """Only analyst+ can lock tickets."""
    resp = await client.post(
        "/tickets/ANY/lock",
        json={"agent_id": "agent-viewer"},
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CUSTOMER CONTACT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_contact(client):
    """Analyst can create a contact."""
    resp = await client.post(
        "/contacts",
        json={
            "email": "alice@example.com",
            "name": "Alice Smith",
            "organisation": "Acme Corp",
            "phone": "+1-555-0100",
            "notes": "VIP customer",
        },
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["email"] == "alice@example.com"
    assert data["data"]["name"] == "Alice Smith"
    assert data["data"]["organisation"] == "Acme Corp"


@pytest.mark.asyncio
async def test_create_duplicate_contact(client):
    """Creating a contact with duplicate email returns 409."""
    await client.post(
        "/contacts",
        json={"email": "dup@example.com", "name": "First"},
        headers={"X-Api-Key": "analyst-key"},
    )
    resp = await client.post(
        "/contacts",
        json={"email": "dup@example.com", "name": "Second"},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_contacts(client):
    """Can list all contacts."""
    await client.post(
        "/contacts",
        json={"email": "a@test.com", "name": "A"},
        headers={"X-Api-Key": "analyst-key"},
    )
    await client.post(
        "/contacts",
        json={"email": "b@test.com", "name": "B"},
        headers={"X-Api-Key": "analyst-key"},
    )

    resp = await client.get(
        "/contacts",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["contacts"]) == 2


@pytest.mark.asyncio
async def test_link_contact_to_ticket(client):
    """Can link a contact to a ticket."""
    # Create contact
    contact_resp = await client.post(
        "/contacts",
        json={"email": "link@test.com", "name": "Link Test"},
        headers={"X-Api-Key": "analyst-key"},
    )
    contact_id = contact_resp.json()["data"]["id"]

    # Create ticket
    ticket_id = await _create_test_ticket(client)

    # Link
    resp = await client.post(
        f"/contacts/{contact_id}/tickets/{ticket_id}",
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["contact_id"] == contact_id
    assert resp.json()["ticket_id"] == ticket_id


@pytest.mark.asyncio
async def test_get_contact_tickets(client):
    """Can get all tickets for a contact."""
    # Create contact
    contact_resp = await client.post(
        "/contacts",
        json={"email": "tickets@test.com", "name": "Tickets Test"},
        headers={"X-Api-Key": "analyst-key"},
    )
    contact_id = contact_resp.json()["data"]["id"]

    # Create and link two tickets
    ticket1 = await _create_test_ticket(client)
    ticket2 = await _create_test_ticket(client)

    await client.post(
        f"/contacts/{contact_id}/tickets/{ticket1}",
        headers={"X-Api-Key": "analyst-key"},
    )
    await client.post(
        f"/contacts/{contact_id}/tickets/{ticket2}",
        headers={"X-Api-Key": "analyst-key"},
    )

    resp = await client.get(
        f"/contacts/{contact_id}/tickets",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["ticket_ids"]) == 2


@pytest.mark.asyncio
async def test_link_nonexistent_contact(client):
    """Linking a nonexistent contact returns 404."""
    resp = await client.post(
        "/contacts/nonexistent/tickets/TKT-001",
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_tickets_nonexistent_contact(client):
    """Getting tickets for nonexistent contact returns 404."""
    resp = await client.get(
        "/contacts/nonexistent/tickets",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_link(client):
    """Linking a ticket already linked to a contact returns 409."""
    contact_resp = await client.post(
        "/contacts",
        json={"email": "duplink@test.com", "name": "Dup Link"},
        headers={"X-Api-Key": "analyst-key"},
    )
    contact_id = contact_resp.json()["data"]["id"]
    ticket_id = await _create_test_ticket(client)

    await client.post(
        f"/contacts/{contact_id}/tickets/{ticket_id}",
        headers={"X-Api-Key": "analyst-key"},
    )
    resp = await client.post(
        f"/contacts/{contact_id}/tickets/{ticket_id}",
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_contact_management_disabled(client):
    """Feature flag gating works."""
    from config import settings as _s  # noqa: PLC0415

    _s.contact_management_enabled = False
    resp = await client.get(
        "/contacts",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403
    _s.contact_management_enabled = True


@pytest.mark.asyncio
async def test_contact_rbac(client):
    """Only analyst+ can create contacts."""
    resp = await client.post(
        "/contacts",
        json={"email": "noauth@test.com", "name": "No Auth"},
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# 5. MACROS
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_macro(client):
    """Admin can create a macro."""
    resp = await client.post(
        "/macros",
        json={
            "name": "Escalate & Notify",
            "description": "Set priority to critical and add escalated tag",
            "actions": [
                {"action_type": "set_priority", "parameters": {"priority": "critical"}},
                {"action_type": "add_tag", "parameters": {"tag": "escalated"}},
            ],
        },
        headers={"X-Api-Key": "admin-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Escalate & Notify"
    assert len(data["data"]["actions"]) == 2


@pytest.mark.asyncio
async def test_list_macros(client):
    """Can list all macros."""
    for name in ["Macro A", "Macro B"]:
        await client.post(
            "/macros",
            json={
                "name": name,
                "actions": [{"action_type": "set_status", "parameters": {"status": "closed"}}],
            },
            headers={"X-Api-Key": "admin-key"},
        )

    resp = await client.get(
        "/macros",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["macros"]) == 2


@pytest.mark.asyncio
async def test_delete_macro(client):
    """Admin can delete a macro."""
    create_resp = await client.post(
        "/macros",
        json={
            "name": "To Delete",
            "actions": [{"action_type": "set_status", "parameters": {"status": "closed"}}],
        },
        headers={"X-Api-Key": "admin-key"},
    )
    macro_id = create_resp.json()["data"]["id"]

    resp = await client.delete(
        f"/macros/{macro_id}",
        headers={"X-Api-Key": "admin-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == macro_id

    # Verify it's gone
    list_resp = await client.get(
        "/macros",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert len(list_resp.json()["macros"]) == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_macro(client):
    """Deleting a nonexistent macro returns 404."""
    resp = await client.delete(
        "/macros/nonexistent-id",
        headers={"X-Api-Key": "admin-key"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_execute_macro(client):
    """Analyst can execute a macro on a ticket."""
    # Create a macro
    create_resp = await client.post(
        "/macros",
        json={
            "name": "Close & Comment",
            "actions": [
                {"action_type": "set_status", "parameters": {"status": "closed"}},
                {"action_type": "add_comment", "parameters": {"text": "Closed via macro"}},
            ],
        },
        headers={"X-Api-Key": "admin-key"},
    )
    macro_id = create_resp.json()["data"]["id"]

    # Create a ticket
    ticket_id = await _create_test_ticket(client)

    # Execute
    resp = await client.post(
        f"/macros/{macro_id}/execute",
        params={"ticket_id": ticket_id},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["ticket_id"] == ticket_id
    assert len(data["actions_performed"]) == 2
    assert "set_status:closed" in data["actions_performed"]


@pytest.mark.asyncio
async def test_execute_macro_nonexistent(client):
    """Executing a nonexistent macro returns 404."""
    resp = await client.post(
        "/macros/nonexistent/execute",
        params={"ticket_id": "TKT-001"},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_execute_macro_nonexistent_ticket(client):
    """Executing a macro on a nonexistent ticket returns 404."""
    # Create a macro first
    create_resp = await client.post(
        "/macros",
        json={
            "name": "Test macro",
            "actions": [{"action_type": "set_status", "parameters": {"status": "closed"}}],
        },
        headers={"X-Api-Key": "admin-key"},
    )
    macro_id = create_resp.json()["data"]["id"]

    resp = await client.post(
        f"/macros/{macro_id}/execute",
        params={"ticket_id": "NONEXISTENT"},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_macro_rbac_create(client):
    """Only admins can create macros."""
    resp = await client.post(
        "/macros",
        json={
            "name": "Unauthorized",
            "actions": [{"action_type": "set_status", "parameters": {"status": "closed"}}],
        },
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_macro_rbac_execute(client):
    """Only analyst+ can execute macros."""
    # Create as admin
    create_resp = await client.post(
        "/macros",
        json={
            "name": "Exec test",
            "actions": [{"action_type": "set_status", "parameters": {"status": "closed"}}],
        },
        headers={"X-Api-Key": "admin-key"},
    )
    macro_id = create_resp.json()["data"]["id"]

    resp = await client.post(
        f"/macros/{macro_id}/execute",
        params={"ticket_id": "TKT-001"},
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_macros_disabled(client):
    """Feature flag gating works."""
    from config import settings as _s  # noqa: PLC0415

    _s.macros_enabled = False
    resp = await client.get(
        "/macros",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403
    _s.macros_enabled = True


@pytest.mark.asyncio
async def test_macro_set_priority_action(client):
    """Macro with set_priority action updates ticket priority."""
    create_resp = await client.post(
        "/macros",
        json={
            "name": "Set Priority",
            "actions": [
                {"action_type": "set_priority", "parameters": {"priority": "critical"}},
            ],
        },
        headers={"X-Api-Key": "admin-key"},
    )
    macro_id = create_resp.json()["data"]["id"]

    ticket_id = await _create_test_ticket(client)

    resp = await client.post(
        f"/macros/{macro_id}/execute",
        params={"ticket_id": ticket_id},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert resp.status_code == 200
    assert "set_priority:critical" in resp.json()["actions_performed"]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. CROSS-FEATURE INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_approval_then_lock_workflow(client):
    """End-to-end: request approval, approve, then lock for editing."""
    ticket_id = await _create_test_ticket(client)

    # Request approval
    await client.post(
        f"/tickets/{ticket_id}/approval-request",
        json={"approver": "manager-1", "reason": "Change request"},
        headers={"X-Api-Key": "analyst-key"},
    )

    # Approve
    await client.post(
        f"/tickets/{ticket_id}/approve",
        json={"decision": "approved", "comment": "Go ahead"},
        headers={"X-Api-Key": "admin-key"},
    )

    # Lock for editing
    lock_resp = await client.post(
        f"/tickets/{ticket_id}/lock",
        json={"agent_id": "agent-alice"},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert lock_resp.status_code == 200
    assert lock_resp.json()["locked"] is True

    # Verify approval history
    approval_resp = await client.get(
        f"/tickets/{ticket_id}/approvals",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert len(approval_resp.json()["approvals"]) == 1
    assert approval_resp.json()["approvals"][0]["status"] == "approved"


@pytest.mark.asyncio
async def test_contact_with_macro_execution(client):
    """End-to-end: create contact, link ticket, run macro on it."""
    # Create contact
    contact_resp = await client.post(
        "/contacts",
        json={"email": "integration@test.com", "name": "Integration Test"},
        headers={"X-Api-Key": "analyst-key"},
    )
    contact_id = contact_resp.json()["data"]["id"]

    # Create ticket
    ticket_id = await _create_test_ticket(client)

    # Link
    await client.post(
        f"/contacts/{contact_id}/tickets/{ticket_id}",
        headers={"X-Api-Key": "analyst-key"},
    )

    # Create and execute macro
    macro_resp = await client.post(
        "/macros",
        json={
            "name": "Quick Close",
            "actions": [{"action_type": "set_status", "parameters": {"status": "resolved"}}],
        },
        headers={"X-Api-Key": "admin-key"},
    )
    macro_id = macro_resp.json()["data"]["id"]

    exec_resp = await client.post(
        f"/macros/{macro_id}/execute",
        params={"ticket_id": ticket_id},
        headers={"X-Api-Key": "analyst-key"},
    )
    assert exec_resp.status_code == 200
    assert "set_status:resolved" in exec_resp.json()["actions_performed"]

    # Verify contact still linked
    tickets_resp = await client.get(
        f"/contacts/{contact_id}/tickets",
        headers={"X-Api-Key": "viewer-key"},
    )
    assert ticket_id in tickets_resp.json()["ticket_ids"]
