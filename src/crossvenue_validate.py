#!/usr/bin/env python3
"""Frozen validation gate for manifest-bound prospective cross-venue P&L evidence."""
import argparse, hashlib, json, random, statistics
from collections import defaultdict
from pathlib import Path

DEVELOPMENT_COMPLETE_PERIODS = 140
HOLDOUT_COMPLETE_PERIODS = 60
MIN_COMPLETE_PERIODS = 200
MIN_COLLECTION_DAYS = 56
DAY = 86_400_000
BLOCK_SIZE = 8
BOOTSTRAP_SAMPLES = 4000
CAPITAL_FRACTION = 0.10
MAX_TOTAL_FRACTION_PER_PERIOD = 1.0
MAX_POSITIVE_CONCENTRATION = 0.70
MAX_FAILED_ATTEMPT_RATE = 0.05
SEED = 20260723


def read_jsonl(path):
    target = Path(path)
    return [] if not target.exists() else [json.loads(x) for x in target.read_text().splitlines() if x.strip()]


def read_json(path):
    target = Path(path)
    return None if not target.exists() else json.loads(target.read_text())


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


def grouped_periods(rows):
    grouped = defaultdict(list)
    for row in rows: grouped[event_time(row)].append(row)
    return [(time, sorted(period, key=lambda r: (str(r.get("event_id") or ""), str(r.get("coin") or ""))))
            for time, period in sorted(grouped.items())]


def is_complete_period(period):
    return any(row.get("pnl_status") == "complete" for row in period)


def split_attempts(attempts):
    development, holdout, complete_periods = [], [], 0
    for _, period in grouped_periods(attempts):
        target = development if complete_periods < DEVELOPMENT_COMPLETE_PERIODS else holdout
        target.extend(period)
        if is_complete_period(period): complete_periods += 1
    return development, holdout


def complete_period_count(rows):
    return sum(is_complete_period(period) for _, period in grouped_periods(rows))


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


def chain_identity(report):
    if report is None:
        return {"present": False, "valid": False, "errors": ["chain_report_missing"]}
    errors = list(report.get("errors") or [])
    valid = report.get("valid") is True and not errors
    return {"present": True, "valid": valid, "errors": errors,
            "previous_artifact_present": bool(report.get("previous_artifact_present")),
            "freeze_manifest_upgraded": bool(report.get("freeze_manifest_upgraded"))}


