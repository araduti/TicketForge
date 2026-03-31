# TicketForge Load Tests

Load testing suite for TicketForge, powered by [Locust](https://locust.io/).

## Prerequisites

Install Locust:

```bash
pip install locust==2.43.3
```

Optionally, set the API key used during tests:

```bash
export TICKETFORGE_API_KEY="your-api-key"
```

## Running the Tests

### Web UI Mode

Start Locust with the interactive web dashboard:

```bash
locust -f loadtests/locustfile.py --host=http://localhost:8000
```

Then open the dashboard at **<http://localhost:8089>** to configure and monitor the test run in real time. You can set the number of users, spawn rate, and watch live charts for request rate, response times, and failure rate.

### Headless Mode

Run a fully automated test from the command line:

```bash
locust -f loadtests/locustfile.py \
  --host=http://localhost:8000 \
  --users 100 \
  --spawn-rate 10 \
  --run-time 5m \
  --headless
```

| Flag            | Description                                |
|-----------------|--------------------------------------------|
| `--users`       | Total number of concurrent simulated users |
| `--spawn-rate`  | Users spawned per second                   |
| `--run-time`    | Duration of the test (e.g., `5m`, `1h`)    |
| `--headless`    | Run without the web UI                     |

### Running Tagged Subsets

Run only smoke tests:

```bash
locust -f loadtests/locustfile.py --host=http://localhost:8000 --tags smoke --headless --users 5 --spawn-rate 1 --run-time 30s
```

## Performance Targets

| Metric              | Target            |
|---------------------|-------------------|
| Throughput          | ≥ 100 tickets/sec |
| P99 response time   | < 2 s             |
| P95 response time   | < 1 s             |
| Error rate          | < 1 %             |

## Output

Locust prints a summary table to the terminal when a headless run completes. You can also export results to CSV:

```bash
locust -f loadtests/locustfile.py --host=http://localhost:8000 --headless \
  --users 100 --spawn-rate 10 --run-time 5m \
  --csv=loadtests/results
```

This generates `results_stats.csv`, `results_failures.csv`, and `results_stats_history.csv` in the `loadtests/` directory.
