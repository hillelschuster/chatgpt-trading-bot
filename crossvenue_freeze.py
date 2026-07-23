#!/usr/bin/env python3
"""Freeze the prospective experiment contract and reject later research-logic drift."""
import argparse
import hashlib
import json
import time
from pathlib import Path

DEFAULT_FILES = (
    "CROSS_VENUE_EXPERIMENT.md",
    "crossvenue_snapshot.py",
    "crossvenue_events.py",
    "crossvenue_settlements.py",
    "crossvenue_pnl.py",
    "crossvenue_validate.py",
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
    latest = 0
    for path in paths:
        for row in read_jsonl(path):
            latest = max(latest, event_time(row))
    return latest


def verify_or_create(manifest_path, files=DEFAULT_FILES, evidence_paths=(), now_ms=None):
    manifest_path = Path(manifest_path)
    hashes = {str(path): sha256_file(path) for path in files}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        expected = manifest.get("files") or {}
        changed = {path: {"expected": expected.get(path), "actual": digest}
                   for path, digest in hashes.items() if expected.get(path) != digest}
        missing = sorted(set(expected) - set(hashes))
        if changed or missing:
            raise ValueError(json.dumps({"changed": changed, "missing": missing}, sort_keys=True))
        return manifest, False

    manifest = {
        "schema": "crossvenue-experiment-freeze-v1",
        "frozen_at_ms": int(now_ms if now_ms is not None else time.time() * 1000),
        "evidence_cutoff_ms": latest_evidence_ms(evidence_paths),
        "files": hashes,
        "rule": "Only attempts strictly after evidence_cutoff_ms are eligible for promotion.",
    }
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
    args = parser.parse_args()
    manifest, created = verify_or_create(
        args.manifest, tuple(args.files or DEFAULT_FILES), tuple(args.evidence))
    report = {
        "status": "FROZEN",
        "created": created,
        "manifest": args.manifest,
        "frozen_at_ms": manifest["frozen_at_ms"],
        "evidence_cutoff_ms": manifest["evidence_cutoff_ms"],
        "files": manifest["files"],
    }
    write_json(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
