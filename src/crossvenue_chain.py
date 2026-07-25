#!/usr/bin/env python3
"""Verify that restored prospective evidence remains append-only across workflow runs."""
import argparse, json
from pathlib import Path

FILES = {
    "snapshots": "crossvenue_snapshots.jsonl",
    "events": "crossvenue_events.jsonl",
    "settlements": "crossvenue_settled_events.jsonl",
    "pnl": "crossvenue_pnl_events.jsonl",
}
MANIFEST = "crossvenue_experiment_freeze.json"
EVENT_CORE = (
    "event_id", "schema_version", "coin", "signal_time_ms", "entry_target_ms",
    "exit_target_ms", "hyperliquid_funding_time_ms", "okx_funding_time_ms",
    "predicted_funding", "direction", "signal_books", "entry", "exit",
)
TERMINAL_EVENT = {"complete", "rejected"}
TERMINAL_PNL = {"complete", "failed_attempt", "invalid"}


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_json(path):
    path = Path(path)
    return None if not path.exists() else json.loads(path.read_text())


def snapshot_key(row):
    return int(row["cadence_slot_ms"]), row["coin"]


def event_map(rows):
    return {row["event_id"]: row for row in rows if row.get("event_id")}


def same_fields(left, right, fields):
    return all(left.get(field) == right.get(field) for field in fields)


def safe_manifest_upgrade(old, new, old_pnl):
    if not old or not new or old == new:
        return False
    if any(row.get("pnl_status") == "complete" for row in old_pnl):
        return False
    return (int(new.get("frozen_at_ms") or 0) >= int(old.get("frozen_at_ms") or 0)
            and int(new.get("evidence_cutoff_ms") or 0) >= int(old.get("evidence_cutoff_ms") or 0)
            and bool(new.get("files")))


def audit(previous_dir, current_dir, require_previous=False):
    previous_dir, current_dir = Path(previous_dir), Path(current_dir)
    previous = {name: read_jsonl(previous_dir / filename) for name, filename in FILES.items()}
    current = {name: read_jsonl(current_dir / filename) for name, filename in FILES.items()}
    old_manifest = read_json(previous_dir / MANIFEST)
    new_manifest = read_json(current_dir / MANIFEST)
    previous_present = any(previous.values()) or old_manifest is not None
    errors = []

    if require_previous and not previous_present:
        errors.append("previous_artifact_missing")

    manifest_upgraded = False
    if old_manifest is not None:
        if new_manifest is None:
            errors.append("freeze_manifest_removed")
        elif old_manifest != new_manifest:
            if safe_manifest_upgrade(old_manifest, new_manifest, previous["pnl"]):
                manifest_upgraded = True
            else:
                errors.append("freeze_manifest_mutated")

    old_snapshots = {snapshot_key(row): row for row in previous["snapshots"]}
    new_snapshots = {snapshot_key(row): row for row in current["snapshots"]}
    if len(old_snapshots) != len(previous["snapshots"]):
        errors.append("previous_snapshot_duplicates")
    if len(new_snapshots) != len(current["snapshots"]):
        errors.append("current_snapshot_duplicates")
    for key, row in old_snapshots.items():
        if key not in new_snapshots:
            errors.append(f"snapshot_removed:{key[0]}:{key[1]}")
        elif new_snapshots[key] != row:
            errors.append(f"snapshot_mutated:{key[0]}:{key[1]}")

    old_events, new_events = event_map(previous["events"]), event_map(current["events"])
    if len(old_events) != len(previous["events"]):
        errors.append("previous_event_duplicates")
    if len(new_events) != len(current["events"]):
        errors.append("current_event_duplicates")
    for event_id, old in old_events.items():
        new = new_events.get(event_id)
        if new is None:
            errors.append(f"event_removed:{event_id}")
            continue
        if not same_fields(old, new, EVENT_CORE):
            errors.append(f"event_core_mutated:{event_id}")
        old_status, new_status = old.get("status"), new.get("status")
        if old_status in TERMINAL_EVENT and new_status != old_status:
            errors.append(f"event_terminal_changed:{event_id}:{old_status}:{new_status}")

    old_settled, new_settled = event_map(previous["settlements"]), event_map(current["settlements"])
    if len(old_settled) != len(previous["settlements"]):
        errors.append("previous_settlement_duplicates")
    if len(new_settled) != len(current["settlements"]):
        errors.append("current_settlement_duplicates")
    newly_settled = 0
    for event_id, old in old_settled.items():
        new = new_settled.get(event_id)
        if new is None:
            errors.append(f"settlement_removed:{event_id}")
            continue
        old_obs = old.get("settlement_observations") or {}
        new_obs = new.get("settlement_observations") or {}
        for venue, observation in old_obs.items():
            if observation is not None and new_obs.get(venue) != observation:
                errors.append(f"settlement_observation_changed:{event_id}:{venue}")
        if old.get("settlement_status") == "complete" and new.get("settlement_status") != "complete":
            errors.append(f"settlement_downgraded:{event_id}")
        if int(new.get("settlement_attempts") or 0) < int(old.get("settlement_attempts") or 0):
            errors.append(f"settlement_attempts_decreased:{event_id}")
        if old.get("settlement_status") != "complete" and new.get("settlement_status") == "complete":
            newly_settled += 1

    old_pnl, new_pnl = event_map(previous["pnl"]), event_map(current["pnl"])
    if len(old_pnl) != len(previous["pnl"]):
        errors.append("previous_pnl_duplicates")
    if len(new_pnl) != len(current["pnl"]):
        errors.append("current_pnl_duplicates")
    newly_scored = 0
    for event_id, old in old_pnl.items():
        new = new_pnl.get(event_id)
        if new is None:
            errors.append(f"pnl_removed:{event_id}")
            continue
        old_status, new_status = old.get("pnl_status"), new.get("pnl_status")
        if not same_fields(old, new, EVENT_CORE):
            errors.append(f"pnl_core_mutated:{event_id}")
        if old.get("experiment_freeze") != new.get("experiment_freeze") and not (
                manifest_upgraded and old_status not in TERMINAL_PNL):
            errors.append(f"pnl_freeze_changed:{event_id}")
        if old_status in TERMINAL_PNL and new != old:
            errors.append(f"pnl_terminal_changed:{event_id}:{old_status}:{new_status}")
        if old_status not in TERMINAL_PNL and new_status in TERMINAL_PNL:
            newly_scored += 1

    return {
        "valid": not errors,
        "previous_artifact_present": previous_present,
        "freeze_manifest_present": new_manifest is not None,
        "freeze_manifest_upgraded": manifest_upgraded,
        "errors": errors,
        "previous": {name: len(rows) for name, rows in previous.items()},
        "current": {name: len(rows) for name, rows in current.items()},
        "new_snapshots": len(new_snapshots) - len(old_snapshots),
        "new_events": len(new_events) - len(old_events),
        "newly_settled": newly_settled,
        "newly_scored": newly_scored,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-dir", required=True)
    parser.add_argument("--current-dir", required=True)
    parser.add_argument("--report", default="reports/crossvenue_chain.json")
    parser.add_argument("--require-previous", action="store_true")
    args = parser.parse_args()
    report = audit(args.previous_dir, args.current_dir, args.require_previous)
    target = Path(args.report); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2))
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
