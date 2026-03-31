# Changelog

All notable changes to TicketForge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Security**: API keys are now hashed at rest using SHA-256 and compared via constant-time `hmac.compare_digest` (A1)
- **Security**: API key rotation endpoint `POST /api-keys/rotate` for generating new keys without restart (A2)
- **Security**: Input sanitisation middleware strips script tags and HTML-escapes string values in JSON request bodies (A3)
- **Security**: Request ID middleware assigns a UUID to every request, propagated via `X-Request-ID` header and structlog context (A4)
- **Security**: CORS middleware with configurable allowed origins via `CORS_ALLOWED_ORIGINS` env var (A5)
- **Security**: Content-Security-Policy, X-Content-Type-Options, X-Frame-Options, and Referrer-Policy headers on all responses (A7)
- **API**: Standardised error response format with `{"detail": ..., "error": {"code", "message", "request_id"}}` (B3)
- **API**: OpenAPI spec available at `/docs` (Swagger UI) and `/redoc` (ReDoc) (B2)
- **Ops**: Readiness probe endpoint `GET /ready` with dependency health checks (C3)
- **CI/CD**: GitHub Actions pipeline with linting (ruff), security scanning (bandit), and tests (B6)
- **Docs**: `CHANGELOG.md` with semantic versioning (B7)
- **Docs**: `CONTRIBUTING.md` with development setup instructions (B8)
- **Docs**: Production deployment guide in `docs/PRODUCTION_DEPLOYMENT.md` (C1)

## [0.1.0] — 2024-01-01

### Added
- Initial release with 126 API endpoints
- AI-powered ticket analysis, classification, and routing
- Knowledge base management
- SLA tracking and prediction
- Multi-connector support (ServiceNow, Jira, Zendesk)
- Role-based access control (admin/analyst/viewer)
- Prometheus metrics and structured logging
- Docker and Docker Compose support
