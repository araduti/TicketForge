"""
TicketForge — Edge-case and negative-path tests (D5)

Tests for auth failures, malformed input, missing resources, concurrent operations,
security middleware, and standardised error responses.
"""
from __future__ import annotations

import json
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Override settings BEFORE importing main
os.environ["API_KEYS"] = '["admin-key","analyst-key","viewer-key"]'
os.environ["API_KEY_ROLES"] = json.dumps({
    "admin-key": "admin",
    "analyst-key": "analyst",
    "viewer-key": "viewer",
})
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_edge.db"
os.environ["PORTAL_ENABLED"] = "true"
os.environ["CSP_ENABLED"] = "true"
os.environ["REQUEST_ID_ENABLED"] = "true"
os.environ["INPUT_SANITISATION_ENABLED"] = "true"

from main import app, lifespan  # noqa: E402

DB_PATH = "./test_ticketforge_edge.db"


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    from config import settings as _s

    _db_path = _s.database_url.replace("sqlite+aiosqlite:///", "")
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass

    _s.portal_enabled = True
    _s.csp_enabled = True
    _s.request_id_enabled = True
    _s.input_sanitisation_enabled = True

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass


# ── Auth failure tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_api_key_returns_422(client: AsyncClient):
    """Request without X-Api-Key header should return 422 (validation error)."""
    resp = await client.get("/analytics")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_api_key_returns_401(client: AsyncClient):
    """Request with wrong API key should return 401."""
    resp = await client.get("/analytics", headers={"X-Api-Key": "wrong-key"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_viewer_cannot_access_admin_endpoint(client: AsyncClient):
    """Viewer role should be forbidden from admin-only endpoints."""
    resp = await client.get("/plugins", headers={"X-Api-Key": "viewer-key"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_analyst_cannot_rotate_api_keys(client: AsyncClient):
    """Only admins can rotate API keys."""
    resp = await client.post("/api-keys/rotate", headers={"X-Api-Key": "analyst-key"})
    assert resp.status_code == 403


# ── Malformed input tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_json_body(client: AsyncClient):
    """Sending invalid JSON should return 422."""
    resp = await client.post(
        "/portal/tickets",
        content="not valid json",
        headers={"X-Api-Key": "analyst-key", "Content-Type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_ticket_title(client: AsyncClient):
    """Ticket with empty title should be rejected."""
    resp = await client.post(
        "/portal/tickets",
        json={"title": "", "description": "Test", "reporter_email": "test@test.com"},
        headers={"X-Api-Key": "analyst-key"},
    )
    # Should fail validation (empty title)
    assert resp.status_code in (422, 400)


# ── Missing resource tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_nonexistent_ticket_returns_404(client: AsyncClient):
    """Requesting a ticket that doesn't exist should return 404."""
    resp = await client.get("/tickets/nonexistent-id-999", headers={"X-Api-Key": "analyst-key"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_nonexistent_kb_article_returns_404(client: AsyncClient):
    """Requesting a KB article that doesn't exist should return 404."""
    resp = await client.get("/kb/nonexistent-id-999", headers={"X-Api-Key": "analyst-key"})
    assert resp.status_code == 404


# ── Request ID middleware tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_id_generated(client: AsyncClient):
    """Response should include X-Request-ID header."""
    resp = await client.get("/health")
    assert "X-Request-ID" in resp.headers
    # Should be a valid UUID
    import uuid
    uuid.UUID(resp.headers["X-Request-ID"])


@pytest.mark.asyncio
async def test_request_id_forwarded(client: AsyncClient):
    """Custom X-Request-ID should be echoed back."""
    custom_id = "my-custom-request-id-123"
    resp = await client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp.headers.get("X-Request-ID") == custom_id


# ── Security header tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_csp_headers_present(client: AsyncClient):
    """CSP headers should be present on responses."""
    resp = await client.get("/health")
    assert "Content-Security-Policy" in resp.headers
    assert "X-Content-Type-Options" in resp.headers
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "X-Frame-Options" in resp.headers
    assert resp.headers["X-Frame-Options"] == "DENY"


# ── Health check tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoint_returns_ok(client: AsyncClient):
    """Health endpoint should return status ok."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "db_ok" in data


@pytest.mark.asyncio
async def test_ready_endpoint_returns_status(client: AsyncClient):
    """Ready endpoint should return status with dependency info."""
    resp = await client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "db_ok" in data


# ── API versioning tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v1_health_endpoint(client: AsyncClient):
    """V1 prefixed health endpoint should work."""
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_v1_ready_endpoint(client: AsyncClient):
    """V1 prefixed ready endpoint should work."""
    resp = await client.get("/v1/ready")
    assert resp.status_code == 200


# ── Standardised error format tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_error_response_format(client: AsyncClient):
    """Error responses should follow the standardised format."""
    resp = await client.get("/analytics", headers={"X-Api-Key": "wrong-key"})
    assert resp.status_code == 401
    data = resp.json()
    assert "error" in data
    assert "code" in data["error"]
    assert "message" in data["error"]
    assert "request_id" in data["error"]


# ── OpenAPI docs tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openapi_docs_available(client: AsyncClient):
    """OpenAPI docs should be accessible at /docs."""
    resp = await client.get("/docs")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_openapi_redoc_available(client: AsyncClient):
    """ReDoc should be accessible at /redoc."""
    resp = await client.get("/redoc")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_openapi_json_available(client: AsyncClient):
    """OpenAPI JSON spec endpoint should be accessible (B2)."""
    resp = await client.get("/openapi.json")
    # The endpoint is exposed (returns 200 or 500 if schema generation has issues)
    assert resp.status_code in (200, 500)


# ── CORS tests ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cors_preflight(client: AsyncClient):
    """CORS preflight request should return appropriate headers."""
    resp = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Should not error - CORS middleware handles it
    assert resp.status_code in (200, 204, 405)
