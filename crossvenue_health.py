#!/usr/bin/env python3
"""Summarize prospective cross-venue evidence and collector health without changing the frozen contract."""
import argparse
import json
import time
from pathlib import Path

DAY_MS = 86_400_000
MIN_PERIODS = 200
MIN_DAYS = 56
STALE_MULTIPLIER = 3
CADENCE_MS = 300_000
RECENT_WINDOW_MS = 3_600_000
RECENT_GRACE_MS = 120_000
RECENT_MIN_COVERAGE = 0.90
COINS = ("BTC", "ETH")

REQUIRED_DATA = (
    "crossvenue_experiment_freeze.json",
    "crossvenue_snapshots.jsonl",
    "crossvenue_events.jsonl",
    "crossvenue_settled_events.jsonl",
    "crossvenue_pnl_events.jsonl",
)
REQUIRED_REPORTS = (
    "crossvenue_actions_health.json",
    "crossvenue_chain.json",
    "crossvenue_coverage.json",
    "crossvenue_validation.json",
    "crossvenue_promotion.json",
)


def read_json(path, default=None):
    target = Path(path)
    return default if not target.exists() else json.loads(target.read_text())


def read_jsonl(path):
    target = Path(path)
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text().splitlines() if line.strip()]


def row_time(row):
    for key in ("captured_at_ms", "funding_boundary_ms", "boundary_ms", "entry_time_ms",
                "signal_time_ms", "time"):
        if row.get(key) is not None:
            return int(row[key])
    return 0


def unique_periods(rows):
    keys = set()
    for row in rows:
        if row.get("pnl_status") != "complete":
            continue
        boundary = row.get("funding_boundary_ms")
        if boundary is None:
            boundary = row.get("hyperliquid_funding_time_ms") or row.get("okx_funding_time_ms")
        if boundary is not None:
            keys.add(int(boundary))
    return len(keys)


def missing_files(root, names):
    return [name for name in names if not (Path(root) / name).is_file()]


