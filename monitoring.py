"""
TicketForge — Model monitoring and drift detection

Tracks prediction distributions over time and detects drift
in category, priority, and sentiment predictions.
"""
from __future__ import annotations

import math
from collections import Counter

import structlog

log = structlog.get_logger(__name__)


def compute_distribution(values: list[str]) -> dict[str, float]:
    """Compute percentage distribution from a list of values."""
    if not values:
        return {}
    counts = Counter(values)
    total = len(values)
    return {k: round(v / total, 4) for k, v in counts.most_common()}


def compute_drift_score(
    baseline: dict[str, float],
    current: dict[str, float],
) -> float:
    """
    Compute Jensen-Shannon divergence between two distributions.

    Returns a score between 0.0 (identical) and 1.0 (completely different).
    Uses a simplified approach: average of absolute differences across all keys.
    """
    if not baseline and not current:
        return 0.0
    if not baseline or not current:
        return 1.0

    all_keys = set(baseline.keys()) | set(current.keys())
    total_diff = 0.0
    for key in all_keys:
        b = baseline.get(key, 0.0)
        c = current.get(key, 0.0)
        total_diff += abs(b - c)

    # Normalize: max possible total_diff is 2.0 (completely disjoint distributions)
    return min(1.0, round(total_diff / 2.0, 4))


async def compute_drift_metrics(
    db,
    baseline_days: int = 30,
    window_days: int = 7,
    drift_threshold: float = 0.3,
) -> dict:
    """
    Compute drift metrics by comparing recent predictions to a baseline period.

    Returns a dict with metrics, total_tickets, and overall_health.
    """
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    now = datetime.now(tz=timezone.utc)
    baseline_start = (now - timedelta(days=baseline_days)).isoformat()
    window_start = (now - timedelta(days=window_days)).isoformat()

    # Fetch baseline period data
    async with db.execute(
        "SELECT category, priority, sentiment FROM processed_tickets "
        "WHERE processed_at >= ? AND processed_at < ?",
        (baseline_start, window_start),
    ) as cursor:
        baseline_rows = await cursor.fetchall()

    # Fetch recent window data
    async with db.execute(
        "SELECT category, priority, sentiment FROM processed_tickets "
        "WHERE processed_at >= ?",
        (window_start,),
    ) as cursor:
        window_rows = await cursor.fetchall()

    # Total tickets analysed
    async with db.execute("SELECT COUNT(*) FROM processed_tickets") as cursor:
        total = (await cursor.fetchone())[0]

    # Compute distributions for each field
    fields = [
        ("category", 0),
        ("priority", 1),
        ("sentiment", 2),
    ]

    metrics = []
    drift_count = 0

    for field_name, idx in fields:
        baseline_values = [r[idx] or "unknown" for r in baseline_rows]
        window_values = [r[idx] or "unknown" for r in window_rows]

        baseline_dist = compute_distribution(baseline_values)
        current_dist = compute_distribution(window_values)
        drift_score = compute_drift_score(baseline_dist, current_dist)
        is_drifting = drift_score >= drift_threshold

        if is_drifting:
            drift_count += 1

        metrics.append({
            "field": field_name,
            "current_distribution": current_dist,
            "baseline_distribution": baseline_dist,
            "drift_score": drift_score,
            "is_drifting": is_drifting,
        })

    # Determine overall health
    if drift_count == 0:
        overall_health = "healthy"
    elif drift_count <= 1:
        overall_health = "warning"
    else:
        overall_health = "degraded"

    return {
        "metrics": metrics,
        "total_tickets_analysed": total,
        "baseline_period_days": baseline_days,
        "monitoring_period_days": window_days,
        "overall_health": overall_health,
    }
