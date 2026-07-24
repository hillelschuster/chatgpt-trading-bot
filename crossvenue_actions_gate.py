#!/usr/bin/env python3
"""Bind the authoritative combined health report to independently recomputed Actions evidence."""
import argparse
import json
import time
from pathlib import Path
from crossvenue_actions_binding import MAX_REPORT_AGE_MS, verify


def apply_gate(health_path, binding_path, runs_path, restoration_path, actions_report_path, now_ms=None):
    health_target = Path(health_path)
    health = json.loads(health_target.read_text())
    binding_target = Path(binding_path)
    binding = json.loads(binding_target.read_text()) if binding_target.is_file() else {}
    checked_at_ms = int(now_ms if now_ms is not None else time.time() * 1000)

    expected = {}
    binding_exact = False
    binding_age_ms = None
    if binding:
        verified_at_ms = binding.get("verified_at_ms")
        if verified_at_ms is not None:
            try:
                verified_at_ms = int(verified_at_ms)
                expected = verify(
                    runs_path, restoration_path, actions_report_path,
                    now_ms=verified_at_ms,
                )
                binding_exact = expected == binding
                binding_age_ms = checked_at_ms - verified_at_ms
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                expected = {}

    binding_fresh = bool(
        binding_age_ms is not None
        and 0 <= binding_age_ms <= MAX_REPORT_AGE_MS
    )
    binding_valid = bool(
        binding
        and binding_exact
        and binding_fresh
        and binding.get("status") == "HEALTHY"
        and binding.get("valid") is True
    )

    integrity = health.setdefault("integrity", {})
    blockers = list(integrity.get("blockers") or [])
    blocker = None
    if not binding:
        blocker = "actions_binding_missing"
    elif not binding_exact:
        blocker = "actions_binding_evidence_mismatch"
    elif not binding_fresh:
        blocker = "actions_binding_stale_or_future"
    elif not binding_valid:
        blocker = "actions_binding_invalid"
    if blocker and blocker not in blockers:
        blockers.append(blocker)

    operations = health.setdefault("operations", {})
    operations["binding"] = {
        "status": binding.get("status"),
        "valid": binding.get("valid"),
        "checked_at_ms": checked_at_ms,
        "verified_at_ms": binding.get("verified_at_ms"),
        "age_ms": binding_age_ms,
        "maximum_age_ms": MAX_REPORT_AGE_MS,
        "exact_recomputation_match": binding_exact,
        "fresh": binding_fresh,
        "workflow_runs_sha256": binding.get("workflow_runs_sha256"),
        "restoration_sha256": binding.get("restoration_sha256"),
        "blockers": binding.get("blockers", []),
    }
    integrity.update({
        "actions_binding_present": bool(binding),
        "actions_binding_valid": binding_valid,
        "actions_binding_exact_recomputation_match": binding_exact,
        "actions_binding_fresh": binding_fresh,
        "actions_binding_blockers": binding.get("blockers", []),
        "blockers": blockers,
    })
    if blocker:
        health["status"] = "INVALID"

    health_target.write_text(json.dumps(health, indent=2, allow_nan=False) + "\n")
    return health


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-report", default="reports/crossvenue_health.json")
    parser.add_argument("--binding", default="reports/crossvenue_actions_binding.json")
    parser.add_argument("--runs", default="reports/crossvenue_workflow_runs.json")
    parser.add_argument("--restoration", default="reports/crossvenue_restoration.json")
    parser.add_argument("--actions-report", default="reports/crossvenue_actions_health.json")
    args = parser.parse_args()
    report = apply_gate(
        args.health_report, args.binding, args.runs, args.restoration,
        args.actions_report,
    )
    print(json.dumps(report, indent=2, allow_nan=False))
    if report.get("status") == "INVALID":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
