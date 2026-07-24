#!/usr/bin/env python3
"""Fail-closed audit of recent prospective snapshot payload and timestamp integrity."""
import argparse
import json
import time
from pathlib import Path

from crossvenue_snapshot import DEFAULT_CADENCE_MS, SCHEMA_VERSION, validate

RECENT_WINDOW_MS = 3_600_000
FUTURE_TOLERANCE_MS = 60_000
COINS = ("BTC", "ETH")


def read_jsonl(path):
    target = Path(path)
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text().splitlines() if line.strip()]


def audit(rows, now_ms=None, window_ms=RECENT_WINDOW_MS,
          cadence_ms=DEFAULT_CADENCE_MS, future_tolerance_ms=FUTURE_TOLERANCE_MS):
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    window_start = now_ms - int(window_ms)
    recent = []
    invalid = []
    seen = set()
    duplicates = []

    for index, row in enumerate(rows):
        captured = int(row.get("captured_at_ms") or 0)
        if captured < window_start:
            continue
        recent.append(row)
        slot = int(row.get("cadence_slot_ms") or -1)
        coin = row.get("coin")
        key = (slot, coin)
        if key in seen:
            duplicates.append({"row": index, "cadence_slot_ms": slot, "coin": coin})
        seen.add(key)

        errors = []
        if row.get("schema_version") != SCHEMA_VERSION:
            errors.append("schema_version")
        if coin not in COINS:
            errors.append("coin")
        if captured > now_ms + future_tolerance_ms:
            errors.append("captured_at_future")
        if slot < 0 or captured < slot or captured >= slot + cadence_ms:
            errors.append("captured_at_outside_cadence_slot")
        errors.extend(validate(row))
        if errors:
            invalid.append({
                "row": index,
                "cadence_slot_ms": slot if slot >= 0 else None,
                "coin": coin,
                "errors": sorted(set(errors)),
            })

    healthy = bool(recent) and not invalid and not duplicates
    return {
        "status": "HEALTHY" if healthy else "INVALID",
        "healthy": healthy,
        "generated_at_ms": now_ms,
        "window_minutes": window_ms / 60_000,
        "future_tolerance_ms": future_tolerance_ms,
        "schema_version": SCHEMA_VERSION,
        "recent_rows": len(recent),
        "unique_recent_rows": len(seen),
        "invalid_rows": len(invalid),
        "duplicate_rows": len(duplicates),
        "invalid_examples": invalid[:10],
        "duplicate_examples": duplicates[:10],
        "blockers": (["recent_snapshots_missing"] if not recent else [])
                    + (["recent_snapshot_payload_invalid"] if invalid else [])
                    + (["recent_snapshot_duplicates"] if duplicates else []),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", default="data/crossvenue_snapshots.jsonl")
    parser.add_argument("--out", default="reports/crossvenue_snapshot_health.json")
    args = parser.parse_args()
    report = audit(read_jsonl(args.snapshots))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    if not report["healthy"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
