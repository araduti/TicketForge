"""
TicketForge — Test suite for Phase 5 features
Tests for Multi-Agent Architecture, Persistent Vector Store,
and PostgreSQL asyncpg driver integration.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

import numpy as np
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
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ticketforge_phase5.db"
os.environ["CSAT_ENABLED"] = "true"
os.environ["WEBSOCKET_NOTIFICATIONS_ENABLED"] = "true"
os.environ["I18N_ENABLED"] = "true"
os.environ["CHATBOT_ENABLED"] = "true"
os.environ["PORTAL_ENABLED"] = "true"
os.environ["MONITORING_ENABLED"] = "true"
os.environ["MULTI_AGENT_ENABLED"] = "false"
os.environ["VECTOR_STORE_BACKEND"] = "in_memory"

from main import app, lifespan  # noqa: E402
from models import (  # noqa: E402
    MultiAgentStatusResponse,
    VectorStoreStatusResponse,
)


@pytest_asyncio.fixture
async def client():
    """Create an async test client with lifespan context."""
    from config import settings as _s  # noqa: PLC0415
    _db_path = _s.database_url.replace("sqlite+aiosqlite:///", "")
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Clean up test database
    try:
        os.remove(_db_path)
    except FileNotFoundError:
        pass


# ── Multi-Agent Status Tests ─────────────────────────────────────────────────

class TestMultiAgentStatus:
    """Test the GET /multi-agent/status endpoint."""

    @pytest.mark.asyncio
    async def test_multi_agent_status_disabled(self, client: AsyncClient) -> None:
        """When MULTI_AGENT_ENABLED=false, status reports disabled."""
        resp = await client.get(
            "/multi-agent/status",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["enabled"] is False
        assert data["agents"] == []
        assert "single" in data["description"].lower() or "disabled" in data["description"].lower()

    @pytest.mark.asyncio
    async def test_multi_agent_status_requires_auth(self, client: AsyncClient) -> None:
        """Endpoint requires authentication."""
        resp = await client.get("/multi-agent/status")
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_multi_agent_status_invalid_key(self, client: AsyncClient) -> None:
        """Invalid API key returns 401."""
        resp = await client.get(
            "/multi-agent/status",
            headers={"X-Api-Key": "invalid-key"},
        )
        assert resp.status_code == 401


# ── Vector Store Status Tests ────────────────────────────────────────────────

class TestVectorStoreStatus:
    """Test the GET /vector-store/status endpoint."""

    @pytest.mark.asyncio
    async def test_vector_store_status_in_memory(self, client: AsyncClient) -> None:
        """When VECTOR_STORE_BACKEND=in_memory, status reports in_memory."""
        resp = await client.get(
            "/vector-store/status",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["backend"] == "in_memory"
        assert data["total_vectors"] == 0

    @pytest.mark.asyncio
    async def test_vector_store_status_requires_auth(self, client: AsyncClient) -> None:
        """Endpoint requires authentication."""
        resp = await client.get("/vector-store/status")
        assert resp.status_code in (401, 422)

    @pytest.mark.asyncio
    async def test_vector_store_status_invalid_key(self, client: AsyncClient) -> None:
        """Invalid API key returns 401."""
        resp = await client.get(
            "/vector-store/status",
            headers={"X-Api-Key": "invalid-key"},
        )
        assert resp.status_code == 401


# ── Multi-Agent Orchestrator Unit Tests ──────────────────────────────────────

class TestMultiAgentOrchestrator:
    """Unit tests for the MultiAgentOrchestrator."""

    def test_merge_prefers_validator_fields(self) -> None:
        """Validator's final_ fields should override classifier fields."""
        from multi_agent import MultiAgentOrchestrator  # noqa: PLC0415

        analysis = {
            "summary": "Test summary",
            "sentiment": "negative",
            "sentiment_confidence": 0.9,
            "sentiment_rationale": "User is frustrated",
            "detected_language": "en",
            "root_cause_hypothesis": "Hardware failure",
            "root_cause_confidence": 0.8,
            "kb_articles": [{"title": "KB-001", "url": "", "relevance_score": 0.9}],
        }
        classification = {
            "category": "Hardware",
            "sub_category": "Laptop",
            "category_confidence": 0.85,
            "priority": "high",
            "priority_score": 80,
            "priority_rationale": "Hardware failure",
            "recommended_queue": "L2 Hardware",
            "recommended_team": "Desktop Support",
            "routing_rationale": "Hardware issue",
        }
        validation = {
            "validated": True,
            "corrections": [],
            "final_category": "Hardware",
            "final_sub_category": "Desktop",
            "final_category_confidence": 0.9,
            "final_priority": "critical",
            "final_priority_score": 95,
            "final_priority_rationale": "Critical hardware failure",
            "final_recommended_queue": "L3 Hardware",
            "final_recommended_team": "Hardware Engineering",
            "final_routing_rationale": "Escalated",
        }

        merged = MultiAgentOrchestrator._merge(analysis, classification, validation)

        # Validator's values should win
        assert merged["category"] == "Hardware"
        assert merged["sub_category"] == "Desktop"
        assert merged["category_confidence"] == 0.9
        assert merged["priority"] == "critical"
        assert merged["priority_score"] == 95
        assert merged["recommended_queue"] == "L3 Hardware"
        assert merged["recommended_team"] == "Hardware Engineering"

        # Analysis values
        assert merged["summary"] == "Test summary"
        assert merged["sentiment"] == "negative"
        assert merged["detected_language"] == "en"

        # Multi-agent metadata
        assert merged["_multi_agent"] is True
        assert merged["_agent_count"] == 3
        assert merged["_validated"] is True

    def test_merge_falls_back_to_classifier(self) -> None:
        """When validator doesn't have final_ fields, classifier values are used."""
        from multi_agent import MultiAgentOrchestrator  # noqa: PLC0415

        analysis = {"summary": "Test", "sentiment": "neutral"}
        classification = {
            "category": "Software",
            "sub_category": "Email",
            "category_confidence": 0.7,
            "priority": "medium",
            "priority_score": 50,
        }
        validation = {"validated": True, "corrections": []}

        merged = MultiAgentOrchestrator._merge(analysis, classification, validation)
        assert merged["category"] == "Software"
        assert merged["sub_category"] == "Email"
        assert merged["priority"] == "medium"
        assert merged["priority_score"] == 50

    def test_parse_agent_json_strips_markdown(self) -> None:
        """JSON extraction should handle markdown code fences."""
        from multi_agent import _parse_agent_json  # noqa: PLC0415

        raw = '```json\n{"category": "Hardware", "priority": "high"}\n```'
        result = _parse_agent_json(raw)
        assert result["category"] == "Hardware"
        assert result["priority"] == "high"

    def test_parse_agent_json_plain(self) -> None:
        """JSON extraction works on plain JSON."""
        from multi_agent import _parse_agent_json  # noqa: PLC0415

        raw = '{"summary": "Test ticket"}'
        result = _parse_agent_json(raw)
        assert result["summary"] == "Test ticket"

    def test_parse_agent_json_no_json_raises(self) -> None:
        """Raises JSONDecodeError when no JSON is found."""
        from multi_agent import _parse_agent_json  # noqa: PLC0415

        with pytest.raises(json.JSONDecodeError):
            _parse_agent_json("No JSON here at all")


