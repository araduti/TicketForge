"""
TicketForge — Gunicorn configuration for production deployment (C5)

Run with:
    gunicorn main:app -c gunicorn.conf.py

Or override individual settings:
    gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
"""
import multiprocessing
import os

# ── Bind ──────────────────────────────────────────────────────────────────────
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# ── Workers ───────────────────────────────────────────────────────────────────
# Use 2× CPU cores + 1 as a baseline, capped at 8 for typical deployments.
workers = int(os.getenv("GUNICORN_WORKERS", min(2 * multiprocessing.cpu_count() + 1, 8)))
worker_class = "uvicorn.workers.UvicornWorker"

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", 30))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", 5))

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")  # stdout
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")     # stderr
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# ── Process naming ────────────────────────────────────────────────────────────
proc_name = "ticketforge"

# ── Security ──────────────────────────────────────────────────────────────────
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

# ── Pre-fork hooks ────────────────────────────────────────────────────────────
def on_starting(server):
    """Called just before the master process is initialised."""
    server.log.info("TicketForge starting with %d workers", server.app.cfg.workers)


def post_worker_init(worker):
    """Called just after a worker has been initialised."""
    worker.log.info("Worker %s initialised (pid: %s)", worker.age, worker.pid)
