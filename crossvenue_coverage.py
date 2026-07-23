#!/usr/bin/env python3
"""Measure post-freeze cadence and event-opportunity coverage without using returns."""
import argparse, json
from collections import defaultdict
from pathlib import Path

CADENCE_MS = 300_000
MIN_COLLECTION_DAYS = 56
MIN_SLOT_COVERAGE = 0.95
MIN_COMPLETE_SLOT_COVERAGE = 0.95
MIN_EVENT_ACCOUNTING = 1.0
DAY_MS = 86_400_000
MIN_SIGNAL_LEAD_MS = 10 * 60_000


def read_jsonl(path):
    target = Path(path)
    return [] if not target.exists() else [json.loads(x) for x in target.read_text().splitlines() if x.strip()]


def read_json(path):
    return json.loads(Path(path).read_text())


def as_int(value, default=0):
    return default if value is None else int(value)


def boundary_key(row):
    hl = row.get("hyperliquid") or {}
    okx = row.get("okx_swap") or {}
    hlt = hl.get("effective_next_funding_time_ms")
    okt = okx.get("funding_time_ms")
    return None if hlt is None or okt is None else (str(row.get("coin")), int(hlt), int(okt))


def coverage(snapshots, events, freeze, coins=("BTC", "ETH"), cadence_ms=CADENCE_MS):
    cutoff = as_int(freeze.get("evidence_cutoff_ms"), 0)
    expected_coins = {str(c).upper() for c in coins}
    rows = [r for r in snapshots if as_int(r.get("captured_at_ms"), 0) > cutoff
            and str(r.get("coin") or "").upper() in expected_coins]
    keys = [(as_int(r.get("cadence_slot_ms"), -1), str(r.get("coin") or "").upper()) for r in rows]
    duplicate_rows = len(keys) - len(set(keys))
    slots = sorted({slot for slot, _ in keys if slot >= 0})
    first_slot = slots[0] if slots else None
    last_slot = slots[-1] if slots else None
    expected_slots = ((last_slot - first_slot) // cadence_ms + 1) if slots else 0
    by_slot = defaultdict(set)
    for slot, coin in keys:
        if slot >= 0:
            by_slot[slot].add(coin)
    observed_coin_slots = len({key for key in keys if key[0] >= 0})
    expected_coin_slots = expected_slots * len(expected_coins)
    complete_slots = sum(by_slot[slot] == expected_coins for slot in slots)
    slot_coverage = observed_coin_slots / expected_coin_slots if expected_coin_slots else 0.0
    complete_slot_coverage = complete_slots / expected_slots if expected_slots else 0.0
    span_days = ((last_slot - first_slot) / DAY_MS) if len(slots) > 1 else 0.0

    opportunities = set()
    for row in rows:
        key = boundary_key(row)
        if key and as_int(row.get("captured_at_ms"), 0) <= min(key[1], key[2]) - MIN_SIGNAL_LEAD_MS:
            opportunities.add(key)
    event_keys = {(str(e.get("coin")), as_int(e.get("hyperliquid_funding_time_ms"), 0),
                   as_int(e.get("okx_funding_time_ms"), 0)) for e in events}
    accounted = len(opportunities & event_keys)
    event_accounting = accounted / len(opportunities) if opportunities else 0.0

    integrity_ok = duplicate_rows == 0
    coverage_ok = (slot_coverage >= MIN_SLOT_COVERAGE
                   and complete_slot_coverage >= MIN_COMPLETE_SLOT_COVERAGE
                   and event_accounting >= MIN_EVENT_ACCOUNTING)
    ready = span_days >= MIN_COLLECTION_DAYS
    status = "PASS" if ready and integrity_ok and coverage_ok else "INVALID" if ready else "COLLECTING"
    return {
        "status": status,
        "promotion_coverage_valid": status == "PASS",
        "contract": {"cadence_ms": cadence_ms, "minimum_collection_days": MIN_COLLECTION_DAYS,
                     "minimum_slot_coverage": MIN_SLOT_COVERAGE,
                     "minimum_complete_slot_coverage": MIN_COMPLETE_SLOT_COVERAGE,
                     "minimum_event_accounting": MIN_EVENT_ACCOUNTING,
                     "coins": sorted(expected_coins)},
        "evidence_cutoff_ms": cutoff, "first_slot_ms": first_slot, "last_slot_ms": last_slot,
        "collection_span_days": span_days, "rows": len(rows), "duplicate_rows": duplicate_rows,
        "expected_slots": expected_slots, "observed_slots": len(slots),
        "complete_slots": complete_slots, "slot_coverage": slot_coverage,
        "complete_slot_coverage": complete_slot_coverage,
        "eligible_event_opportunities": len(opportunities), "accounted_events": accounted,
        "event_accounting": event_accounting,
        "gates": {"no_duplicate_coin_slots": integrity_ok,
                  "slot_coverage_at_least_95pct": slot_coverage >= MIN_SLOT_COVERAGE,
                  "complete_slot_coverage_at_least_95pct": complete_slot_coverage >= MIN_COMPLETE_SLOT_COVERAGE,
                  "all_observed_event_opportunities_accounted": event_accounting >= MIN_EVENT_ACCOUNTING,
                  "minimum_collection_span_56_days": ready}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshots", default="data/crossvenue_snapshots.jsonl")
    p.add_argument("--events", default="data/crossvenue_events.jsonl")
    p.add_argument("--freeze-manifest", default="data/crossvenue_experiment_freeze.json")
    p.add_argument("--report", default="reports/crossvenue_coverage.json")
    p.add_argument("--coins", default="BTC,ETH")
    a = p.parse_args()
    report = coverage(read_jsonl(a.snapshots), read_jsonl(a.events), read_json(a.freeze_manifest),
                      [x.strip().upper() for x in a.coins.split(",") if x.strip()])
    out = Path(a.report); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__": main()
