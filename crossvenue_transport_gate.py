#!/usr/bin/env python3
"""Bind the authoritative health verdict to artifact transport and bundle restoration evidence."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

EXPECTED_EXTRACTION = "crash_recoverable_transactional_bundle_replace"
EXPECTED_DESTINATION_POLICY = "no_symlink_or_special_file_components"
EXPECTED_RECOVERY_POLICY = "old_and_new_sha256_verified_before_mutation"


def apply_transport_gate(health: dict, artifact_binding: dict, bundle: dict) -> dict:
    blockers = []
    binding_valid = artifact_binding.get("status") == "VALID"
    bundle_valid = bundle.get("status") == "VALID"
    binding_sha = artifact_binding.get("archive_sha256")
    bundle_sha = bundle.get("zip_sha256")
    digest_matches = bool(binding_sha and bundle_sha and binding_sha == bundle_sha)
    extraction_valid = bundle.get("extraction") == EXPECTED_EXTRACTION
    destination_policy_valid = bundle.get("destination_path_policy") == EXPECTED_DESTINATION_POLICY
    recovery_policy_valid = bundle.get("recovery_policy") == EXPECTED_RECOVERY_POLICY

    if not artifact_binding:
        blockers.append("artifact_binding_missing")
    elif not binding_valid:
        blockers.append("artifact_binding_invalid")
    if not bundle:
        blockers.append("bundle_report_missing")
    elif not bundle_valid:
        blockers.append("bundle_restore_invalid")
    if artifact_binding and bundle and not digest_matches:
        blockers.append("artifact_bundle_digest_mismatch")
    if bundle and not extraction_valid:
        blockers.append("bundle_extraction_policy_invalid")
    if bundle and not destination_policy_valid:
        blockers.append("bundle_destination_policy_invalid")
    if bundle and not recovery_policy_valid:
        blockers.append("bundle_recovery_policy_invalid")

    integrity = health.setdefault("integrity", {})
    existing = list(integrity.get("blockers") or [])
    for blocker in blockers:
        if blocker not in existing:
            existing.append(blocker)
    integrity["blockers"] = existing
    integrity["transport"] = {
        "artifact_binding_present": bool(artifact_binding),
        "artifact_binding_valid": binding_valid,
        "bundle_report_present": bool(bundle),
        "bundle_valid": bundle_valid,
        "archive_sha256": binding_sha,
        "bundle_zip_sha256": bundle_sha,
        "digest_matches": digest_matches,
        "extraction_policy_valid": extraction_valid,
        "destination_policy_valid": destination_policy_valid,
        "recovery_policy_valid": recovery_policy_valid,
        "recovered_interrupted_transactions": bundle.get("recovered_interrupted_transactions"),
        "blockers": blockers,
    }
    if blockers:
        health["status"] = "INVALID"
    return health


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-report", type=Path, required=True)
    parser.add_argument("--artifact-binding", type=Path, required=True)
    parser.add_argument("--bundle-report", type=Path, required=True)
    args = parser.parse_args()
    try:
        health = _load(args.health_report)
        binding = _load(args.artifact_binding)
        bundle = _load(args.bundle_report)
        report = apply_transport_gate(health, binding, bundle)
    except (OSError, json.JSONDecodeError) as exc:
        report = {"status": "INVALID", "integrity": {"blockers": [f"transport_gate_input_error:{exc}"]}}
    args.health_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") != "INVALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
