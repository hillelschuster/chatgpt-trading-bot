#!/usr/bin/env python3
"""Bind the authoritative combined health report to exact saved Actions evidence."""
import argparse
import hashlib
import json
from pathlib import Path


def file_sha256(path):
    target = Path(path)
    return hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None


def apply_gate(health_path, binding_path, runs_path, restoration_path):
    health_target = Path(health_path)
    health = json.loads(health_target.read_text())
    binding_target = Path(binding_path)
    binding = json.loads(binding_target.read_text()) if binding_target.is_file() else {}

    runs_digest = file_sha256(runs_path)
    restoration_digest = file_sha256(restoration_path)
    digest_matches = bool(
        runs_digest
        and restoration_digest
        and binding.get("workflow_runs_sha256") == runs_digest
        and binding.get("restoration_sha256") == restoration_digest
    )
    binding_valid = bool(
        binding
        and binding.get("status") == "HEALTHY"
        and binding.get("valid") is True
        and digest_matches
    )

    integrity = health.setdefault("integrity", {})
    blockers = list(integrity.get("blockers") or [])
    blocker = None
    if not binding:
        blocker = "actions_binding_missing"
    elif not binding_valid:
        blocker = "actions_binding_invalid"
    if blocker and blocker not in blockers:
        blockers.append(blocker)

    operations = health.setdefault("operations", {})
    operations["binding"] = {
        "status": binding.get("status"),
        "valid": binding.get("valid"),
        "workflow_runs_sha256": runs_digest,
        "bound_workflow_runs_sha256": binding.get("workflow_runs_sha256"),
        "restoration_sha256": restoration_digest,
        "bound_restoration_sha256": binding.get("restoration_sha256"),
        "digest_matches": digest_matches,
        "blockers": binding.get("blockers", []),
    }
    integrity.update({
        "actions_binding_present": bool(binding),
        "actions_binding_valid": binding_valid,
        "actions_binding_digest_matches": digest_matches,
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
    args = parser.parse_args()
    report = apply_gate(args.health_report, args.binding, args.runs, args.restoration)
    print(json.dumps(report, indent=2, allow_nan=False))
    if report.get("status") == "INVALID":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
