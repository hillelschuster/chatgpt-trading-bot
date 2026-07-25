#!/usr/bin/env python3
"""Independently bind authoritative health to exact artifact and restored bytes."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

from crossvenue_artifact_binding import verify as verify_artifact_binding
from crossvenue_bundle import inspect_bundle

EXPECTED_EXTRACTION = "crash_recoverable_transactional_bundle_replace"
EXPECTED_DESTINATION_POLICY = "no_symlink_or_special_file_components"
EXPECTED_RECOVERY_POLICY = "old_and_new_sha256_verified_before_mutation"
DEFAULT_REQUIRED_MEMBERS = {
    "data/crossvenue_experiment_freeze.json",
    "data/crossvenue_snapshots.jsonl",
    "reports/crossvenue_chain.json",
    "reports/crossvenue_validation.json",
    "reports/crossvenue_promotion.json",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def recompute_transport(
    archive: Path,
    restoration: dict,
    destination: Path,
    required_members: set[str] | None = None,
) -> tuple[dict, dict, list[str]]:
    """Recompute transport evidence from exact archive/restored bytes."""
    blockers: list[str] = []
    required = set(required_members or DEFAULT_REQUIRED_MEMBERS)
    artifact_binding = verify_artifact_binding(archive, restoration)
    try:
        archive_bundle = inspect_bundle(archive, required)
    except (OSError, ValueError) as exc:
        archive_bundle = {"status": "INVALID", "error": str(exc)}
        blockers.append(f"bundle_recomputation_failed:{exc}")
        return artifact_binding, archive_bundle, blockers

    restored_members = {}
    for name, metadata in (archive_bundle.get("members") or {}).items():
        target = destination / name
        try:
            restored_members[name] = {**metadata, "sha256": _sha256_file(target)}
        except OSError as exc:
            blockers.append(f"restored_member_unreadable:{name}:{exc}")
    archive_bundle["members"] = dict(sorted(restored_members.items()))
    return artifact_binding, archive_bundle, blockers


def apply_transport_gate(
    health: dict,
    artifact_binding: dict,
    bundle: dict,
    *,
    recomputed_binding: dict | None = None,
    recomputed_bundle: dict | None = None,
    recomputation_blockers: list[str] | None = None,
) -> dict:
    blockers = list(recomputation_blockers or [])
    binding_valid = artifact_binding.get("status") == "VALID"
    bundle_valid = bundle.get("status") == "VALID"
    binding_sha = artifact_binding.get("archive_sha256")
    bundle_sha = bundle.get("zip_sha256")
    digest_matches = bool(binding_sha and bundle_sha and binding_sha == bundle_sha)
    extraction_valid = bundle.get("extraction") == EXPECTED_EXTRACTION
    destination_policy_valid = bundle.get("destination_path_policy") == EXPECTED_DESTINATION_POLICY
    recovery_policy_valid = bundle.get("recovery_policy") == EXPECTED_RECOVERY_POLICY

    binding_exact = recomputed_binding is None or _canonical(artifact_binding) == _canonical(recomputed_binding)
    bundle_exact = True
    if recomputed_bundle is not None:
        comparable = {
            key: bundle.get(key)
            for key in (
                "status", "schema_version", "member_count", "total_uncompressed_bytes",
                "members", "zip_sha256",
            )
        }
        bundle_exact = _canonical(comparable) == _canonical(recomputed_bundle)

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
    if not binding_exact:
        blockers.append("artifact_binding_recomputation_mismatch")
    if not bundle_exact:
        blockers.append("bundle_recomputation_mismatch")

    blockers = list(dict.fromkeys(blockers))
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
        "artifact_binding_exact_recomputation_match": binding_exact,
        "bundle_exact_recomputation_match": bundle_exact,
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
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--restoration", type=Path)
    parser.add_argument("--destination", type=Path, default=Path("."))
    parser.add_argument("--required-member", action="append", default=[])
    args = parser.parse_args()
    try:
        health = _load(args.health_report)
        binding = _load(args.artifact_binding)
        bundle = _load(args.bundle_report)
        recomputed_binding = recomputed_bundle = None
        recomputation_blockers: list[str] = []
        if args.archive or args.restoration:
            if not args.archive or not args.restoration:
                raise ValueError("archive_and_restoration_must_be_supplied_together")
            required = set(args.required_member) if args.required_member else DEFAULT_REQUIRED_MEMBERS
            recomputed_binding, recomputed_bundle, recomputation_blockers = recompute_transport(
                args.archive, _load(args.restoration), args.destination, required
            )
        report = apply_transport_gate(
            health, binding, bundle,
            recomputed_binding=recomputed_binding,
            recomputed_bundle=recomputed_bundle,
            recomputation_blockers=recomputation_blockers,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {"status": "INVALID", "integrity": {"blockers": [f"transport_gate_input_error:{exc}"]}}
    args.health_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") != "INVALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
