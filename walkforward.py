#!/usr/bin/env python3
"""Anchored walk-forward validation for the funding-fade hypothesis."""
import argparse, json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from evaluate import load, observations, summarize
from portfolio import simulate
from research import run_grid


def windows(records, folds=4, min_train_fraction=.4):
    times = sorted({int(r["captured_at_ms"]) for r in records})
    if len(times) < folds + 2:
        return []
    start = max(1, int(len(times) * min_train_fraction))
    step = max(1, (len(times) - start) // folds)
    out = []
    for i in range(folds):
        train_end = min(len(times) - 1, start + i * step)
        test_end = len(times) if i == folds - 1 else min(len(times), train_end + step)
        if test_end <= train_end:
            continue
        train_cut, test_cut = times[train_end - 1], times[test_end - 1]
        train = [r for r in records if int(r["captured_at_ms"]) <= train_cut]
        test = [r for r in records if train_cut < int(r["captured_at_ms"]) <= test_cut]
        if train and test:
            out.append((train, test, train_cut, test_cut))
    return out


def by_coin(trades):
    groups = defaultdict(list)
    for trade in trades:
        groups[trade["coin"]].append(trade)
    return {coin: summarize(rows) for coin, rows in sorted(groups.items())}


def validate(records, horizons=(1, 4, 8, 24), thresholds=(.25, .5, 1, 2, 5),
             selection_cost=12, stress_costs=(9, 12, 15, 18), min_trades=30,
             folds=4, min_train_fraction=.4, capital=10_000,
             max_positions=3, risk_fraction=1.0, max_trade_notional=5_000,
             max_coin_positions=1):
    fold_rows, all_trades, choices = [], [], []
    for number, (train, test, train_cut, test_cut) in enumerate(
            windows(records, folds, min_train_fraction), 1):
        _, ranked = run_grid(train, horizons, thresholds, (selection_cost,), min_trades)
        selected = ranked[0] if ranked else None
        trades = [] if not selected else observations(
            test, selected["horizon_hours"], selected["min_funding_bps"], selection_cost)
        stats = summarize(trades)
        fold_rows.append({"fold": number, "train_end_ms": train_cut,
                          "test_end_ms": test_cut, "selected": selected,
                          "out_of_sample": stats})
        if selected:
            choices.append((selected["horizon_hours"], selected["min_funding_bps"]))
        all_trades.extend(trades)

    aggregate = summarize(all_trades)
    portfolio = simulate(all_trades, capital, max_positions, risk_fraction,
                         max_trade_notional, max_coin_positions)
    sensitivity = {}
    for cost in stress_costs:
        stressed = [{**t, "net_return_pct": t["net_return_pct"] - (cost - selection_cost) / 100}
                    for t in all_trades]
        sensitivity[str(cost)] = summarize(stressed)
    profitable_folds = sum(f["out_of_sample"]["mean_net_return_pct"] > 0 for f in fold_rows)
    stable_choice = Counter(choices).most_common(1)[0] if choices else (None, 0)
    enough = aggregate["trades"] >= max(20, min_trades // 2)
    robust_cost = all(s["mean_net_return_pct"] > 0 for s in sensitivity.values()) if sensitivity else False
    verdict = ("PROMISING" if enough and aggregate["mean_lcb95_pct"] > 0
               and portfolio["return_pct"] > 0 and profitable_folds >= max(2, len(fold_rows) - 1)
               and robust_cost else "REJECT_OR_REWORK")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": len(records), "selection_cost_bps": selection_cost,
        "folds": fold_rows, "aggregate_oos": aggregate, "by_coin": by_coin(all_trades),
        "portfolio": {k: v for k, v in portfolio.items() if k != "ledger"},
        "cost_sensitivity_bps": sensitivity,
        "parameter_stability": {"most_common": stable_choice[0],
                                "folds_selected": stable_choice[1],
                                "all_choices": choices},
        "profitable_folds": profitable_folds, "verdict": verdict,
    }, all_trades, portfolio["ledger"]


def write(path, value, jsonl=False):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    if jsonl:
        target.write_text("\n".join(json.dumps(x, separators=(",", ":")) for x in value)
                          + ("\n" if value else ""))
    else:
        target.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", default="data/history.jsonl")
    p.add_argument("--out", default="reports/walkforward.json")
    p.add_argument("--trades-out", default="reports/walkforward_trades.jsonl")
    p.add_argument("--ledger-out", default="reports/walkforward_ledger.jsonl")
    p.add_argument("--folds", type=int, default=4)
    p.add_argument("--min-trades", type=int, default=30)
    p.add_argument("--roundtrip-bps", type=float, default=12)
    p.add_argument("--capital", type=float, default=10_000)
    a = p.parse_args()
    result, trades, ledger = validate(load(a.path), folds=a.folds,
                                      min_trades=a.min_trades, capital=a.capital,
                                      selection_cost=a.roundtrip_bps)
    write(a.out, result); write(a.trades_out, trades, True); write(a.ledger_out, ledger, True)
    print(json.dumps({"out": a.out, "verdict": result["verdict"],
                      "trades": result["aggregate_oos"]["trades"],
                      "portfolio_return_pct": result["portfolio"]["return_pct"]}, indent=2))


if __name__ == "__main__":
    main()
