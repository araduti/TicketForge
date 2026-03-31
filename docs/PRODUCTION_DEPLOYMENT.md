# TicketForge — Production Deployment Guide

> **Audience:** Platform / DevOps engineers deploying TicketForge to a
> production environment.
>
> This guide covers a single-server deployment behind a TLS-terminating reverse
> proxy. For Kubernetes / Helm deployments, see the Kubernetes manifests in the
> repository root.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Configuration](#2-environment-configuration)
3. [Reverse Proxy with TLS](#3-reverse-proxy-with-tls)
4. [Running with Gunicorn + Uvicorn Workers](#4-running-with-gunicorn--uvicorn-workers)
5. [Systemd Service](#5-systemd-service)
6. [Docker Compose — Production Setup](#6-docker-compose--production-setup)
7. [PostgreSQL Setup](#7-postgresql-setup)
8. [Database Migrations with Alembic](#8-database-migrations-with-alembic)
9. [Security Checklist](#9-security-checklist)
10. [Monitoring — Prometheus + Grafana](#10-monitoring--prometheus--grafana)
11. [Log Management](#11-log-management)
12. [Health-Check Verification](#12-health-check-verification)
13. [Scaling Considerations](#13-scaling-considerations)

---

## 1. Prerequisites

| Requirement | Minimum | Recommended |
|---|---|---|
| **OS** | Ubuntu 22.04 LTS / Debian 12 | Ubuntu 24.04 LTS |
| **Python** | 3.11 | 3.11+ (via `deadsnakes` PPA or pyenv) |
| **RAM** | 4 GB | 8 GB+ (LLM model loaded in memory) |
| **CPU** | 2 vCPUs | 4+ vCPUs |
| **Disk** | 20 GB | 40 GB+ (logs, model weights, database) |
| **Reverse proxy** | nginx 1.18+ **or** Caddy 2.x | Latest stable |
| **Database** | SQLite (single-node only) | PostgreSQL 15+ |
| **GPU (optional)** | — | NVIDIA GPU + Container Toolkit for faster LLM inference |

Install core system packages:

```bash
sudo apt update && sudo apt install -y \
  python3.11 python3.11-venv python3-pip \
  build-essential curl git \
  nginx          # or: sudo apt install caddy
```

Create a dedicated service user:

```bash
sudo useradd -r -m -s /usr/sbin/nologin ticketforge
```

---

## 2. Environment Configuration

TicketForge reads its configuration from environment variables or a `.env` file
located alongside `main.py`. **Never commit `.env` to version control.**

```bash
sudo mkdir -p /opt/ticketforge
sudo cp -r . /opt/ticketforge/
sudo chown -R ticketforge:ticketforge /opt/ticketforge
cd /opt/ticketforge
sudo -u ticketforge python3.11 -m venv venv
sudo -u ticketforge venv/bin/pip install -r requirements.txt
```

Create `/opt/ticketforge/.env`:

```dotenv
# ─── Security ────────────────────────────────────────────────────────────────
API_KEYS=replace-with-strong-random-key-1,replace-with-strong-random-key-2
API_KEY_ROLES={"replace-with-strong-random-key-1":"admin","replace-with-strong-random-key-2":"analyst"}
RATE_LIMIT_PER_MINUTE=120

# ─── LLM Provider ───────────────────────────────────────────────────────────
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_TIMEOUT=120
OLLAMA_MAX_RETRIES=3

# Uncomment below for OpenAI-compatible provider instead of Ollama:
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-…
# OPENAI_BASE_URL=https://api.openai.com
# OPENAI_MODEL=gpt-4o-mini

# ─── Database (PostgreSQL for production) ────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://ticketforge:STRONG_PASSWORD@127.0.0.1:5432/ticketforge
DB_TICKET_TTL_HOURS=720

# ─── Embeddings ──────────────────────────────────────────────────────────────
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# ─── Notifications ──────────────────────────────────────────────────────────
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/…
# TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/…
NOTIFICATION_MIN_PRIORITY=high
NOTIFY_ON_SLA_BREACH=true

# ─── Outbound Webhooks ──────────────────────────────────────────────────────
# OUTBOUND_WEBHOOK_URL=https://your-service.example.com/hook
# OUTBOUND_WEBHOOK_SECRET=replace-with-hmac-secret

# ─── Connector Credentials (uncomment as needed) ────────────────────────────
# SERVICENOW_INSTANCE=dev12345.service-now.com
# SERVICENOW_USERNAME=api_user
# SERVICENOW_PASSWORD=…
# JIRA_BASE_URL=https://yourorg.atlassian.net
# JIRA_USER_EMAIL=bot@yourorg.com
# JIRA_API_TOKEN=…
# ZENDESK_SUBDOMAIN=yourorg
# ZENDESK_USER_EMAIL=bot@yourorg.com
# ZENDESK_API_TOKEN=…

# ─── Feature Flags ──────────────────────────────────────────────────────────
CHATBOT_ENABLED=true
PORTAL_ENABLED=true
MONITORING_ENABLED=true
EMAIL_INGESTION_ENABLED=false
CSAT_ENABLED=true
WEBSOCKET_NOTIFICATIONS_ENABLED=true
I18N_ENABLED=true

# ─── Observability ──────────────────────────────────────────────────────────
LOG_LEVEL=INFO
```

Lock down the file permissions:

```bash
sudo chmod 600 /opt/ticketforge/.env
sudo chown ticketforge:ticketforge /opt/ticketforge/.env
```

---

## 3. Reverse Proxy with TLS

Both examples assume the domain `ticketforge.example.com` resolves to
your server's public IP.

### 3a. nginx + Let's Encrypt (certbot)

Install certbot and obtain a certificate:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d ticketforge.example.com
```

Create `/etc/nginx/sites-available/ticketforge`:

```nginx
upstream ticketforge_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name ticketforge.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ticketforge.example.com;

    ssl_certificate     /etc/letsencrypt/live/ticketforge.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ticketforge.example.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security headers
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Content-Type-Options    "nosniff" always;
    add_header X-Frame-Options           "DENY" always;
    add_header Referrer-Policy           "strict-origin-when-cross-origin" always;

    client_max_body_size 10M;

    # REST / OpenAPI
    location / {
        proxy_pass         http://ticketforge_backend;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    # WebSocket notifications
    location /ws/ {
        proxy_pass         http://ticketforge_backend;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       $host;
        proxy_read_timeout 86400s;
    }
}
```

Enable the site and reload:

```bash
sudo ln -sf /etc/nginx/sites-available/ticketforge /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Certbot sets up auto-renewal via a systemd timer. Verify with:

```bash
sudo certbot renew --dry-run
```

### 3b. Caddy (automatic TLS)

Caddy obtains and renews TLS certificates automatically from Let's Encrypt.

Create `/etc/caddy/Caddyfile`:

```caddyfile
ticketforge.example.com {
    reverse_proxy localhost:8000

    # WebSocket support
    @websocket {
        header Connection *Upgrade*
        header Upgrade    websocket
    }
    reverse_proxy @websocket localhost:8000

    # Security headers
    header {
        Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
        X-Content-Type-Options    "nosniff"
        X-Frame-Options           "DENY"
        Referrer-Policy           "strict-origin-when-cross-origin"
    }

    log {
        output file /var/log/caddy/ticketforge.log
        format json
    }
}
```

Reload Caddy:

```bash
sudo systemctl reload caddy
```

---

## 4. Running with Gunicorn + Uvicorn Workers

For production workloads, run TicketForge behind **Gunicorn** using
**UvicornWorker** classes. This gives you multi-process concurrency with
async I/O in each worker.

Install Gunicorn (if not already in your virtualenv):

```bash
sudo -u ticketforge /opt/ticketforge/venv/bin/pip install gunicorn
```

Start the application:

```bash
sudo -u ticketforge /opt/ticketforge/venv/bin/gunicorn main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -
```

| Flag | Purpose |
|---|---|
| `-w 4` | Number of worker processes — a good default is `(2 × CPU cores) + 1`. |
| `-k uvicorn.workers.UvicornWorker` | Each worker uses Uvicorn's async event loop. |
| `--bind 0.0.0.0:8000` | Bind to all interfaces on port 8000. |
| `--timeout 120` | Kill a worker if it hasn't responded in 120 s (covers slow LLM calls). |
| `--graceful-timeout 30` | Allow in-flight requests 30 s to finish during reload. |

> **Tip:** Set `--workers` equal to the number of CPU cores available if the
> server also hosts Ollama (which is CPU/GPU-intensive).

---

## 5. Systemd Service

Create `/etc/systemd/system/ticketforge.service`:

```ini
[Unit]
Description=TicketForge AI Ticket Enrichment API
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=notify
User=ticketforge
Group=ticketforge
WorkingDirectory=/opt/ticketforge
EnvironmentFile=/opt/ticketforge/.env
ExecStart=/opt/ticketforge/venv/bin/gunicorn main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ticketforge

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/ticketforge

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ticketforge
sudo systemctl status ticketforge
sudo journalctl -u ticketforge -f   # follow logs
```

---

## 6. Docker Compose — Production Setup

The following `docker-compose.prod.yml` extends the development file with
production-grade settings: PostgreSQL, TLS termination via nginx, persistent
volumes, and resource limits.

```yaml
version: "3.9"

services:
  # ── Reverse Proxy ────────────────────────────────────────────────────────
  nginx:
    image: nginx:1.27-alpine
    container_name: ticketforge_nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/ticketforge.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      app:
        condition: service_healthy
    restart: unless-stopped

  # ── TicketForge API ──────────────────────────────────────────────────────
  app:
    build: .
    container_name: ticketforge_app
    env_file: .env
    environment:
      DATABASE_URL: "postgresql+asyncpg://ticketforge:${POSTGRES_PASSWORD}@postgres:5432/ticketforge"
      OLLAMA_BASE_URL: "http://ollama:11434"
    expose:
      - "8000"
    depends_on:
      postgres:
        condition: service_healthy
      ollama:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    volumes:
      - app_data:/app/data
    deploy:
      resources:
        limits:
          cpus: "4"
          memory: 4G
    restart: unless-stopped

  # ── PostgreSQL ───────────────────────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    container_name: ticketforge_postgres
    environment:
      POSTGRES_USER: ticketforge
      POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"
      POSTGRES_DB: ticketforge
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ticketforge"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: 2G
    restart: unless-stopped

  # ── Ollama LLM ──────────────────────────────────────────────────────────
  ollama:
    image: ollama/ollama:latest
    container_name: ticketforge_ollama
    volumes:
      - ollama_data:/root/.ollama
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 5
    deploy:
      resources:
        limits:
          cpus: "4"
          memory: 8G
        # Uncomment for NVIDIA GPU acceleration:
        # reservations:
        #   devices:
        #     - driver: nvidia
        #       count: 1
        #       capabilities: [gpu]
    restart: unless-stopped

volumes:
  app_data:
  pg_data:
  ollama_data:
```

Start the production stack:

```bash
export POSTGRES_PASSWORD="$(openssl rand -base64 32)"
docker compose -f docker-compose.prod.yml up -d
docker compose exec ollama ollama pull llama3.1:8b
curl -k https://localhost/health
```

---

## 7. PostgreSQL Setup

SQLite is acceptable for development and single-user demos. **Use PostgreSQL
for any production deployment** — it provides concurrent writes, proper
transaction isolation, point-in-time recovery, and connection pooling.

### 7a. Install PostgreSQL

```bash
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

### 7b. Create the database and role

```bash
sudo -u postgres psql <<SQL
CREATE ROLE ticketforge WITH LOGIN PASSWORD 'STRONG_PASSWORD';
CREATE DATABASE ticketforge OWNER ticketforge;
GRANT ALL PRIVILEGES ON DATABASE ticketforge TO ticketforge;
SQL
```

### 7c. Configure connection in `.env`

```dotenv
DATABASE_URL=postgresql+asyncpg://ticketforge:STRONG_PASSWORD@127.0.0.1:5432/ticketforge
```

### 7d. Tune `postgresql.conf`

Key settings for a 4-core / 8 GB RAM server:

```
shared_buffers = 2GB
effective_cache_size = 6GB
work_mem = 64MB
maintenance_work_mem = 512MB
max_connections = 100
wal_level = replica          # required for PITR / streaming replication
archive_mode = on
archive_command = 'cp %p /var/lib/postgresql/wal_archive/%f'
```

Restart PostgreSQL after changes:

```bash
sudo systemctl restart postgresql
```

---

## 8. Database Migrations with Alembic

TicketForge uses **Alembic** for schema version control.

### 8a. Initialise Alembic (first time)

```bash
cd /opt/ticketforge
sudo -u ticketforge venv/bin/alembic init alembic
```

Edit `alembic.ini` to point at your production database:

```ini
sqlalchemy.url = postgresql+asyncpg://ticketforge:STRONG_PASSWORD@127.0.0.1:5432/ticketforge
```

### 8b. Generate and apply migrations

```bash
# Auto-generate a migration from model changes
sudo -u ticketforge venv/bin/alembic revision --autogenerate -m "describe the change"

# Apply all pending migrations
sudo -u ticketforge venv/bin/alembic upgrade head

# Rollback one revision
sudo -u ticketforge venv/bin/alembic downgrade -1
```

### 8c. Run migrations before every release

Add this to your deployment script or CI/CD pipeline:

```bash
sudo -u ticketforge /opt/ticketforge/venv/bin/alembic upgrade head
sudo systemctl restart ticketforge
```

---

## 9. Security Checklist

Complete every item before exposing TicketForge to the internet.

| # | Item | How to verify |
|---|------|---------------|
| 1 | **Replace default API keys** — generate cryptographically random keys (`openssl rand -hex 32`). | `grep API_KEYS .env` contains no `changeme`. |
| 2 | **API key hashing** — ensure keys are stored as bcrypt hashes (managed via `passlib`). Never log raw keys. | Check application logs for absence of raw keys. |
| 3 | **Enforce HTTPS** — the reverse proxy must redirect all HTTP → HTTPS (see §3). | `curl -I http://ticketforge.example.com` returns `301`. |
| 4 | **CORS policy** — restrict `Access-Control-Allow-Origin` to known front-end origins; avoid `*`. | Inspect response headers with `curl -I`. |
| 5 | **Content-Security-Policy (CSP)** — add CSP headers via the reverse proxy or FastAPI middleware. | Browser DevTools → Console for CSP violations. |
| 6 | **Input sanitisation** — TicketForge sanitises ticket descriptions before LLM calls to prevent prompt injection. | Review `ticket_processor.py` sanitisation logic. |
| 7 | **Rate limiting** — confirm `RATE_LIMIT_PER_MINUTE` is set appropriately for your traffic. | `GET /docs` shows `429` responses in endpoint docs. |
| 8 | **Database credentials** — use a strong password; restrict PostgreSQL `pg_hba.conf` to `127.0.0.1/32`. | `psql -h 127.0.0.1 -U ticketforge` succeeds; remote access fails. |
| 9 | **File permissions** — `.env` must be `600` and owned by the service user. | `ls -la /opt/ticketforge/.env`. |
| 10 | **Firewall** — allow only 80, 443, and 22 (SSH). Block direct access to 8000, 5432, and 11434. | `sudo ufw status`. |
| 11 | **Disable debug mode** — ensure `LOG_LEVEL` is `INFO` or `WARNING` (not `DEBUG`) in production. | `grep LOG_LEVEL .env`. |
| 12 | **Keep dependencies updated** — run `pip audit` and `pip install --upgrade` regularly. | `pip audit` reports no known vulnerabilities. |

---

## 10. Monitoring — Prometheus + Grafana

TicketForge exposes Prometheus metrics via
`prometheus-fastapi-instrumentator` at the `/metrics` endpoint.

### 10a. Prometheus scrape configuration

Add to `/etc/prometheus/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "ticketforge"
    scrape_interval: 15s
    static_configs:
      - targets: ["127.0.0.1:8000"]
    metrics_path: /metrics
```

### 10b. Key metrics to monitor

| Metric | Description |
|---|---|
| `http_requests_total` | Total request count by method, path, and status. |
| `http_request_duration_seconds` | Request latency histogram. |
| `http_requests_in_progress` | Current in-flight requests. |
| Custom: `processed_tickets` table | Query drift metrics via `GET /monitoring/drift`. |

### 10c. Grafana dashboards

1. Install Grafana: `sudo apt install -y grafana && sudo systemctl enable --now grafana-server`
2. Add Prometheus as a data source at `http://localhost:9090`.
3. Import or create dashboards for:
   - **Request rate & latency** — `http_request_duration_seconds` histogram.
   - **Error rate** — `http_requests_total{status=~"5.."}`.
   - **Worker utilisation** — `http_requests_in_progress`.
   - **Model drift** — poll `GET /monitoring/drift` and visualise
     `drift_score` per field.

### 10d. Alerting rules

Create `/etc/prometheus/rules/ticketforge.yml`:

```yaml
groups:
  - name: ticketforge
    rules:
      - alert: HighErrorRate
        expr: |
          rate(http_requests_total{job="ticketforge",status=~"5.."}[5m])
          / rate(http_requests_total{job="ticketforge"}[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "TicketForge error rate above 5 %"

      - alert: HighLatency
        expr: |
          histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="ticketforge"}[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "TicketForge p95 latency above 5 s"

      - alert: HealthCheckFailing
        expr: up{job="ticketforge"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "TicketForge health check is failing"
```

---

## 11. Log Management

TicketForge uses **structlog** to emit structured JSON log lines to stdout,
making them straightforward to ingest into any centralised logging platform.

### 11a. JSON log output

With `LOG_LEVEL=INFO`, every log entry is a JSON object:

```json
{
  "event": "ticket_analysed",
  "ticket_id": "INC0012345",
  "category": "network",
  "priority": "high",
  "duration_ms": 342,
  "timestamp": "2026-04-10T14:23:01Z",
  "level": "info",
  "request_id": "a1b2c3d4"
}
```

### 11b. Forwarding to ELK (Elasticsearch + Logstash + Kibana)

Use **Filebeat** or **Fluentd** to ship journald / Docker logs:

```yaml
# /etc/filebeat/filebeat.yml (excerpt)
filebeat.inputs:
  - type: journald
    id: ticketforge
    include_matches:
      - _SYSTEMD_UNIT=ticketforge.service

output.elasticsearch:
  hosts: ["https://elasticsearch.example.com:9200"]
  index: "ticketforge-%{+yyyy.MM.dd}"
```

### 11c. Forwarding to Grafana Loki

Use **Promtail** to scrape journal logs:

```yaml
# /etc/promtail/config.yml (excerpt)
scrape_configs:
  - job_name: ticketforge
    journal:
      labels:
        job: ticketforge
      matches: _SYSTEMD_UNIT=ticketforge.service
    relabel_configs:
      - source_labels: ["__journal__systemd_unit"]
        target_label: unit
```

### 11d. Docker log driver

When running in Docker, configure the JSON-file or Loki log driver in
`docker-compose.prod.yml`:

```yaml
services:
  app:
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"
```

---

## 12. Health-Check Verification

TicketForge exposes a `GET /health` endpoint that returns:

```json
{
  "status": "healthy",
  "ollama": "ok",
  "database": "ok"
}
```

### Automated checks

```bash
# Quick smoke test
curl -sf https://ticketforge.example.com/health | python3 -m json.tool

# Nagios / Icinga-compatible check
curl -sf -o /dev/null -w "%{http_code}" https://ticketforge.example.com/health
# Expected: 200
```

Use the Prometheus `up` metric or Docker / systemd health checks to trigger
alerts when the endpoint becomes unreachable (see §10d).

---

## 13. Scaling Considerations

### 13a. Vertical scaling

- Increase Gunicorn workers: `-w $(( 2 * $(nproc) + 1 ))`.
- Add RAM for larger LLM models (e.g. `llama3.1:70b-q4` requires ~40 GB).
- Attach an NVIDIA GPU and uncomment the GPU reservation in Docker Compose
  for significantly faster inference.

### 13b. Horizontal scaling with a load balancer

```
                 ┌──────────────┐
  Internet ───►  │  nginx / LB  │
                 └──┬───┬───┬───┘
                    │   │   │
              ┌─────┘   │   └─────┐
              ▼         ▼         ▼
        ┌──────┐  ┌──────┐  ┌──────┐
        │ App1 │  │ App2 │  │ App3 │
        └──┬───┘  └──┬───┘  └──┬───┘
           │         │         │
           └─────────┼─────────┘
                     ▼
              ┌─────────────┐
              │ PostgreSQL  │
              │  (shared)   │
              └─────────────┘
```

Key requirements for horizontal scaling:

| Concern | Solution |
|---|---|
| **Shared database** | All app instances must connect to the same PostgreSQL server (or cluster). SQLite cannot be shared. |
| **Session / state** | TicketForge is stateless per request — no sticky sessions required. |
| **Ollama** | Run Ollama on a dedicated GPU node and point all app instances at it via `OLLAMA_BASE_URL`. |
| **WebSockets** | Use a Redis pub/sub adapter or sticky sessions for persistent WebSocket connections. |
| **Load balancer** | nginx `upstream` with `least_conn`, or a cloud LB (AWS ALB, GCP LB). |
| **Health checks** | Configure the LB to probe `GET /health` and remove unhealthy instances automatically. |

### 13c. Read replicas

For read-heavy analytics workloads, configure PostgreSQL streaming
replication and point read-only endpoints (e.g. `GET /analytics`,
`GET /export/tickets`) at the replica using a secondary `DATABASE_URL`.

---

*Last updated: July 2025*
