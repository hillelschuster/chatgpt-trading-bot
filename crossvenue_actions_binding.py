#!/usr/bin/env python3
"""Recompute Actions health from exact saved inputs and bind the verdict to their bytes."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from crossvenue_actions_health import summarize
from crossvenue_scheduler_health import merge

MAX_REPORT_AGE_MS = 10 * 60_000


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_runs(path):
    payload = json.loads(Path(path).read_text())
    return payload.get("workflow_runs") if isinstance(payload, dict) else payload


def verify(runs_path, restoration_path, report_path, now_ms=None):
    verified_at_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    report = json.loads(Path(report_path).read_text())
    generated_at_ms = report.get("generated_at_ms")
    if generated_at_ms is None:
        return {
            "status": "INVALID",
            "valid": False,
            "verified_at_ms": verified_at_ms,
            "blockers": ["actions_health_generated_at_missing"],
        }

    generated_at_ms = int(generated_at_ms)
    report_age_ms = verified_at_ms - generated_at_ms
    blockers = []
    if generated_at_ms > verified_at_ms:
        blockers.append("actions_health_generated_at_future")
    if report_age_ms > MAX_REPORT_AGE_MS:
        blockers.append("actions_health_report_stale")

    runs = load_runs(runs_path) or []
    restoration = json.loads(Path(restoration_path).read_text())
    expected = merge(
        summarize(runs, restoration, now_ms=generated_at_ms),
        runs,
        generated_at_ms,
    )
    mismatches = sorted(
        key for key in set(expected) | set(report)
        if expected.get(key) != report.get(key)
    )
    if mismatches:
        blockers.append("actions_health_evidence_mismatch")

    valid = not blockers
    return {
        "status": "HEALTHY" if valid else "INVALID",
        "valid": valid,
        "generated_at_ms": generated_at_ms,
        "verified_at_ms": verified_at_ms,
        "report_age_ms": report_age_ms,
        "maximum_report_age_ms": MAX_REPORT_AGE_MS,
        "workflow_runs_sha256": file_sha256(runs_path),
        "restoration_sha256": file_sha256(restoration_path),
        "mismatched_fields": mismatches,
        "blockers": blockers,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default="reports/crossvenue_workflow_runs.json")
    parser.add_argument("--restoration", default="reports/crossvenue_restoration.json")
    parser.add_argument("--actions-report", default="reports/crossvenue_actions_health.json")
    parser.add_argument("--out", default="reports/crossvenue_actions_binding.json")
    args = parser.parse_args()
    result = verify(args.runs, args.restoration, args.actions_report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
