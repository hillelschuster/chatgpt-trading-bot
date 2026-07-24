#!/usr/bin/env python3
"""Bind a downloaded prospective artifact to its persisted selection report."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def verify(archive: Path, restoration: dict) -> dict:
    actual_sha256, actual_bytes = sha256_file(archive)
    blockers = []
    if restoration.get("status") != "downloaded":
        blockers.append("restoration_not_downloaded")
    if restoration.get("schema_version") != 2:
        blockers.append("unsupported_restoration_schema")
    if restoration.get("archive_sha256") != actual_sha256:
        blockers.append("archive_sha256_mismatch")
    if restoration.get("archive_bytes") != actual_bytes:
        blockers.append("archive_size_mismatch")
    for field in ("artifact_id", "workflow_run_id", "created_at", "branch", "workflow_path"):
        if restoration.get(field) in (None, ""):
            blockers.append(f"missing_restoration_{field}")
    return {
        "status": "VALID" if not blockers else "INVALID",
        "schema_version": 1,
        "archive_sha256": actual_sha256,
        "archive_bytes": actual_bytes,
        "artifact_id": restoration.get("artifact_id"),
        "workflow_run_id": restoration.get("workflow_run_id"),
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--restoration", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        restoration = json.loads(args.restoration.read_text(encoding="utf-8"))
        report = verify(args.archive, restoration)
    except (OSError, json.JSONDecodeError) as exc:
        report = {"status": "INVALID", "schema_version": 1, "blockers": [str(exc)]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
