#!/usr/bin/env python3
"""Select funding-fade parameters in-sample and validate portfolio deployment out-of-sample."""
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from evaluate import load, observations, summarize
from portfolio import simulate


def split(records, train_fraction=.7):
    if not records:
        return [], [], None
    times = sorted({int(r["captured_at_ms"]) for r in records})
    cut = times[min(len(times) - 1, max(0, int(len(times) * train_fraction) - 1))]
    return ([r for r in records if int(r["captured_at_ms"]) <= cut],
            [r for r in records if int(r["captured_at_ms"]) > cut], cut)


def run_grid(records, horizons, thresholds, costs, min_trades=30):
    rows = []
    for horizon in horizons:
        for threshold in thresholds:
            for cost in costs:
                stats = summarize(observations(records, horizon, threshold, cost))
                rows.append({"horizon_hours": horizon, "min_funding_bps": threshold,
                             "roundtrip_bps": cost, **stats})
    eligible = [r for r in rows if r["trades"] >= min_trades]
    eligible.sort(key=lambda r: (r["mean_lcb95_pct"], r["mean_net_return_pct"]), reverse=True)
    return rows, eligible


def study(records, horizons=(1, 4, 8, 24), thresholds=(.25, .5, 1, 2, 5),
          costs=(3, 6, 9), min_trades=30, train_fraction=.7,
          capital=10_000, max_positions=3, risk_fraction=1.0,
          max_trade_notional=5_000, max_coin_positions=1):
    train, test, cut = split(records, train_fraction)
    _, ranked = run_grid(train, horizons, thresholds, costs, min_trades)
    selected = ranked[0] if ranked else None
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": len(records), "train_records": len(train), "test_records": len(test),
        "split_at_ms": cut, "selection_rule": "highest train 95% lower confidence bound",
        "min_train_trades": min_trades, "selected": selected,
        "out_of_sample": None, "portfolio": None, "verdict": "INSUFFICIENT_DATA",
        "top_train": ranked[:10],
    }
    trades = []
    if selected:
        trades = observations(test, selected["horizon_hours"],
                              selected["min_funding_bps"], selected["roundtrip_bps"])
        result["out_of_sample"] = summarize(trades)
        portfolio = simulate(trades, capital, max_positions, risk_fraction,
                             max_trade_notional, max_coin_positions)
        result["portfolio"] = {k: v for k, v in portfolio.items() if k != "ledger"}
        stats = result["out_of_sample"]
        enough = stats["trades"] >= max(10, min_trades // 3)
        result["verdict"] = ("PROMISING" if enough and stats["mean_lcb95_pct"] > 0
                             and result["portfolio"]["return_pct"] > 0
                             else "REJECT_OR_REWORK")
    return result, trades


def write_jsonl(path, rows):
    if not path:
        return
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in rows)
                      + ("\n" if rows else ""))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", default="data/history.jsonl")
    p.add_argument("--out", default="reports/funding_fade.json")
    p.add_argument("--trades-out", default="reports/oos_trades.jsonl")
    p.add_argument("--ledger-out", default="reports/portfolio_ledger.jsonl")
    p.add_argument("--min-trades", type=int, default=30)
    p.add_argument("--train-fraction", type=float, default=.7)
    p.add_argument("--capital", type=float, default=10_000)
    p.add_argument("--max-positions", type=int, default=3)
    p.add_argument("--risk-fraction", type=float, default=1.0)
    p.add_argument("--max-trade-notional", type=float, default=5_000)
    p.add_argument("--max-coin-positions", type=int, default=1)
    a = p.parse_args()
    result, trades = study(load(a.path), min_trades=a.min_trades,
                           train_fraction=a.train_fraction, capital=a.capital,
                           max_positions=a.max_positions, risk_fraction=a.risk_fraction,
                           max_trade_notional=a.max_trade_notional,
                           max_coin_positions=a.max_coin_positions)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    write_jsonl(a.trades_out, trades)
    portfolio = simulate(trades, a.capital, a.max_positions, a.risk_fraction,
                         a.max_trade_notional, a.max_coin_positions)
    write_jsonl(a.ledger_out, portfolio["ledger"])
    print(json.dumps({"out": str(out), "verdict": result["verdict"],
                      "selected": result["selected"],
                      "out_of_sample": result["out_of_sample"],
                      "portfolio": result["portfolio"]}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
