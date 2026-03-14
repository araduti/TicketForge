# TicketForge

Open-source, forge-your-own intelligent ticket enhancer.

A **lightweight, self-hosted AI layer** that enriches enterprise IT tickets
(ServiceNow, Jira, Zendesk, …) with intelligent categorisation, priority
scoring, queue routing, automation opportunity detection, KB suggestions, and
root-cause hypotheses — all running locally with Ollama on a ~$10-20/mo VPS.

---

## Enterprise features

| Feature | Description |
|---|---|
| **Role-Based Access Control** | API keys mapped to admin / analyst / viewer roles with endpoint-level authorisation |
| **Audit Logging** | Every API action is recorded with user, role, timestamp, and result for compliance |
| **Bulk Ticket Analysis** | Analyse up to 50 tickets in a single `POST /analyse/bulk` call |
| **Analytics Dashboard** | `GET /analytics` returns ticket counts by category, priority, daily trends, and avg automation score |
| **SLA Tracking** | Configurable response/resolution targets per priority level with breach detection |
| **Data Export** | `GET /export/tickets` in JSON or CSV format with category/priority filters |
| **Sentiment Analysis** | Detects user sentiment (positive/neutral/negative/frustrated) with confidence scoring |
| **Cloud LLM Support** | Pluggable LLM provider — use Ollama (local) or any OpenAI-compatible API (OpenAI, Azure, vLLM, LiteLLM) |
| **Ticket Lifecycle** | Track ticket status (open/in_progress/resolved/closed) via `PATCH /tickets/{id}/status` |
| **Language Detection** | Auto-detects ticket language (ISO 639-1) during analysis |
| **Slack & Teams Alerts** | Push notifications for high-priority tickets and SLA breaches to Slack and Microsoft Teams |
| **AI Response Suggestions** | `POST /suggest-response` generates draft agent responses for enriched tickets using the LLM |
| **Duplicate Detection** | `POST /tickets/detect-duplicates` finds similar tickets using sentence-transformer vector similarity |
| **Web Dashboard** | Built-in HTML dashboard at `GET /dashboard` showing tickets, analytics charts, and SLA overview |
| **Knowledge Base** | Full CRUD API (`/kb/articles`) with semantic vector search (`POST /kb/search`) for self-service content |
| **Email Ingestion** | `POST /ingest/email` webhook endpoint for SendGrid, Mailgun, and generic email providers |
| **Chatbot Interface** | `POST /chat` conversational endpoint for ticket creation, status lookup, and KB search with multi-turn sessions |
| **Self-Service Portal** | `GET /portal` HTML page for end-users to submit tickets, check status, browse KB, and chat |
| **Model Monitoring** | `GET /monitoring/drift` detects prediction drift in category, priority, and sentiment distributions |
| **Plugin System** | Pluggable enrichment architecture with pre/post analysis hooks and a `GET /plugins` management endpoint |
| **CSAT Surveys** | `POST /tickets/{id}/csat` to collect customer satisfaction ratings (1-5); `GET /analytics/csat` for aggregate scores |
| **WebSocket Notifications** | Real-time event streaming via `WS /ws/notifications` for ticket creation, status changes, and SLA breaches |
| **Multi-Language (i18n)** | `GET /i18n/languages` lists 27 supported languages; LLM responses generated in the ticket's detected language |
| **Multi-Agent Pipeline** | Configurable Analyser → Classifier → Validator pipeline for enhanced accuracy; toggle via `MULTI_AGENT_ENABLED` |
| **Persistent Vector Store** | Pluggable vector store with in-memory (default) and persistent SQLite-backed backends via `VECTOR_STORE_BACKEND` |
| **PostgreSQL Support** | Full PostgreSQL async connectivity via asyncpg driver; configure via `DATABASE_URL=postgresql://...` |

---

## Architecture

