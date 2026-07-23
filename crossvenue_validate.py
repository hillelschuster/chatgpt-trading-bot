#!/usr/bin/env python3
"""Frozen validation gate for prospective cross-venue P&L evidence."""
import argparse, json, random, statistics
from collections import defaultdict
from pathlib import Path

MIN_COMPLETE_EVENTS = 200
HOLDOUT_FRACTION = 0.30
BLOCK_SIZE = 8
BOOTSTRAP_SAMPLES = 4000
CAPITAL_FRACTION = 0.10
MAX_POSITIVE_CONCENTRATION = 0.50
MAX_FAILED_ATTEMPT_RATE = 0.10
SEED = 20260723


def read_jsonl(path):
    target = Path(path)
    return [] if not target.exists() else [json.loads(x) for x in target.read_text().splitlines() if x.strip()]


def event_time(row):
    for key in ("funding_boundary_ms", "boundary_ms", "entry_time_ms", "signal_time_ms", "time"):
        if row.get(key) is not None:
            return int(row[key])
    return 0


def eligible_attempts(rows):
    attempts = [r for r in rows if r.get("pnl_status") in ("complete", "failed_attempt")]
    return sorted(attempts, key=lambda r: (event_time(r), str(r.get("event_id") or ""), str(r.get("coin") or "")))


def moving_block_lcb(values, block_size=BLOCK_SIZE, samples=BOOTSTRAP_SAMPLES, seed=SEED):
    if not values:
        return None
    n = len(values); block = max(1, min(block_size, n)); starts = list(range(n - block + 1))
    rng = random.Random(seed); means = []
    for _ in range(samples):
        sample = []
        while len(sample) < n:
            start = rng.choice(starts); sample.extend(values[start:start + block])
        means.append(statistics.fmean(sample[:n]))
    means.sort(); return means[max(0, int(0.025 * samples) - 1)]


def finite_capital(rows, return_field, starting_capital=10_000, fraction=CAPITAL_FRACTION):
    equity = peak = float(starting_capital); max_drawdown = 0.0; ledger = []
    for row in rows:
        ret = float(row[return_field]) / 100; notional = equity * fraction; pnl = notional * ret; equity += pnl
        peak = max(peak, equity); max_drawdown = min(max_drawdown, equity / peak - 1)
        ledger.append({"event_id": row.get("event_id"), "coin": row.get("coin"), "time": event_time(row),
                       "notional": notional, "return_pct": ret * 100, "pnl": pnl, "equity": equity})
    return {"starting_capital": starting_capital, "ending_equity": equity,
            "return_pct": 100 * (equity / starting_capital - 1),
            "max_drawdown_pct": 100 * max_drawdown, "trades": len(ledger), "ledger": ledger}


def concentration(rows):
    by_coin = defaultdict(float)
    for row in rows: by_coin[row.get("coin") or "UNKNOWN"] += float(row["base_net_return_pct"])
    positives = {k: v for k, v in by_coin.items() if v > 0}; total = sum(positives.values())
    return (max(positives.values()) / total if total else None), dict(sorted(by_coin.items()))


def validate(rows):
    attempts = eligible_attempts(rows); complete = [r for r in attempts if r["pnl_status"] == "complete"]
    ready = len(complete) >= MIN_COMPLETE_EVENTS
    split = int(len(attempts) * (1 - HOLDOUT_FRACTION)) if ready else len(attempts)
    development, holdout = attempts[:split], attempts[split:] if ready else []
    base = [float(r["base_net_return_pct"]) for r in holdout]; stress = [float(r["stress_net_return_pct"]) for r in holdout]
    lcb = moving_block_lcb(base) if ready else None
    base_portfolio = finite_capital(holdout, "base_net_return_pct") if ready else None
    stress_portfolio = finite_capital(holdout, "stress_net_return_pct") if ready else None
    conc, by_coin = concentration(holdout) if ready else (None, {})
    failure_rate = (sum(r["pnl_status"] == "failed_attempt" for r in holdout) / len(holdout)) if holdout else None
    gates = {"minimum_complete_events": ready,
             "holdout_block_bootstrap_lcb_positive": lcb is not None and lcb > 0,
             "holdout_stress_mean_positive": bool(stress) and statistics.fmean(stress) > 0,
             "holdout_base_portfolio_positive": base_portfolio is not None and base_portfolio["return_pct"] > 0,
             "holdout_stress_portfolio_positive": stress_portfolio is not None and stress_portfolio["return_pct"] > 0,
             "positive_pnl_concentration_at_most_50pct": conc is not None and conc <= MAX_POSITIVE_CONCENTRATION,
             "failed_attempt_rate_at_most_10pct": failure_rate is not None and failure_rate <= MAX_FAILED_ATTEMPT_RATE}
    verdict = "COLLECTING" if not ready else "PASS" if all(gates.values()) else "REJECT"
    report = {"contract": {"minimum_complete_events": MIN_COMPLETE_EVENTS, "holdout_fraction": HOLDOUT_FRACTION,
                            "block_size_events": BLOCK_SIZE, "bootstrap_samples": BOOTSTRAP_SAMPLES,
                            "capital_fraction_per_attempt": CAPITAL_FRACTION,
                            "max_positive_pnl_concentration": MAX_POSITIVE_CONCENTRATION,
                            "max_failed_attempt_rate": MAX_FAILED_ATTEMPT_RATE, "seed": SEED},
              "verdict": verdict, "profitability_claim_permitted": verdict == "PASS",
              "total_attempts": len(attempts), "complete_events": len(complete),
              "development_attempts": len(development), "holdout_attempts": len(holdout),
              "holdout_base_mean_return_pct": statistics.fmean(base) if base else None,
              "holdout_base_block_bootstrap_lcb95_pct": lcb,
              "holdout_stress_mean_return_pct": statistics.fmean(stress) if stress else None,
              "holdout_failed_attempt_rate": failure_rate, "holdout_positive_pnl_concentration": conc,
              "holdout_by_coin_base_return_pct": by_coin,
              "base_portfolio": ({k: v for k, v in base_portfolio.items() if k != "ledger"} if base_portfolio else None),
              "stress_portfolio": ({k: v for k, v in stress_portfolio.items() if k != "ledger"} if stress_portfolio else None),
              "gates": gates}
    return report, (base_portfolio or {}).get("ledger", []), (stress_portfolio or {}).get("ledger", [])


def write_json(path, value):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def write_jsonl(path, rows):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(x, separators=(",", ":"), allow_nan=False) + "\n" for x in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="data/crossvenue_pnl_events.jsonl")
    parser.add_argument("--report", default="reports/crossvenue_validation.json")
    parser.add_argument("--base-ledger", default="data/crossvenue_validation_base_ledger.jsonl")
    parser.add_argument("--stress-ledger", default="data/crossvenue_validation_stress_ledger.jsonl")
    args = parser.parse_args(); report, base_ledger, stress_ledger = validate(read_jsonl(args.path))
    write_json(args.report, report); write_jsonl(args.base_ledger, base_ledger); write_jsonl(args.stress_ledger, stress_ledger)
    print(json.dumps({"report": args.report, **report}, indent=2, allow_nan=False))


if __name__ == "__main__": main()
