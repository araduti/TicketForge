"""Operational endpoints: health, readiness, API-key rotation, status views."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
import httpx
import structlog

import deps
from config import settings
from deps import require_admin, require_viewer, _hash_api_key
from models import (
    HealthResponse,
    MultiAgentStatusResponse,
    PluginInfo,
    PluginListResponse,
    VectorStoreStatusResponse,
)

log = structlog.get_logger(__name__)
router = APIRouter()


# ── Health / readiness ───────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse, tags=["ops"])
async def health_check() -> HealthResponse:
    """Liveness probe — returns ok if the application is running."""
    # Check Ollama reachability
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:  # noqa: BLE001
        pass

    db_ok = deps.db is not None
    return HealthResponse(status="ok", ollama_reachable=ollama_ok, db_ok=db_ok)


@router.get("/ready", response_model=HealthResponse, tags=["ops"])
async def readiness_check() -> HealthResponse:
    """Readiness probe — returns ok only when all critical dependencies are available."""
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:  # noqa: BLE001
        pass

    db_ok = deps.db is not None
    processor_ok = deps.processor is not None

    all_ok = db_ok and processor_ok
    resp = HealthResponse(status="ok" if all_ok else "degraded", ollama_reachable=ollama_ok, db_ok=db_ok)
    if not all_ok:
        resp.status = "degraded"
    return resp


# ── API key rotation (A2) ───────────────────────────────────────────────────


@router.post("/api-keys/rotate", tags=["security"])
async def rotate_api_key(
    request: Request,
    api_key: str = Depends(require_admin),
) -> JSONResponse:
    """
    Rotate an API key: generates a new key and invalidates the caller's current key.
    Only admins can rotate keys. Returns the new key (shown only once).
    """
    new_key = secrets.token_urlsafe(32)

    # Replace the caller's key in the settings
    current_keys = list(settings.api_keys)
    if api_key in current_keys:
        idx = current_keys.index(api_key)
        current_keys[idx] = new_key
    else:
        current_keys.append(new_key)

    # Migrate role from old key to new key
    old_role = settings.api_key_roles.get(api_key, "admin")
    new_roles = dict(settings.api_key_roles)
    new_roles.pop(api_key, None)
    new_roles[new_key] = old_role

    settings.api_keys = current_keys
    settings.api_key_roles = new_roles

    log.info("api_key.rotated", old_key_hash=_hash_api_key(api_key), new_key_hash=_hash_api_key(new_key))

    return JSONResponse(
        status_code=200,
        content={
            "message": "API key rotated successfully",
            "new_api_key": new_key,
            "old_key_hash": _hash_api_key(api_key),
            "new_key_hash": _hash_api_key(new_key),
            "note": "Store the new key securely. It will not be shown again.",
        },
    )


# ── Plugin listing ───────────────────────────────────────────────────────────


@router.get(
    "/plugins",
    response_model=PluginListResponse,
    tags=["plugins"],
)
async def list_plugins(
    api_key: str = Depends(require_admin),
) -> PluginListResponse:
    """
    List all registered plugins and their status.
    Admin only.
    """
    from plugin_system import plugin_registry  # noqa: PLC0415

    plugins_data = plugin_registry.list_plugins()
    plugins = [
        PluginInfo(
            name=p["name"],
            version=p["version"],
            description=p["description"],
            hook=p["hook"],
            enabled=p["enabled"],
        )
        for p in plugins_data
    ]
    return PluginListResponse(plugins=plugins, total=len(plugins))


# ── Multi-agent status ───────────────────────────────────────────────────────


@router.get("/multi-agent/status", response_model=MultiAgentStatusResponse, tags=["multi-agent"])
async def multi_agent_status(
    api_key: str = Depends(require_viewer),
) -> MultiAgentStatusResponse:
    """
    Return the current multi-agent pipeline configuration.
    Shows whether multi-agent is enabled and which agents are in the pipeline.
    """
    if settings.multi_agent_enabled:
        return MultiAgentStatusResponse(
            enabled=True,
            agents=["analyser", "classifier", "validator"],
            description="Analyser → Classifier → Validator pipeline",
        )
    return MultiAgentStatusResponse(
        enabled=False,
        agents=[],
        description="Single LLM call (multi-agent disabled)",
    )


# ── Vector store status ──────────────────────────────────────────────────────


@router.get("/vector-store/status", response_model=VectorStoreStatusResponse, tags=["vector-store"])
async def vector_store_status(
    api_key: str = Depends(require_viewer),
) -> VectorStoreStatusResponse:
    """
    Return the current vector store backend and number of stored vectors.
    """
    total = 0
    backend = "in_memory"
    if deps.vector_store is not None:
        total = await deps.vector_store.count()
        backend = deps.vector_store.backend_name
    return VectorStoreStatusResponse(
        backend=backend,
        total_vectors=total,
    )
