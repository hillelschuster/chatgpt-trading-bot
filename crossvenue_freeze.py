#!/usr/bin/env python3
"""Freeze the prospective experiment contract and reject later research-logic drift."""
import argparse
import hashlib
import json
import time
from pathlib import Path

SCHEMA = "crossvenue-experiment-freeze-v2"
DEFAULT_FILES = (
    "CROSS_VENUE_EXPERIMENT.md",
    ".github/workflows/crossvenue-probe.yml",
    "crossvenue_snapshot.py",
    "crossvenue_events.py",
    "crossvenue_settlements.py",
    "crossvenue_pnl.py",
    "crossvenue_validate.py",
    "crossvenue_coverage.py",
    "crossvenue_promote.py",
    "crossvenue_chain.py",
    "crossvenue_freeze.py",
)


def sha256_file(path):
    target = Path(path)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def read_jsonl(path):
    target = Path(path)
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text().splitlines() if line.strip()]


def event_time(row):
    for key in ("funding_boundary_ms", "boundary_ms", "entry_time_ms", "signal_time_ms", "time"):
        if row.get(key) is not None:
            return int(row[key])
    return 0


def latest_evidence_ms(paths):
    return max((event_time(row) for path in paths for row in read_jsonl(path)), default=0)


def has_complete_evidence(paths):
    return any(row.get("pnl_status") == "complete" for path in paths for row in read_jsonl(path))


def new_manifest(hashes, evidence_paths, now_ms):
    return {
        "schema": SCHEMA,
        "frozen_at_ms": int(now_ms if now_ms is not None else time.time() * 1000),
        "evidence_cutoff_ms": latest_evidence_ms(evidence_paths),
        "files": hashes,
        "rule": "Only attempts strictly after evidence_cutoff_ms are eligible for promotion.",
    }


def verify_or_create(manifest_path, files=DEFAULT_FILES, evidence_paths=(), now_ms=None,
                     allow_safe_upgrade=False):
    manifest_path = Path(manifest_path)
    hashes = {str(path): sha256_file(path) for path in files}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        expected = manifest.get("files") or {}
        changed = {path: {"expected": expected.get(path), "actual": digest}
                   for path, digest in hashes.items() if expected.get(path) != digest}
        missing = sorted(set(expected) - set(hashes))
        schema_changed = manifest.get("schema") != SCHEMA
        if changed or missing or schema_changed:
            if not allow_safe_upgrade or has_complete_evidence(evidence_paths):
                raise ValueError(json.dumps({"schema_changed": schema_changed,
                                             "changed": changed, "missing": missing}, sort_keys=True))
            manifest = new_manifest(hashes, evidence_paths, now_ms)
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            return manifest, True
        return manifest, False

    manifest = new_manifest(hashes, evidence_paths, now_ms)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest, True


def write_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/crossvenue_experiment_freeze.json")
    parser.add_argument("--report", default="reports/crossvenue_freeze.json")
    parser.add_argument("--file", action="append", dest="files")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--allow-safe-upgrade", action="store_true",
                        help="re-freeze changed logic only while no complete P&L evidence exists")
    args = parser.parse_args()
    manifest, created = verify_or_create(
        args.manifest, tuple(args.files or DEFAULT_FILES), tuple(args.evidence),
        allow_safe_upgrade=args.allow_safe_upgrade)
    report = {
        "status": "FROZEN",
        "created_or_upgraded": created,
        "manifest": args.manifest,
        "schema": manifest["schema"],
        "frozen_at_ms": manifest["frozen_at_ms"],
        "evidence_cutoff_ms": manifest["evidence_cutoff_ms"],
        "files": manifest["files"],
    }
    write_json(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