```
                       ┌────────────────────────────────────────┐
                       │          External Ticket Systems        │
                       │  ServiceNow │  Jira Cloud  │  Zendesk  │
                       └──────┬──────┴──────┬────────┴─────┬─────┘
                              │  REST API / │              │
                              │  Webhooks   │              │
                              ▼             ▼              ▼
                       ┌─────────────────────────────────────────┐
                       │          TicketForge  (FastAPI)          │
                       │                                         │
                       │  POST /analyse   POST /webhook/{source} │
                       │                                         │
                       │  ┌──────────────┐  ┌─────────────────┐ │
                       │  │ Connectors   │  │   API Key Auth  │ │
                       │  │ (parse only) │  │   Rate Limiter  │ │
                       │  └──────┬───────┘  └─────────────────┘ │
                       │         │                               │
                       │  ┌──────▼──────────────────────────┐   │
                       │  │        TicketProcessor           │   │
                       │  │                                  │   │
                       │  │  1. Build prompt                 │   │
                       │  │  2. Call LLM provider             │   │
                       │  │     (Ollama / OpenAI-compatible)  │   │
                       │  │  3. Parse structured JSON        │   │
                       │  │  4. Assemble EnrichedTicket      │   │
                       │  └──────┬──────────────┬───────────┘   │
                       │         │              │               │
                       │  ┌──────▼──────┐ ┌────▼────────────┐  │
                       │  │ Automation  │ │   SQLite cache  │  │
                       │  │ Detector    │ │  (24-hour TTL)  │  │
                       │  │ (DBSCAN +   │ └─────────────────┘  │
                       │  │  MiniLM-L6) │                       │
                       │  └─────────────┘                       │
                       └─────────────────────────────────────────┘
                                          │
                               ┌──────────▼──────────┐
                               │        Ollama        │
                               │  (Llama 3.1 8B / 70B │
                               │   or Mistral-Nemo)   │
                               └─────────────────────┘
```

### Key components

| File | Role |
|---|---|
| `main.py` | FastAPI app, routes, auth, RBAC, rate limiting, lifecycle |
| `config.py` | Pydantic-settings: all env-var config in one place |
| `models.py` | Pydantic request / response schemas |
| `ticket_processor.py` | Core pipeline: prompt → Ollama → structured JSON |
| `automation_detector.py` | sentence-transformers + DBSCAN clustering |
| `prompts.py` | All LLM prompt templates |
| `audit.py` | Audit logging service (compliance trail) |
| `connectors/servicenow.py` | ServiceNow Table API client |
| `connectors/jira.py` | Jira Cloud / Server REST API client |
| `connectors/zendesk.py` | Zendesk Support API v2 client |
| `tests/` | pytest test suite for enterprise features |

---

## Directory structure

```
TicketForge/
├── connectors/
│   ├── __init__.py
│   ├── jira.py
│   ├── servicenow.py
│   └── zendesk.py
├── tests/
│   ├── __init__.py
│   └── test_enterprise_features.py
├── audit.py
├── automation_detector.py
├── config.py
├── docker-compose.yml
├── Dockerfile
├── main.py
├── models.py
├── prompts.py
├── requirements.txt
├── ticket_processor.py
└── README.md
```

---

## Setup & run

### Prerequisites

* Docker ≥ 24 and Docker Compose v2
* ~4 GB RAM free for the 8B quantized model
* (Optional) NVIDIA GPU — uncomment the `deploy` section in `docker-compose.yml`

### 1 · Clone and configure

```bash
git clone https://github.com/araduti/TicketForge.git
cd TicketForge

# Create an env file — at minimum set a real API key
cat > .env <<'EOF'
API_KEYS=my-super-secret-key
OLLAMA_MODEL=llama3.1:8b
# ServiceNow, Jira, Zendesk credentials go here (optional)
EOF
```

### 2 · Start the stack

```bash
docker compose up -d
```

### 3 · Pull the LLM model (first run only, ~4.5 GB download)

```bash
docker compose exec ollama ollama pull llama3.1:8b
```

### 4 · Verify health

```bash
curl http://localhost:8000/health
# {"status":"ok","ollama_reachable":true,"db_ok":true,"version":"0.1.0"}
```

