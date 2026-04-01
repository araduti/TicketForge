# TicketForge — Database Backup & Restore Procedures

> **Audience:** Platform / DevOps engineers responsible for TicketForge data
> continuity.
>
> This guide covers backup and restore procedures for both **SQLite**
> (development / small deployments) and **PostgreSQL** (recommended for
> production). For initial database setup, see
> [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md).

---

## Table of Contents

1. [SQLite Backup](#1-sqlite-backup)
   - [File-based backup](#1a-file-based-backup)
   - [Online backup](#1b-online-backup-sqlite-backup-command)
   - [Automated backup with cron](#1c-automated-backup-with-cron)
   - [Restoration](#1d-restoration)
2. [PostgreSQL Backup](#2-postgresql-backup)
   - [Logical backup — pg_dump](#2a-logical-backup--pg_dump)
   - [Physical backup — pg_basebackup](#2b-physical-backup--pg_basebackup)
   - [Automated backup with cron](#2c-automated-backup-with-cron)
   - [Point-in-time recovery (PITR)](#2d-point-in-time-recovery-pitr)
   - [Restoration — logical](#2e-restoration--logical)
   - [Restoration — physical](#2f-restoration--physical)
3. [Backup Best Practices](#3-backup-best-practices)
   - [Retention policies](#3a-retention-policies)
   - [Off-site storage](#3b-off-site-storage-s3--gcs)
   - [Backup verification](#3c-backup-verification--testing)
   - [Monitoring backup success](#3d-monitoring-backup-success)
4. [Docker Volume Backup Considerations](#4-docker-volume-backup-considerations)

---

## 1. SQLite Backup

TicketForge stores its SQLite database at `./ticketforge.db` by default
(configurable via `DATABASE_URL` in `.env`). SQLite is a single-file database,
which makes backups straightforward — but care must be taken to avoid copying
a file mid-transaction.

### 1a. File-based backup

The simplest approach: stop the application, copy the file, then restart.

```bash
# Stop the service to guarantee a consistent snapshot
sudo systemctl stop ticketforge

# Copy the database file
cp /opt/ticketforge/ticketforge.db \
   /opt/ticketforge/backups/ticketforge-$(date +%Y%m%d-%H%M%S).db

# Restart the service
sudo systemctl start ticketforge
```

For remote backups, use **rsync** to transfer the file to another host:

```bash
sudo systemctl stop ticketforge
rsync -avz /opt/ticketforge/ticketforge.db \
  backup-server:/backups/ticketforge/ticketforge-$(date +%Y%m%d-%H%M%S).db
sudo systemctl start ticketforge
```

> **Downtime:** This method requires a brief service interruption. For
> zero-downtime backups, use the online backup method below.

### 1b. Online backup (SQLite `.backup` command)

SQLite's built-in `.backup` command creates a consistent copy while the
application continues to serve requests.

```bash
sqlite3 /opt/ticketforge/ticketforge.db \
  ".backup '/opt/ticketforge/backups/ticketforge-$(date +%Y%m%d-%H%M%S).db'"
```

This acquires a read lock, copies all pages, and releases the lock — no
downtime required.

### 1c. Automated backup with cron

Create `/opt/ticketforge/scripts/backup-sqlite.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/opt/ticketforge/backups/sqlite"
DB_PATH="/opt/ticketforge/ticketforge.db"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RETENTION_DAYS=30

mkdir -p "${BACKUP_DIR}"

# Online backup (no downtime)
sqlite3 "${DB_PATH}" ".backup '${BACKUP_DIR}/ticketforge-${TIMESTAMP}.db'"

# Compress the backup
gzip "${BACKUP_DIR}/ticketforge-${TIMESTAMP}.db"

# Remove backups older than retention period
find "${BACKUP_DIR}" -name "ticketforge-*.db.gz" -mtime +${RETENTION_DAYS} -delete

echo "[$(date --iso-8601=seconds)] SQLite backup completed: ticketforge-${TIMESTAMP}.db.gz"
```

Make it executable and schedule via cron:

```bash
chmod +x /opt/ticketforge/scripts/backup-sqlite.sh

# Run daily at 02:00 UTC
sudo crontab -u ticketforge -e
# Add the following line:
# 0 2 * * * /opt/ticketforge/scripts/backup-sqlite.sh >> /var/log/ticketforge-backup.log 2>&1
```

### 1d. Restoration

```bash
# Stop the application
sudo systemctl stop ticketforge

# Replace the database with the backup
gunzip -k /opt/ticketforge/backups/sqlite/ticketforge-20260410-020000.db.gz
cp /opt/ticketforge/backups/sqlite/ticketforge-20260410-020000.db \
   /opt/ticketforge/ticketforge.db
chown ticketforge:ticketforge /opt/ticketforge/ticketforge.db

# Verify integrity
sqlite3 /opt/ticketforge/ticketforge.db "PRAGMA integrity_check;"
# Expected output: ok

# Restart
sudo systemctl start ticketforge
```

---

## 2. PostgreSQL Backup

PostgreSQL is the recommended database for production deployments. It offers
multiple backup strategies depending on your recovery objectives.

| Strategy | RPO | RTO | Complexity |
|---|---|---|---|
| **pg_dump** (logical) | Since last dump | Minutes | Low |
| **pg_basebackup** (physical) | Since last backup | Minutes | Medium |
| **PITR** (WAL archiving) | Seconds | Minutes–hours | High |

> **RPO** = Recovery Point Objective (maximum data loss).
> **RTO** = Recovery Time Objective (time to restore service).

### 2a. Logical backup — `pg_dump`

`pg_dump` exports the database as SQL statements or a custom-format archive.
It is consistent, portable, and can selectively restore individual tables.

```bash
# Plain-text SQL dump
pg_dump -U ticketforge -h 127.0.0.1 -d ticketforge \
  > /opt/ticketforge/backups/pg/ticketforge-$(date +%Y%m%d-%H%M%S).sql

# Custom-format dump (compressed, supports parallel restore)
pg_dump -U ticketforge -h 127.0.0.1 -d ticketforge \
  -Fc -f /opt/ticketforge/backups/pg/ticketforge-$(date +%Y%m%d-%H%M%S).dump
```

> **Tip:** Use custom format (`-Fc`) for production backups — it compresses
> automatically and allows parallel restore with `pg_restore -j`.

### 2b. Physical backup — `pg_basebackup`

`pg_basebackup` creates a binary copy of the entire PostgreSQL data
directory. It is faster than `pg_dump` for large databases and is required
as the base for point-in-time recovery.

```bash
pg_basebackup -U ticketforge -h 127.0.0.1 \
  -D /opt/ticketforge/backups/pg/base-$(date +%Y%m%d-%H%M%S) \
  -Ft -z -P
```

| Flag | Purpose |
|---|---|
| `-D` | Destination directory. |
| `-Ft` | Output as tar files. |
| `-z` | Compress with gzip. |
| `-P` | Show progress. |

> **Prerequisite:** The PostgreSQL user must have the `REPLICATION` privilege
> and `pg_hba.conf` must allow replication connections.

```sql
ALTER ROLE ticketforge WITH REPLICATION;
```

### 2c. Automated backup with cron

Create `/opt/ticketforge/scripts/backup-postgres.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/opt/ticketforge/backups/pg"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RETENTION_DAYS=30
PGHOST="127.0.0.1"
PGUSER="ticketforge"
PGDATABASE="ticketforge"

export PGPASSFILE="/opt/ticketforge/.pgpass"

mkdir -p "${BACKUP_DIR}"

# Custom-format dump (compressed)
pg_dump -h "${PGHOST}" -U "${PGUSER}" -d "${PGDATABASE}" \
  -Fc -f "${BACKUP_DIR}/ticketforge-${TIMESTAMP}.dump"

# Remove backups older than retention period
find "${BACKUP_DIR}" -name "ticketforge-*.dump" -mtime +${RETENTION_DAYS} -delete

echo "[$(date --iso-8601=seconds)] PostgreSQL backup completed: ticketforge-${TIMESTAMP}.dump"
```

Create `/opt/ticketforge/.pgpass` for passwordless `pg_dump`:

```
127.0.0.1:5432:ticketforge:ticketforge:STRONG_PASSWORD
```

```bash
chmod 600 /opt/ticketforge/.pgpass
chown ticketforge:ticketforge /opt/ticketforge/.pgpass
chmod +x /opt/ticketforge/scripts/backup-postgres.sh

# Schedule daily at 02:00 UTC
sudo crontab -u ticketforge -e
# 0 2 * * * /opt/ticketforge/scripts/backup-postgres.sh >> /var/log/ticketforge-backup.log 2>&1
```

### 2d. Point-in-time recovery (PITR)

PITR lets you restore the database to **any point in time** by replaying
Write-Ahead Log (WAL) segments on top of a base backup. This minimises data
loss to seconds rather than hours.

#### Step 1 — Enable WAL archiving

Edit `postgresql.conf`:

```
wal_level = replica
archive_mode = on
archive_command = 'cp %p /opt/ticketforge/backups/pg/wal_archive/%f'
```

Create the archive directory and restart PostgreSQL:

```bash
sudo mkdir -p /opt/ticketforge/backups/pg/wal_archive
sudo chown postgres:postgres /opt/ticketforge/backups/pg/wal_archive
sudo systemctl restart postgresql
```

#### Step 2 — Take a base backup

```bash
pg_basebackup -U ticketforge -h 127.0.0.1 \
  -D /opt/ticketforge/backups/pg/base-$(date +%Y%m%d) \
  -Ft -z -P
```

#### Step 3 — Restore to a specific point in time

```bash
# Stop PostgreSQL
sudo systemctl stop postgresql

# Clear the current data directory
sudo rm -rf /var/lib/postgresql/16/main/*

# Extract the base backup
sudo tar xzf /opt/ticketforge/backups/pg/base-20260410/base.tar.gz \
  -C /var/lib/postgresql/16/main/

# Create recovery configuration
sudo tee /var/lib/postgresql/16/main/postgresql.auto.conf > /dev/null <<EOF
restore_command = 'cp /opt/ticketforge/backups/pg/wal_archive/%f %p'
recovery_target_time = '2026-04-10 14:30:00 UTC'
recovery_target_action = 'promote'
EOF

# Signal PostgreSQL to enter recovery mode
sudo touch /var/lib/postgresql/16/main/recovery.signal
sudo chown -R postgres:postgres /var/lib/postgresql/16/main/

# Start PostgreSQL — it will replay WAL up to the target time
sudo systemctl start postgresql
```

After recovery completes, verify with:

```bash
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"
# Expected: f (false — promoted to primary)
```

### 2e. Restoration — logical

Restore from a custom-format dump:

```bash
# Drop and recreate the database
sudo -u postgres psql -c "DROP DATABASE IF EXISTS ticketforge;"
sudo -u postgres psql -c "CREATE DATABASE ticketforge OWNER ticketforge;"

# Restore (parallel with 4 jobs)
pg_restore -U ticketforge -h 127.0.0.1 -d ticketforge \
  -j 4 /opt/ticketforge/backups/pg/ticketforge-20260410-020000.dump

# Verify
psql -U ticketforge -h 127.0.0.1 -d ticketforge \
  -c "SELECT count(*) FROM processed_tickets;"
```

Restore from a plain-text SQL dump:

```bash
sudo -u postgres psql -c "DROP DATABASE IF EXISTS ticketforge;"
sudo -u postgres psql -c "CREATE DATABASE ticketforge OWNER ticketforge;"
psql -U ticketforge -h 127.0.0.1 -d ticketforge \
  < /opt/ticketforge/backups/pg/ticketforge-20260410-020000.sql
```

### 2f. Restoration — physical

Physical restore replaces the entire PostgreSQL data directory:

```bash
sudo systemctl stop postgresql

sudo rm -rf /var/lib/postgresql/16/main/*
sudo tar xzf /opt/ticketforge/backups/pg/base-20260410/base.tar.gz \
  -C /var/lib/postgresql/16/main/
sudo chown -R postgres:postgres /var/lib/postgresql/16/main/

sudo systemctl start postgresql
```

> **Note:** A physical restore replaces **all** databases on the cluster, not
> just the TicketForge database.

---

## 3. Backup Best Practices

### 3a. Retention policies

Implement a tiered retention schedule to balance storage costs with recovery
flexibility:

| Tier | Frequency | Retention | Purpose |
|---|---|---|---|
| **Daily** | Every day at 02:00 UTC | 7 days | Quick recovery from recent incidents |
| **Weekly** | Every Sunday at 03:00 UTC | 4 weeks | Medium-term recovery |
| **Monthly** | 1st of each month at 04:00 UTC | 12 months | Compliance and audit trail |

Implement with a wrapper script or cron jobs:

```bash
# /opt/ticketforge/scripts/rotate-backups.sh
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/opt/ticketforge/backups/pg"
DAY_OF_WEEK=$(date +%u)   # 1=Monday … 7=Sunday
DAY_OF_MONTH=$(date +%d)

# Daily backup
/opt/ticketforge/scripts/backup-postgres.sh

# Promote to weekly (copy Sunday's backup)
if [ "${DAY_OF_WEEK}" -eq 7 ]; then
    LATEST=$(ls -t "${BACKUP_DIR}"/ticketforge-*.dump | head -1)
    cp "${LATEST}" "${BACKUP_DIR}/weekly/$(basename "${LATEST}")"
    find "${BACKUP_DIR}/weekly" -name "*.dump" -mtime +28 -delete
fi

# Promote to monthly (copy 1st of month)
if [ "${DAY_OF_MONTH}" -eq "01" ]; then
    LATEST=$(ls -t "${BACKUP_DIR}"/ticketforge-*.dump | head -1)
    cp "${LATEST}" "${BACKUP_DIR}/monthly/$(basename "${LATEST}")"
    find "${BACKUP_DIR}/monthly" -name "*.dump" -mtime +365 -delete
fi

# Clean up daily backups older than 7 days
find "${BACKUP_DIR}" -maxdepth 1 -name "ticketforge-*.dump" -mtime +7 -delete
```

### 3b. Off-site storage (S3 / GCS)

Never keep backups solely on the same server as the database. Upload copies
to an object storage bucket.

#### Amazon S3

```bash
# Install the AWS CLI
sudo apt install -y awscli

# Upload after each backup
aws s3 cp /opt/ticketforge/backups/pg/ticketforge-20260410-020000.dump \
  s3://your-bucket/ticketforge/daily/

# Sync the entire backup directory
aws s3 sync /opt/ticketforge/backups/pg/ s3://your-bucket/ticketforge/ \
  --storage-class STANDARD_IA
```

Enable **S3 Object Lock** or **versioning** to protect backups against
accidental deletion.

#### Google Cloud Storage

```bash
# Install gsutil
sudo apt install -y google-cloud-cli

# Upload
gsutil cp /opt/ticketforge/backups/pg/ticketforge-20260410-020000.dump \
  gs://your-bucket/ticketforge/daily/

# Lifecycle rule — auto-delete after 90 days
gsutil lifecycle set lifecycle.json gs://your-bucket/
```

### 3c. Backup verification / testing

A backup that has never been tested is not a backup. Schedule regular restore
tests:

```bash
#!/usr/bin/env bash
# /opt/ticketforge/scripts/verify-backup.sh
set -euo pipefail

BACKUP_FILE="$1"
TEST_DB="ticketforge_restore_test"

echo "Creating test database …"
sudo -u postgres psql -c "DROP DATABASE IF EXISTS ${TEST_DB};"
sudo -u postgres psql -c "CREATE DATABASE ${TEST_DB} OWNER ticketforge;"

echo "Restoring backup …"
pg_restore -U ticketforge -h 127.0.0.1 -d "${TEST_DB}" -j 4 "${BACKUP_FILE}"

echo "Running integrity checks …"
TICKET_COUNT=$(psql -U ticketforge -h 127.0.0.1 -d "${TEST_DB}" -tAc \
  "SELECT count(*) FROM processed_tickets;")
echo "Processed tickets: ${TICKET_COUNT}"

if [ "${TICKET_COUNT}" -gt 0 ]; then
    echo "✅ Backup verification PASSED"
else
    echo "❌ Backup verification FAILED — table is empty"
    exit 1
fi

# Clean up
sudo -u postgres psql -c "DROP DATABASE ${TEST_DB};"
```

Run weekly as part of your backup pipeline:

```bash
# 0 5 * * 0  /opt/ticketforge/scripts/verify-backup.sh /opt/ticketforge/backups/pg/ticketforge-latest.dump >> /var/log/ticketforge-backup-verify.log 2>&1
```

### 3d. Monitoring backup success

Track backup outcomes to catch silent failures:

| Method | Implementation |
|---|---|
| **Cron exit code** | Pipe cron output to a log file and monitor for non-zero exit codes. |
| **Prometheus push** | After a successful backup, push a metric via Pushgateway: `echo "ticketforge_backup_last_success $(date +%s)" \| curl --data-binary @- http://pushgateway:9091/metrics/job/ticketforge_backup`. |
| **Heartbeat service** | Use a dead-man's switch service (e.g. Healthchecks.io, Cronitor). Add `curl -fsS https://hc-ping.com/YOUR-UUID` as the last line of the backup script. |
| **File age check** | Alert if the newest backup file is older than 26 hours: `find /opt/ticketforge/backups -name "*.dump" -mmin -1560 \| grep -q . \|\| echo "ALERT"`. |

---

## 4. Docker Volume Backup Considerations

When running TicketForge via Docker Compose, data is stored in named volumes
(`pg_data`, `app_data`, `ollama_data`). These require special handling.

### 4a. Back up a named volume

```bash
# PostgreSQL data volume
docker run --rm \
  -v ticketforge_pg_data:/source:ro \
  -v /opt/ticketforge/backups/docker:/backup \
  alpine \
  tar czf /backup/pg_data-$(date +%Y%m%d-%H%M%S).tar.gz -C /source .
```

### 4b. Back up PostgreSQL from within the container

A cleaner approach is to run `pg_dump` inside the running container:

```bash
docker compose exec -T postgres \
  pg_dump -U ticketforge -Fc ticketforge \
  > /opt/ticketforge/backups/pg/ticketforge-$(date +%Y%m%d-%H%M%S).dump
```

### 4c. Restore a named volume

```bash
# Stop the stack
docker compose -f docker-compose.prod.yml down

# Remove the existing volume
docker volume rm ticketforge_pg_data

# Recreate from backup
docker run --rm \
  -v ticketforge_pg_data:/target \
  -v /opt/ticketforge/backups/docker:/backup:ro \
  alpine \
  sh -c "cd /target && tar xzf /backup/pg_data-20260410-020000.tar.gz"

# Restart the stack
docker compose -f docker-compose.prod.yml up -d
```

### 4d. Application data volume

The `app_data` volume stores cached embeddings and application state. Back it
up alongside the database:

```bash
docker run --rm \
  -v ticketforge_app_data:/source:ro \
  -v /opt/ticketforge/backups/docker:/backup \
  alpine \
  tar czf /backup/app_data-$(date +%Y%m%d-%H%M%S).tar.gz -C /source .
```

### 4e. Ollama model volume

The `ollama_data` volume stores downloaded LLM model weights. These can be
re-downloaded with `ollama pull`, so backing up is optional — but saves time
during disaster recovery:

```bash
docker run --rm \
  -v ticketforge_ollama_data:/source:ro \
  -v /opt/ticketforge/backups/docker:/backup \
  alpine \
  tar czf /backup/ollama_data-$(date +%Y%m%d-%H%M%S).tar.gz -C /source .
```

> **Tip:** Ollama model weights are large (4–40 GB). Consider skipping this
> backup and re-pulling models after a restore unless download bandwidth is
> constrained.

---

*Last updated: July 2025*
