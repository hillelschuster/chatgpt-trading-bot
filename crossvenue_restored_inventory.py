#!/usr/bin/env python3
"""Fail closed when restored prospective evidence is a mixed artifact generation."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path, PurePosixPath

# Only durable prospective series state belongs here. Reports produced while
# downloading or restoring the current artifact are transport metadata, not
# members of the prior evidence generation, and must never be compared against
# their recursively archived predecessor.
MANAGED_MEMBERS = {
    "data/crossvenue_experiment_freeze.json",
    "data/crossvenue_snapshots.jsonl",
    "data/crossvenue_events.jsonl",
    "data/crossvenue_settled_events.jsonl",
    "data/crossvenue_pnl_events.jsonl",
    "data/crossvenue_validation_base_ledger.jsonl",
    "data/crossvenue_validation_stress_ledger.jsonl",
    "reports/crossvenue_freeze.json",
    "reports/crossvenue_continuity.json",
    "reports/crossvenue_events.json",
    "reports/crossvenue_coverage.json",
    "reports/crossvenue_settlements.json",
    "reports/crossvenue_pnl.json",
    "reports/crossvenue_validation.json",
    "reports/crossvenue_promotion.json",
    "reports/crossvenue_chain.json",
}

TRANSPORT_METADATA = {
    "reports/crossvenue_restoration.json",
    "reports/crossvenue_artifact_binding.json",
    "reports/crossvenue_restore_bundle.json",
    "reports/crossvenue_restored_inventory.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_restored_inventory(archive: Path, destination: Path) -> dict:
    raw = archive.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        archive_members = {
            str(PurePosixPath(info.filename.replace("\\", "/")))
            for info in bundle.infolist()
            if not info.is_dir()
        }
        archive_digests = {}
        for name in sorted(MANAGED_MEMBERS & archive_members):
            archive_digests[name] = hashlib.sha256(bundle.read(name)).hexdigest()

    stale = []
    missing = []
    mismatched = []
    present = []
    for name in sorted(MANAGED_MEMBERS):
        target = destination / name
        in_archive = name in archive_members
        exists = target.is_file()
        if exists:
            present.append(name)
        if exists and not in_archive:
            stale.append(name)
        elif in_archive and not exists:
            missing.append(name)
        elif in_archive and exists and _sha256(target) != archive_digests[name]:
            mismatched.append(name)

    blockers = []
    blockers.extend(f"stale_managed_member:{name}" for name in stale)
    blockers.extend(f"missing_restored_member:{name}" for name in missing)
    blockers.extend(f"restored_member_digest_mismatch:{name}" for name in mismatched)
    return {
        "status": "VALID" if not blockers else "INVALID",
        "schema_version": 2,
        "archive_sha256": hashlib.sha256(raw).hexdigest(),
        "managed_member_count": len(MANAGED_MEMBERS),
        "archive_managed_members": sorted(MANAGED_MEMBERS & archive_members),
        "present_managed_members": present,
        "excluded_transport_metadata": sorted(TRANSPORT_METADATA & archive_members),
        "stale_managed_members": stale,
        "missing_restored_members": missing,
        "digest_mismatches": mismatched,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_restored_inventory(args.archive, args.destination)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        report = {"status": "INVALID", "schema_version": 2, "blockers": [f"inventory_input_error:{exc}"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
