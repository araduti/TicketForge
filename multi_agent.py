"""
TicketForge — Multi-Agent Architecture

Implements a configurable multi-agent pipeline for ticket analysis:
  Analyser → Classifier → Validator

Each agent is a specialised LLM call with a focused prompt.  The orchestrator
runs them sequentially and merges the results.  When disabled (default
MULTI_AGENT_ENABLED=false), the existing single-LLM call path is used instead.
"""
from __future__ import annotations

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
from llm_provider import LLMProvider

log = structlog.get_logger(__name__)


# ── Agent prompt templates ────────────────────────────────────────────────────

ANALYSER_SYSTEM = (
    "You are an IT ticket analyser agent. "
    "You examine support tickets and produce a structured analysis. "
    "Respond ONLY with valid JSON — no prose, no markdown."
)

ANALYSER_USER = """\
Analyse this IT support ticket and return a JSON object:

{{
  "summary": "<one-sentence description>",
  "sentiment": "<positive | neutral | negative | frustrated>",
  "sentiment_confidence": <float 0.0-1.0>,
  "sentiment_rationale": "<brief explanation>",
  "detected_language": "<ISO 639-1 code>",
  "root_cause_hypothesis": "<hypothesis or empty string>",
  "root_cause_confidence": <float 0.0-1.0>,
  "kb_articles": [{{"title": "<title>", "url": "", "relevance_score": <float>}}]
}}

TICKET:
ID: {ticket_id}
Source: {source}
Title: {title}
Description: {description}
Reporter: {reporter}
Tags: {tags}
"""

CLASSIFIER_SYSTEM = (
    "You are an IT ticket classifier agent. "
    "Given an analysis summary, assign the correct category, priority, and routing. "
    "Respond ONLY with valid JSON."
)

CLASSIFIER_USER = """\
Based on this ticket analysis, classify and route the ticket:

Summary: {summary}
Sentiment: {sentiment}
Language: {detected_language}
Original title: {title}
Original description excerpt: {description_excerpt}

Return JSON:
{{
  "category": "<ITIL category>",
  "sub_category": "<specific sub-category>",
  "category_confidence": <float 0.0-1.0>,
  "priority": "<critical | high | medium | low>",
  "priority_score": <int 1-100>,
  "priority_rationale": "<one sentence>",
  "recommended_queue": "<queue name>",
  "recommended_team": "<team name>",
  "routing_rationale": "<one sentence>"
}}
"""

VALIDATOR_SYSTEM = (
    "You are an IT ticket validation agent. "
    "You review the combined output from analysis and classification agents "
    "and validate consistency. Respond ONLY with valid JSON."
)

VALIDATOR_USER = """\
Validate the following ticket analysis and classification for consistency.
If everything looks correct, return the data unchanged. If you find
inconsistencies, correct them and explain.

Analysis:
{analysis_json}

Classification:
{classification_json}

Return JSON:
{{
  "validated": true,
  "corrections": [],
  "final_category": "<category>",
  "final_sub_category": "<sub-category>",
  "final_category_confidence": <float>,
  "final_priority": "<priority>",
  "final_priority_score": <int>,
  "final_priority_rationale": "<rationale>",
  "final_recommended_queue": "<queue>",
  "final_recommended_team": "<team>",
  "final_routing_rationale": "<rationale>"
}}
"""


# ── Helper ────────────────────────────────────────────────────────────────────

