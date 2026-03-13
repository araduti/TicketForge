"""
TicketForge — LLM prompt templates
All system/user prompts are centralised here to simplify iteration.
"""
from __future__ import annotations

# ── System prompt (shared) ────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are TicketForge, an expert IT service management (ITSM) analyst.
You respond ONLY with valid JSON — no markdown, no prose outside the JSON block.
Always return the exact JSON schema requested.
If you are uncertain, use your best professional judgement; do NOT hallucinate facts."""


# ── Analysis prompt ───────────────────────────────────────────────────────────

ANALYSE_USER_PROMPT = """\
Analyse the following IT support ticket and return a JSON object with this exact schema:

{{
  "summary": "<one-sentence description of the issue>",
  "category": "<top-level ITIL category, e.g. 'Hardware', 'Software', 'Network', 'Access & Identity', 'Service Request', 'Security Incident'>",
  "sub_category": "<more specific sub-category, e.g. 'VPN', 'Password Reset', 'Email Client', 'Printer'>",
  "category_confidence": <float 0.0–1.0>,
  "priority": "<one of: critical | high | medium | low>",
  "priority_score": <integer 1–100, where 100 = most urgent>,
  "priority_rationale": "<one-sentence explanation>",
  "recommended_queue": "<name of the queue or tier, e.g. 'L1 Service Desk', 'Network Ops', 'Security'>",
  "recommended_team": "<specific team, e.g. 'Windows Desktop Support', 'Cloud Infrastructure'>",
  "routing_rationale": "<one-sentence explanation>",
  "kb_articles": [
    {{"title": "<article title>", "url": "", "relevance_score": <float 0.0–1.0>}}
  ],
  "root_cause_hypothesis": "<only if confidence ≥ 0.75, otherwise empty string>",
  "root_cause_confidence": <float 0.0–1.0>
}}

Return at most 3 KB article suggestions. Leave url as empty string "".

TICKET:
ID: {ticket_id}
Source: {source}
Title: {title}
Description: {description}
Reporter: {reporter}
Tags: {tags}
"""


# ── Automation detection prompt ───────────────────────────────────────────────

AUTOMATION_USER_PROMPT = """\
You have detected a recurring pattern in IT support tickets. Analyse the pattern below
and return a JSON object:

{{
  "automation_score": <integer 0–100>,
  "suggestion_type": "<one of: bot | script | form | kb_article | self_service | none>",
  "suggestion": "<one concrete sentence, e.g. 'Deploy a password-reset chatbot to reduce L1 volume by ~40%'>"
}}

Pattern summary:
- Representative ticket title: {representative_title}
- Cluster size (similar tickets): {cluster_size}
- Frequency per week: {frequency_per_week:.1f}
- Common keywords: {keywords}
"""
