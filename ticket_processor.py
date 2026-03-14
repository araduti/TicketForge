"""
TicketForge — Core ticket processing pipeline
Orchestrates LLM calls (via pluggable providers), parses structured JSON output,
and assembles the final EnrichedTicket result.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import httpx
from automation_detector import AutomationDetector
from config import Settings
from llm_provider import LLMProvider, create_llm_provider
from models import (
    AutomationOpportunity,
    AutomationSuggestionType,
    CategoryResult,
    EnrichedTicket,
    KBArticle,
    Priority,
    PriorityResult,
    RawTicket,
    RootCauseHypothesis,
    RoutingResult,
    Sentiment,
    SentimentResult,
)
from prompts import ANALYSE_USER_PROMPT, SYSTEM_PROMPT

log = structlog.get_logger(__name__)

# Root-cause hypothesis is only included when LLM confidence is above this threshold
_ROOT_CAUSE_CONFIDENCE_THRESHOLD = 0.75


class TicketProcessor:
    """
    Main processing pipeline:
    1. Format prompt → call LLM provider → parse JSON
    2. Optionally run automation detection
    3. Return EnrichedTicket
    """

    def __init__(self, settings: Settings, automation_detector: AutomationDetector) -> None:
        self._settings = settings
        self._detector = automation_detector
        self._llm: LLMProvider = create_llm_provider(settings)

    async def aclose(self) -> None:
        await self._llm.aclose()

    async def process(
        self,
        ticket: RawTicket,
        *,
        include_automation: bool = True,
    ) -> EnrichedTicket:
        start = time.monotonic()

        # Build the combined text used for embeddings / automation
        ticket_text = f"{ticket.title}\n{ticket.description}".strip()

        # Run LLM analysis and optionally automation detection concurrently
        if include_automation:
            # Feed the ticket into history *before* detect so it may join its own cluster
            self._detector.add_to_history(ticket_text, ticket.created_at)
            llm_task = asyncio.create_task(self._analyse_with_llm(ticket))
            auto_task = asyncio.create_task(self._detector.detect(ticket_text))
            llm_data, automation = await asyncio.gather(llm_task, auto_task)
        else:
            llm_data = await self._analyse_with_llm(ticket)
            automation = AutomationOpportunity(
                score=0, suggestion_type=AutomationSuggestionType.none
            )

        elapsed_ms = (time.monotonic() - start) * 1000

        enriched = _build_enriched(ticket, llm_data, automation, elapsed_ms)
        log.info(
            "ticket_processor.processed",
            ticket_id=ticket.id,
            source=ticket.source,
            category=enriched.category.category,
            priority=enriched.priority.priority,
            automation_score=enriched.automation.score,
            ms=round(elapsed_ms, 1),
        )
        return enriched

    # ── LLM interaction ───────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, json.JSONDecodeError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _analyse_with_llm(self, ticket: RawTicket) -> dict[str, Any]:
        max_desc_chars = self._settings.llm_description_max_chars
        prompt = ANALYSE_USER_PROMPT.format(
            ticket_id=ticket.id,
            source=ticket.source.value,
            title=ticket.title,
            description=ticket.description[:max_desc_chars],  # configurable cap (avoids token overflow)
            reporter=ticket.reporter,
            tags=", ".join(ticket.tags),
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        log.debug(
            "ticket_processor.llm_request",
            ticket_id=ticket.id,
            provider=self._llm.provider_name,
            model=self._llm.model_name,
        )
        raw_content = await self._llm.chat(messages, temperature=0.1, max_tokens=1024)
        return _parse_llm_json(raw_content)


# ── JSON extraction ───────────────────────────────────────────────────────────

def _parse_llm_json(raw: str) -> dict[str, Any]:
    """
    Extract JSON from the LLM response.
    The model sometimes wraps JSON in markdown code blocks — strip those first.
    """
    # Strip markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)

    # Find the outermost JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("No JSON object found in LLM response", raw, 0)

    return json.loads(match.group())


# ── Model assembly ────────────────────────────────────────────────────────────

def _build_enriched(
    ticket: RawTicket,
    llm: dict[str, Any],
    automation: AutomationOpportunity,
    elapsed_ms: float,
) -> EnrichedTicket:
    # Category
    category = CategoryResult(
        category=llm.get("category", "Uncategorised"),
        sub_category=llm.get("sub_category", ""),
        confidence=_clamp(float(llm.get("category_confidence", 0.5))),
    )

    # Priority
    priority_str = (llm.get("priority") or "medium").lower()
    try:
        priority_enum = Priority(priority_str)
    except ValueError:
        priority_enum = Priority.medium

    priority = PriorityResult(
        priority=priority_enum,
        score=_clamp_int(int(llm.get("priority_score", 50)), 1, 100),
        rationale=llm.get("priority_rationale", ""),
    )

    # Routing
    routing = RoutingResult(
        recommended_queue=llm.get("recommended_queue", ""),
        recommended_team=llm.get("recommended_team", ""),
        rationale=llm.get("routing_rationale", ""),
    )

    # KB articles (max 3)
    kb_raw: list[dict[str, Any]] = llm.get("kb_articles", [])
    kb_articles = [
        KBArticle(
            title=a.get("title", ""),
            url=a.get("url", ""),
            relevance_score=_clamp(float(a.get("relevance_score", 0.5))),
        )
        for a in kb_raw[:3]
        if a.get("title")
    ]

    # Root cause
    hypothesis_text = llm.get("root_cause_hypothesis", "")
    rc_confidence = _clamp(float(llm.get("root_cause_confidence", 0.0)))
    include_rc = bool(hypothesis_text) and rc_confidence >= _ROOT_CAUSE_CONFIDENCE_THRESHOLD
    root_cause = RootCauseHypothesis(
        hypothesis=hypothesis_text if include_rc else "",
        confidence=rc_confidence,
        included=include_rc,
    )

    # Sentiment
    sentiment_str = (llm.get("sentiment") or "neutral").lower()
    try:
        sentiment_enum = Sentiment(sentiment_str)
    except ValueError:
        sentiment_enum = Sentiment.neutral

    sentiment = SentimentResult(
        sentiment=sentiment_enum,
        confidence=_clamp(float(llm.get("sentiment_confidence", 0.5))),
        rationale=llm.get("sentiment_rationale", ""),
    )

    # Language
    detected_language = llm.get("detected_language", "en") or "en"

    return EnrichedTicket(
        ticket_id=ticket.id,
        source=ticket.source,
        summary=llm.get("summary", ticket.title),
        category=category,
        priority=priority,
        routing=routing,
        automation=automation,
        kb_articles=kb_articles,
        root_cause=root_cause,
        sentiment=sentiment,
        detected_language=detected_language,
        processing_time_ms=elapsed_ms,
    )


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


def _clamp_int(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, val))
