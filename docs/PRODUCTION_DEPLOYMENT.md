# Production Deployment Guide

This guide covers deploying TicketForge in a production environment with TLS termination, process management, and recommended security practices.

## Architecture Overview

```
                    ┌───────────────────┐
   HTTPS (443)      │   Reverse Proxy   │
  ─────────────────►│  (nginx / Caddy)  │
                    │   TLS termination  │
                    └────────┬──────────┘
                             │ HTTP (8000)
                    ┌────────▼──────────┐
                    │  Gunicorn + Uvicorn│
                    │  (process manager) │
                    └────────┬──────────┘
                             │
                    ┌────────▼──────────┐
                    │   TicketForge App  │
                    │   (FastAPI)        │
                    └────────┬──────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         ┌────▼───┐    ┌────▼───┐    ┌────▼───┐
         │ SQLite │    │ Ollama │    │ Vector │
         │  / PG  │    │  LLM   │    │ Store  │
         └────────┘    └────────┘    └────────┘
```

## 1. Reverse Proxy with TLS

### Option A: Caddy (recommended — automatic HTTPS)

Install Caddy and create `/etc/caddy/Caddyfile`:

```caddyfile
ticketforge.example.com {
    reverse_proxy localhost:8000

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
    }

    log {
        output file /var/log/caddy/ticketforge.log
    }
}
```

Start Caddy:
```bash
sudo systemctl enable --now caddy
```

Caddy automatically provisions and renews Let's Encrypt TLS certificates.

### Option B: nginx

Install nginx and create `/etc/nginx/sites-available/ticketforge`:

```nginx
server {
    listen 80;
    server_name ticketforge.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ticketforge.example.com;

    ssl_certificate /etc/letsencrypt/live/ticketforge.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ticketforge.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Obtain a certificate with certbot:
```bash
sudo certbot --nginx -d ticketforge.example.com
```

Enable and start:
```bash
sudo ln -s /etc/nginx/sites-available/ticketforge /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 2. Multi-Worker Process Management

Use Gunicorn as a process manager with Uvicorn workers for production:

```bash
pip install gunicorn
```

Run with multiple workers:

```bash
gunicorn main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --access-logfile /var/log/ticketforge/access.log \
    --error-logfile /var/log/ticketforge/error.log
```

**Worker count guideline**: `(2 × CPU cores) + 1`

### Systemd Service

Create `/etc/systemd/system/ticketforge.service`:

```ini
[Unit]
Description=TicketForge API
After=network.target

[Service]
User=ticketforge
Group=ticketforge
WorkingDirectory=/opt/ticketforge
EnvironmentFile=/opt/ticketforge/.env
ExecStart=/opt/ticketforge/.venv/bin/gunicorn main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:8000 \
    --timeout 120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ticketforge
```

## 3. Environment Configuration

Create `/opt/ticketforge/.env`:

```env
# API security
API_KEYS=<generate-with-python-c-'import secrets; print(secrets.token_urlsafe(32))'>
API_KEY_ROLES={"your-key-here": "admin"}

# CORS
CORS_ALLOWED_ORIGINS=https://ticketforge.example.com

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/ticketforge.db
# Or for PostgreSQL:
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/ticketforge

# LLM
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

# Application
ENVIRONMENT=production
LOG_LEVEL=INFO
HOST=127.0.0.1
PORT=8000
```

## 4. Health Checks

TicketForge provides two health check endpoints:

| Endpoint | Purpose | Use Case |
|----------|---------|----------|
| `GET /health` | Liveness probe | Kubernetes `livenessProbe`, load balancer health |
| `GET /ready` | Readiness probe | Kubernetes `readinessProbe`, deployment rollout |

The `/ready` endpoint returns HTTP 503 if any dependency (database, vector store, processor) is not available, making it safe for orchestrators to use for traffic routing decisions.

## 5. Docker Production Deployment

For containerised deployments:

```bash
docker build -t ticketforge:latest .

docker run -d \
    --name ticketforge \
    --restart unless-stopped \
    -p 127.0.0.1:8000:8000 \
    --env-file /opt/ticketforge/.env \
    -v ticketforge-data:/app/data \
    ticketforge:latest
```

## 6. Security Checklist

Before exposing to the internet:

- [ ] Replace default API keys (`changeme`) with strong random keys
- [ ] Configure `CORS_ALLOWED_ORIGINS` to your specific domain(s)
- [ ] Enable TLS via reverse proxy (Caddy or nginx)
- [ ] Bind the application to `127.0.0.1` (not `0.0.0.0`) when behind a reverse proxy
- [ ] Set `ENVIRONMENT=production`
- [ ] Review and rotate API keys regularly via `POST /api-keys/rotate`
- [ ] Monitor `/health` and `/ready` endpoints
- [ ] Set up log aggregation for structured JSON logs
