# Contributing to TicketForge

Thank you for your interest in contributing to TicketForge! This guide will help
you get started.

## Prerequisites

| Tool | Version | Required |
|------|---------|----------|
| Python | 3.11+ | Yes |
| Docker & Docker Compose | Latest | Optional — for containerised runs |
| Git | 2.x+ | Yes |

## Getting Started

### 1. Fork and clone

```bash
# Fork via the GitHub UI, then:
git clone https://github.com/<your-username>/TicketForge.git
cd TicketForge
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Linux / macOS
# .venv\Scripts\activate    # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example environment file (if present) or export the required variables
described in `config.py`:

```bash
cp .env.example .env   # then edit .env as needed
```

### 5. Run the application locally

```bash
uvicorn main:app --reload
```

The API will be available at `http://127.0.0.1:8000`. Interactive documentation
is served at `/docs` (Swagger UI) and `/redoc` (ReDoc).

### 6. Run the tests

```bash
python -m pytest tests/ -v
```

## Project Structure

```
TicketForge/
├── main.py                 # FastAPI application entry point
├── config.py               # Configuration and environment handling
├── models.py               # Pydantic data models
├── ticket_processor.py     # Core ticket analysis logic
├── llm_provider.py         # LLM provider abstraction
├── vector_store.py         # Semantic search / vector embeddings
├── multi_agent.py          # Multi-agent pipeline orchestration
├── chatbot.py              # Conversational chatbot interface
├── email_ingestion.py      # Inbound email webhook handler
├── notifications.py        # Slack / Teams notification module
├── webhook_events.py       # Outbound webhook events
├── automation_detector.py  # ML-based automation detection
├── monitoring.py           # Model drift monitoring
├── plugin_system.py        # Plugin architecture
├── prompts.py              # LLM prompt templates
├── audit.py                # Audit logging
├── connectors/             # External system integrations
│   ├── jira.py
│   ├── servicenow.py
│   ├── zendesk.py
│   ├── pagerduty.py
│   └── opsgenie.py
├── tests/                  # Test suite
├── docs/                   # Additional documentation
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and
formatting. Please ensure your changes pass before opening a pull request:

```bash
# Lint
ruff check .

# Auto-format
ruff format .
```

Key conventions:

- **British English** spelling in user-facing strings and documentation
  (e.g. *categorisation*, *authorisation*, *colour*).
- Type hints on all public function signatures.
- Docstrings on modules, classes and public functions.

## How to Contribute

### Reporting Issues

1. Search [existing issues](https://github.com/TicketForge/TicketForge/issues)
   to avoid duplicates.
2. Open a new issue using the appropriate template (bug report or feature
   request).
3. Include steps to reproduce, expected behaviour and actual behaviour for bugs.

### Submitting Changes

1. **Fork** the repository and create a feature branch from `main`:

   ```bash
   git checkout -b feat/my-feature
   ```

2. **Make your changes** — keep commits small and focused.

3. **Write or update tests** for any new or changed behaviour.

4. **Run the full test suite** to verify nothing is broken:

   ```bash
   python -m pytest tests/ -v
   ```

5. **Lint your code**:

   ```bash
   ruff check .
   ```

6. **Push** your branch and open a pull request against `main`.

### Pull Request Guidelines

- Reference the related issue number in the PR description (e.g. `Closes #42`).
- Keep PRs focused on a single concern; split unrelated changes into separate
  PRs.
- Ensure CI checks pass before requesting review.
- Be responsive to review feedback.

## Commit Message Conventions

This project follows
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <short summary>

[optional body]

[optional footer(s)]
```

**Types:**

| Type | Purpose |
|------|---------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation-only changes |
| `style` | Formatting; no logic change |
| `refactor` | Code restructuring without behaviour change |
| `test` | Adding or updating tests |
| `chore` | Build, CI or tooling changes |
| `perf` | Performance improvements |

**Examples:**

```
feat(chatbot): add multi-turn conversation memory
fix(routing): correct skill-weight calculation for new agents
docs: update CHANGELOG for v0.11.0
```

## Code of Conduct

Please be respectful and constructive in all interactions. We are committed to
providing a welcoming and inclusive environment for everyone.

## Questions?

If you have questions that are not covered here, feel free to open a
[Discussion](https://github.com/TicketForge/TicketForge/discussions) or reach
out via an issue.
