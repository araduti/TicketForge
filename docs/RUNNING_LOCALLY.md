# Running TicketForge Locally with Docker

This guide walks you through running TicketForge on your local machine using
**Docker Desktop**. Instructions are provided for **Windows (PowerShell)**,
**macOS**, and **Linux**.

---

## Prerequisites

| Requirement | Details |
|---|---|
| **Docker Desktop** | [Download for Windows / macOS](https://www.docker.com/products/docker-desktop/) — includes Docker Engine + Docker Compose v2. On Linux, install [Docker Engine](https://docs.docker.com/engine/install/) and the [Compose plugin](https://docs.docker.com/compose/install/linux/). |
| **RAM** | ~4 GB free for the Ollama LLM model (8B quantised). |
| **Disk** | ~6 GB for the Docker images + LLM model weights. |
| **GPU (optional)** | NVIDIA GPU with the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) for faster inference. |

> **Windows users**: Make sure Docker Desktop is running (system tray icon)
> before executing any `docker` commands.

---

## 1 · Clone the repository

### Windows (PowerShell)

```powershell
git clone https://github.com/araduti/TicketForge.git
cd TicketForge
```

### macOS / Linux

```bash
git clone https://github.com/araduti/TicketForge.git
cd TicketForge
```

---

## 2 · Create an environment file

The `.env` file stores your configuration. At minimum, set a secure API key.

### Windows (PowerShell)

```powershell
@"
API_KEYS=my-super-secret-key
OLLAMA_MODEL=llama3.1:8b
"@ | Out-File -Encoding utf8 .env
```

### macOS / Linux

```bash
cat > .env <<'EOF'
API_KEYS=my-super-secret-key
OLLAMA_MODEL=llama3.1:8b
EOF
```

> **Tip:** Replace `my-super-secret-key` with a strong random string, e.g.
> generated via `openssl rand -hex 32` (macOS/Linux) or
> `[System.Guid]::NewGuid().ToString("N")` (PowerShell).

---

## 3 · Start the stack

```
docker compose up -d
```

This command works the same on **all platforms** (Windows PowerShell, macOS
Terminal, Linux shell). It will:

1. Build the TicketForge FastAPI image (first run takes a few minutes).
2. Pull and start the Ollama LLM container.
3. Run both containers in the background (`-d`).

> **First build note:** The Docker image pre-downloads the
> `all-MiniLM-L6-v2` embedding model (~80 MB) so this step may take a few
> minutes the first time.

---

## 4 · Pull the LLM model (first run only)

The Ollama container needs a language model. Pull the default model (~4.5 GB
download):

```
docker compose exec ollama ollama pull llama3.1:8b
```

This is a one-time download. The model is persisted in a Docker volume
(`ollama_data`) and survives container restarts.

---

## 5 · Verify everything is running

### Windows (PowerShell)

```powershell
Invoke-RestMethod http://localhost:8000/health
```

### macOS / Linux

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "ok", "ollama_reachable": true, "db_ok": true, "version": "0.1.0"}
```

---

## 6 · Open the dashboard

Open your browser and navigate to:

```
http://localhost:8000/dashboard
```

This shows the built-in web dashboard with tickets, analytics charts, and SLA
overview.

You can also visit the **self-service portal** at:

```
http://localhost:8000/portal
```

---

## 7 · Try an API call

### Windows (PowerShell)

```powershell
$headers = @{
    "Content-Type" = "application/json"
    "X-Api-Key"    = "my-super-secret-key"
}
$body = @{
    ticket = @{
        id          = "INC0012345"
        source      = "servicenow"
        title       = "Cannot connect to VPN from home"
        description = "Since this morning I cannot connect to the corporate VPN. I get error code 800. Tried restarting the client."
        reporter    = "john.doe@example.com"
        tags        = @("vpn", "remote-work")
    }
    include_automation_detection = $true
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri http://localhost:8000/analyse `
    -Method POST -Headers $headers -Body $body
```

### macOS / Linux

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

---

## Common tasks

### View logs

```
docker compose logs -f app
```

### Restart the stack

```
docker compose restart
```

### Stop the stack

```
docker compose down
```

### Rebuild after code changes

```
docker compose up -d --build
```

### Remove all data (volumes)

```
docker compose down -v
```

---

## GPU acceleration (optional)

If you have an NVIDIA GPU and the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
installed, uncomment the GPU section in `docker-compose.yml`:

```yaml
ollama:
  # ...
  deploy:
    resources:
      reservations:
        devices:
          - capabilities: [gpu]
```

Then restart the stack:

```
docker compose down && docker compose up -d
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `docker compose` not found | Make sure Docker Desktop is installed and running. On older installs, try `docker-compose` (with hyphen). |
| Port 8000 already in use | Change the host port in `docker-compose.yml`: `"9000:8000"`, then access via `http://localhost:9000`. |
| Ollama health check failing | The LLM container can take 30-60 s to start. Wait and check with `docker compose ps`. |
| `ollama_reachable: false` in `/health` | Run `docker compose exec ollama ollama pull llama3.1:8b` to download the model. |
| Build fails on Windows | Ensure Docker Desktop uses **WSL 2** backend (Settings → General → Use WSL 2 based engine). |
| Slow first request | The embedding model loads on first use. Subsequent requests are faster. |