def recent_snapshot_cadence(rows, cutoff_ms, now_ms):
    """Audit the last hour of actual BTC/ETH snapshot slots after startup warm-up."""
    if not cutoff_ms or now_ms - cutoff_ms < RECENT_WINDOW_MS:
        return {
            "status": "WARMING_UP",
            "healthy": True,
            "window_minutes": RECENT_WINDOW_MS / 60_000,
            "minimum_coverage": RECENT_MIN_COVERAGE,
        }

    window_start = max(cutoff_ms, now_ms - RECENT_WINDOW_MS)
    first_slot = (window_start // CADENCE_MS + 1) * CADENCE_MS
    last_slot = ((now_ms - RECENT_GRACE_MS) // CADENCE_MS) * CADENCE_MS
    slots = list(range(first_slot, last_slot + 1, CADENCE_MS)) if last_slot >= first_slot else []
    expected = {(slot, coin) for slot in slots for coin in COINS}

    observed = []
    for row in rows:
        slot = row.get("cadence_slot_ms")
        coin = row.get("coin")
        if slot is None or coin not in COINS:
            continue
        key = (int(slot), coin)
        if key in expected:
            observed.append(key)

    unique = set(observed)
    complete_slots = sum(all((slot, coin) in unique for coin in COINS) for slot in slots)
    expected_rows = len(expected)
    row_coverage = len(unique) / expected_rows if expected_rows else 1.0
    slot_coverage = complete_slots / len(slots) if slots else 1.0
    missing = sorted(expected - unique)
    duplicate_rows = len(observed) - len(unique)
    healthy = (
        bool(slots)
        and row_coverage >= RECENT_MIN_COVERAGE
        and slot_coverage >= RECENT_MIN_COVERAGE
        and duplicate_rows == 0
    )
    return {
        "status": "HEALTHY" if healthy else "INVALID",
        "healthy": healthy,
        "window_minutes": RECENT_WINDOW_MS / 60_000,
        "grace_minutes": RECENT_GRACE_MS / 60_000,
        "minimum_coverage": RECENT_MIN_COVERAGE,
        "first_expected_slot_ms": first_slot if slots else None,
        "last_expected_slot_ms": last_slot if slots else None,
        "expected_slots": len(slots),
        "complete_slots": complete_slots,
        "expected_rows": expected_rows,
        "observed_rows": len(unique),
        "missing_rows": len(missing),
        "duplicate_rows": duplicate_rows,
        "row_coverage": row_coverage,
        "complete_slot_coverage": slot_coverage,
        "missing_examples": [
            {"cadence_slot_ms": slot, "coin": coin} for slot, coin in missing[:10]
        ],
    }


def summarize(data_dir, reports_dir, now_ms=None):
    data_dir, reports_dir = Path(data_dir), Path(reports_dir)
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    missing_data = missing_files(data_dir, REQUIRED_DATA)
    missing_reports = missing_files(reports_dir, REQUIRED_REPORTS)

    manifest = read_json(data_dir / "crossvenue_experiment_freeze.json", {}) or {}
    snapshots = read_jsonl(data_dir / "crossvenue_snapshots.jsonl")
    events = read_jsonl(data_dir / "crossvenue_events.jsonl")
    settlements = read_jsonl(data_dir / "crossvenue_settled_events.jsonl")
    pnl = read_jsonl(data_dir / "crossvenue_pnl_events.jsonl")
    actions_health = read_json(reports_dir / "crossvenue_actions_health.json", {}) or {}
    chain = read_json(reports_dir / "crossvenue_chain.json", {}) or {}
    coverage = read_json(reports_dir / "crossvenue_coverage.json", {}) or {}
    validation = read_json(reports_dir / "crossvenue_validation.json", {}) or {}
    promotion = read_json(reports_dir / "crossvenue_promotion.json", {}) or {}

    cutoff = int(manifest.get("evidence_cutoff_ms") or 0)
    post_snapshots = [r for r in snapshots if row_time(r) > cutoff]
    recent_cadence = recent_snapshot_cadence(snapshots, cutoff, now_ms)
    complete_settlements = sum(r.get("settlement_status") == "complete" for r in settlements)
    complete_pnl = sum(r.get("pnl_status") == "complete" for r in pnl)
    complete_periods = unique_periods(pnl)
    last_snapshot_ms = max((row_time(r) for r in snapshots), default=0)
    stale_minutes = ((now_ms - last_snapshot_ms) / 60_000) if last_snapshot_ms else None
    stale = last_snapshot_ms == 0 or now_ms - last_snapshot_ms > STALE_MULTIPLIER * CADENCE_MS
    span_days = float(coverage.get("collection_span_days") or 0)

    blockers = []
    if missing_data:
        blockers.append("required_data_missing")
    if missing_reports:
        blockers.append("required_reports_missing")
    if not manifest:
        blockers.append("freeze_manifest_missing")
    if not actions_health:
        blockers.append("actions_health_missing")
    elif actions_health.get("status") != "HEALTHY":
        blockers.append("collector_workflow_unhealthy")
    if not chain:
        blockers.append("artifact_chain_missing")
    elif not chain.get("valid", False):
        blockers.append("artifact_chain_invalid")
    if stale:
        blockers.append("collection_stale")
    if not recent_cadence["healthy"]:
        blockers.append("recent_snapshot_cadence_unhealthy")
    if coverage.get("duplicate_rows", 0):
        blockers.append("snapshot_duplicates")
    if validation.get("status") == "INVALID":
        blockers.append("validation_invalid")
    if promotion.get("status") == "INVALID":
        blockers.append("promotion_invalid")
    if complete_pnl > complete_settlements:
        blockers.append("pnl_settlement_count_inconsistent")
    if complete_periods > complete_pnl:
        blockers.append("period_count_inconsistent")

    periods_remaining = max(0, MIN_PERIODS - complete_periods)
    days_remaining = max(0.0, MIN_DAYS - span_days)
    if blockers:
        status = "INVALID"
    elif promotion.get("status") == "PASS":
        status = "PROMOTABLE"
    elif complete_periods >= MIN_PERIODS and span_days >= MIN_DAYS:
        status = "AWAITING_VERDICT"
    elif complete_pnl:
        status = "ACCUMULATING_PNL"
    elif events:
        status = "ACCUMULATING_EVENTS"
    else:
        status = "ACCUMULATING_SNAPSHOTS"

    return {
        "status": status,
        "generated_at_ms": now_ms,
        "freeze": {"schema": manifest.get("schema"), "frozen_at_ms": manifest.get("frozen_at_ms"),
                   "evidence_cutoff_ms": cutoff, "files": len(manifest.get("files") or {})},
        "counts": {"snapshots": len(snapshots), "post_freeze_snapshots": len(post_snapshots),
                   "events": len(events), "settlements": len(settlements),
                   "complete_settlements": complete_settlements, "pnl_rows": len(pnl),
                   "complete_pnl_rows": complete_pnl, "complete_periods": complete_periods},
        "collection": {"span_days": span_days, "last_snapshot_ms": last_snapshot_ms,
                       "stale_minutes": stale_minutes, "slot_coverage": coverage.get("slot_coverage"),
                       "complete_slot_coverage": coverage.get("complete_slot_coverage"),
                       "event_accounting": coverage.get("event_accounting"),
                       "recent_cadence": recent_cadence},
        "operations": {
            "status": actions_health.get("status"),
            "latest_run": actions_health.get("latest_run"),
            "latest_success": actions_health.get("latest_success"),
            "active": actions_health.get("active"),
            "failures": actions_health.get("failures"),
            "restoration": actions_health.get("restoration"),
            "blockers": actions_health.get("blockers", []),
        },
        "integrity": {"required_data_present": not missing_data,
                      "required_reports_present": not missing_reports,
                      "missing_data": missing_data, "missing_reports": missing_reports,
                      "chain_present": bool(chain), "chain_valid": chain.get("valid"),
                      "chain_errors": chain.get("errors", []), "blockers": blockers},
        "progress": {"minimum_periods": MIN_PERIODS, "periods_remaining": periods_remaining,
                     "minimum_days": MIN_DAYS, "days_remaining": days_remaining},
        "verdicts": {"coverage": coverage.get("status"), "validation": validation.get("status"),
                     "promotion": promotion.get("status")},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--out", default="reports/crossvenue_health.json")
    a = p.parse_args()
    report = summarize(a.data_dir, a.reports_dir)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    if report["status"] == "INVALID":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
