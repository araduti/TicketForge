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
  "sentiment": "<one of: positive | neutral | negative | frustrated>",
  "sentiment_confidence": <float 0.0–1.0>,
  "sentiment_rationale": "<one-sentence explanation of why this sentiment was detected>",
  "detected_language": "<ISO 639-1 two-letter language code, e.g. 'en', 'es', 'fr', 'de', 'ja'>",
  "kb_articles": [
    {{"title": "<article title>", "url": "", "relevance_score": <float 0.0–1.0>}}
  ],
  "root_cause_hypothesis": "<only if confidence ≥ 0.75, otherwise empty string>",
  "root_cause_confidence": <float 0.0–1.0>
}}

Return at most 3 KB article suggestions. Leave url as empty string "".
For sentiment, consider the user's tone, urgency, and frustration level:
- "positive": User is appreciative or satisfied
- "neutral": Standard professional request
- "negative": User is unhappy or dissatisfied
- "frustrated": User is visibly frustrated, angry, or has escalated the issue

TICKET:
ID: {ticket_id}
Source: {source}
Title: {title}
Description: {description}
Reporter: {reporter}
Tags: {tags}
"""


# ── Automation detection prompt ───────────────────────────────────────────────

SUGGEST_RESPONSE_PROMPT = """\
You are drafting a professional response for an IT support agent to send to the user who submitted the ticket below.

Ticket info:
- ID: {ticket_id}
- Title: {title}
- Description: {description}
- Category: {category}
- Sub-category: {sub_category}
- Priority: {priority}
- Sentiment: {sentiment}
- Summary: {summary}
- KB articles: {kb_articles}
- Root cause hypothesis: {root_cause}

Return a JSON object with this exact schema:
{{
  "subject": "<email-style subject line>",
  "body": "<professional response message to the user, use newlines for paragraphs>",
  "tone": "<one of: empathetic | professional | urgent | informational>",
  "suggested_actions": ["<action 1>", "<action 2>"]
}}

Guidelines:
- Acknowledge the user's issue and sentiment
- Reference relevant KB articles if available
- Include concrete next steps
- Match the urgency to the ticket priority
- If user is frustrated, use an empathetic tone
- Keep the response concise but helpful
"""


CHATBOT_SYSTEM_PROMPT = """\
You are TicketForge Assistant, a helpful IT support chatbot.
You help users with:
1. Creating support tickets by gathering issue details
2. Checking ticket status
3. Searching the knowledge base for solutions
4. General IT support questions

Be concise, professional, and helpful. Guide users through the process step by step.
If the user's language is not English, respond in the same language they use."""


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


# ── Internationalisation (i18n) prompt additions ─────────────────────────────

I18N_LANGUAGE_INSTRUCTION = """\

IMPORTANT: The ticket is written in {language_name} (ISO code: {language_code}).
Respond with ALL text fields in {language_name}. This includes the summary,
priority_rationale, routing_rationale, sentiment_rationale, kb_articles titles,
and root_cause_hypothesis. Keep JSON keys in English."""

I18N_RESPONSE_LANGUAGE_INSTRUCTION = """\

IMPORTANT: The user's ticket is in {language_name} (ISO code: {language_code}).
Write the response body in {language_name}. The subject line should also be in
{language_name}. Keep JSON keys in English."""

# Language code → human-readable name (common IT-support languages)
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
    "nl": "Dutch",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
    "sv": "Swedish",
    "pl": "Polish",
    "da": "Danish",
    "fi": "Finnish",
    "nb": "Norwegian",
    "tr": "Turkish",
    "cs": "Czech",
    "ro": "Romanian",
    "uk": "Ukrainian",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ms": "Malay",
    "he": "Hebrew",
}


def get_language_name(code: str) -> str:
    """Return the human-readable name for an ISO 639-1 language code."""
    return LANGUAGE_NAMES.get(code.lower(), code.upper())


def get_i18n_analysis_prompt(language_code: str) -> str:
    """Return the language instruction to append to the analysis prompt, or empty string for English."""
    if language_code.lower() == "en":
        return ""
    name = get_language_name(language_code)
    return I18N_LANGUAGE_INSTRUCTION.format(language_name=name, language_code=language_code)


def get_i18n_response_prompt(language_code: str) -> str:
    """Return the language instruction to append to the response-suggestion prompt, or empty string for English."""
    if language_code.lower() == "en":
        return ""
    name = get_language_name(language_code)
    return I18N_RESPONSE_LANGUAGE_INSTRUCTION.format(language_name=name, language_code=language_code)


# ── Auto-resolution prompt ───────────────────────────────────────────────────

AUTO_RESOLVE_PROMPT = """\
You are an AI auto-resolution engine. Based on the ticket information and matching knowledge base
articles below, determine whether this ticket can be automatically resolved.

Ticket info:
- ID: {ticket_id}
- Title: {title}
- Category: {category}
- Priority: {priority}
- Sentiment: {sentiment}
- Summary: {summary}

Matching KB articles:
{kb_articles}

Return a JSON object with this exact schema:
{{
  "can_resolve": <true if the KB articles provide a clear solution, false otherwise>,
  "confidence": <float 0.0–1.0, how confident you are in the resolution>,
  "resolution_summary": "<one-sentence summary of the resolution>",
  "response_draft": "<professional response to the user explaining the solution, reference KB articles>"
}}

Guidelines:
- Only set can_resolve=true if the KB articles directly address the user's issue
- The confidence should reflect how well the KB articles match the ticket
- For frustrated users, use an empathetic tone in the response draft
- Include specific steps or links from KB articles
- If no KB articles match well, set can_resolve=false with confidence=0.0
"""
