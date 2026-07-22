#!/usr/bin/env python3
"""Cost-aware cross-sectional momentum/reversal benchmark on hourly perp panels."""
import argparse, json, math, statistics
from datetime import datetime, timezone
from pathlib import Path
from portfolio import simulate

HOUR = 3_600_000


def load(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def marks(records):
    return {int(r["captured_at_ms"]): {a["coin"]: float(a["mark"]) for a in r["assets"]}
            for r in records}


def trades(records, lookback, horizon, mode, roundtrip_bps, min_assets=3):
    panel = marks(records); out = []
    for t in sorted(panel):
        past, future = panel.get(t - lookback * HOUR), panel.get(t + horizon * HOUR)
        common = sorted(set(panel[t]) & set(past or {}) & set(future or {}))
        if len(common) < min_assets:
            continue
        ranked = sorted(common, key=lambda c: panel[t][c] / past[c] - 1)
        short, long = ((ranked[0], ranked[-1]) if mode == "momentum"
                       else (ranked[-1], ranked[0]))
        for coin, side in ((long, "LONG"), (short, "SHORT")):
            gross = (future[coin] / panel[t][coin] - 1) * (1 if side == "LONG" else -1) * 100
            out.append({"time": t, "exit_time": t + horizon * HOUR, "coin": coin,
                        "side": side, "mode": mode, "lookback_hours": lookback,
                        "horizon_hours": horizon, "gross_return_pct": gross,
                        "net_return_pct": gross - roundtrip_bps / 100})
    return out


def summarize(rows):
    values = [r["net_return_pct"] for r in rows]
    if not values:
        return {"trades": 0, "mean_net_return_pct": 0, "mean_lcb95_pct": 0,
                "win_rate_pct": 0}
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0
    return {"trades": len(values), "mean_net_return_pct": mean,
            "mean_lcb95_pct": mean - 1.96 * sd / math.sqrt(len(values)),
            "win_rate_pct": 100 * sum(v > 0 for v in values) / len(values)}


def split(records, fraction=.7):
    times = sorted(int(r["captured_at_ms"]) for r in records)
    cut = times[max(0, min(len(times) - 1, int(len(times) * fraction) - 1))] if times else None
    return ([r for r in records if int(r["captured_at_ms"]) <= cut],
            [r for r in records if int(r["captured_at_ms"]) > cut], cut)


def study(records, lookbacks=(1, 4, 8, 24), horizons=(1, 4, 8, 24),
          modes=("momentum", "reversal"), costs=(3, 6, 9, 12), min_trades=40,
          train_fraction=.7, capital=10_000):
    train, test, cut = split(records, train_fraction); grid = []
    for mode in modes:
        for lookback in lookbacks:
            for horizon in horizons:
                for cost in costs:
                    stats = summarize(trades(train, lookback, horizon, mode, cost))
                    grid.append({"mode": mode, "lookback_hours": lookback,
                                 "horizon_hours": horizon, "roundtrip_bps": cost, **stats})
    eligible = [r for r in grid if r["trades"] >= min_trades]
    eligible.sort(key=lambda r: (r["mean_lcb95_pct"], r["mean_net_return_pct"]), reverse=True)
    selected = eligible[0] if eligible else None
    oos = (trades(test, selected["lookback_hours"], selected["horizon_hours"],
                  selected["mode"], selected["roundtrip_bps"]) if selected else [])
    portfolio = (simulate(oos, capital, max_positions=2, risk_fraction=1,
                          max_trade_notional=capital / 2, max_coin_positions=1)
                 if selected else None)
    stats = summarize(oos)
    enough = stats["trades"] >= max(20, min_trades // 3)
    verdict = ("PROMISING" if selected and enough and stats["mean_lcb95_pct"] > 0
               and portfolio["return_pct"] > 0 else
               "REJECT_OR_REWORK" if selected else "INSUFFICIENT_DATA")
    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "records": len(records), "split_at_ms": cut, "selected": selected,
              "out_of_sample": stats,
              "portfolio": {k: v for k, v in (portfolio or {}).items() if k != "ledger"} or None,
              "verdict": verdict, "top_train": eligible[:10]}
    return report, oos, (portfolio or {}).get("ledger", [])


def write(path, value):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def write_jsonl(path, rows):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", default="data/history.jsonl")
    p.add_argument("--out", default="reports/xsection.json")
    p.add_argument("--trades-out", default="reports/xsection_trades.jsonl")
    p.add_argument("--ledger-out", default="reports/xsection_ledger.jsonl")
    p.add_argument("--min-trades", type=int, default=40)
    p.add_argument("--capital", type=float, default=10_000)
    a = p.parse_args()
    report, rows, ledger = study(load(a.path), min_trades=a.min_trades, capital=a.capital)
    write(a.out, report); write_jsonl(a.trades_out, rows); write_jsonl(a.ledger_out, ledger)
    print(json.dumps({"out": a.out, "verdict": report["verdict"],
                      "selected": report["selected"],
                      "out_of_sample": report["out_of_sample"],
                      "portfolio": report["portfolio"]}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
