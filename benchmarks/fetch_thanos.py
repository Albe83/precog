"""Fetch sample series from Thanos query for the backtests.

Requires a port-forward to the in-cluster Thanos query:

    kubectl -n thanos-system port-forward svc/thanos-query 9091:9090 &

Then:

    .venv/bin/python benchmarks/fetch_thanos.py
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://localhost:9091/api/v1/query_range"
INSTANCE = "172.16.10.41:9100"
OUT = Path(__file__).parent / "data" / "complex_series.json"

EXPRESSIONS = {
    "cpu_busy": f'sum(rate(node_cpu_seconds_total{{instance="{INSTANCE}",mode!="idle"}}[1h]))',
    "net_rx_bytes": f'sum(rate(node_network_receive_bytes_total{{instance="{INSTANCE}"}}[1h]))',
    "net_tx_bytes": f'sum(rate(node_network_transmit_bytes_total{{instance="{INSTANCE}"}}[1h]))',
    "mem_free_bytes": f'node_memory_MemFree_bytes{{instance="{INSTANCE}"}}',
    "load15": f'node_load15{{instance="{INSTANCE}"}}',
    "procs_running": f'node_procs_running{{instance="{INSTANCE}"}}',
    "ctx_switches": f'sum(rate(node_context_switches_total{{instance="{INSTANCE}"}}[1h]))',
    "disk_io_time": f'sum(rate(node_disk_io_time_seconds_total{{instance="{INSTANCE}"}}[1h]))',
}


def fetch(expr: str, start: int, end: int, step: int) -> list[float]:
    params = urllib.parse.urlencode({"query": expr, "start": start, "end": end, "step": step})
    with urllib.request.urlopen(f"{BASE}?{params}", timeout=60) as resp:
        payload = json.load(resp)
    results = payload["data"]["result"]
    return [float(v) for _, v in results[0]["values"]] if results else []


def main() -> None:
    now = int(time.time())
    start = now - 30 * 86400
    step = 3600
    out: dict = {
        "source": f"Thanos thanos-system/thanos-query, node-exporter {INSTANCE}",
        "step_seconds": step,
        "start": start,
        "end": now,
        "series": {},
    }
    for name, expr in EXPRESSIONS.items():
        values = fetch(expr, start, now, step)
        out["series"][name] = values
        print(f"{name:16s} {len(values):4d} points")
    OUT.write_text(json.dumps(out, indent=1))
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