# ── Vector Store Unit Tests ──────────────────────────────────────────────────

class TestInMemoryVectorStore:
    """Unit tests for InMemoryVectorStore."""

    @pytest.mark.asyncio
    async def test_upsert_and_count(self) -> None:
        """Upsert adds vectors, count reflects them."""
        from vector_store import InMemoryVectorStore  # noqa: PLC0415

        store = InMemoryVectorStore()
        assert await store.count() == 0

        await store.upsert("vec-1", [1.0, 0.0, 0.0], {"label": "test"})
        assert await store.count() == 1

        await store.upsert("vec-2", [0.0, 1.0, 0.0])
        assert await store.count() == 2

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self) -> None:
        """Upserting the same key updates the vector."""
        from vector_store import InMemoryVectorStore  # noqa: PLC0415

        store = InMemoryVectorStore()
        await store.upsert("vec-1", [1.0, 0.0, 0.0], {"version": 1})
        await store.upsert("vec-1", [0.0, 1.0, 0.0], {"version": 2})
        assert await store.count() == 1

        results = await store.search([0.0, 1.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0]["metadata"]["version"] == 2

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        """Delete removes a vector by key."""
        from vector_store import InMemoryVectorStore  # noqa: PLC0415

        store = InMemoryVectorStore()
        await store.upsert("vec-1", [1.0, 0.0, 0.0])
        await store.upsert("vec-2", [0.0, 1.0, 0.0])
        assert await store.count() == 2

        await store.delete("vec-1")
        assert await store.count() == 1

    @pytest.mark.asyncio
    async def test_delete_missing_key(self) -> None:
        """Delete on non-existent key does not raise."""
        from vector_store import InMemoryVectorStore  # noqa: PLC0415

        store = InMemoryVectorStore()
        await store.delete("nonexistent")  # Should not raise

    @pytest.mark.asyncio
    async def test_search_empty_store(self) -> None:
        """Searching an empty store returns empty list."""
        from vector_store import InMemoryVectorStore  # noqa: PLC0415

        store = InMemoryVectorStore()
        results = await store.search([1.0, 0.0, 0.0])
        assert results == []

    @pytest.mark.asyncio
    async def test_search_returns_sorted(self) -> None:
        """Search returns results sorted by descending similarity."""
        from vector_store import InMemoryVectorStore  # noqa: PLC0415

        store = InMemoryVectorStore()
        await store.upsert("exact", [1.0, 0.0, 0.0], {"label": "exact"})
        await store.upsert("partial", [0.7, 0.7, 0.0], {"label": "partial"})
        await store.upsert("orthogonal", [0.0, 1.0, 0.0], {"label": "orthogonal"})

        results = await store.search([1.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3
        # Exact match should be first
        assert results[0]["key"] == "exact"
        assert results[0]["score"] == pytest.approx(1.0, abs=0.01)
        # Scores should be descending
        assert results[0]["score"] >= results[1]["score"] >= results[2]["score"]

    @pytest.mark.asyncio
    async def test_search_respects_top_k(self) -> None:
        """Search limits results to top_k."""
        from vector_store import InMemoryVectorStore  # noqa: PLC0415

        store = InMemoryVectorStore()
        for i in range(10):
            vec = [0.0] * 3
            vec[i % 3] = 1.0
            await store.upsert(f"vec-{i}", vec)

        results = await store.search([1.0, 0.0, 0.0], top_k=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_search_respects_min_score(self) -> None:
        """Search filters out results below min_score."""
        from vector_store import InMemoryVectorStore  # noqa: PLC0415

        store = InMemoryVectorStore()
        await store.upsert("similar", [0.9, 0.1, 0.0])
        await store.upsert("different", [0.0, 0.0, 1.0])

        results = await store.search([1.0, 0.0, 0.0], min_score=0.5)
        assert len(results) == 1
        assert results[0]["key"] == "similar"

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        """Clear removes all vectors."""
        from vector_store import InMemoryVectorStore  # noqa: PLC0415

        store = InMemoryVectorStore()
        await store.upsert("vec-1", [1.0, 0.0, 0.0])
        await store.upsert("vec-2", [0.0, 1.0, 0.0])
        assert await store.count() == 2

        await store.clear()
        assert await store.count() == 0

    @pytest.mark.asyncio
    async def test_backend_name(self) -> None:
        """Backend name is 'in_memory'."""
        from vector_store import InMemoryVectorStore  # noqa: PLC0415

        store = InMemoryVectorStore()
        assert store.backend_name == "in_memory"

    @pytest.mark.asyncio
    async def test_search_zero_vector(self) -> None:
        """Searching with a zero vector returns empty results."""
        from vector_store import InMemoryVectorStore  # noqa: PLC0415

        store = InMemoryVectorStore()
        await store.upsert("vec-1", [1.0, 0.0, 0.0])
        results = await store.search([0.0, 0.0, 0.0])
        assert results == []


class TestPersistentVectorStore:
    """Unit tests for PersistentVectorStore."""

    @pytest.mark.asyncio
    async def test_persistent_store_lifecycle(self) -> None:
        """PersistentVectorStore supports full CRUD lifecycle."""
        import aiosqlite  # noqa: PLC0415
        from vector_store import PersistentVectorStore  # noqa: PLC0415

        db_path = "./test_vector_store_lifecycle.db"
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass

        db = await aiosqlite.connect(db_path)
        try:
            store = PersistentVectorStore(db)
            await store.initialise()
            assert store.backend_name == "persistent"

            # Empty initially
            assert await store.count() == 0

            # Upsert
            await store.upsert("vec-1", [1.0, 0.0, 0.0], {"label": "first"})
            assert await store.count() == 1

            await store.upsert("vec-2", [0.0, 1.0, 0.0], {"label": "second"})
            assert await store.count() == 2

            # Search
            results = await store.search([1.0, 0.0, 0.0], top_k=1)
            assert len(results) == 1
            assert results[0]["key"] == "vec-1"

            # Delete
            await store.delete("vec-1")
            assert await store.count() == 1

            # Clear
            await store.clear()
            assert await store.count() == 0
        finally:
            await db.close()
            try:
                os.remove(db_path)
            except FileNotFoundError:
                pass

    @pytest.mark.asyncio
    async def test_persistent_store_survives_reconnect(self) -> None:
        """Data persists across database reconnections."""
        import aiosqlite  # noqa: PLC0415
        from vector_store import PersistentVectorStore  # noqa: PLC0415

        db_path = "./test_vector_store_persist.db"
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass

        try:
            # First connection: insert data
            db1 = await aiosqlite.connect(db_path)
            store1 = PersistentVectorStore(db1)
            await store1.initialise()
            await store1.upsert("persistent-vec", [1.0, 0.0, 0.0], {"label": "persisted"})
            assert await store1.count() == 1
            await db1.close()

            # Second connection: data should still be there
            db2 = await aiosqlite.connect(db_path)
            store2 = PersistentVectorStore(db2)
            await store2.initialise()
            assert await store2.count() == 1

            results = await store2.search([1.0, 0.0, 0.0], top_k=1)
            assert len(results) == 1
            assert results[0]["key"] == "persistent-vec"
            assert results[0]["metadata"]["label"] == "persisted"
            await db2.close()
        finally:
            try:
                os.remove(db_path)
            except FileNotFoundError:
                pass


class TestVectorStoreFactory:
    """Tests for the create_vector_store factory function."""

    @pytest.mark.asyncio
    async def test_create_in_memory(self) -> None:
        """Factory creates InMemoryVectorStore for 'in_memory' backend."""
        from vector_store import create_vector_store  # noqa: PLC0415

        store = await create_vector_store("in_memory")
        assert store.backend_name == "in_memory"

    @pytest.mark.asyncio
    async def test_create_persistent_with_db(self) -> None:
        """Factory creates PersistentVectorStore when db is provided."""
        import aiosqlite  # noqa: PLC0415
        from vector_store import create_vector_store  # noqa: PLC0415

        db_path = "./test_vector_store_factory.db"
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass

        db = await aiosqlite.connect(db_path)
        try:
            store = await create_vector_store("persistent", db=db)
            assert store.backend_name == "persistent"
        finally:
            await db.close()
            try:
                os.remove(db_path)
            except FileNotFoundError:
                pass

    @pytest.mark.asyncio
    async def test_create_persistent_without_db_falls_back(self) -> None:
        """Factory falls back to in-memory when persistent requested but no db."""
        from vector_store import create_vector_store  # noqa: PLC0415

        store = await create_vector_store("persistent", db=None)
        assert store.backend_name == "in_memory"


# ── Multi-Agent Configuration Tests ──────────────────────────────────────────

class TestMultiAgentConfig:
    """Test multi-agent configuration settings."""

    def test_multi_agent_enabled_default(self) -> None:
        """Multi-agent is disabled by default."""
        from config import settings  # noqa: PLC0415
        assert settings.multi_agent_enabled is False

    def test_vector_store_backend_default(self) -> None:
        """Vector store backend defaults to in_memory."""
        from config import settings  # noqa: PLC0415
        assert settings.vector_store_backend == "in_memory"


# ── Multi-Agent Prompt Tests ─────────────────────────────────────────────────

class TestMultiAgentPrompts:
    """Test the multi-agent prompt templates."""

    def test_analyser_prompt_has_ticket_fields(self) -> None:
        """Analyser user prompt template includes ticket placeholders."""
        from multi_agent import ANALYSER_USER  # noqa: PLC0415
        assert "{ticket_id}" in ANALYSER_USER
        assert "{title}" in ANALYSER_USER
        assert "{description}" in ANALYSER_USER

    def test_classifier_prompt_has_summary_field(self) -> None:
        """Classifier user prompt template includes summary placeholder."""
        from multi_agent import CLASSIFIER_USER  # noqa: PLC0415
        assert "{summary}" in CLASSIFIER_USER
        assert "{sentiment}" in CLASSIFIER_USER

    def test_validator_prompt_has_json_fields(self) -> None:
        """Validator user prompt template includes analysis/classification JSON."""
        from multi_agent import VALIDATOR_USER  # noqa: PLC0415
        assert "{analysis_json}" in VALIDATOR_USER
        assert "{classification_json}" in VALIDATOR_USER

    def test_all_system_prompts_mention_json(self) -> None:
        """All agent system prompts require JSON output."""
        from multi_agent import ANALYSER_SYSTEM, CLASSIFIER_SYSTEM, VALIDATOR_SYSTEM  # noqa: PLC0415
        assert "JSON" in ANALYSER_SYSTEM
        assert "JSON" in CLASSIFIER_SYSTEM
        assert "JSON" in VALIDATOR_SYSTEM


# ── PostgreSQL asyncpg Integration Tests ─────────────────────────────────────

class TestAsyncpgAvailable:
    """Test that asyncpg is importable and available."""

    def test_asyncpg_import(self) -> None:
        """asyncpg package is installed and importable."""
        import asyncpg  # noqa: PLC0415, F401
        assert hasattr(asyncpg, "connect")

    def test_database_url_accepts_postgresql(self) -> None:
        """Config accepts PostgreSQL connection string format."""
        from config import Settings  # noqa: PLC0415

        s = Settings(
            database_url="postgresql://user:pass@localhost:5432/ticketforge",
            api_keys=["test-key"],
        )
        assert s.database_url.startswith("postgresql://")


# ── Ticket Processor Multi-Agent Integration ─────────────────────────────────

class TestTicketProcessorMultiAgent:
    """Test that TicketProcessor correctly wires up multi-agent mode."""

    def test_processor_no_multi_agent_by_default(self) -> None:
        """When multi_agent_enabled=False, processor has no orchestrator."""
        from config import Settings  # noqa: PLC0415
        from automation_detector import AutomationDetector  # noqa: PLC0415
        from ticket_processor import TicketProcessor  # noqa: PLC0415

        s = Settings(
            multi_agent_enabled=False,
            api_keys=["test"],
        )
        det = AutomationDetector(s)
        proc = TicketProcessor(s, det)
        assert proc._multi_agent is None

    def test_processor_has_multi_agent_when_enabled(self) -> None:
        """When multi_agent_enabled=True, processor creates orchestrator."""
        from config import Settings  # noqa: PLC0415
        from automation_detector import AutomationDetector  # noqa: PLC0415
        from ticket_processor import TicketProcessor  # noqa: PLC0415

        s = Settings(
            multi_agent_enabled=True,
            api_keys=["test"],
        )
        det = AutomationDetector(s)
        proc = TicketProcessor(s, det)
        assert proc._multi_agent is not None


# ── Existing Feature Regression Tests ────────────────────────────────────────

class TestPhase5Regression:
    """Ensure Phase 5 changes don't break existing endpoints."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: AsyncClient) -> None:
        """Health endpoint still works."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_i18n_languages_still_works(self, client: AsyncClient) -> None:
        """i18n languages endpoint is unaffected."""
        resp = await client.get(
            "/i18n/languages",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "supported_languages" in data

    @pytest.mark.asyncio
    async def test_analytics_endpoint_still_works(self, client: AsyncClient) -> None:
        """Analytics endpoint is unaffected."""
        resp = await client.get(
            "/analytics",
            headers={"X-Api-Key": "analyst-key"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_portal_endpoint_still_works(self, client: AsyncClient) -> None:
        """Portal endpoint is unaffected."""
        resp = await client.get(
            "/portal",
            headers={"X-Api-Key": "viewer-key"},
        )
        assert resp.status_code == 200