---

## Example API calls

### Analyse a ticket inline

```bash
curl -s -X POST http://localhost:8000/analyse \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: my-super-secret-key" \
  -d '{
    "ticket": {
      "id": "INC0012345",
      "source": "servicenow",
      "title": "Cannot connect to VPN from home",
      "description": "Since this morning I cannot connect to the corporate VPN. I get error code 800. Tried restarting the client.",
      "reporter": "john.doe@example.com",
      "tags": ["vpn", "remote-work"]
    },
    "include_automation_detection": true
  }' | jq .
```

**Example response** (truncated):

```json
{
  "success": true,
  "data": {
    "ticket_id": "INC0012345",
    "source": "servicenow",
    "summary": "User is unable to connect to corporate VPN from home since this morning, receiving error code 800.",
    "category": {
      "category": "Network",
      "sub_category": "VPN",
      "confidence": 0.95
    },
    "priority": {
      "priority": "high",
      "score": 72,
      "rationale": "VPN outage affects remote work capability and productivity."
    },
    "routing": {
      "recommended_queue": "Network Ops",
      "recommended_team": "Network Infrastructure",
      "rationale": "VPN issues require network team investigation."
    },
    "automation": {
      "score": 0,
      "suggestion_type": "none",
      "suggestion": "",
      "pattern_count": 0
    },
    "kb_articles": [
      {
        "title": "VPN Troubleshooting Guide — Error Codes 800/868",
        "url": "",
        "relevance_score": 0.92
      }
    ],
    "root_cause": {
      "hypothesis": "VPN gateway may be blocking UDP port 1194 for the user's ISP.",
      "confidence": 0.78,
      "included": true
    },
    "processing_time_ms": 4231.5
  }
}
```

### Ingest a ServiceNow webhook

```bash
curl -s -X POST http://localhost:8000/webhook/servicenow \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: my-super-secret-key" \
  -d '{
    "payload": {
      "sys_id": "abc123",
      "number": "INC0099",
      "short_description": "Outlook keeps crashing on startup",
      "description": "After the latest Windows update Outlook crashes immediately on open.",
      "priority": "3",
      "caller_id": "jane.smith@example.com",
      "assigned_to": "",
      "sys_created_on": "2024-03-01 09:00:00",
      "sys_tags": "email,outlook"
    }
  }'
```

### Metrics (Prometheus)

```bash
curl http://localhost:8000/metrics
```

### Bulk analysis (up to 50 tickets)

```bash
curl -s -X POST http://localhost:8000/analyse/bulk \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: my-super-secret-key" \
  -d '{
    "tickets": [
      {"id": "T1", "title": "VPN not working", "description": "Error 800 on connect"},
      {"id": "T2", "title": "Outlook crash", "description": "Crashes on startup after update"}
    ]
  }' | jq .
```

### Analytics dashboard

```bash
curl -s http://localhost:8000/analytics?days=30 \
  -H "X-Api-Key: my-super-secret-key" | jq .
```

### Export tickets as CSV

```bash
curl -s "http://localhost:8000/export/tickets?format=csv&priority=high" \
  -H "X-Api-Key: my-super-secret-key" -o tickets.csv
```

### Audit logs (admin only)

```bash
curl -s http://localhost:8000/audit/logs?page=1&page_size=20 \
  -H "X-Api-Key: my-admin-key" | jq .
```

### Chat with the assistant

```bash
curl -s http://localhost:8000/chat \
  -H "X-Api-Key: my-key" \
  -H "Content-Type: application/json" \
  -d '{"message": "How to reset my VPN connection?"}' | jq .
```

### Submit a ticket via the self-service portal

```bash
curl -s http://localhost:8000/portal/tickets \
  -H "X-Api-Key: my-key" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Laptop won'\''t boot",
    "description": "Black screen after pressing power button",
    "reporter_email": "user@company.com",
    "category": "Hardware"
  }' | jq .
```

