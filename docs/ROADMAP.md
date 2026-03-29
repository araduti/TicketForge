# TicketForge — v1.0 Release Roadmap

> **Last updated:** March 2026
>
> This document assesses TicketForge's current state, benchmarks it against
> competitor features, and lays out the remaining work to reach a production-ready
> **v1.0** release.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State](#2-current-state)
3. [Competitor Benchmark](#3-competitor-benchmark)
4. [Gap Analysis — What's Missing for v1](#4-gap-analysis--whats-missing-for-v1)
5. [Roadmap Phases](#5-roadmap-phases)
6. [Release Criteria](#6-release-criteria)

---

## 1. Executive Summary

TicketForge has **completed all 11 feature phases** (55 recommendations) and
ships an impressive breadth of AI-powered enrichment capabilities — sentiment
analysis, multi-agent pipelines, automation detection, chatbot, knowledge base,
self-service portal, and 120+ API endpoints — running entirely on local
infrastructure.

**However, the project is not yet v1-ready.** Critical production concerns
remain around security hardening, code architecture, deployment tooling, and API
maturity. This roadmap organises the remaining work into four focused phases
estimated at **10–14 weeks** of effort.

### Readiness Scorecard

| Dimension               | Score | Notes                                              |
|--------------------------|-------|----------------------------------------------------|
| Feature completeness     | ★★★★★ | 55/55 recommendations delivered                   |
| Test coverage            | ★★★★☆ | 633 tests across 15 files; mostly happy-path       |
| Security                 | ★★☆☆☆ | Plain-text API keys, no OAuth2/OIDC, no hashing    |
| Code architecture        | ★★☆☆☆ | 8,698-line monolithic main.py                      |
| Deployment / ops         | ★★☆☆☆ | Docker Compose only; no K8s, no TLS guide          |
| API maturity             | ★★★☆☆ | 124 endpoints but no versioning, no OpenAPI spec   |
| Documentation            | ★★★☆☆ | Good README + competitive analysis; no API docs    |
| Observability            | ★★★☆☆ | Prometheus metrics; no tracing or alerting          |
| Database                 | ★★★☆☆ | SQLite + PostgreSQL; no migration framework         |

---

## 2. Current State

### 2.1 Technology Stack

| Component        | Technology                          |
|------------------|-------------------------------------|
| Framework        | FastAPI 0.115.6 / Uvicorn 0.32.1    |
| Validation       | Pydantic 2.10.3                     |
| Database         | SQLite (aiosqlite) / PostgreSQL (asyncpg) |
| LLM              | Ollama (local) / OpenAI-compatible  |
| Embeddings       | sentence-transformers 3.3.1         |
| Clustering       | scikit-learn 1.6.0                  |
| Auth             | python-jose / passlib               |
| Rate limiting    | slowapi 0.1.9                       |
| Monitoring       | prometheus-fastapi-instrumentator   |
| Logging          | structlog 24.4.0 (JSON)             |

### 2.2 Codebase Metrics

| Metric                   | Value              |
|--------------------------|--------------------|
| Application code         | ~13,700 lines      |
| `main.py`                | 8,698 lines        |
| `models.py`              | 2,040 lines        |
| `config.py`              | 498 lines          |
| Supporting modules       | 10 files, ~2,900 lines |
| API endpoints            | 124                |
| Database tables          | 31                 |
| Test files               | 15                 |
| Total tests              | 633                |
| Feature flags            | 60+                |

### 2.3 Completed Feature Phases

All 11 implementation phases are **100 % complete**:

| Phase | Theme                                | Key Deliverables                                                  |
|-------|--------------------------------------|-------------------------------------------------------------------|
| 1     | Quick Wins                           | Sentiment analysis, cloud LLM, dashboard, Slack, status tracking  |
| 2     | Core Enhancements                    | KB module, PostgreSQL, email ingestion, response suggestions, duplicate detection |
| 3     | Differentiation                      | Chatbot, i18n (27 languages), portal, drift monitoring, plugins   |
| 4     | Enhancement                          | CSAT surveys, WebSocket notifications                             |
| 5     | Production Readiness                 | Multi-agent pipeline, persistent vector store                     |
| 6     | Integration Ecosystem                | Auto-resolution, outbound webhooks, PagerDuty, OpsGenie           |
| 7     | Operational Excellence               | Scheduled reports, ticket merging, custom fields, tags, saved filters |
| 8     | Predictive Analytics                 | SLA breach prediction, response templates, timeline, bulk ops, skill routing |
| 9     | Enterprise Workflow                  | Automation rules, approvals, collision detection, contacts, macros |
| 10a   | Advanced Analytics                   | Team dashboards, SLA prediction, volume forecasting               |
| 10b   | AI Customisation                     | Custom classifiers, anomaly detection, KB auto-generation         |
| 10c   | Platform Maturity                    | Visual workflow builder, compliance/PII, caching, UX/onboarding   |
| 11    | Intelligent Automation               | Troubleshooting flows, intent/entity extraction, resolution & satisfaction prediction, smart assignment |

---

## 3. Competitor Benchmark

### 3.1 Competitive Landscape

TicketForge competes across three tiers:

| Tier | Competitors | Positioning |
|------|-------------|-------------|
| **Direct open-source (AI-first)** | ai-ticket-classifier, ai-support-ticket-analyzer, langgraph-ticket-routing, NLP-Ticket-Classification-MLOps, databricks-ai-ticket-vectorsearch | TicketForge leads on feature depth, enterprise features, and local-first AI |
| **Indirect open-source (full helpdesk)** | GLPI, Zammad, FreeScout, Frappe Helpdesk, Peppermint, LibreDesk, Trudesk, Znuny, Helpy, OpenSupports | TicketForge augments these — complementary rather than competing |
| **Commercial SaaS** | Zendesk AI, Freshservice/Freddy AI, ServiceNow, Jira Service Management, Moveworks, Aisera | TicketForge targets the same use cases at ~90 % lower cost, self-hosted |

### 3.2 Feature Comparison Matrix

Features are compared across the competitive set. ✅ = implemented, ⬜ = not available.

| Feature Area | TicketForge | Zendesk AI | Freshservice | ai-ticket-classifier | langgraph | LibreDesk |
|---|---|---|---|---|---|---|
| **Core AI** | | | | | | |
| Categorisation | ✅ | ✅ | ✅ | ✅ | ✅ | ⬜ |
| Priority scoring | ✅ | ✅ | ✅ | ✅ | ✅ | ⬜ |
| Sentiment analysis | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| Root cause hypotheses | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| Automation detection | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| Intent detection | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| Multi-agent pipeline | ✅ | ⬜ | ⬜ | ⬜ | ✅ | ⬜ |
| **Self-service** | | | | | | |
| Knowledge base | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| Self-service portal | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| Chatbot | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| Auto-resolution | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| **Enterprise** | | | | | | |
| RBAC | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| Audit logging | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| SLA tracking | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| Approval workflows | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| SSO/OAuth2/OIDC | ⬜ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| API versioning | ⬜ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| **Integration** | | | | | | |
| ServiceNow | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| Jira | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| Zendesk | ✅ | native | ⬜ | ✅ | ⬜ | ⬜ |
| Slack / Teams | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| PagerDuty / OpsGenie | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Outbound webhooks | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| **Deployment** | | | | | | |
| Self-hosted | ✅ | ⬜ | ⬜ | ✅ | ✅ | ✅ |
| Local LLM | ✅ | ⬜ | ⬜ | ✅ | ⬜ | ⬜ |
| Docker | ✅ | N/A | N/A | ⬜ | ✅ | ✅ |
| Kubernetes / Helm | ⬜ | N/A | N/A | ⬜ | ⬜ | ⬜ |
| **Ops / Quality** | | | | | | |
| CI/CD pipeline | ⬜ | ✅ | ✅ | ✅ | ⬜ | ✅ |
| DB migrations | ⬜ | ✅ | ✅ | N/A | ⬜ | ✅ |
| OpenAPI / Swagger | ⬜ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| Distributed tracing | ⬜ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |

### 3.3 TicketForge's Unique Advantages

These capabilities have **no equivalent** across the open-source competitive set:

1. **100 % local AI processing** — data never leaves infrastructure (Ollama)
2. **Automation opportunity detection** — DBSCAN clustering on embeddings
3. **Root cause hypothesis generation** — AI-generated with confidence scoring
4. **Augmentation architecture** — enriches ServiceNow/Jira/Zendesk rather than replacing them
5. **Enterprise features in open source** — RBAC, audit, SLA, PagerDuty, all free
6. **Cost advantage** — ~$10–20/mo VPS vs $29–115/agent/mo commercial SaaS

### 3.4 Where Competitors Lead

| Competitor Gap | Impact | Addressed in Roadmap |
|---|---|---|
| **SSO / OAuth2 / OIDC** — Zendesk, Freshservice, ServiceNow all support federated identity | Blocks enterprise adoption | Phase A |
| **API versioning** — all commercial APIs use versioned paths (`/v1/`, `/v2/`) | Breaks client contracts on changes | Phase B |
| **Database migrations** — LibreDesk, GLPI, Zammad all use managed schema migrations | Blocks safe upgrades | Phase B |
| **CI/CD pipeline** — ai-ticket-classifier, LibreDesk ship with GitHub Actions | Blocks contributor confidence | Phase B |
| **OpenAPI documentation** — Zendesk, Freshservice publish interactive API docs | Blocks developer adoption | Phase B |
| **Kubernetes support** — Zendesk and ServiceNow run at K8s scale | Blocks cloud-native deployment | Phase C |
| **Distributed tracing** — ServiceNow, Zendesk use OpenTelemetry/Datadog | Blocks production debugging | Phase D |
| **Mobile app** — Zendesk, Freshservice have native mobile apps | Nice-to-have, not a v1 blocker | Post-v1 |

---

## 4. Gap Analysis — What's Missing for v1

### 4.1 🔴 Blockers (Must fix before v1)

#### B1. Security Hardening

- **API keys are stored and compared in plain text** — must hash with bcrypt/argon2
- **No OAuth2 / OIDC / SSO** — enterprise customers require federated identity
- **No API key rotation** — compromised keys cannot be revoked
- **No request signing** — webhook payloads lack integrity verification
- **No input sanitisation middleware** — XSS/injection vectors in ticket text

#### B2. Code Architecture

- **`main.py` is 8,698 lines** — all 124 endpoints, database schema, WebSocket
  handlers, auth logic, and business rules in a single file
- **No dependency injection** — global singletons (`_processor`, `_db`,
  `_vector_store`) are tightly coupled to the app
- **31 SQL table definitions hard-coded** — no schema version control

#### B3. API Maturity

- **No API versioning** — all endpoints live at root (`/analyse`, not `/v1/analyse`)
- **No OpenAPI/Swagger spec** — FastAPI generates this automatically when
  configured, but it is not exposed at `/docs` or `/redoc`
- **No standardised error response format** — inconsistent error payloads

#### B4. Deployment & Operations

- **No production deployment guide** — only Docker Compose for local dev
- **No database migration framework** — raw SQL table creation at startup
- **No CI/CD pipeline** — no GitHub Actions, no linting, no security scanning
- **No TLS/SSL documentation** — no reverse proxy guidance

### 4.2 🟡 Important (Should fix for v1)

| Gap | Detail |
|-----|--------|
| Distributed rate limiting | slowapi is in-memory; need Redis-backed for multi-instance |
| Secret management | Secrets in `.env`; should support Vault/AWS Secrets Manager |
| Request ID tracing | No correlation ID across log entries |
| Error tracking | No Sentry / error aggregation integration |
| Performance profiling | No benchmarks for LLM call latency or DB query time |
| Concurrent load testing | No multi-worker / race condition verification |

### 4.3 🟢 Nice-to-have (Post-v1)

| Gap | Detail |
|-----|--------|
| Mobile app | Native iOS/Android for agents |
| GraphQL API | Alternative to REST for complex queries |
| Multi-tenancy | Org-level data isolation |
| Custom ML model training | Bring-your-own-model support beyond classifiers |
| Advanced A/B testing | Feature flag service integration (LaunchDarkly) |

---

## 5. Roadmap Phases

### Phase A — Security Hardening (2–3 weeks)

> **Goal:** Make TicketForge safe to expose to the internet.

| # | Task | Effort | Priority |
|---|------|--------|----------|
| A1 | Hash API keys at rest (bcrypt/argon2); compare via constant-time check | S | 🔴 Critical |
| A2 | Add API key rotation endpoint (`POST /api-keys/rotate`) | S | 🔴 Critical |
| A3 | Add input sanitisation middleware (HTML escape ticket text, strip script tags) | S | 🔴 Critical |
| A4 | Add request ID middleware (UUID per request, propagate in structlog context) | S | 🟡 Important |
| A5 | Add CORS configuration (configurable allowed origins) | S | 🟡 Important |
| A6 | Document OAuth2/OIDC integration pathway (token validation middleware) | M | 🟡 Important |
| A7 | Add Content Security Policy headers for dashboard/portal HTML | S | 🟡 Important |

**Exit criteria:** API keys hashed, input sanitised, request IDs in logs.

### Phase B — API Maturity & Code Quality (3–4 weeks)

> **Goal:** Stabilise the API contract, enable safe upgrades, and improve
> developer experience.

| # | Task | Effort | Priority |
|---|------|--------|----------|
| B1 | Add `/v1/` API version prefix (FastAPI `APIRouter` with prefix) | M | 🔴 Critical |
| B2 | Expose OpenAPI spec at `/docs` and `/redoc` | S | 🔴 Critical |
| B3 | Standardise error response format (`{"error": {"code": ..., "message": ..., "request_id": ...}}`) | M | 🔴 Critical |
| B4 | Integrate Alembic for database migrations; convert 31 tables to migration scripts | L | 🔴 Critical |
| B5 | Split `main.py` into modular route files (`routes/tickets.py`, `routes/kb.py`, `routes/analytics.py`, etc.) | L | 🔴 Critical |
| B6 | Add CI/CD pipeline — GitHub Actions for tests, linting (ruff), security scanning (bandit) | M | 🔴 Critical |
| B7 | Add `CHANGELOG.md` and semantic versioning | S | 🟡 Important |
| B8 | Add `CONTRIBUTING.md` with development setup instructions | S | 🟡 Important |

**Exit criteria:** Versioned API, auto-generated docs, migrations, modular code,
CI green.

### Phase C — Production Deployment (2–3 weeks)

> **Goal:** Enable reliable production deployments.

| # | Task | Effort | Priority |
|---|------|--------|----------|
| C1 | Write production deployment guide (nginx/Caddy reverse proxy + TLS) | M | 🔴 Critical |
| C2 | Create Kubernetes manifests + Helm chart (Deployment, Service, Ingress, ConfigMap, Secret) | L | 🟡 Important |
| C3 | Add health check endpoints (`/health`, `/ready`) with dependency checks | S | 🔴 Critical |
| C4 | Document database backup/restore procedures for SQLite and PostgreSQL | M | 🟡 Important |
| C5 | Add multi-worker Uvicorn configuration with Gunicorn process manager | S | 🟡 Important |
| C6 | Add Docker image publishing workflow (GitHub Container Registry) | M | 🟡 Important |

**Exit criteria:** Documented production deployment path, health checks,
container registry.

### Phase D — Observability & Hardening (2–3 weeks)

> **Goal:** Enable production debugging and performance monitoring.

| # | Task | Effort | Priority |
|---|------|--------|----------|
| D1 | Add OpenTelemetry tracing (spans for LLM calls, DB queries, endpoint handlers) | M | 🟡 Important |
| D2 | Add Prometheus alerting rules (error rate, latency p99, SLA breach rate) | M | 🟡 Important |
| D3 | Add structured error tracking (Sentry SDK integration, optional) | S | 🟡 Important |
| D4 | Add load testing suite (Locust or k6 scripts for key endpoints) | M | 🟡 Important |
| D5 | Add edge-case and negative-path tests (auth failures, malformed input, concurrent locks) | M | 🟡 Important |
| D6 | Publish performance benchmarks (tickets/sec, p50/p95/p99 latency) | S | 🟢 Nice-to-have |

**Exit criteria:** Tracing enabled, alerting rules defined, load tested.

### Timeline Summary

```
Week     1   2   3   4   5   6   7   8   9  10  11  12  13  14
       ├───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┼───┤
Phase A ████████████
Phase B         ████████████████████
Phase C                         ████████████
Phase D                                 ████████████████
v1 RC                                                   ████
v1.0                                                        🚀
```

**Estimated total: 10–14 weeks** to v1.0 release (phases overlap).

---

## 6. Release Criteria

A commit may be tagged **v1.0.0** when all of the following are met:

### Must-Have ✅

- [ ] API keys hashed at rest; plain-text comparison eliminated
- [ ] Input sanitisation middleware active on all user-supplied text
- [ ] API versioned under `/v1/` prefix
- [ ] OpenAPI spec accessible at `/docs` and `/redoc`
- [ ] Standardised error response format on all endpoints
- [ ] Database migrations via Alembic (or equivalent); no raw `CREATE TABLE` at startup
- [ ] `main.py` refactored into modular route files (no file > 1,000 lines)
- [ ] CI/CD pipeline running tests, lint, and security scan on every PR
- [ ] Production deployment guide with TLS and reverse proxy
- [ ] Health check endpoints (`/health`, `/ready`) with dependency verification
- [ ] `CHANGELOG.md` with semantic versioning
- [ ] All 633+ existing tests passing

### Should-Have 🟡

- [ ] OAuth2/OIDC integration documented or implemented
- [ ] Kubernetes Helm chart published
- [ ] OpenTelemetry tracing for LLM and DB calls
- [ ] Load testing results published (target: 100 tickets/sec enrichment)
- [ ] Docker image published to GitHub Container Registry
- [ ] `CONTRIBUTING.md` with development setup

### Nice-to-Have 🟢

- [ ] Sentry error tracking integration
- [ ] Performance benchmarks published
- [ ] Prometheus alerting rule examples
- [ ] GraphQL API layer

---

*This roadmap is a living document. Priorities may shift based on community
feedback and contributor availability. See
[COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md) for the full competitor
research that informed this plan.*
