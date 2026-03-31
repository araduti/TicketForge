# Contributing to TicketForge

Thank you for your interest in contributing to TicketForge! This guide will help you get set up and productive quickly.

## Development Setup

### Prerequisites

- Python 3.11+
- Docker and Docker Compose (for running Ollama locally)

### Quick Start

1. **Clone the repository**
   ```bash
   git clone https://github.com/araduti/TicketForge.git
   cd TicketForge
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   # or .venv\Scripts\activate on Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   pip install pytest pytest-asyncio ruff bandit  # dev tools
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env  # if available, or create your own
   # At minimum, set:
   export API_KEYS="your-dev-key"
   export DATABASE_URL="sqlite+aiosqlite:///./ticketforge.db"
   ```

5. **Run the application**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

6. **Verify it works**
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc
   - Health check: http://localhost:8000/health
   - Readiness check: http://localhost:8000/ready

## Running Tests

```bash
python -m pytest tests/ -v
```

To run a specific test file:
```bash
python -m pytest tests/test_enterprise_features.py -v
```

## Code Quality

### Linting

We use [ruff](https://docs.astral.sh/ruff/) for linting:

```bash
ruff check .
ruff check --fix .  # auto-fix where possible
```

### Security Scanning

We use [bandit](https://bandit.readthedocs.io/) for security scanning:

```bash
bandit -r . -x ./tests --severity-level medium
```

## Project Structure

```
TicketForge/
├── main.py                 # FastAPI app, all 126+ endpoints
├── config.py               # Pydantic-based configuration
├── models.py               # Pydantic request/response models
├── ticket_processor.py     # Core ticket processing pipeline
├── llm_provider.py         # LLM abstraction (Ollama/OpenAI)
├── vector_store.py         # Vector similarity search
├── audit.py                # Audit logging
├── automation_detector.py  # Pattern detection
├── notifications.py        # Push notifications
├── prompts.py              # LLM prompt templates
├── connectors/             # External system connectors
│   ├── jira.py
│   ├── servicenow.py
│   ├── zendesk.py
│   ├── opsgenie.py
│   └── pagerduty.py
├── tests/                  # Test suites
├── docs/                   # Documentation
└── .github/workflows/      # CI/CD pipeline
```

## Coding Conventions

- **British English** spelling: categorisation, authorisation, analysed, etc.
- **Pydantic models** for all request/response schemas
- **structlog** for structured JSON logging
- **async/await** throughout — all endpoints and DB access are async
- **Type hints** on all function signatures
- **FastAPI dependencies** for authentication and authorisation

## Submitting Changes

1. Create a feature branch from `main`
2. Make your changes with clear commit messages
3. Ensure all tests pass: `python -m pytest tests/ -v`
4. Ensure linting passes: `ruff check .`
5. Open a pull request describing your changes

## Reporting Issues

Please use GitHub Issues with:
- A clear title and description
- Steps to reproduce (if applicable)
- Expected vs actual behaviour
- Environment details (Python version, OS, etc.)
