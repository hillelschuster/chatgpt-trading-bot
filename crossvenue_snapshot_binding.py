#!/usr/bin/env python3
"""Verify snapshot-health output against exact restored bytes and fixed audit semantics."""
import argparse
import hashlib
import json
from pathlib import Path

from crossvenue_snapshot_health import (
    FUTURE_TOLERANCE_MS,
    RECENT_WINDOW_MS,
    audit,
    read_jsonl,
)


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(snapshots_path, report_path):
    report = json.loads(Path(report_path).read_text())
    generated_at_ms = report.get("generated_at_ms")
    if generated_at_ms is None:
        return {
            "status": "INVALID",
            "valid": False,
            "blockers": ["snapshot_health_generated_at_missing"],
        }

    expected = audit(
        read_jsonl(snapshots_path),
        now_ms=int(generated_at_ms),
        window_ms=RECENT_WINDOW_MS,
        future_tolerance_ms=FUTURE_TOLERANCE_MS,
    )
    mismatches = sorted(
        key for key in set(expected) | set(report)
        if expected.get(key) != report.get(key)
    )
    digest = file_sha256(snapshots_path)
    valid = not mismatches
    return {
        "status": "HEALTHY" if valid else "INVALID",
        "valid": valid,
        "generated_at_ms": int(generated_at_ms),
        "audit_window_ms": RECENT_WINDOW_MS,
        "future_tolerance_ms": FUTURE_TOLERANCE_MS,
        "snapshot_sha256": digest,
        "mismatched_fields": mismatches,
        "blockers": [] if valid else ["snapshot_health_evidence_mismatch"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", default="data/crossvenue_snapshots.jsonl")
    parser.add_argument("--snapshot-report", default="reports/crossvenue_snapshot_health.json")
    parser.add_argument("--out", default="reports/crossvenue_snapshot_binding.json")
    args = parser.parse_args()
    result = verify(args.snapshots, args.snapshot_report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
