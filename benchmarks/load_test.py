"""Concurrent load test against a running Precog API.

    PRECOG_API_URL=http://127.0.0.1:8000 CONCURRENCY=4 REQUESTS=16 \
      .venv/bin/python -m benchmarks.load_test

Optional ``LABEL`` names the output file (``data/load_test_<label>.json``).
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from pathlib import Path

import httpx

from benchmarks.synthetic import generate_series

API = os.environ.get("PRECOG_API_URL", "http://127.0.0.1:8000")
CONCURRENCY = int(os.environ.get("CONCURRENCY", "4"))
REQUESTS = int(os.environ.get("REQUESTS", "16"))
LABEL = os.environ.get("LABEL", "")
OUT = Path(__file__).parent / "data" / (f"load_test_{LABEL}.json" if LABEL else "load_test.json")

PAYLOAD = {
    "horizon": 24,
    "targets": [{"id": "synthetic", "values": generate_series(168).tolist()}],
    "quantiles": [0.1, 0.5, 0.9],
}


async def _one(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    latencies: list[float],
    statuses: list[int],
) -> None:
    async with semaphore:
        started = time.perf_counter()
        try:
            response = await client.post("/v1/forecast", json=PAYLOAD)
            statuses.append(response.status_code)
        except httpx.HTTPError:
            statuses.append(0)
        latencies.append((time.perf_counter() - started) * 1000)


async def run() -> dict:
    semaphore = asyncio.Semaphore(CONCURRENCY)
    latencies: list[float] = []
    statuses: list[int] = []
    async with httpx.AsyncClient(base_url=API, timeout=300.0) as client:
        started = time.perf_counter()
        await asyncio.gather(
            *(_one(client, semaphore, latencies, statuses) for _ in range(REQUESTS))
        )
        elapsed = time.perf_counter() - started
    ordered = sorted(latencies)
    return {
        "api": API,
        "concurrency": CONCURRENCY,
        "requests": REQUESTS,
        "elapsed_s": round(elapsed, 3),
        "throughput_rps": round(REQUESTS / elapsed, 3),
        "latency_ms": {
            "mean": round(statistics.fmean(ordered), 1),
            "p50": round(ordered[len(ordered) // 2], 1),
            "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 1),
            "max": round(ordered[-1], 1),
        },
        "status_counts": {str(code): statuses.count(code) for code in sorted(set(statuses))},
    }


def main() -> None:
    result = asyncio.run(run())
    print(json.dumps(result, indent=2))
    OUT.write_text(json.dumps(result, indent=1))
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
