#!/usr/bin/env python3
"""Frozen validation gate for manifest-bound prospective cross-venue P&L evidence."""
import argparse, hashlib, json, random, statistics
from collections import defaultdict
from pathlib import Path

DEVELOPMENT_COMPLETE_EVENTS = 140
HOLDOUT_COMPLETE_EVENTS = 60
MIN_COMPLETE_EVENTS = 200
BLOCK_SIZE = 8
BOOTSTRAP_SAMPLES = 4000
CAPITAL_FRACTION = 0.10
MAX_TOTAL_FRACTION_PER_PERIOD = 1.0
MAX_POSITIVE_CONCENTRATION = 0.50
MAX_FAILED_ATTEMPT_RATE = 0.10
SEED = 20260723


def read_jsonl(path):
    target = Path(path)
    return [] if not target.exists() else [json.loads(x) for x in target.read_text().splitlines() if x.strip()]


def manifest_identity(path):
    raw = Path(path).read_bytes(); manifest = json.loads(raw)
    return {"schema": manifest.get("schema"), "frozen_at_ms": int(manifest.get("frozen_at_ms") or 0),
            "evidence_cutoff_ms": int(manifest.get("evidence_cutoff_ms") or 0),
            "sha256": hashlib.sha256(raw).hexdigest()}


def event_time(row):
    for key in ("funding_boundary_ms", "boundary_ms", "entry_time_ms", "signal_time_ms", "time"):
        if row.get(key) is not None: return int(row[key])
    return 0


def eligible_attempts(rows, freeze):
    cutoff = freeze["evidence_cutoff_ms"]; digest = freeze["sha256"]
    attempts, mismatched = [], 0
    for row in rows:
        if row.get("pnl_status") not in ("complete", "failed_attempt"): continue
        if event_time(row) <= cutoff: continue
        if (row.get("experiment_freeze") or {}).get("sha256") != digest:
            mismatched += 1; continue
        attempts.append(row)
    attempts.sort(key=lambda r: (event_time(r), str(r.get("event_id") or ""), str(r.get("coin") or "")))
    return attempts, mismatched


def split_attempts(attempts):
    development, holdout, complete = [], [], 0
    for row in attempts:
        if complete < DEVELOPMENT_COMPLETE_EVENTS:
            development.append(row); complete += row.get("pnl_status") == "complete"
        else: holdout.append(row)
    return development, holdout


def moving_block_lcb(values, block_size=BLOCK_SIZE, samples=BOOTSTRAP_SAMPLES, seed=SEED):
    if not values: return None
    n = len(values); block = max(1, min(block_size, n)); starts = list(range(n - block + 1))
    rng = random.Random(seed); means = []
    for _ in range(samples):
        sample = []
        while len(sample) < n:
            start = rng.choice(starts); sample.extend(values[start:start + block])
        means.append(statistics.fmean(sample[:n]))
    means.sort(); return means[max(0, int(0.025 * samples) - 1)]


def grouped_periods(rows):
    grouped = defaultdict(list)
    for row in rows: grouped[event_time(row)].append(row)
    return [(time, sorted(period, key=lambda r: (str(r.get("event_id") or ""), str(r.get("coin") or ""))))
            for time, period in sorted(grouped.items())]


def period_returns(rows, return_field, fraction=CAPITAL_FRACTION):
    values = []
    for _, period in grouped_periods(rows):
        if len(period) * fraction > MAX_TOTAL_FRACTION_PER_PERIOD + 1e-12:
            raise ValueError("simultaneous attempts exceed total capital allocation")
        values.append(sum(fraction * float(row[return_field]) for row in period))
    return values


def finite_capital(rows, return_field, starting_capital=10_000, fraction=CAPITAL_FRACTION):
    equity = peak = float(starting_capital); max_drawdown = 0.0; ledger = []
    for time, period in grouped_periods(rows):
        if len(period) * fraction > MAX_TOTAL_FRACTION_PER_PERIOD + 1e-12:
            raise ValueError("simultaneous attempts exceed total capital allocation")
        equity_before = equity; period_pnl = 0.0; start_index = len(ledger)
        for row in period:
            ret = float(row[return_field]) / 100; notional = equity_before * fraction; pnl = notional * ret
            period_pnl += pnl
            ledger.append({"event_id": row.get("event_id"), "coin": row.get("coin"), "time": time,
                           "notional": notional, "return_pct": ret * 100, "pnl": pnl,
                           "equity_before_period": equity_before})
        equity += period_pnl
        peak = max(peak, equity); max_drawdown = min(max_drawdown, equity / peak - 1)
        for item in ledger[start_index:]: item["equity_after_period"] = equity
    return {"starting_capital": starting_capital, "ending_equity": equity,
            "return_pct": 100 * (equity / starting_capital - 1),
            "max_drawdown_pct": 100 * max_drawdown, "trades": len(ledger),
            "periods": len(grouped_periods(rows)), "ledger": ledger}


def concentration(rows):
    by_coin = defaultdict(float)
    for row in rows: by_coin[row.get("coin") or "UNKNOWN"] += float(row["base_net_return_pct"])
    positives = {k: v for k, v in by_coin.items() if v > 0}; total = sum(positives.values())
    return (max(positives.values()) / total if total else None), dict(sorted(by_coin.items()))


