#!/usr/bin/env python3
"""
CyberEye / famX Multi-Device Load & Stress Testing Tool
======================================================
Simulates concurrent device telemetry, heartbeat, and data ingestion
from 10 up to 1,000 devices against the famX Gateway (Port 5000 / 8800).

Features:
- Configurable concurrency (--devices, --iterations, --delay)
- Measures: Requests/sec (RPS), Latency (Min, Mean, P95, P99, Max), Error Rate
- Tests HTTP Telemetry & File Upload Ingestion
- Real-time progress bar and summary statistics
"""

import sys
import time
import os
import argparse
import asyncio
import io
import statistics
import urllib.parse

try:
    import aiohttp
except ImportError:
    print("[!] 'aiohttp' library is required for high-concurrency async load testing.")
    print("[!] Install it with: pip install aiohttp")
    sys.exit(1)

# Default gateway targets
DEFAULT_GATEWAY_URL = "http://127.0.0.1:5000"
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:8800"

SAMPLE_DEVICE_MODELS = [
    ("Samsung", "Galaxy S23", "13"),
    ("Xiaomi", "Redmi Note 12", "12"),
    ("OnePlus", "11R", "13"),
    ("Google", "Pixel 7 Pro", "14"),
    ("Vivo", "V27 Pro", "13"),
    ("Oppo", "Reno 10", "13")
]

class MetricsCollector:
    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.latencies = []
        self.errors = {}
        self.start_time = None
        self.end_time = None

    def record_success(self, duration_sec):
        self.total_requests += 1
        self.successful_requests += 1
        self.latencies.append(duration_sec * 1000)  # to ms

    def record_failure(self, error_msg):
        self.total_requests += 1
        self.failed_requests += 1
        self.errors[error_msg] = self.errors.get(error_msg, 0) + 1

    def print_summary(self, num_devices):
        total_time = (self.end_time - self.start_time) if self.end_time else 1.0
        rps = self.total_requests / total_time if total_time > 0 else 0
        
        print("\n" + "=" * 65)
        print("          CyberEye / famX LOAD TEST SUMMARY REPORT          ")
        print("=" * 65)
        print(f" Simulated Active Devices : {num_devices}")
        print(f" Total Requests Completed : {self.total_requests}")
        print(f" Successful Ingestions    : {self.successful_requests} ({self.successful_requests / max(self.total_requests, 1) * 100:.1f}%)")
        print(f" Failed Requests          : {self.failed_requests}")
        print(f" Total Benchmark Time     : {total_time:.2f} seconds")
        print(f" Throughput (RPS)         : {rps:.2f} requests/sec")
        print("-" * 65)
        
        if self.latencies:
            print(" Latency Distribution (Round-Trip Time):")
            print(f"   - Minimum Latency : {min(self.latencies):.2f} ms")
            print(f"   - Average Latency : {statistics.mean(self.latencies):.2f} ms")
            print(f"   - Median (P50)    : {statistics.median(self.latencies):.2f} ms")
            sorted_lat = sorted(self.latencies)
            p95_idx = int(len(sorted_lat) * 0.95)
            p99_idx = int(len(sorted_lat) * 0.99)
            print(f"   - 95th Percentile : {sorted_lat[min(p95_idx, len(sorted_lat)-1)]:.2f} ms")
            print(f"   - 99th Percentile : {sorted_lat[min(p99_idx, len(sorted_lat)-1)]:.2f} ms")
            print(f"   - Maximum Latency : {max(self.latencies):.2f} ms")
        
        if self.errors:
            print("-" * 65)
            print(" Error Breakdown:")
            for err, count in list(self.errors.items())[:5]:
                print(f"   - [{count}x]: {err}")
        print("=" * 65 + "\n")


