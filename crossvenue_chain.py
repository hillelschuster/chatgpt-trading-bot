#!/usr/bin/env python3
"""Verify that restored prospective evidence remains append-only across workflow runs."""
import argparse, json
from pathlib import Path

FILES = {
    "snapshots": "crossvenue_snapshots.jsonl",
    "events": "crossvenue_events.jsonl",
    "settlements": "crossvenue_settled_events.jsonl",
}
EVENT_CORE = (
    "event_id", "schema_version", "coin", "signal_time_ms", "entry_target_ms",
    "exit_target_ms", "hyperliquid_funding_time_ms", "okx_funding_time_ms",
    "predicted_funding", "direction", "signal_books", "entry", "exit",
)
TERMINAL_EVENT = {"complete", "rejected"}


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def snapshot_key(row):
    return int(row["cadence_slot_ms"]), row["coin"]


def event_map(rows):
    return {row["event_id"]: row for row in rows if row.get("event_id")}


def same_fields(left, right, fields):
    return all(left.get(field) == right.get(field) for field in fields)


def audit(previous_dir, current_dir, require_previous=False):
    previous_dir, current_dir = Path(previous_dir), Path(current_dir)
    previous = {name: read_jsonl(previous_dir / filename) for name, filename in FILES.items()}
    current = {name: read_jsonl(current_dir / filename) for name, filename in FILES.items()}
    previous_present = any(previous.values())
    errors = []

    if require_previous and not previous_present:
        errors.append("previous_artifact_missing")

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

    return {
        "valid": not errors,
        "previous_artifact_present": previous_present,
        "errors": errors,
        "previous": {name: len(rows) for name, rows in previous.items()},
        "current": {name: len(rows) for name, rows in current.items()},
        "new_snapshots": len(new_snapshots) - len(old_snapshots),
        "new_events": len(new_events) - len(old_events),
        "newly_settled": newly_settled,
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