def validate(rows, freeze):
    all_attempts = [r for r in rows if r.get("pnl_status") in ("complete", "failed_attempt")]
    attempts, mismatched = eligible_attempts(rows, freeze)
    development, holdout = split_attempts(attempts)
    development_complete = sum(r["pnl_status"] == "complete" for r in development)
    holdout_complete = sum(r["pnl_status"] == "complete" for r in holdout)
    integrity_ok = mismatched == 0
    ready = integrity_ok and development_complete >= DEVELOPMENT_COMPLETE_EVENTS and holdout_complete >= HOLDOUT_COMPLETE_EVENTS
    evaluated = holdout if ready else []
    base_periods = period_returns(evaluated, "base_net_return_pct") if ready else []
    stress_periods = period_returns(evaluated, "stress_net_return_pct") if ready else []
    lcb = moving_block_lcb(base_periods) if ready else None
    bp = finite_capital(evaluated, "base_net_return_pct") if ready else None
    sp = finite_capital(evaluated, "stress_net_return_pct") if ready else None
    conc, by_coin = concentration(evaluated) if ready else (None, {})
    failure_rate = sum(r["pnl_status"] == "failed_attempt" for r in evaluated) / len(evaluated) if evaluated else None
    gates = {"manifest_binding_valid": integrity_ok, "minimum_complete_events": ready,
             "holdout_block_bootstrap_lcb_positive": lcb is not None and lcb > 0,
             "holdout_stress_period_mean_positive": bool(stress_periods) and statistics.fmean(stress_periods) > 0,
             "holdout_base_portfolio_positive": bp is not None and bp["return_pct"] > 0,
             "holdout_stress_portfolio_positive": sp is not None and sp["return_pct"] > 0,
             "positive_pnl_concentration_at_most_50pct": conc is not None and conc <= MAX_POSITIVE_CONCENTRATION,
             "failed_attempt_rate_at_most_10pct": failure_rate is not None and failure_rate <= MAX_FAILED_ATTEMPT_RATE}
    verdict = "INVALID" if not integrity_ok else "COLLECTING" if not ready else "PASS" if all(gates.values()) else "REJECT"
    report = {"contract": {"development_complete_events": DEVELOPMENT_COMPLETE_EVENTS,
                            "holdout_complete_events": HOLDOUT_COMPLETE_EVENTS,
                            "minimum_complete_events": MIN_COMPLETE_EVENTS,
                            "block_size_periods": BLOCK_SIZE, "bootstrap_samples": BOOTSTRAP_SAMPLES,
                            "capital_fraction_per_attempt": CAPITAL_FRACTION,
                            "max_total_fraction_per_period": MAX_TOTAL_FRACTION_PER_PERIOD,
                            "max_positive_pnl_concentration": MAX_POSITIVE_CONCENTRATION,
                            "max_failed_attempt_rate": MAX_FAILED_ATTEMPT_RATE, "seed": SEED},
              "experiment_freeze": freeze, "manifest_mismatched_attempts": mismatched,
              "verdict": verdict, "profitability_claim_permitted": verdict == "PASS",
              "evidence_cutoff_ms": freeze["evidence_cutoff_ms"],
              "excluded_prefreeze_or_unbound_attempts": len(all_attempts) - len(attempts),
              "total_attempts": len(attempts), "complete_events": development_complete + holdout_complete,
              "development_attempts": len(development), "development_complete_events": development_complete,
              "holdout_attempts_collected": len(holdout), "holdout_complete_events_collected": holdout_complete,
              "holdout_attempts_evaluated": len(evaluated), "holdout_periods_evaluated": len(base_periods),
              "holdout_base_period_mean_return_pct": statistics.fmean(base_periods) if base_periods else None,
              "holdout_base_block_bootstrap_lcb95_pct": lcb,
              "holdout_stress_period_mean_return_pct": statistics.fmean(stress_periods) if stress_periods else None,
              "holdout_failed_attempt_rate": failure_rate, "holdout_positive_pnl_concentration": conc,
              "holdout_by_coin_base_return_pct": by_coin,
              "base_portfolio": ({k: v for k, v in bp.items() if k != "ledger"} if bp else None),
              "stress_portfolio": ({k: v for k, v in sp.items() if k != "ledger"} if sp else None),
              "gates": gates}
    return report, (bp or {}).get("ledger", []), (sp or {}).get("ledger", [])


def write_json(path, value):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def write_jsonl(path, rows):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(x, separators=(",", ":"), allow_nan=False) + "\n" for x in rows))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", default="data/crossvenue_pnl_events.jsonl")
    p.add_argument("--freeze-manifest", default="data/crossvenue_experiment_freeze.json")
    p.add_argument("--report", default="reports/crossvenue_validation.json")
    p.add_argument("--base-ledger", default="data/crossvenue_validation_base_ledger.jsonl")
    p.add_argument("--stress-ledger", default="data/crossvenue_validation_stress_ledger.jsonl")
    a = p.parse_args(); report, base, stress = validate(read_jsonl(a.path), manifest_identity(a.freeze_manifest))
    write_json(a.report, report); write_jsonl(a.base_ledger, base); write_jsonl(a.stress_ledger, stress)
    print(json.dumps({"report": a.report, **report}, indent=2, allow_nan=False))


if __name__ == "__main__": main()