### Model drift monitoring (admin only)

```bash
curl -s http://localhost:8000/monitoring/drift \
  -H "X-Api-Key: my-admin-key" | jq .
```

### List registered plugins (admin only)

```bash
curl -s http://localhost:8000/plugins \
  -H "X-Api-Key: my-admin-key" | jq .
```

### Submit a CSAT rating

```bash
curl -s http://localhost:8000/tickets/TICKET-001/csat \
  -H "X-Api-Key: my-key" \
  -H "Content-Type: application/json" \
  -d '{"rating": 5, "comment": "Resolved quickly!"}' | jq .
```

### Get CSAT analytics (analyst+)

```bash
curl -s http://localhost:8000/analytics/csat \
  -H "X-Api-Key: my-analyst-key" | jq .
```

### WebSocket real-time notifications

```bash
# Connect via wscat or similar WebSocket client
wscat -c "ws://localhost:8000/ws/notifications?api_key=my-key"
```

### List supported i18n languages

```bash
curl -s http://localhost:8000/i18n/languages \
  -H "X-Api-Key: my-key" | jq .
```

### Check multi-agent pipeline status

```bash
curl -s http://localhost:8000/multi-agent/status \
  -H "X-Api-Key: my-key" | jq .
```

### Check vector store status

```bash
curl -s http://localhost:8000/vector-store/status \
  -H "X-Api-Key: my-key" | jq .
```

---

## RBAC setup

API keys are mapped to roles via the `API_KEY_ROLES` environment variable (JSON):

```bash
API_KEYS=admin-key-123,analyst-key-456,viewer-key-789
API_KEY_ROLES='{"admin-key-123":"admin","analyst-key-456":"analyst","viewer-key-789":"viewer"}'
```

| Role | Permissions |
|---|---|
| **admin** | Full access: analyse, bulk, webhooks, analytics, audit logs, export, monitoring, plugins |
| **analyst** | Analyse tickets (single & bulk), ingest webhooks, view analytics, export, KB management |
| **viewer** | Read-only: view tickets, analytics, export, chat, portal, KB search |

Keys not listed in `API_KEY_ROLES` default to `analyst`.

---

## SLA targets

Configurable per priority level via environment variables (values in minutes):

| Priority | Response target | Resolution target | Env vars |
|---|---|---|---|
| Critical | 15 min | 4 hours | `SLA_RESPONSE_CRITICAL`, `SLA_RESOLUTION_CRITICAL` |
| High | 1 hour | 8 hours | `SLA_RESPONSE_HIGH`, `SLA_RESOLUTION_HIGH` |
| Medium | 4 hours | 24 hours | `SLA_RESPONSE_MEDIUM`, `SLA_RESOLUTION_MEDIUM` |
| Low | 8 hours | 48 hours | `SLA_RESPONSE_LOW`, `SLA_RESOLUTION_LOW` |

Every enriched ticket includes an `sla` object with status (`within`, `at_risk`, `breached`),
elapsed time, and breach risk score (0.0–1.0).

---

## Configuration reference

All settings are read from environment variables (or a `.env` file):

