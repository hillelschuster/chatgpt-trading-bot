#!/usr/bin/env python3
"""Verify snapshot-health output against exact restored bytes and fixed audit semantics."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from crossvenue_snapshot_health import (
    FUTURE_TOLERANCE_MS,
    RECENT_WINDOW_MS,
    audit,
    read_jsonl,
)

MAX_REPORT_AGE_MS = 10 * 60_000


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(snapshots_path, report_path, now_ms=None):
    verified_at_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    report = json.loads(Path(report_path).read_text())
    generated_at_ms = report.get("generated_at_ms")
    if generated_at_ms is None:
        return {
            "status": "INVALID",
            "valid": False,
            "verified_at_ms": verified_at_ms,
            "blockers": ["snapshot_health_generated_at_missing"],
        }

    generated_at_ms = int(generated_at_ms)
    report_age_ms = verified_at_ms - generated_at_ms
    temporal_blockers = []
    if generated_at_ms > verified_at_ms + FUTURE_TOLERANCE_MS:
        temporal_blockers.append("snapshot_health_generated_at_future")
    if report_age_ms > MAX_REPORT_AGE_MS:
        temporal_blockers.append("snapshot_health_report_stale")

    rows = read_jsonl(snapshots_path)
    expected = audit(
        rows,
        now_ms=generated_at_ms,
        window_ms=RECENT_WINDOW_MS,
        future_tolerance_ms=FUTURE_TOLERANCE_MS,
    )
    mismatches = sorted(
        key for key in set(expected) | set(report)
        if expected.get(key) != report.get(key)
    )
    digest = file_sha256(snapshots_path)
    valid = not mismatches and not temporal_blockers
    blockers = list(temporal_blockers)
    if mismatches:
        blockers.append("snapshot_health_evidence_mismatch")
    return {
        "status": "HEALTHY" if valid else "INVALID",
        "valid": valid,
        "generated_at_ms": generated_at_ms,
        "verified_at_ms": verified_at_ms,
        "report_age_ms": report_age_ms,
        "maximum_report_age_ms": MAX_REPORT_AGE_MS,
        "audit_window_ms": RECENT_WINDOW_MS,
        "future_tolerance_ms": FUTURE_TOLERANCE_MS,
        "snapshot_sha256": digest,
        "mismatched_fields": mismatches,
        "blockers": blockers,
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
