#!/usr/bin/env python3
"""Build leakage-safe funding-event windows from prospective cross-venue snapshots."""
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path

from crossvenue_snapshot import DEFAULT_CADENCE_MS, SCHEMA_VERSION, read_jsonl, validate

MIN_SIGNAL_LEAD_MS = 10 * 60_000
ENTRY_DELAY_MS = 60_000
SETTLEMENT_DELAY_MS = 60_000
MAX_SAMPLE_LAG_MS = DEFAULT_CADENCE_MS
MAX_COORDINATION_SKEW_MS = 5_000


def event_key(row):
    hl = row.get("hyperliquid") or {}
    okx = row.get("okx_swap") or {}
    hlt = hl.get("effective_next_funding_time_ms")
    okt = okx.get("funding_time_ms")
    if hlt is None or okt is None:
        return None
    return row.get("coin"), int(hlt), int(okt)


def first_at_or_after(rows, target_ms, max_lag_ms=MAX_SAMPLE_LAG_MS):
    candidates = [row for row in rows if int(row["captured_at_ms"]) >= target_ms]
    if not candidates:
        return None
    row = min(candidates, key=lambda item: int(item["captured_at_ms"]))
    return row if int(row["captured_at_ms"]) - target_ms <= max_lag_ms else None


def coordinated(row, max_skew_ms=MAX_COORDINATION_SKEW_MS):
    stamps = [int((row.get(venue) or {}).get("book_time_ms") or 0)
              for venue in ("hyperliquid", "okx_swap")]
    return all(stamps) and max(stamps) - min(stamps) <= max_skew_ms


def entry_prices(row, long_venue):
    hl, okx = row["hyperliquid"], row["okx_swap"]
    if long_venue == "hyperliquid":
        return {"long_entry_price": hl["ask"], "short_entry_price": okx["bid"]}
    return {"long_entry_price": okx["ask"], "short_entry_price": hl["bid"]}


def exit_prices(row, long_venue):
    hl, okx = row["hyperliquid"], row["okx_swap"]
    if long_venue == "hyperliquid":
        return {"long_exit_price": hl["bid"], "short_exit_price": okx["ask"]}
    return {"long_exit_price": okx["bid"], "short_exit_price": hl["ask"]}


def direction(signal):
    hl_rate = float(signal["hyperliquid"]["predicted_funding_rate"])
    okx_rate = float(signal["okx_swap"]["predicted_funding_rate"])
    long_venue = "hyperliquid" if hl_rate <= okx_rate else "okx_swap"
    return long_venue, hl_rate, okx_rate


def build_events(rows, min_signal_lead_ms=MIN_SIGNAL_LEAD_MS,
                 entry_delay_ms=ENTRY_DELAY_MS, settlement_delay_ms=SETTLEMENT_DELAY_MS,
                 max_sample_lag_ms=MAX_SAMPLE_LAG_MS,
                 max_coordination_skew_ms=MAX_COORDINATION_SKEW_MS):
    clean = [row for row in rows if row.get("schema_version") == SCHEMA_VERSION and not validate(row)]
    by_coin = defaultdict(list)
    for row in clean:
        by_coin[row["coin"]].append(row)
    events, reasons = [], Counter()

    for coin, coin_rows in sorted(by_coin.items()):
        coin_rows.sort(key=lambda row: int(row["captured_at_ms"]))
        grouped = defaultdict(list)
        for row in coin_rows:
            key = event_key(row)
            if key:
                grouped[key].append(row)
        for key, candidates in sorted(grouped.items(), key=lambda item: item[0][1:]):
            _, hl_boundary, okx_boundary = key
            earliest = min(hl_boundary, okx_boundary)
            eligible = [row for row in candidates
                        if int(row["captured_at_ms"]) <= earliest - min_signal_lead_ms]
            if not eligible:
                reasons["no_signal_with_required_lead"] += 1
                continue
            signal = max(eligible, key=lambda row: int(row["captured_at_ms"]))
            entry_target = int(signal["captured_at_ms"]) + entry_delay_ms
            exit_target = max(hl_boundary, okx_boundary) + settlement_delay_ms
            entry = first_at_or_after(coin_rows, entry_target, max_sample_lag_ms)
            exit_ = first_at_or_after(coin_rows, exit_target, max_sample_lag_ms)
            status, reason = "complete", None
            if entry is None:
                status, reason = "pending", "entry_snapshot_missing"
            elif not coordinated(entry, max_coordination_skew_ms):
                status, reason = "rejected", "entry_books_not_coordinated"
            elif exit_ is None:
                status, reason = "pending", "exit_snapshot_missing"
            elif not coordinated(exit_, max_coordination_skew_ms):
                status, reason = "rejected", "exit_books_not_coordinated"
            if reason:
                reasons[reason] += 1

            long_venue, hl_rate, okx_rate = direction(signal)
            event = {
                "event_id": f"{coin}:{hl_boundary}:{okx_boundary}",
                "schema_version": 1,
                "coin": coin,
                "status": status,
                "reason": reason,
                "signal_time_ms": int(signal["captured_at_ms"]),
                "entry_target_ms": entry_target,
                "exit_target_ms": exit_target,
                "hyperliquid_funding_time_ms": hl_boundary,
                "okx_funding_time_ms": okx_boundary,
                "predicted_funding": {"hyperliquid": hl_rate, "okx_swap": okx_rate,
                                      "difference_hl_minus_okx": hl_rate - okx_rate},
                "direction": {"long_venue": long_venue,
                              "short_venue": "okx_swap" if long_venue == "hyperliquid" else "hyperliquid"},
                "signal_books": {
                    "hyperliquid": {k: signal["hyperliquid"][k] for k in ("bid", "ask", "book_time_ms")},
                    "okx_swap": {k: signal["okx_swap"][k] for k in ("bid", "ask", "book_time_ms")}},
                "entry": None,
                "exit": None,
            }
            if entry is not None:
                event["entry"] = {"captured_at_ms": int(entry["captured_at_ms"]),
                                  **entry_prices(entry, long_venue),
                                  "coordinated": coordinated(entry, max_coordination_skew_ms)}
            if exit_ is not None:
                event["exit"] = {"captured_at_ms": int(exit_["captured_at_ms"]),
                                 **exit_prices(exit_, long_venue),
                                 "coordinated": coordinated(exit_, max_coordination_skew_ms)}
            events.append(event)

    summary = {"input_rows": len(rows), "valid_rows": len(clean), "events": len(events),
               "complete": sum(e["status"] == "complete" for e in events),
               "pending": sum(e["status"] == "pending" for e in events),
               "rejected": sum(e["status"] == "rejected" for e in events),
               "reasons": dict(sorted(reasons.items()))}
    return events, summary


def write_jsonl(path, rows):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n"
                              for row in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="data/crossvenue_snapshots.jsonl")
    parser.add_argument("--out", default="data/crossvenue_events.jsonl")
    parser.add_argument("--report", default="reports/crossvenue_events.json")
    args = parser.parse_args()
    events, summary = build_events(read_jsonl(args.path))
    write_jsonl(args.out, events)
    report = Path(args.report); report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"out": args.out, "report": args.report, **summary}, indent=2))


if __name__ == "__main__":
    main()