def _parse_agent_json(raw: str) -> dict[str, Any]:
    """Extract JSON from an agent response, stripping markdown fences."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("No JSON object found in agent response", raw, 0)
    return json.loads(match.group())


# ── Orchestrator ──────────────────────────────────────────────────────────────

class MultiAgentOrchestrator:
    """
    Runs the Analyser → Classifier → Validator pipeline.

    Returns a merged dict that is compatible with the single-LLM output format
    used by ``ticket_processor._build_enriched``.
    """

    def __init__(self, llm: LLMProvider, *, max_description_chars: int = 3000) -> None:
        self._llm = llm
        self._max_desc = max_description_chars

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, json.JSONDecodeError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _call_agent(
        self,
        system: str,
        user: str,
        *,
        agent_name: str = "agent",
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        log.debug("multi_agent.call", agent=agent_name)
        raw = await self._llm.chat(messages, temperature=0.1, max_tokens=1024)
        return _parse_agent_json(raw)

    async def run(
        self,
        *,
        ticket_id: str,
        source: str,
        title: str,
        description: str,
        reporter: str,
        tags: str,
    ) -> dict[str, Any]:
        """Execute the full multi-agent pipeline and return merged results."""
        start = time.monotonic()

        # ── Step 1: Analyser ──────────────────────────────────────────────────
        analysis = await self._call_agent(
            ANALYSER_SYSTEM,
            ANALYSER_USER.format(
                ticket_id=ticket_id,
                source=source,
                title=title,
                description=description[:self._max_desc],
                reporter=reporter,
                tags=tags,
            ),
            agent_name="analyser",
        )

        # ── Step 2: Classifier ────────────────────────────────────────────────
        classification = await self._call_agent(
            CLASSIFIER_SYSTEM,
            CLASSIFIER_USER.format(
                summary=analysis.get("summary", title),
                sentiment=analysis.get("sentiment", "neutral"),
                detected_language=analysis.get("detected_language", "en"),
                title=title,
                description_excerpt=description[:500],
            ),
            agent_name="classifier",
        )

        # ── Step 3: Validator ─────────────────────────────────────────────────
        validation = await self._call_agent(
            VALIDATOR_SYSTEM,
            VALIDATOR_USER.format(
                analysis_json=json.dumps(analysis, indent=2),
                classification_json=json.dumps(classification, indent=2),
            ),
            agent_name="validator",
        )

        elapsed_ms = (time.monotonic() - start) * 1000
        log.info(
            "multi_agent.completed",
            ticket_id=ticket_id,
            agents=3,
            ms=round(elapsed_ms, 1),
        )

        # ── Merge into single-LLM compatible format ──────────────────────────
        return self._merge(analysis, classification, validation)

    @staticmethod
    def _merge(
        analysis: dict[str, Any],
        classification: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        """Combine agent outputs into the format expected by _build_enriched."""
        # Prefer validator's final_ fields when present, fall back to classifier
        return {
            "summary": analysis.get("summary", ""),
            "sentiment": analysis.get("sentiment", "neutral"),
            "sentiment_confidence": analysis.get("sentiment_confidence", 0.5),
            "sentiment_rationale": analysis.get("sentiment_rationale", ""),
            "detected_language": analysis.get("detected_language", "en"),
            "root_cause_hypothesis": analysis.get("root_cause_hypothesis", ""),
            "root_cause_confidence": analysis.get("root_cause_confidence", 0.0),
            "kb_articles": analysis.get("kb_articles", []),
            "category": validation.get("final_category", classification.get("category", "Uncategorised")),
            "sub_category": validation.get("final_sub_category", classification.get("sub_category", "")),
            "category_confidence": validation.get("final_category_confidence", classification.get("category_confidence", 0.5)),
            "priority": validation.get("final_priority", classification.get("priority", "medium")),
            "priority_score": validation.get("final_priority_score", classification.get("priority_score", 50)),
            "priority_rationale": validation.get("final_priority_rationale", classification.get("priority_rationale", "")),
            "recommended_queue": validation.get("final_recommended_queue", classification.get("recommended_queue", "")),
            "recommended_team": validation.get("final_recommended_team", classification.get("recommended_team", "")),
            "routing_rationale": validation.get("final_routing_rationale", classification.get("routing_rationale", "")),
            # Multi-agent metadata
            "_multi_agent": True,
            "_agent_count": 3,
            "_validated": validation.get("validated", False),
            "_corrections": validation.get("corrections", []),
        }
