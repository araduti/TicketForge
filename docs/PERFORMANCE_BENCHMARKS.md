# Performance Benchmarks

This document describes the methodology, targets, and results format for TicketForge performance benchmarks.

## Methodology

All benchmarks are executed using [Locust](https://locust.io/) against a single TicketForge instance. Tests ramp up concurrent users linearly and hold the target concurrency for a sustained period to capture steady-state behavior.

**Standard test profile:**

| Phase     | Duration | Users | Spawn Rate |
|-----------|----------|-------|------------|
| Warm-up   | 1 min    | 10    | 2/s        |
| Ramp-up   | 2 min    | 100   | 10/s       |
| Sustained | 5 min    | 100   | —          |
| Cool-down | 1 min    | 0     | —          |

Metrics are collected from both Locust (client-side) and Prometheus (server-side) to cross-validate results.

## Baseline Targets

| Metric                      | Target         |
|-----------------------------|----------------|
| Throughput (ticket creates)  | ≥ 100 req/s   |
| P50 response time            | < 200 ms      |
| P95 response time            | < 1 s         |
| P99 response time            | < 2 s         |
| Error rate (5xx)             | < 1 %         |
| SLA breach rate              | < 10 %        |

## Hardware Requirements

Recommended infrastructure for each benchmark tier:

| Scale    | CPU   | Memory | Database              | Expected Throughput |
|----------|-------|--------|-----------------------|---------------------|
| Small    | 2 vCPU | 4 GB  | PostgreSQL (shared)   | ~50 req/s           |
| Medium   | 4 vCPU | 8 GB  | PostgreSQL (dedicated) | ~200 req/s         |
| Large    | 8 vCPU | 16 GB | PostgreSQL (HA cluster) | ~500 req/s        |

Load test runners should have sufficient resources so the client does not become the bottleneck. A separate machine or container with at least 2 vCPU and 4 GB RAM is recommended.

## Results Template

Copy the table below to record results from each benchmark run.

| Date | Git SHA | Users | Duration | Avg RPS | P50 (ms) | P95 (ms) | P99 (ms) | Error % | Notes |
|------|---------|-------|----------|---------|----------|----------|----------|---------|-------|
|      |         |       |          |         |          |          |          |         |       |
|      |         |       |          |         |          |          |          |         |       |
|      |         |       |          |         |          |          |          |         |       |

## Optimization Tips

1. **Enable response caching** — The `/tickets` endpoint supports caching. Ensure cache headers are configured in production to reduce database load.
2. **Connection pooling** — Use a connection pool (e.g., PgBouncer) in front of PostgreSQL to avoid connection overhead under high concurrency.
3. **Async workers** — Run TicketForge with multiple Uvicorn workers (`--workers 4`) to utilize all available CPU cores.
4. **Database indexing** — Ensure indexes exist on frequently queried columns (`status`, `priority`, `created_at`) in the tickets table.
5. **Rate limiting** — Configure rate limits to protect the service from abuse while allowing legitimate burst traffic.
6. **Payload size** — Keep ticket descriptions concise in automated tests; large payloads increase serialization time and network overhead.
7. **Monitor garbage collection** — Under sustained load, Python GC pauses can cause latency spikes. Monitor GC metrics and tune thresholds if needed.
8. **Horizontal scaling** — For throughput beyond a single instance, deploy multiple replicas behind a load balancer and run benchmarks against the balanced endpoint.