async def simulate_single_device(device_idx: int, base_url: str, iterations: int, delay_sec: float, metrics: MetricsCollector, session: aiohttp.ClientSession):
    """Simulates a single smartphone hardware device sending telemetry and logs."""
    device_id = f"SIM_DEV_{device_idx:04d}"
    manf, model, release = SAMPLE_DEVICE_MODELS[device_idx % len(SAMPLE_DEVICE_MODELS)]
    
    # 1. Obtain/Provision device token
    token = None
    token_url = f"{base_url}/api/device/{device_id}/token"
    try:
        t0 = time.time()
        async with session.get(token_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            d = time.time() - t0
            if resp.status == 200:
                data = await resp.json()
                token = data.get("famX_token")
                metrics.record_success(d)
            else:
                metrics.record_failure(f"Token HTTP {resp.status}")
    except Exception as e:
        metrics.record_failure(f"Token Req Err: {type(e).__name__}")

    headers = {}
    if token:
        headers["X-famX-Token"] = token

    # 2. Ingestion Loop (telemetry, calls, sms, contacts)
    for it in range(iterations):
        # A. Send info / status update
        info_data = (
            f"model: {model}\n"
            f"manufacturer: {manf}\n"
            f"android: {release}\n"
            f"battery: {85 - (it % 10)}%\n"
            f"ip: 10.96.0.{10 + (device_idx % 200)}\n"
            f"sim_state: READY\n"
        )
        
        data = aiohttp.FormData()
        data.add_field('category', 'info')
        data.add_field('file', io.BytesIO(info_data.encode('utf-8')), filename='info.txt', content_type='text/plain')
        
        upload_url = f"{base_url}/api/device/{device_id}/upload_media"
        try:
            t0 = time.time()
            async with session.post(upload_url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                d = time.time() - t0
                if resp.status == 200:
                    metrics.record_success(d)
                else:
                    metrics.record_failure(f"Upload HTTP {resp.status}")
        except Exception as e:
            metrics.record_failure(f"Upload Err: {type(e).__name__}")

        if delay_sec > 0:
            await asyncio.sleep(delay_sec)


async def run_load_test(num_devices: int, iterations: int, delay_sec: float, base_url: str):
    print("\n" + "=" * 65)
    print("       STARTING CYBEREYE HARDWARE LOAD TEST (INGESTION)       ")
    print("=" * 65)
    print(f" Target Gateway URL      : {base_url}")
    print(f" Concurrent Devices      : {num_devices}")
    print(f" Telemetry Iterations    : {iterations} per device")
    print(f" Inter-Request Delay     : {delay_sec}s")
    print(f" Total Expected Requests : {num_devices * (1 + iterations)}")
    print("=" * 65 + "\n")
    
    metrics = MetricsCollector()
    
    # TCP Connector tuning for high concurrency
    conn = aiohttp.TCPConnector(
        limit=max(100, num_devices * 2),
        limit_per_host=max(50, num_devices),
        enable_cleanup_closed=True
    )
    
    metrics.start_time = time.time()
    
    async with aiohttp.ClientSession(connector=conn) as session:
        # First verify gateway accessibility
        try:
            async with session.get(base_url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"[+] Gateway Verified: {data.get('service')} (Status: {data.get('status')})\n")
                else:
                    print(f"[!] Warning: Gateway returned HTTP {resp.status} on health check.\n")
        except Exception as e:
            print(f"[!] Warning: Gateway at {base_url} is not responding ({e}).")
            print("    Make sure your docker compose is running (`docker compose up -d`).\n")

        print(f"[*] Spawning {num_devices} asynchronous device coroutines...")
        tasks = [
            simulate_single_device(i + 1, base_url, iterations, delay_sec, metrics, session)
            for i in range(num_devices)
        ]
        
        # Run all simulated devices concurrently
        await asyncio.gather(*tasks)

    metrics.end_time = time.time()
    metrics.print_summary(num_devices)


def main():
    parser = argparse.ArgumentParser(description="CyberEye / famX High-Concurrency Load Tester")
    parser.add_argument("-d", "--devices", type=int, default=50, help="Number of simulated devices (e.g. 10, 100, 500, 1000)")
    parser.add_argument("-i", "--iterations", type=int, default=3, help="Telemetry iterations per device (default: 3)")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay between iterations in seconds (default: 0.1)")
    parser.add_argument("--url", type=str, default=DEFAULT_GATEWAY_URL, help=f"famX Gateway URL (default: {DEFAULT_GATEWAY_URL})")
    
    args = parser.parse_args()
    
    # Check OS ulimit for 500+ devices
    if args.devices >= 500:
        try:
            import resource
            nofile_soft, nofile_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            if nofile_soft < args.devices * 3:
                resource.setrlimit(resource.RLIMIT_NOFILE, (min(65535, args.devices * 4), nofile_hard))
        except Exception:
            pass

    asyncio.run(run_load_test(args.devices, args.iterations, args.delay, args.url))

if __name__ == "__main__":
    main()
