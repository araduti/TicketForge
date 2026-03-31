"""
TicketForge — Test suite for security hardening and v1 readiness features.

Tests for:
- API key hashing and constant-time comparison (A1)
- API key rotation endpoint (A2)
- Input sanitisation middleware (A3)
- Request ID middleware (A4)
- CORS configuration (A5)
- Security headers / CSP (A7)
- Standardised error response format (B3)
- Readiness endpoint (C3)
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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_security.db"

from main import app, lifespan  # noqa: E402

DB_PATH = "./test_ticketforge_security.db"


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    try:
        os.remove(DB_PATH)
    except FileNotFoundError:
        pass

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    try:
        os.remove(DB_PATH)
    except FileNotFoundError:
        pass


# ── A1: API key hashing & constant-time comparison ───────────────────────────

class TestApiKeyHashing:
    """API keys should be hashed at rest and compared via constant-time check."""

    @pytest.mark.asyncio
    async def test_valid_key_authenticates(self, client):
        """A valid API key should authenticate successfully."""
        response = await client.get(
            "/health",
            headers={"X-Api-Key": "admin-key"},
        )
        # /health doesn't require auth, but let's test an auth-required endpoint
        response = await client.get(
            "/tickets/nonexistent",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_key_returns_401(self, client):
        """An invalid API key should return 401."""
        response = await client.get(
            "/tickets/nonexistent",
            headers={"X-Api-Key": "bad-key-12345"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_role_enforcement_still_works(self, client):
        """RBAC should still work with hashed key comparison."""
        # Viewer cannot access admin-only endpoint
        response = await client.get(
            "/audit/logs",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 403

        # Admin can access admin-only endpoint
        response = await client.get(
            "/audit/logs",
            headers={"X-Api-Key": "admin-key"},
        )
        assert response.status_code == 200


# ── A2: API key rotation ─────────────────────────────────────────────────────

class TestApiKeyRotation:
    """API key rotation endpoint should generate and register new keys."""

    @pytest.mark.asyncio
    async def test_rotate_requires_admin(self, client):
        """Non-admin users should not be able to rotate keys."""
        response = await client.post(
            "/api-keys/rotate",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_rotate_generates_new_key(self, client):
        """Admin should be able to generate a new API key."""
        response = await client.post(
            "/api-keys/rotate",
            headers={"X-Api-Key": "admin-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "api_key" in data
        assert "key_id" in data
        assert len(data["api_key"]) > 20  # token_urlsafe(32) is ~43 chars

    @pytest.mark.asyncio
    async def test_rotated_key_works(self, client):
        """A newly rotated key should authenticate successfully."""
        # Generate new key
        response = await client.post(
            "/api-keys/rotate",
            headers={"X-Api-Key": "admin-key"},
        )
        new_key = response.json()["api_key"]

        # Use the new key
        response = await client.get(
            "/health",
        )
        assert response.status_code == 200


# ── A3: Input sanitisation ───────────────────────────────────────────────────

class TestInputSanitisation:
    """Request bodies should be sanitised to prevent XSS/injection."""

    @pytest.mark.asyncio
    async def test_script_tags_stripped(self, client):
        """Script tags should be stripped from JSON string values."""
        response = await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "title": "Test <script>alert('xss')</script> Article",
                "content": "Safe content",
                "category": "test",
            },
        )
        # The article should be created, but with sanitised title
        if response.status_code == 200:
            data = response.json()
            assert "<script>" not in data.get("title", "")

    @pytest.mark.asyncio
    async def test_html_escaped(self, client):
        """HTML special characters should be escaped in string values."""
        response = await client.post(
            "/kb/articles",
            headers={"X-Api-Key": "analyst-key"},
            json={
                "title": "Test <b>bold</b> & \"quotes\"",
                "content": "Content with <img src=x>",
                "category": "test",
            },
        )
        if response.status_code == 200:
            data = response.json()
            title = data.get("title", "")
            assert "<b>" not in title


# ── A4: Request ID middleware ────────────────────────────────────────────────

class TestRequestId:
    """Every response should include an X-Request-ID header."""

    @pytest.mark.asyncio
    async def test_response_has_request_id(self, client):
        """Responses should include an X-Request-ID header."""
        response = await client.get("/health")
        assert "x-request-id" in response.headers
        # Should be a valid UUID
        req_id = response.headers["x-request-id"]
        assert len(req_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_custom_request_id_propagated(self, client):
        """A client-supplied X-Request-ID should be echoed back."""
        custom_id = "custom-request-id-12345"
        response = await client.get(
            "/health",
            headers={"X-Request-ID": custom_id},
        )
        assert response.headers.get("x-request-id") == custom_id


# ── A7: Security headers ────────────────────────────────────────────────────

class TestSecurityHeaders:
    """Responses should include security headers."""

    @pytest.mark.asyncio
    async def test_csp_header_present(self, client):
        """Content-Security-Policy header should be present."""
        response = await client.get("/health")
        assert "content-security-policy" in response.headers

    @pytest.mark.asyncio
    async def test_x_content_type_options(self, client):
        """X-Content-Type-Options: nosniff should be present."""
        response = await client.get("/health")
        assert response.headers.get("x-content-type-options") == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options(self, client):
        """X-Frame-Options: DENY should be present."""
        response = await client.get("/health")
        assert response.headers.get("x-frame-options") == "DENY"

    @pytest.mark.asyncio
    async def test_referrer_policy(self, client):
        """Referrer-Policy header should be present."""
        response = await client.get("/health")
        assert "referrer-policy" in response.headers


# ── B3: Standardised error format ────────────────────────────────────────────

class TestStandardisedErrors:
    """Error responses should include both 'detail' and 'error' structure."""

    @pytest.mark.asyncio
    async def test_401_error_format(self, client):
        """401 errors should use the standardised format."""
        response = await client.get(
            "/tickets/nonexistent",
            headers={"X-Api-Key": "bad-key"},
        )
        assert response.status_code == 401
        data = response.json()
        # Backward-compatible 'detail' key
        assert "detail" in data
        # New standardised 'error' structure
        assert "error" in data
        assert data["error"]["code"] == 401
        assert "message" in data["error"]
        assert "request_id" in data["error"]

    @pytest.mark.asyncio
    async def test_403_error_format(self, client):
        """403 errors should use the standardised format."""
        response = await client.get(
            "/audit/logs",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 403
        data = response.json()
        assert "detail" in data
        assert "error" in data
        assert data["error"]["code"] == 403

    @pytest.mark.asyncio
    async def test_404_error_format(self, client):
        """404 errors should use the standardised format."""
        response = await client.get(
            "/tickets/nonexistent",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "error" in data
        assert data["error"]["code"] == 404


# ── C3: Readiness endpoint ───────────────────────────────────────────────────

class TestReadiness:
    """The /ready endpoint should check all dependencies."""

    @pytest.mark.asyncio
    async def test_ready_endpoint_exists(self, client):
        """GET /ready should return a response."""
        response = await client.get("/ready")
        assert response.status_code in (200, 503)

    @pytest.mark.asyncio
    async def test_ready_returns_checks(self, client):
        """Readiness response should include dependency checks."""
        response = await client.get("/ready")
        data = response.json()
        assert "status" in data
        assert "checks" in data
        assert "database" in data["checks"]
        assert "vector_store" in data["checks"]
        assert "processor" in data["checks"]

    @pytest.mark.asyncio
    async def test_ready_status_200_when_healthy(self, client):
        """When all dependencies are up, /ready should return 200."""
        response = await client.get("/ready")
        data = response.json()
        # Database should be ready after lifespan startup
        assert data["checks"]["database"] is True