| Variable | Default | Description |
|---|---|---|
| `API_KEYS` | `changeme` | Comma-separated list of valid API keys |
| `API_KEY_ROLES` | `{}` | JSON mapping of API key → role (admin/analyst/viewer) |
| `LLM_PROVIDER` | `ollama` | LLM backend: `ollama` (local) or `openai` (OpenAI-compatible API) |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama service URL |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model to use for analysis (Ollama provider) |
| `OLLAMA_TIMEOUT` | `120` | Seconds before LLM call times out |
| `OPENAI_API_KEY` | _(empty)_ | API key for OpenAI-compatible provider |
| `OPENAI_BASE_URL` | `https://api.openai.com` | Base URL for OpenAI-compatible API |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name for OpenAI-compatible provider |
| `DATABASE_URL` | `sqlite+aiosqlite:///./ticketforge.db` | SQLite path |
| `DB_TICKET_TTL_HOURS` | `24` | Hours to retain ticket cache |
| `DBSCAN_EPS` | `0.3` | DBSCAN neighbourhood distance |
| `DBSCAN_MIN_SAMPLES` | `3` | DBSCAN minimum cluster size |
| `AUTOMATION_LOOKBACK_HOURS` | `168` | Rolling window for clustering (7 days) |
| `RATE_LIMIT_PER_MINUTE` | `60` | Max requests/min per client IP |
| `SERVICENOW_INSTANCE` | _(empty)_ | e.g. `mycompany.service-now.com` |
| `JIRA_BASE_URL` | _(empty)_ | e.g. `https://mycompany.atlassian.net` |
| `ZENDESK_SUBDOMAIN` | _(empty)_ | e.g. `mycompany` |
| `OUTBOUND_WEBHOOK_URL` | _(empty)_ | POST enriched JSON here (Slack, Teams, …) |
| `SLACK_WEBHOOK_URL` | _(empty)_ | Slack incoming webhook URL for notifications |
| `TEAMS_WEBHOOK_URL` | _(empty)_ | Microsoft Teams incoming webhook URL for notifications |
| `NOTIFICATION_MIN_PRIORITY` | `high` | Minimum priority to trigger Slack/Teams alerts |
| `NOTIFY_ON_SLA_BREACH` | `true` | Send alerts when SLA is breached or at risk |
| `SLA_RESPONSE_CRITICAL` | `15` | Response SLA for critical tickets (minutes) |
| `SLA_RESPONSE_HIGH` | `60` | Response SLA for high tickets (minutes) |
| `SLA_RESPONSE_MEDIUM` | `240` | Response SLA for medium tickets (minutes) |
| `SLA_RESPONSE_LOW` | `480` | Response SLA for low tickets (minutes) |
| `SLA_RESOLUTION_CRITICAL` | `240` | Resolution SLA for critical tickets (minutes) |
| `SLA_RESOLUTION_HIGH` | `480` | Resolution SLA for high tickets (minutes) |
| `SLA_RESOLUTION_MEDIUM` | `1440` | Resolution SLA for medium tickets (minutes) |
| `SLA_RESOLUTION_LOW` | `2880` | Resolution SLA for low tickets (minutes) |
| `LOG_LEVEL` | `INFO` | Structured log verbosity |
| `CHATBOT_ENABLED` | `true` | Enable the `POST /chat` chatbot endpoint |
| `CHATBOT_MAX_HISTORY` | `20` | Maximum conversation messages kept per session |
| `PORTAL_ENABLED` | `true` | Enable the `GET /portal` self-service endpoint |
| `MONITORING_ENABLED` | `true` | Enable the `GET /monitoring/drift` endpoint |
| `MONITORING_BASELINE_DAYS` | `30` | Baseline period in days for drift comparison |
| `MONITORING_WINDOW_DAYS` | `7` | Recent monitoring window in days |
| `DRIFT_THRESHOLD` | `0.3` | Drift score threshold (0.0–1.0) to flag as drifting |
| `EMAIL_INGESTION_ENABLED` | `false` | Enable the `POST /ingest/email` endpoint |
| `CSAT_ENABLED` | `true` | Enable CSAT survey endpoints (`/tickets/{id}/csat`, `/analytics/csat`) |
| `WEBSOCKET_NOTIFICATIONS_ENABLED` | `true` | Enable WebSocket real-time event streaming at `/ws/notifications` |
| `I18N_ENABLED` | `true` | Enable multi-language prompt templates and localised LLM responses |
| `I18N_DEFAULT_LANGUAGE` | `en` | Default language (ISO 639-1) when no language is detected |
| `MULTI_AGENT_ENABLED` | `false` | Enable multi-agent pipeline (Analyser → Classifier → Validator) instead of single LLM call |
| `VECTOR_STORE_BACKEND` | `in_memory` | Vector store backend: `in_memory` (default) or `persistent` (SQLite-backed) |

---

## License

MIT

