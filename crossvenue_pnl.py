#!/usr/bin/env python3
"""Compute frozen two-leg P&L only from exact settled prospective events."""
import argparse, json, math, statistics
from collections import Counter, defaultdict
from pathlib import Path

# Official base-tier taker rates frozen for v1 on 2026-07-23.
HL_TAKER_RATE = 0.00045
OKX_TAKER_RATE = 0.00050
STRESS_TAKER_RATE = 0.00050
BASE_SLIPPAGE_RATE = 0.00020
STRESS_SLIPPAGE_RATE = 0.00040
REBALANCE_RATE = 0.00020
ONE_LEG_FAILURE_RATE = 0.0010


def read_jsonl(path):
    target = Path(path)
    return [] if not target.exists() else [json.loads(x) for x in target.read_text().splitlines() if x.strip()]


def write_jsonl(path, rows):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(x, separators=(",", ":"), allow_nan=False) + "\n" for x in rows))


def finite_positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def exact_rate(event, venue):
    realized = event.get("realized_funding") or {}
    observation = realized.get(venue)
    if not isinstance(observation, dict) or observation.get("rate") is None:
        return None
    try:
        value = float(observation["rate"])
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def fixed_cost_pct(stress=False):
    """Cost as percent of total 50/50 capital, not summed leg notional."""
    hl_fee = STRESS_TAKER_RATE if stress else HL_TAKER_RATE
    okx_fee = STRESS_TAKER_RATE if stress else OKX_TAKER_RATE
    slippage = STRESS_SLIPPAGE_RATE if stress else BASE_SLIPPAGE_RATE
    return 100 * (hl_fee + okx_fee + 2 * slippage + REBALANCE_RATE)


def score_event(source):
    event = dict(source)
    status = event.get("status")
    if status == "rejected":
        event["pnl_status"] = "failed_attempt"
        event["pnl_reason"] = event.get("reason") or "event_rejected"
        loss = -100 * ONE_LEG_FAILURE_RATE / 2
        event["base_net_return_pct"] = loss
        event["stress_net_return_pct"] = loss
        return event
    if status != "complete":
        event["pnl_status"] = "pending"
        event["pnl_reason"] = "event_not_complete"
        return event
    if event.get("settlement_status") != "complete":
        event["pnl_status"] = "pending"
        event["pnl_reason"] = "settlement_not_complete"
        return event

    entry, exit_ = event.get("entry") or {}, event.get("exit") or {}
    prices = {name: finite_positive(value) for name, value in {
        "long_entry": entry.get("long_entry_price"),
        "short_entry": entry.get("short_entry_price"),
        "long_exit": exit_.get("long_exit_price"),
        "short_exit": exit_.get("short_exit_price"),
    }.items()}
    if any(value is None for value in prices.values()):
        event["pnl_status"] = "invalid"
        event["pnl_reason"] = "missing_or_invalid_executable_price"
        return event
    if not entry.get("coordinated") or not exit_.get("coordinated"):
        event["pnl_status"] = "invalid"
        event["pnl_reason"] = "uncoordinated_complete_event"
        return event

    hl_rate, okx_rate = exact_rate(event, "hyperliquid"), exact_rate(event, "okx_swap")
    if hl_rate is None or okx_rate is None:
        event["pnl_status"] = "invalid"
        event["pnl_reason"] = "missing_exact_realized_funding"
        return event
    long_venue = (event.get("direction") or {}).get("long_venue")
    if long_venue not in ("hyperliquid", "okx_swap"):
        event["pnl_status"] = "invalid"
        event["pnl_reason"] = "invalid_direction"
        return event

    long_price = prices["long_exit"] / prices["long_entry"] - 1
    short_price = 1 - prices["short_exit"] / prices["short_entry"]
    price_return_pct = 50 * (long_price + short_price)
    funding_return_pct = (50 * (okx_rate - hl_rate) if long_venue == "hyperliquid"
                          else 50 * (hl_rate - okx_rate))
    base_cost, stress_cost = fixed_cost_pct(False), fixed_cost_pct(True)
    event.update({
        "pnl_status": "complete", "pnl_reason": None,
        "price_return_pct": price_return_pct,
        "funding_return_pct": funding_return_pct,
        "base_fixed_cost_pct": base_cost,
        "stress_fixed_cost_pct": stress_cost,
        "base_net_return_pct": price_return_pct + funding_return_pct - base_cost,
        "stress_net_return_pct": price_return_pct + funding_return_pct - stress_cost,
        "cost_model": {
            "capital_split": "50/50", "fills": "taker",
            "hyperliquid_taker_rate": HL_TAKER_RATE,
            "okx_taker_rate": OKX_TAKER_RATE,
            "base_slippage_rate_per_fill": BASE_SLIPPAGE_RATE,
            "stress_slippage_rate_per_fill": STRESS_SLIPPAGE_RATE,
            "rebalance_rate_total_capital": REBALANCE_RATE,
        },
    })
    return event


def summarize(rows):
    scored = [score_event(row) for row in rows]
    counts = Counter(row["pnl_status"] for row in scored)
    complete = [row for row in scored if row["pnl_status"] == "complete"]
    attempts = complete + [row for row in scored if row["pnl_status"] == "failed_attempt"]
    by_coin = defaultdict(float)
    for row in attempts:
        by_coin[row.get("coin") or "UNKNOWN"] += float(row["base_net_return_pct"])
    positives = {coin: value for coin, value in by_coin.items() if value > 0}
    positive_total = sum(positives.values())
    concentration = max(positives.values()) / positive_total if positive_total else None
    base = [float(row["base_net_return_pct"]) for row in attempts]
    stress = [float(row["stress_net_return_pct"]) for row in attempts]
    failure_rate = counts["failed_attempt"] / len(attempts) if attempts else None
    report = {
        "events": len(scored), "statuses": dict(sorted(counts.items())),
        "complete_settled_events": len(complete), "scored_attempts": len(attempts),
        "base_fixed_cost_pct": fixed_cost_pct(False),
        "stress_fixed_cost_pct": fixed_cost_pct(True),
        "base_mean_return_pct": statistics.fmean(base) if base else None,
        "stress_mean_return_pct": statistics.fmean(stress) if stress else None,
        "cumulative_base_return_pct": sum(base),
        "failed_attempt_rate": failure_rate,
        "positive_pnl_concentration": concentration,
        "by_coin_base_return_pct": dict(sorted(by_coin.items())),
        "inference_status": "COLLECTING" if len(complete) < 200 else "READY_FOR_FROZEN_VALIDATION",
        "profitability_claim_permitted": False,
        "minimum_complete_events": 200,
    }
    return scored, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="data/crossvenue_settled_events.jsonl")
    parser.add_argument("--out", default="data/crossvenue_pnl_events.jsonl")
    parser.add_argument("--report", default="reports/crossvenue_pnl.json")
    args = parser.parse_args()
    rows, report = summarize(read_jsonl(args.path))
    write_jsonl(args.out, rows)
    target = Path(args.report); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"out": args.out, "report": args.report, **report}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
