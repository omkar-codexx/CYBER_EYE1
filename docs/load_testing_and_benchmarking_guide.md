# CyberEye / famX Multi-Device Load Testing & Benchmarking Guide

This document provides a production-grade guide to stress-testing and benchmarking the CyberEye backend and famX Hardware Ingestion Gateway with **10 to 1,000 concurrent simulated devices**.

---

## 1. Overview & Architecture Validation

The load testing framework simulates high-frequency hardware traffic from Android devices in the field to verify:
1. **famX Gateway Ingestion (Port 5000)**: Non-blocking async handling of hardware authentication, device telemetry, and file uploads.
2. **PostgreSQL 15 Persistence**: Ensuring ACID database writes and connection pooling under heavy concurrent transactions.
3. **Redis 7 In-Memory Cache**: Real-time tracking of device online states and `last_seen` timestamps without disk bottlenecks.
4. **Nginx Reverse Proxy**: Connection buffering, request queuing, and rate limits protecting the backend.

```
                     ┌────────────────────────────────────────────────────────┐
                     │          Server Environment (Docker Compose)          │
                     │                                                        │
[10 - 1000 Devices]  │    ┌──────────────┐     ┌──────────────┐              │
Hardware Simulation  ├───>│  Port 5000   │────>│  famX Ingest │              │
(simulate_devices.py)│    │ (Nginx / VPN)│     │  (Port 5001) │              │
                     │    └──────────────┘     └──────┬───────┘              │
                     │                                │                      │
                     │              ┌─────────────────┴─────────────────┐    │
                     │              ▼                                   ▼    │
                     │      ┌───────────────┐                   ┌──────────┐ │
                     │      │ PostgreSQL 15 │                   │ Redis 7  │ │
                     │      │  (Relational) │                   │  (Cache) │ │
                     │      └───────────────┘                   └──────────┘ │
                     └────────────────────────────────────────────────────────┘
```

---

## 2. Server OS Prerequisites (Before Testing 500+ Devices)

When opening hundreds or thousands of simultaneous TCP connections from a single host, Linux default file descriptor limits must be checked.

### A. Increase Host File Descriptor Limit (`nofile`)
Check current limits on the host machine:
```bash
ulimit -n
```
If it returns `1024`, temporarily increase it for the load test terminal session:
```bash
ulimit -n 65535
```

### B. Docker Container Limits (`ulimits: 65535`)
By default, Docker containers inherit a limit of only 1,024 file descriptors. During high-concurrency stress testing with hundreds of in-flight sockets and files, this triggers `OSError: [Errno 24] Too many open files`.

In `docker-compose.yml`, `ulimits` has been configured for `cybereye-app`, `proton-nginx`, and `proton-vpn`:
```yaml
    ulimits:
      nofile:
        soft: 65535
        hard: 65535
```

### C. Python Client Dependency
The asynchronous benchmark script requires `aiohttp`:
```bash
pip install aiohttp
```

---

## 3. The Load Test Script (`simulate_devices_load_test.py`)

The automated script is located at:
[`scripts/simulate_devices_load_test.py`](file:///home/vedx/Videos/Proton/scripts/simulate_devices_load_test.py)

### Supported Command-Line Flags

| Flag | Default | Description |
| :--- | :--- | :--- |
| `-d`, `--devices` | `50` | Number of simultaneous simulated devices |
| `-i`, `--iterations` | `3` | Number of telemetry packets sent per device |
| `--delay` | `0.1` | Delay in seconds between telemetry cycles |
| `--url` | `http://127.0.0.1:5000` | Target famX Gateway endpoint |

---

## 4. Step-by-Step Server Test Plan

Run the benchmark through four progressive stages:

### Stage 1: Warmup Benchmark (10 Devices)
Validates network path, authentication, and token generation:
```bash
python3 scripts/simulate_devices_load_test.py --devices 10 --iterations 3 --delay 0.1
```
- **Expected Latency**: `< 20 ms`
- **Success Rate**: `100%`
- **Target RPS**: `30 - 80 req/sec`

---

### Stage 2: Normal Fleet Load (100 Devices)
Simulates a typical commercial fleet sending active status updates:
```bash
python3 scripts/simulate_devices_load_test.py --devices 100 --iterations 5 --delay 0.05
```
- **Expected Latency**: `25 - 60 ms`
- **Success Rate**: `100%`
- **Target RPS**: `200 - 450 req/sec`

---

### Stage 3: Heavy Field Load (500 Devices)
Tests database write throughput and Redis caching under high concurrency:
```bash
python3 scripts/simulate_devices_load_test.py --devices 500 --iterations 5 --delay 0.02
```
- **Expected Latency**: `40 - 120 ms` (P95 `< 180 ms`)
- **Success Rate**: `99.9% - 100%`
- **Target RPS**: `500 - 1,200 req/sec`

---

### Stage 4: Extreme Stress Test (1,000 Concurrent Devices)
Pushing the server to maximum simultaneous connection capacity:
```bash
python3 scripts/simulate_devices_load_test.py --devices 1000 --iterations 5 --delay 0.01
```
- **Expected Latency**: `80 - 250 ms` (P99 `< 500 ms`)
- **Success Rate**: `> 99%`
- **Target RPS**: `1,000 - 2,500 req/sec`

---

## 5. Live Server Monitoring Commands

Keep these monitoring commands running in separate terminal sessions while executing the load tests:

### 1. Docker Resource Monitor
Shows live CPU percentage, Memory usage, and Network I/O of all 5 containers:
```bash
docker stats
```

### 2. PostgreSQL Active Connections & Activity
Inspect database connection count and queries:
```bash
docker compose exec postgres psql -U proton_admin -d proton_db -c "
SELECT count(*) AS active_connections FROM pg_stat_activity WHERE state = 'active';
"
```
Count registered devices in PostgreSQL:
```bash
docker compose exec postgres psql -U proton_admin -d proton_db -c "
SELECT count(*) AS total_registered_devices FROM devices;
"
```

### 3. Redis Throughput & Memory
Check memory consumption and ops/sec:
```bash
docker compose exec redis redis-cli info stats | grep -E "total_commands_processed|instantaneous_ops_per_sec"
```
Monitor real-time cache writes live:
```bash
docker compose exec redis redis-cli monitor
```

### 4. Nginx Real-Time Access Logs
Watch incoming requests hitting the reverse proxy:
```bash
docker compose logs -f nginx
```

---

## 6. Interpreting the Benchmark Report

At the conclusion of each test run, the script prints an automated summary:

```text
=================================================================
          CyberEye / famX LOAD TEST SUMMARY REPORT          
=================================================================
 Simulated Active Devices : 500
 Total Requests Completed : 3000
 Successful Ingestions    : 3000 (100.0%)
 Failed Requests          : 0
 Total Benchmark Time     : 4.12 seconds
 Throughput (RPS)         : 728.15 requests/sec
-----------------------------------------------------------------
 Latency Distribution (Round-Trip Time):
   - Minimum Latency : 14.20 ms
   - Average Latency : 68.45 ms
   - Median (P50)    : 61.10 ms
   - 95th Percentile : 115.30 ms
   - 99th Percentile : 162.80 ms
   - Maximum Latency : 210.50 ms
=================================================================
```

### Key Performance Indicators (KPIs)
- **Success Rate >= 99%**: Ensures no packets are dropped.
- **P95 Latency < 250ms**: Ensures devices receive immediate acknowledgments without battery drain.
- **CPU Spikes**: If `cybereye-app` hits 100% CPU on 1,000 devices, scale gunicorn workers in `Dockerfile` or add an additional app replica behind Nginx.