def validate(rows, freeze, chain_report=None):
    chain = chain_identity(chain_report)
    all_attempts = [r for r in rows if r.get("pnl_status") in ("complete", "failed_attempt")]
    attempts, mismatched = eligible_attempts(rows, freeze)
    development, holdout = split_attempts(attempts)
    development_complete_attempts = sum(r["pnl_status"] == "complete" for r in development)
    holdout_complete_attempts = sum(r["pnl_status"] == "complete" for r in holdout)
    development_complete_periods = complete_period_count(development)
    holdout_complete_periods = complete_period_count(holdout)
    complete_times = [time for time, period in grouped_periods(attempts) if is_complete_period(period)]
    collection_span_days = ((complete_times[-1] - complete_times[0]) / DAY
                            if len(complete_times) > 1 else 0.0)
    manifest_ok = mismatched == 0
    integrity_ok = manifest_ok and chain["valid"]
    sample_ready = (development_complete_periods >= DEVELOPMENT_COMPLETE_PERIODS
                    and holdout_complete_periods >= HOLDOUT_COMPLETE_PERIODS)
    span_ready = collection_span_days >= MIN_COLLECTION_DAYS
    ready = integrity_ok and sample_ready and span_ready
    evaluated = holdout if ready else []
    base_periods = period_returns(evaluated, "base_net_return_pct") if ready else []
    stress_periods = period_returns(evaluated, "stress_net_return_pct") if ready else []
    lcb = moving_block_lcb(base_periods) if ready else None
    bp = finite_capital(evaluated, "base_net_return_pct") if ready else None
    sp = finite_capital(evaluated, "stress_net_return_pct") if ready else None
    conc, by_coin = concentration(evaluated) if ready else (None, {})
    failure_rate = sum(r["pnl_status"] == "failed_attempt" for r in evaluated) / len(evaluated) if evaluated else None
    gates = {"append_only_chain_valid": chain["valid"],
             "manifest_binding_valid": manifest_ok, "minimum_complete_periods": sample_ready,
             "minimum_collection_span_56_days": span_ready,
             "holdout_block_bootstrap_lcb_positive": lcb is not None and lcb > 0,
             "holdout_stress_period_mean_positive": bool(stress_periods) and statistics.fmean(stress_periods) > 0,
             "holdout_base_portfolio_positive": bp is not None and bp["return_pct"] > 0,
             "holdout_stress_portfolio_positive": sp is not None and sp["return_pct"] > 0,
             "positive_pnl_concentration_at_most_70pct": conc is not None and conc <= MAX_POSITIVE_CONCENTRATION,
             "failed_attempt_rate_below_5pct": failure_rate is not None and failure_rate <= MAX_FAILED_ATTEMPT_RATE}
    verdict = "INVALID" if not integrity_ok else "COLLECTING" if not ready else "PASS" if all(gates.values()) else "REJECT"
    report = {"contract": {"development_complete_periods": DEVELOPMENT_COMPLETE_PERIODS,
                            "holdout_complete_periods": HOLDOUT_COMPLETE_PERIODS,
                            "minimum_complete_periods": MIN_COMPLETE_PERIODS,
                            "minimum_collection_days": MIN_COLLECTION_DAYS,
                            "complete_period_definition": "funding boundary with at least one exact complete attempt",
                            "block_size_periods": BLOCK_SIZE, "bootstrap_samples": BOOTSTRAP_SAMPLES,
                            "capital_fraction_per_attempt": CAPITAL_FRACTION,
                            "max_total_fraction_per_period": MAX_TOTAL_FRACTION_PER_PERIOD,
                            "max_positive_pnl_concentration": MAX_POSITIVE_CONCENTRATION,
                            "max_failed_attempt_rate": MAX_FAILED_ATTEMPT_RATE, "seed": SEED},
              "experiment_freeze": freeze, "artifact_chain": chain,
              "manifest_mismatched_attempts": mismatched,
              "verdict": verdict, "profitability_claim_permitted": verdict == "PASS",
              "evidence_cutoff_ms": freeze["evidence_cutoff_ms"],
              "excluded_prefreeze_or_unbound_attempts": len(all_attempts) - len(attempts),
              "total_attempts": len(attempts), "collection_span_days": collection_span_days,
              "complete_attempts": development_complete_attempts + holdout_complete_attempts,
              "complete_periods": development_complete_periods + holdout_complete_periods,
              "development_attempts": len(development),
              "development_complete_attempts": development_complete_attempts,
              "development_complete_periods": development_complete_periods,
              "holdout_attempts_collected": len(holdout),
              "holdout_complete_attempts_collected": holdout_complete_attempts,
              "holdout_complete_periods_collected": holdout_complete_periods,
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
    p.add_argument("--chain-report", default="reports/crossvenue_chain.json")
    p.add_argument("--report", default="reports/crossvenue_validation.json")
    p.add_argument("--base-ledger", default="data/crossvenue_validation_base_ledger.jsonl")
    p.add_argument("--stress-ledger", default="data/crossvenue_validation_stress_ledger.jsonl")
    a = p.parse_args()
    report, base, stress = validate(
        read_jsonl(a.path), manifest_identity(a.freeze_manifest), read_json(a.chain_report))
    write_json(a.report, report); write_jsonl(a.base_ledger, base); write_jsonl(a.stress_ledger, stress)
    print(json.dumps({"report": a.report, **report}, indent=2, allow_nan=False))
    if report["verdict"] == "INVALID":
        raise SystemExit(1)


if __name__ == "__main__": main()
