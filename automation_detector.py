"""
TicketForge — Automation opportunity detector
Uses local sentence-transformer embeddings + DBSCAN clustering to find repeating
ticket patterns and score their automation potential.
"""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import numpy as np
import structlog
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import normalize

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from config import Settings
from models import AutomationOpportunity, AutomationSuggestionType

log = structlog.get_logger(__name__)

# Minimum cluster size to even consider automation
_MIN_CLUSTER_SIZE = 3


class AutomationDetector:
    """
    Detects repeating ticket patterns using:
    1. sentence-transformers for local embeddings
    2. DBSCAN for density-based clustering
    3. Keyword extraction from cluster members
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: SentenceTransformer | None = None
        # Rolling in-memory store: list of (text, created_at)
        self._history: list[tuple[str, datetime]] = []

    def _get_model(self) -> "SentenceTransformer":
        """Lazy-load the embedding model (downloads on first call)."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            log.info("automation_detector.loading_model", model=self._settings.embedding_model)
            self._model = SentenceTransformer(self._settings.embedding_model)
        return self._model

    def get_embedding_model(self) -> "SentenceTransformer":
        """Public interface to retrieve the embedding model (lazy-loaded)."""
        return self._get_model()

    def add_to_history(self, text: str, created_at: datetime | None = None) -> None:
        """Append a ticket text to the rolling history window."""
        ts = created_at or datetime.now(tz=timezone.utc)
        self._history.append((text, ts))
        # Prune entries older than the configured lookback window
        cutoff = datetime.now(tz=timezone.utc) - timedelta(
            hours=self._settings.automation_lookback_hours
        )
        self._history = [(t, dt) for t, dt in self._history if dt >= cutoff]

    async def detect(self, ticket_text: str) -> AutomationOpportunity:
        """
        Compute an automation opportunity score for *ticket_text* by checking
        how many similar tickets exist in the rolling history window.
        """
        if len(self._history) < _MIN_CLUSTER_SIZE:
            return AutomationOpportunity(score=0, suggestion_type=AutomationSuggestionType.none)

        # Run blocking CPU work in a thread pool to keep FastAPI async
        return await asyncio.get_event_loop().run_in_executor(
            None, self._sync_detect, ticket_text
        )

    def _sync_detect(self, ticket_text: str) -> AutomationOpportunity:
        model = self._get_model()
        texts = [t for t, _ in self._history] + [ticket_text]
        embeddings: np.ndarray = model.encode(texts, show_progress_bar=False, batch_size=32)
        embeddings = normalize(embeddings)

        db = DBSCAN(
            eps=self._settings.dbscan_eps,
            min_samples=self._settings.dbscan_min_samples,
            metric="cosine",
        ).fit(embeddings)

        labels: np.ndarray = db.labels_
        target_label = int(labels[-1])  # label of the current ticket

        if target_label == -1:
            # Noise point — no cluster found
            return AutomationOpportunity(score=0, suggestion_type=AutomationSuggestionType.none)

        # Find all cluster members (excluding the target ticket itself)
        cluster_mask = labels[:-1] == target_label
        cluster_size = int(cluster_mask.sum())

        if cluster_size < _MIN_CLUSTER_SIZE:
            return AutomationOpportunity(score=0, suggestion_type=AutomationSuggestionType.none)

        cluster_texts = [self._history[i][0] for i, flag in enumerate(cluster_mask) if flag]
        cluster_dates = [self._history[i][1] for i, flag in enumerate(cluster_mask) if flag]

        # Frequency per week
        if len(cluster_dates) >= 2:
            span_days = max(
                1,
                (max(cluster_dates) - min(cluster_dates)).days,
            )
            freq_per_week = cluster_size / (span_days / 7.0)
        else:
            freq_per_week = float(cluster_size)

        keywords = _extract_keywords(cluster_texts)
        score = _compute_score(cluster_size, freq_per_week)
        suggestion_type, suggestion = _build_suggestion(keywords, cluster_size, freq_per_week)

        log.info(
            "automation_detector.cluster_found",
            cluster_size=cluster_size,
            freq_per_week=round(freq_per_week, 1),
            score=score,
            keywords=keywords[:5],
        )

        return AutomationOpportunity(
            score=score,
            suggestion_type=suggestion_type,
            suggestion=suggestion,
            pattern_count=cluster_size,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

_STOPWORDS = frozenset(
    """a an the is are was were be been being have has had do does did
    will would could should may might shall can cannot i we you he she it they
    my our your his her its their this that these those and or but not
    in on at to for of with by from as into during including until against among
    throughout despite towards upon concerning""".split()
)


def _extract_keywords(texts: list[str], top_n: int = 10) -> list[str]:
    """Naive keyword extraction: tokenise, remove stopwords, pick top-N by freq."""
    words: list[str] = []
    for text in texts:
        tokens = re.findall(r"[a-z]{3,}", text.lower())
        words.extend(w for w in tokens if w not in _STOPWORDS)
    counter = Counter(words)
    return [w for w, _ in counter.most_common(top_n)]


def _compute_score(cluster_size: int, freq_per_week: float) -> int:
    """
    Heuristic score 0–100.
    Scale: cluster_size contributes 60 pts, frequency contributes 40 pts.
    """
    size_score = min(60, int(cluster_size / 20 * 60))  # caps at 20 tickets → 60
    freq_score = min(40, int(freq_per_week / 10 * 40))  # caps at 10/week → 40
    return size_score + freq_score


def _build_suggestion(
    keywords: list[str],
    cluster_size: int,
    freq_per_week: float,
) -> tuple[AutomationSuggestionType, str]:
    """Pick an automation suggestion type and one-liner based on keywords."""
    kw_set = set(keywords)

    # Password / access patterns
    if kw_set & {"password", "reset", "unlock", "locked", "expired"}:
        return (
            AutomationSuggestionType.self_service,
            f"Deploy a self-service password-reset portal to handle "
            f"~{cluster_size} similar requests (~{freq_per_week:.0f}/week) without L1 involvement.",
        )

    # VPN / connectivity
    if kw_set & {"vpn", "connection", "network", "wifi", "internet", "connectivity"}:
        return (
            AutomationSuggestionType.kb_article,
            f"Publish a step-by-step VPN troubleshooting KB article to deflect "
            f"~{cluster_size} tickets/cycle ({freq_per_week:.0f}/week).",
        )

    # Software installation / access
    if kw_set & {"install", "software", "application", "access", "permission", "license"}:
        return (
            AutomationSuggestionType.form,
            f"Create a software access request form with auto-approval rules to reduce "
            f"{cluster_size} similar tickets (~{freq_per_week:.0f}/week).",
        )

    # Repetitive how-to queries
    if kw_set & {"how", "guide", "step", "help", "instruction", "enable", "disable"}:
        return (
            AutomationSuggestionType.kb_article,
            f"Write a KB article covering '{', '.join(keywords[:3])}' to self-serve "
            f"{cluster_size} tickets/cycle.",
        )

    # Generic — bot/script
    if freq_per_week >= 5:
        return (
            AutomationSuggestionType.bot,
            f"Build a chatbot trigger for '{', '.join(keywords[:3])}' pattern "
            f"({cluster_size} tickets, {freq_per_week:.0f}/week) to cut resolution time.",
        )

    return (
        AutomationSuggestionType.script,
        f"Write an auto-resolution script for the '{', '.join(keywords[:3])}' pattern "
        f"({cluster_size} tickets) to reduce manual effort.",
    )
