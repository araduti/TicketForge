# OAuth2 / OpenID Connect Integration Guide

> **Audience:** Platform engineers, identity administrators, and security teams
> integrating TicketForge with an enterprise Single Sign-On (SSO) provider.
>
> **Status:** Phase A — Security (see [ROADMAP.md](../ROADMAP.md))

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Supported Identity Providers](#3-supported-identity-providers)
4. [Configuration Reference](#4-configuration-reference)
5. [Implementation Guide](#5-implementation-guide)
6. [Token Flow Diagram](#6-token-flow-diagram)
7. [Testing with a Local Keycloak Instance](#7-testing-with-a-local-keycloak-instance)
8. [Migration Path — API Key to OAuth2/OIDC](#8-migration-path--api-key-to-oauth2oidc)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Overview

### Why SSO / OAuth2 / OIDC Matters

Enterprise organisations evaluating TicketForge consistently raise the same
blocker: *"How does it integrate with our identity provider?"*  Plain-text API
keys are adequate for developer tooling and CI/CD pipelines, but they fall short
in environments that mandate:

| Requirement | API Keys | OAuth2 / OIDC |
|---|---|---|
| Centralised user lifecycle management | ❌ | ✅ |
| Multi-factor authentication (MFA) | ❌ | ✅ |
| Automatic credential rotation | ❌ | ✅ (token expiry) |
| Fine-grained, claim-based authorisation | ❌ | ✅ |
| Audit trail tied to named users | ❌ | ✅ (sub claim) |
| Compliance (SOC 2, ISO 27001, HIPAA) | Partial | ✅ |

By supporting OAuth2 / OIDC, TicketForge can slot into the same SSO fabric
that already protects ServiceNow, Jira, and Zendesk — closing the most
significant gap identified in our
[Competitive Analysis](./COMPETITIVE_ANALYSIS.md).

### Design Principles

* **TicketForge is a *relying party*, not an identity provider.**  It validates
  tokens issued by an external IdP; it never stores passwords or issues tokens
  itself.
* **Backwards-compatible.**  Existing API-key authentication continues to work.
  OAuth2 is opt-in via the `OAUTH2_ENABLED` flag.
* **Zero additional infrastructure** when used with a managed IdP (Azure AD,
  Okta, Auth0, Google Workspace).  A self-hosted Keycloak instance is needed
  only if no managed IdP is available.

---

## 2. Architecture

### High-Level Component Diagram

```
┌──────────────┐       ┌──────────────┐       ┌──────────────────────┐
│   Browser /  │       │   Identity   │       │     TicketForge      │
│   Client App │       │   Provider   │       │     (FastAPI)        │
│              │       │  (IdP)       │       │                      │
│  1. Login ──────────▶│              │       │                      │
│              │       │  2. Authn ─┐ │       │                      │
│  3. Token ◀──────────│◀───────────┘ │       │                      │
│              │       │              │       │                      │
│  4. Request ─────────────────────────────▶  │ 5. Validate JWT      │
│  Authorization:      │              │       │    ├─ Fetch JWKS     │
│  Bearer <token>      │              │       │    ├─ Verify sig     │
│              │       │              │       │    ├─ Check claims   │
│  7. Response ◀───────────────────────────── │ 6. Map role → RBAC  │
│              │       │              │       │                      │
└──────────────┘       └──────────────┘       └──────────────────────┘
```

### Token Validation Middleware

The middleware is implemented as a **FastAPI dependency** that sits alongside
the existing `verify_api_key()` function.  When `OAUTH2_ENABLED=true`, the
dependency chain becomes:

```
Incoming request
  │
  ├─ Has "Authorization: Bearer <jwt>" header?
  │    ├─ YES → validate JWT (signature, expiry, audience, issuer, scopes)
  │    │         ├─ Valid   → extract role from claims, continue
  │    │         └─ Invalid → 401 Unauthorized
  │    │
  │    └─ NO  → Has "X-Api-Key" header?
  │              ├─ YES → existing API-key path (unchanged)
  │              └─ NO  → 401 Unauthorized
  │
  └─ OAUTH2_ENABLED=false (default)
       └─ existing API-key path only
```

This **dual-auth** approach means OAuth2 and API-key authentication can coexist
during migration.  See [§8 — Migration Path](#8-migration-path--api-key-to-oauth2oidc).

---

## 3. Supported Identity Providers

TicketForge supports any OAuth2-compliant provider that exposes an
[OIDC Discovery](https://openid.net/specs/openid-connect-discovery-1_0.html)
endpoint (`/.well-known/openid-configuration`).  Below are tested
configurations for the most common providers.

### 3.1 Azure AD / Entra ID

```bash
OAUTH2_ENABLED=true
OAUTH2_ISSUER_URL=https://login.microsoftonline.com/<tenant-id>/v2.0
OAUTH2_AUDIENCE=api://<application-id>
OAUTH2_ALGORITHMS=RS256
OAUTH2_SCOPES=openid profile email
OAUTH2_ROLE_CLAIM=roles
OAUTH2_ADMIN_GROUPS=TicketForge-Admins
```

**Azure-specific notes:**

* Register TicketForge as an *App Registration* in the Azure portal.
* Under *Token configuration → Add groups claim*, select **Security groups**.
* Create App Roles (`admin`, `analyst`, `viewer`) under *App roles* and assign
  users or groups to them.  The `roles` claim is then included in the access
  token automatically.
* The `v2.0` issuer endpoint is recommended; the v1 endpoint uses a different
  token format.

### 3.2 Okta

```bash
OAUTH2_ENABLED=true
OAUTH2_ISSUER_URL=https://<your-org>.okta.com/oauth2/default
OAUTH2_AUDIENCE=api://ticketforge
OAUTH2_ALGORITHMS=RS256
OAUTH2_SCOPES=openid profile email
OAUTH2_ROLE_CLAIM=groups
OAUTH2_ADMIN_GROUPS=TicketForge-Admins
```

**Okta-specific notes:**

* Create an *API Authorization Server* (or use the `default` server).
* Add a `groups` claim to the access token under *Security → API →
  Authorization Servers → Claims*.
* Use a *Groups filter* of type "Starts with" with value `TicketForge-` to
  limit which groups are included in the token.

### 3.3 Auth0

```bash
OAUTH2_ENABLED=true
OAUTH2_ISSUER_URL=https://<your-tenant>.auth0.com/
OAUTH2_AUDIENCE=https://ticketforge.example.com/api
OAUTH2_ALGORITHMS=RS256
OAUTH2_SCOPES=openid profile email
OAUTH2_ROLE_CLAIM=https://ticketforge.example.com/roles
OAUTH2_ADMIN_GROUPS=admin
```

**Auth0-specific notes:**

* Register a *Machine-to-Machine* or *Regular Web* application.
* Create an *API* with the audience identifier above.
* Use an **Auth0 Action** (post-login trigger) to inject a custom `roles`
  claim into the access token.  Auth0 requires custom claims to use a
  namespaced URI (e.g. `https://ticketforge.example.com/roles`).

Example Auth0 Action:

```javascript
exports.onExecutePostLogin = async (event, api) => {
  const namespace = "https://ticketforge.example.com";
  const roles = event.authorization?.roles || [];
  api.accessToken.setCustomClaim(`${namespace}/roles`, roles);
};
```

### 3.4 Keycloak (Self-Hosted)

```bash
OAUTH2_ENABLED=true
OAUTH2_ISSUER_URL=http://localhost:8080/realms/ticketforge
OAUTH2_AUDIENCE=ticketforge-api
OAUTH2_ALGORITHMS=RS256
OAUTH2_SCOPES=openid profile email
OAUTH2_ROLE_CLAIM=realm_access.roles
OAUTH2_ADMIN_GROUPS=tf-admin
```

**Keycloak-specific notes:**

* Create a realm called `ticketforge` and a client called `ticketforge-api`.
* Set the client *Access Type* to **confidential** (or *Client authentication*
  on in Keycloak 21+).
* Keycloak embeds realm roles in `realm_access.roles` by default — no
  additional mapper is needed.
* For client-specific roles, use `resource_access.ticketforge-api.roles` as
  the role claim.

### 3.5 Google Workspace

```bash
OAUTH2_ENABLED=true
OAUTH2_ISSUER_URL=https://accounts.google.com
OAUTH2_AUDIENCE=<client-id>.apps.googleusercontent.com
OAUTH2_ALGORITHMS=RS256
OAUTH2_SCOPES=openid profile email
OAUTH2_ROLE_CLAIM=hd
OAUTH2_ADMIN_GROUPS=example.com
```

**Google-specific notes:**

* Google does not natively include group membership in ID tokens.  For basic
  access control, use the `hd` (hosted domain) claim to restrict access to
  your organisation.
* For granular role mapping, use the
  [Google Workspace Admin SDK](https://developers.google.com/admin-sdk) to
  resolve group membership at token validation time, or deploy a lightweight
  token-exchange proxy that enriches the token with a `roles` claim.
* Alternatively, pair Google as the upstream IdP with a Keycloak or Auth0
  instance that performs identity brokering and adds the role claims.

---

## 4. Configuration Reference

All configuration is via environment variables (or `.env` file), consistent
with the existing TicketForge settings pattern in `config.py`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `OAUTH2_ENABLED` | No | `false` | Enable OAuth2/OIDC token validation. When `false`, only API-key auth is active. |
| `OAUTH2_ISSUER_URL` | Yes* | — | OIDC issuer URL. Used for discovery (`/.well-known/openid-configuration`) and `iss` claim validation. |
| `OAUTH2_AUDIENCE` | Yes* | — | Expected `aud` claim in the JWT. Prevents token confusion attacks. |
| `OAUTH2_ALGORITHMS` | No | `RS256` | Comma-separated list of accepted signing algorithms (e.g. `RS256,ES256`). **Never** include `none` or symmetric algorithms like `HS256` unless the IdP specifically requires it. |
| `OAUTH2_JWKS_URL` | No | Auto-discovered | JWKS endpoint URL. Normally auto-discovered from the issuer's OIDC metadata. Set manually only if the IdP does not support OIDC discovery. |
| `OAUTH2_SCOPES` | No | `openid` | Space-separated list of required scopes. The JWT must contain all listed scopes. |
| `OAUTH2_ROLE_CLAIM` | No | `roles` | Dot-notation path to the JWT claim containing the user's roles or groups (e.g. `realm_access.roles`). |
| `OAUTH2_ADMIN_GROUPS` | No | `admin` | Comma-separated list of IdP groups/roles that map to TicketForge's `admin` role. |

> \* Required when `OAUTH2_ENABLED=true`.

### Example `.env` File

```bash
# --- Existing TicketForge settings ---
API_KEYS=sk-pipeline-key-1,sk-pipeline-key-2
API_KEY_ROLES={"sk-pipeline-key-1": "admin", "sk-pipeline-key-2": "analyst"}

# --- OAuth2 / OIDC settings ---
OAUTH2_ENABLED=true
OAUTH2_ISSUER_URL=https://login.microsoftonline.com/contoso.onmicrosoft.com/v2.0
OAUTH2_AUDIENCE=api://ticketforge-prod
OAUTH2_ALGORITHMS=RS256
OAUTH2_SCOPES=openid profile email
OAUTH2_ROLE_CLAIM=roles
OAUTH2_ADMIN_GROUPS=TicketForge-Admins,Platform-Engineering
```

---

## 5. Implementation Guide

### 5.1 JWT Extraction and Validation

The OAuth2 middleware is a FastAPI dependency that runs before every protected
endpoint.  It performs the following steps:

```python
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

bearer_scheme = HTTPBearer(auto_error=False)


async def verify_oauth2_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Extract and validate a JWT from the Authorization: Bearer header."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    jwks = await get_jwks()  # cached; see §5.2

    try:
        payload = jwt.decode(
            token,
            jwks,
            algorithms=settings.oauth2_algorithms,
            audience=settings.oauth2_audience,
            issuer=settings.oauth2_issuer_url,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload
```

### 5.2 JWKS Key Caching with Rotation Support

JSON Web Key Sets are fetched from the IdP's JWKS endpoint and cached
in-memory.  The cache is refreshed:

* **On a timer** — every 6 hours (configurable), to pick up routine key
  rotations.
* **On failure** — if token validation fails with a `kid`-not-found error,
  the cache is force-refreshed once before returning a 401.  This handles
  emergency key rotations gracefully.

```python
import time
from typing import Any

import httpx

_jwks_cache: dict[str, Any] = {}
_jwks_cache_expiry: float = 0.0
JWKS_CACHE_TTL = 6 * 60 * 60  # 6 hours


async def get_jwks() -> dict:
    """Return cached JWKS, refreshing if stale."""
    global _jwks_cache, _jwks_cache_expiry

    if time.monotonic() < _jwks_cache_expiry and _jwks_cache:
        return _jwks_cache

    jwks_url = settings.oauth2_jwks_url or await _discover_jwks_url()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()

    _jwks_cache = resp.json()
    _jwks_cache_expiry = time.monotonic() + JWKS_CACHE_TTL
    return _jwks_cache


async def _discover_jwks_url() -> str:
    """Fetch the jwks_uri from the OIDC discovery document."""
    discovery_url = f"{settings.oauth2_issuer_url.rstrip('/')}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
    return resp.json()["jwks_uri"]
```

### 5.3 Role Mapping — JWT Claims to RBAC Roles

TicketForge uses three RBAC roles with a strict hierarchy (defined in
`models.py`):

| TicketForge Role | Tier | Permissions |
|---|---|---|
| `admin` | 2 | Full access — configuration, user management, all analyst/viewer actions |
| `analyst` | 1 | Analyse tickets, manage knowledge base, view dashboards |
| `viewer` | 0 | Read-only access to enriched tickets and dashboards |

The middleware maps IdP claims to these roles using the following logic:

```python
from models import Role


def resolve_role_from_claims(payload: dict) -> Role:
    """Map JWT claims to a TicketForge RBAC role.

    Walk the dot-notation path in OAUTH2_ROLE_CLAIM to extract
    the list of roles/groups, then map to the highest matching
    TicketForge role.
    """
    claim_path = settings.oauth2_role_claim.split(".")
    value = payload
    for segment in claim_path:
        if isinstance(value, dict):
            value = value.get(segment, [])
        else:
            value = []
            break

    # Normalise to a list of lowercase strings.
    if isinstance(value, str):
        groups = [value.lower()]
    elif isinstance(value, list):
        groups = [str(g).lower() for g in value]
    else:
        groups = []

    admin_groups = {
        g.strip().lower() for g in settings.oauth2_admin_groups.split(",")
    }

    if admin_groups & set(groups):
        return Role.admin
    if groups:
        # Any authenticated user with at least one group is an analyst.
        return Role.analyst
    # Authenticated but no group membership → viewer.
    return Role.viewer
```

### 5.4 Dual-Auth Dependency

The unified authentication dependency selects the correct strategy at
runtime:

```python
async def authenticate(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> tuple[str, Role]:
    """Unified auth dependency — returns (identity, role).

    Returns a tuple of (identity_string, Role).
    - OAuth2 path: identity is the 'sub' claim.
    - API-key path: identity is the hashed API key.
    """
    if settings.oauth2_enabled and bearer is not None:
        payload = await verify_oauth2_token(bearer)
        role = resolve_role_from_claims(payload)
        identity = payload.get("sub", "unknown")
        return identity, role

    # Fallback to API-key authentication.
    api_key = request.headers.get("X-Api-Key")
    if api_key and api_key in settings.get_api_keys():
        role = _resolve_role(api_key)
        identity = _hash_api_key(api_key)
        return identity, role

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid Bearer token or API key required",
    )
```

Existing endpoint signatures remain unchanged — the `require_analyst`,
`require_admin`, and `require_viewer` dependencies are updated internally
to call `authenticate()`.

### 5.5 Audit Log Integration

When OAuth2 is active, the audit log records the JWT `sub` (subject) claim
instead of the hashed API key.  This provides a human-readable audit trail
tied to the IdP identity:

```
# API-key audit entry
{"api_key_hash": "a1b2c3d4e5f6", "role": "analyst", "action": "analyse", ...}

# OAuth2 audit entry
{"api_key_hash": "oidc:alice@contoso.com", "role": "admin", "action": "analyse", ...}
```

The `api_key_hash` column is reused (with an `oidc:` prefix) to avoid
a schema migration.  A future release may rename this column to `identity`.

---

## 6. Token Flow Diagram

### Authorization Code Flow (Browser / SPA)

```
 ┌─────────┐                ┌──────────┐               ┌─────────────┐
 │ Browser │                │   IdP    │               │ TicketForge │
 └────┬────┘                └────┬─────┘               └──────┬──────┘
      │                          │                             │
      │  1. GET /login           │                             │
      │─────────────────────────▶│                             │
      │                          │                             │
      │  2. Login page (MFA)     │                             │
      │◀─────────────────────────│                             │
      │                          │                             │
      │  3. Credentials + MFA    │                             │
      │─────────────────────────▶│                             │
      │                          │                             │
      │  4. 302 redirect         │                             │
      │     ?code=AUTH_CODE      │                             │
      │◀─────────────────────────│                             │
      │                          │                             │
      │  5. Exchange code ───────────────────────────────────▶ │
      │     (via front-end or    │                             │
      │      back-end channel)   │                             │
      │                          │  6. POST /token             │
      │                          │◀────────────────────────────│
      │                          │                             │
      │                          │  7. { access_token, ... }   │
      │                          │────────────────────────────▶│
      │                          │                             │
      │  8. API request with     │                             │
      │     Authorization:       │                             │
      │     Bearer <token>       │                             │
      │───────────────────────────────────────────────────────▶│
      │                          │                             │
      │                          │  9. Fetch JWKS (cached)     │
      │                          │◀────────────────────────────│
      │                          │                             │
      │                          │  10. Return JWKS            │
      │                          │────────────────────────────▶│
      │                          │                             │
      │  11. 200 OK { data }     │                             │
      │◀──────────────────────────────────────────────────────│
      │                          │                             │
```

### Client Credentials Flow (Service-to-Service)

```
 ┌──────────────┐          ┌──────────┐          ┌─────────────┐
 │  CI Pipeline │          │   IdP    │          │ TicketForge │
 │  / Service   │          │          │          │             │
 └──────┬───────┘          └────┬─────┘          └──────┬──────┘
        │                       │                       │
        │ 1. POST /token        │                       │
        │   grant_type=         │                       │
        │   client_credentials  │                       │
        │   client_id=...       │                       │
        │   client_secret=...   │                       │
        │──────────────────────▶│                       │
        │                       │                       │
        │ 2. { access_token }   │                       │
        │◀──────────────────────│                       │
        │                       │                       │
        │ 3. API request        │                       │
        │   Authorization:      │                       │
        │   Bearer <token>      │                       │
        │──────────────────────────────────────────────▶│
        │                       │                       │
        │                       │ 4. Validate JWT       │
        │                       │   (JWKS cached)       │
        │                       │                       │
        │ 5. 200 OK { data }    │                       │
        │◀─────────────────────────────────────────────│
        │                       │                       │
```

---

## 7. Testing with a Local Keycloak Instance

A local Keycloak instance provides a fully self-contained environment for
testing OAuth2/OIDC integration without requiring access to a managed IdP.

### 7.1 Start Keycloak

Add the following service to `docker-compose.yml` (or run standalone):

```yaml
services:
  keycloak:
    image: quay.io/keycloak/keycloak:25.0
    command: start-dev
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: admin
    ports:
      - "8080:8080"
```

```bash
docker compose up -d keycloak
```

### 7.2 Configure the Realm

1. Open `http://localhost:8080` and log in as `admin` / `admin`.
2. Create a new realm: **ticketforge**.
3. Create a client:
   - **Client ID:** `ticketforge-api`
   - **Client authentication:** On
   - **Valid redirect URIs:** `http://localhost:8000/*`
4. Under *Realm roles*, create three roles: `tf-admin`, `tf-analyst`,
   `tf-viewer`.
5. Create a test user (`alice`) and assign the `tf-admin` role.

### 7.3 Configure TicketForge

```bash
export OAUTH2_ENABLED=true
export OAUTH2_ISSUER_URL=http://localhost:8080/realms/ticketforge
export OAUTH2_AUDIENCE=ticketforge-api
export OAUTH2_ALGORITHMS=RS256
export OAUTH2_SCOPES=openid
export OAUTH2_ROLE_CLAIM=realm_access.roles
export OAUTH2_ADMIN_GROUPS=tf-admin
```

### 7.4 Obtain a Token

```bash
# Client-credentials grant (service account)
TOKEN=$(curl -s -X POST \
  "http://localhost:8080/realms/ticketforge/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=ticketforge-api" \
  -d "client_secret=<your-client-secret>" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "$TOKEN"
```

```bash
# Resource-owner password grant (test user — development only)
TOKEN=$(curl -s -X POST \
  "http://localhost:8080/realms/ticketforge/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=ticketforge-api" \
  -d "client_secret=<your-client-secret>" \
  -d "username=alice" \
  -d "password=alice123" \
  -d "scope=openid" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

### 7.5 Call the TicketForge API

```bash
curl -s http://localhost:8000/analyse \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket": {
      "id": "TEST-001",
      "subject": "OAuth2 integration test",
      "description": "Verifying JWT validation works end-to-end."
    }
  }' | python3 -m json.tool
```

A successful response confirms:

* JWT signature validation via JWKS ✅
* Issuer and audience claim checks ✅
* Role mapping from `realm_access.roles` → TicketForge RBAC ✅
* Audit log entry with `oidc:` prefixed identity ✅

### 7.6 Inspect the Token

```bash
# Decode the JWT payload (no verification — for debugging only)
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool
```

Expected claims:

```json
{
  "iss": "http://localhost:8080/realms/ticketforge",
  "sub": "a1b2c3d4-...",
  "aud": "ticketforge-api",
  "realm_access": {
    "roles": ["tf-admin", "default-roles-ticketforge"]
  },
  "scope": "openid profile email",
  "preferred_username": "alice"
}
```

---

## 8. Migration Path — API Key to OAuth2/OIDC

Migrating from API-key authentication to OAuth2/OIDC can be done gradually
using the built-in **dual-auth mode**.  The recommended approach is a
three-phase rollout.

### Phase 1 — Dual-Auth (Parallel Running)

Enable OAuth2 alongside API keys.  Both mechanisms are accepted
simultaneously.

```bash
# Enable OAuth2 without removing API keys
OAUTH2_ENABLED=true
OAUTH2_ISSUER_URL=https://login.microsoftonline.com/<tenant>/v2.0
OAUTH2_AUDIENCE=api://ticketforge
API_KEYS=sk-existing-key-1,sk-existing-key-2      # keep existing keys
API_KEY_ROLES={"sk-existing-key-1": "admin"}       # keep existing mappings
```

**Actions:**

1. Configure and test OAuth2 with a small group of users.
2. Update client applications to send `Authorization: Bearer` tokens.
3. Monitor the audit log: entries with `oidc:` prefix confirm OAuth2
   usage; entries with hex hashes indicate API-key usage.

```bash
# Count auth method usage over the last 7 days
sqlite3 ticketforge.db "
  SELECT
    CASE WHEN api_key_hash LIKE 'oidc:%' THEN 'oauth2' ELSE 'api_key' END AS method,
    COUNT(*) AS requests
  FROM audit_log
  WHERE timestamp > datetime('now', '-7 days')
  GROUP BY method;
"
```

### Phase 2 — OAuth2 Primary, API Keys for Legacy

Once all interactive users have migrated, restrict API keys to
machine-to-machine integrations only.

```bash
# Rotate and reduce API keys to CI/CD pipelines only
API_KEYS=sk-cicd-pipeline-key
API_KEY_ROLES={"sk-cicd-pipeline-key": "analyst"}
```

**Actions:**

1. Revoke API keys for human users.
2. Issue OAuth2 client-credentials grants to remaining service accounts
   (preferred) or keep a minimal set of API keys for pipelines that
   cannot use OAuth2.
3. Update monitoring dashboards and alerting to track auth method ratios.

### Phase 3 — OAuth2 Only

Disable API-key authentication entirely.

```bash
OAUTH2_ENABLED=true
API_KEYS=                    # empty — disables API-key auth
```

**Actions:**

1. Remove all API keys from the configuration.
2. Update the reverse-proxy / API-gateway to reject requests without a
   Bearer token (defence in depth).
3. Archive the legacy API-key documentation.

### Migration Checklist

| Step | Owner | Done |
|---|---|---|
| Register TicketForge in IdP | Identity team | ⬜ |
| Configure RBAC role claims in IdP | Identity team | ⬜ |
| Set `OAUTH2_ENABLED=true` with dual-auth | Platform team | ⬜ |
| Test with a pilot group (≤10 users) | Platform team | ⬜ |
| Migrate all interactive users to SSO | All teams | ⬜ |
| Convert service accounts to client credentials | DevOps team | ⬜ |
| Disable API-key auth | Platform team | ⬜ |
| Update runbooks and incident-response docs | SRE team | ⬜ |

---

## 9. Troubleshooting

### Common Errors

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `401 — Token validation failed: Signature verification failed` | JWKS cache stale or wrong `OAUTH2_ALGORITHMS` | Force JWKS refresh by restarting TicketForge; verify the algorithm matches the IdP. |
| `401 — Token validation failed: Token is expired` | Clock skew between TicketForge host and IdP | Synchronise clocks with NTP; most JWT libraries allow a small leeway (default 30 s). |
| `401 — Token validation failed: Invalid audience` | `OAUTH2_AUDIENCE` does not match the `aud` claim | Inspect the token with `jwt.io` or the decode command in §7.6 and correct the variable. |
| `401 — Token validation failed: Invalid issuer` | `OAUTH2_ISSUER_URL` does not match the `iss` claim | Check for trailing slashes — `https://example.com/` ≠ `https://example.com`. |
| `403 — Requires role 'analyst' or higher` | Role claim not present or not mapped | Check `OAUTH2_ROLE_CLAIM` path and verify the token contains the expected groups. |
| `401 — Missing Bearer token` | Client sending `X-Api-Key` but `OAUTH2_ENABLED=true` and no fallback | Ensure dual-auth mode is active (API keys still configured). |
| JWKS fetch fails (connection refused) | IdP unreachable from TicketForge host | Check network/firewall rules; use `OAUTH2_JWKS_URL` to point to an accessible endpoint. |

### Diagnostic Checklist

1. **Decode the token** — Use the command in §7.6 or [jwt.io](https://jwt.io)
   to verify the `iss`, `aud`, `exp`, and role claims.
2. **Check OIDC discovery** — `curl <OAUTH2_ISSUER_URL>/.well-known/openid-configuration`
   should return a JSON document with a `jwks_uri` field.
3. **Verify JWKS** — `curl <jwks_uri>` should return a JSON object with at
   least one RSA key in the `keys` array.
4. **Check TicketForge logs** — Structured JSON logs include the validation
   error detail.  Filter with:
   ```bash
   docker logs ticketforge 2>&1 | python3 -m json.tool | grep -i "token\|jwt\|oauth"
   ```
5. **Test with `curl`** — Isolate the issue by making a direct API call as
   shown in §7.5.

---

*Last updated: 2025 · TicketForge OAuth2/OIDC Integration Guide · Phase A Security*
