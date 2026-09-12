#!/usr/bin/env python3
"""Reproducible, synthetic benchmark for SessionSifu's non-GUI hot path."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "portable"))

from sessionsifu_portable.model import MonitorSnapshot, SessionSnapshot, WindowSnapshot
from sessionsifu_portable.storage import SessionStore
from sessionsifu_portable.window_rules import WindowRule, WindowRuleStore


def sample_session(count: int) -> SessionSnapshot:
    monitors = [
        MonitorSnapshot("primary", "Primary", [0, 0, 1920, 1080], primary=True),
        MonitorSnapshot("external", "External", [1920, 0, 2560, 1440]),
    ]
    windows = [
        WindowSnapshot(
            window_id=str(index),
            app_id=f"org.example.App{index % 12}",
            app_name=f"Synthetic App {index % 12}",
            title=f"Synthetic document {index}",
            executable=f"/opt/synthetic/app-{index % 12}",
            command=[f"/opt/synthetic/app-{index % 12}"],
            geometry=[40 + index * 11, 30 + index * 7, 960, 720],
            monitor="primary" if index % 2 == 0 else "external",
            workspace=str(index % 6),
            open_files=[f"/home/example/Documents/synthetic-{index}.txt"],
        )
        for index in range(count)
    ]
    return SessionSnapshot("benchmark", "Synthetic desktop", windows, monitors=monitors)


def timed(iterations: int, operation) -> dict[str, float]:
    values = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        operation()
        values.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(values)
    return {
        "mean_ms": round(statistics.fmean(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows", type=int, default=30, choices=range(1, 513))
    parser.add_argument("--iterations", type=int, default=50, choices=range(1, 1001))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    session = sample_session(args.windows)
    with tempfile.TemporaryDirectory(prefix="sessionsifu-benchmark-") as directory:
        store = SessionStore(Path(directory))
        path = store.save_named("Benchmark", session)
        rules = WindowRuleStore(store.root)
        for index in range(min(12, args.windows)):
            rules.save(WindowRule(
                app_id=f"org.example.App{index}",
                monitor="external",
                workspace="2",
                geometry=(2000 + index * 5, 80, 1200, 900),
            ))
        result = {
            "fixture": "synthetic-no-user-data",
            "windows": args.windows,
            "iterations": args.iterations,
            "session_bytes": path.stat().st_size,
            "load": timed(args.iterations, lambda: store.load(path)),
            "rule_application": timed(args.iterations, lambda: rules.apply(session)),
            "serialize": timed(args.iterations, session.to_dict),
        }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"SessionSifu synthetic continuity benchmark ({args.windows} windows)")
        for name in ("load", "rule_application", "serialize"):
            row = result[name]
            print(f"{name:18} mean {row['mean_ms']:8.3f} ms  p95 {row['p95_ms']:8.3f} ms")
        print(f"session size       {result['session_bytes']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
