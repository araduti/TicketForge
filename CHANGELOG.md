# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — v1.0.0

### Added

- Security hardening: API key hashing, input sanitisation, request IDs, CORS
  and CSP headers
- API versioning under `/v1/` prefix
- OpenAPI documentation at `/docs` and `/redoc`
- Standardised error response format with consistent status codes
- Alembic database migrations for schema management
- Modular code architecture (`main.py` split into dedicated route modules)
- CI/CD pipeline via GitHub Actions (lint, test, build)
- Production deployment guide with TLS termination
- Kubernetes manifests and Helm chart for orchestrated deployments
- Health-check endpoints (`/health`, `/ready`)
- Multi-worker Gunicorn configuration for production workloads
- OpenTelemetry distributed tracing
- Prometheus alerting rules
- Sentry error-tracking integration
- Load-testing suite using Locust
- GraphQL API layer
- OAuth2/OIDC authentication documentation
- Edge-case and negative-path test coverage
- Performance benchmarks
- Database backup and restore documentation

## [0.11.0] — 2025-06-01

### Added

- Troubleshooting flows: guided, step-by-step diagnostic trees for common issue
  categories
- Intent and entity extraction from ticket descriptions using NLP
- Resolution prediction model to estimate likelihood of first-contact resolution
- Satisfaction prediction model to forecast CSAT score before survey completion
- Smart assignment: skill-weighted, workload-aware ticket routing to the best
  available agent

## [0.10.2] — 2025-05-15

### Added

- Visual workflow builder for designing automation rules graphically
- Compliance and PII detection module with automatic redaction
- Response caching layer for frequently accessed endpoints
- UX and onboarding improvements: guided setup wizard and contextual tooltips

## [0.10.1] — 2025-05-01

### Added

- Custom classifier training from labelled ticket data
- Anomaly detection for ticket volume and resolution-time spikes
- Knowledge-base article auto-generation from resolved tickets

## [0.10.0] — 2025-04-15

### Added

- Team dashboards with per-queue and per-agent performance metrics
- SLA breach prediction using historical trend analysis
- Ticket volume forecasting to support capacity planning

## [0.9.0] — 2025-04-01

### Added

- Automation rules engine: trigger-condition-action framework for ticket
  workflows
- Approval workflows for sensitive ticket actions
- Agent collision detection to prevent concurrent edits on the same ticket
- Contacts management module linked to ticket history
- Macros for one-click bulk application of common ticket updates

## [0.8.0] — 2025-03-15

### Added

- SLA breach prediction with proactive alerting
- Response templates library with variable interpolation
- Ticket timeline view showing full activity and communication history
- Bulk operations for batch status, priority and assignment changes
- Skill-based routing: match tickets to agents by expertise and availability

## [0.7.0] — 2025-03-01

### Added

- Scheduled reports: configurable daily, weekly and monthly summaries delivered
  via email and Slack
- Ticket merging to consolidate duplicate or related tickets
- Custom fields on tickets for organisation-specific metadata
- Tagging system with auto-suggested and manual tags
- Saved filters for reusable, shareable ticket views

## [0.6.0] — 2025-02-15

### Added

- Auto-resolution for tickets matching high-confidence known solutions
- Outbound webhooks to push ticket lifecycle events to external systems
- PagerDuty integration for critical-ticket escalation
- OpsGenie integration for on-call alert routing

## [0.5.0] — 2025-02-01

### Added

- Multi-agent pipeline: Analyser → Classifier → Validator orchestration
- Persistent vector store backed by sentence-transformers for semantic search

## [0.4.0] — 2025-01-15

### Added

- CSAT survey dispatch and collection after ticket resolution
- WebSocket-based real-time notifications for ticket updates and assignments

## [0.3.0] — 2025-01-01

### Added

- Conversational chatbot interface for end-user self-service
- Internationalisation (i18n) support for 27 languages
- Self-service portal for ticket submission and status tracking
- Model drift monitoring with automatic retraining triggers
- Plugin system for extending functionality via third-party add-ons

## [0.2.0] — 2024-12-15

### Added

- Knowledge-base module for article storage and retrieval
- PostgreSQL support via asyncpg for production-grade persistence
- Email ingestion webhook for automatic ticket creation from inbound email
- LLM-powered response suggestions for agents
- Duplicate ticket detection using semantic similarity

## [0.1.0] — 2024-12-01

### Added

- Sentiment analysis on ticket descriptions
- Cloud LLM provider integration (configurable backend)
- Analytics dashboard with categorisation and priority breakdowns
- Slack notifications for ticket events and escalations
- Ticket status tracking and lifecycle management

[Unreleased]: https://github.com/TicketForge/TicketForge/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/TicketForge/TicketForge/compare/v0.10.2...v0.11.0
[0.10.2]: https://github.com/TicketForge/TicketForge/compare/v0.10.1...v0.10.2
[0.10.1]: https://github.com/TicketForge/TicketForge/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/TicketForge/TicketForge/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/TicketForge/TicketForge/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/TicketForge/TicketForge/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/TicketForge/TicketForge/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/TicketForge/TicketForge/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/TicketForge/TicketForge/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/TicketForge/TicketForge/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/TicketForge/TicketForge/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/TicketForge/TicketForge/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/TicketForge/TicketForge/releases/tag/v0.1.0
