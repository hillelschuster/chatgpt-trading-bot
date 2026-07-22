#!/usr/bin/env python3
"""Cost-aware cross-sectional momentum/reversal benchmark on hourly perp panels."""
import argparse, json, math, statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from portfolio import simulate

HOUR = 3_600_000


def load(path):
    rows = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    return sorted(rows, key=lambda r: int(r["captured_at_ms"]))


def panel(records):
    return {int(r["captured_at_ms"]): {
        a["coin"]: {"mark": float(a["mark"]), "funding_pct": float(a.get("funding_1h_pct") or 0)}
        for a in r["assets"] if a.get("mark")} for r in records}


def breadth(records):
    counts = [len(r["assets"]) for r in records]
    coins = sorted({a["coin"] for r in records for a in r["assets"]})
    return {"unique_assets": len(coins), "assets": coins,
            "min_assets_per_hour": min(counts) if counts else 0,
            "median_assets_per_hour": statistics.median(counts) if counts else 0,
            "max_assets_per_hour": max(counts) if counts else 0}


def trades(records, lookback, horizon, mode, roundtrip_bps, min_assets=6):
    data = panel(records); out = []; next_entry = -math.inf
    for t in sorted(data):
        if t < next_entry:
            continue
        past, future = data.get(t - lookback * HOUR), data.get(t + horizon * HOUR)
        available = sorted(set(data[t]) & set(past or {}))
        if len(available) < min_assets or not future:
            continue
        ranked = sorted(available, key=lambda c: data[t][c]["mark"] / past[c]["mark"] - 1)
        short, long = ((ranked[0], ranked[-1]) if mode == "momentum" else (ranked[-1], ranked[0]))
        if long not in future or short not in future:
            continue  # Never rerank using future availability.
        for coin, side in ((long, "LONG"), (short, "SHORT")):
            sign = 1 if side == "LONG" else -1
            entry, exit_ = data[t][coin]["mark"], future[coin]["mark"]
            gross = (exit_ / entry - 1) * sign * 100
            held = 0.0
            for step in range(1, horizon):
                point = data.get(t + step * HOUR, {}).get(coin)
                if point:
                    held += -sign * point["funding_pct"]
            out.append({"time": t, "exit_time": t + horizon * HOUR, "coin": coin,
                        "side": side, "mode": mode, "lookback_hours": lookback,
                        "horizon_hours": horizon, "cross_section_size": len(available),
                        "gross_return_pct": gross, "funding_return_pct": held,
                        "net_return_pct": gross + held - roundtrip_bps / 100})
        next_entry = t + horizon * HOUR
    return out


def summarize(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[int(row["time"])].append(float(row["net_return_pct"]))
    values = [statistics.fmean(v) for _, v in sorted(grouped.items())]
    if not values:
        return {"trades": 0, "legs": 0, "mean_net_return_pct": 0,
                "mean_lcb95_pct": 0, "win_rate_pct": 0}
    mean = statistics.fmean(values); sd = statistics.stdev(values) if len(values) > 1 else 0
    return {"trades": len(values), "legs": len(rows), "mean_net_return_pct": mean,
            "mean_lcb95_pct": mean - 1.96 * sd / math.sqrt(len(values)),
            "win_rate_pct": 100 * sum(v > 0 for v in values) / len(values)}


def split(records, fraction=.7):
    times = sorted(int(r["captured_at_ms"]) for r in records)
    cut = times[max(0, min(len(times) - 1, int(len(times) * fraction) - 1))] if times else None
    return ([r for r in records if int(r["captured_at_ms"]) <= cut],
            [r for r in records if int(r["captured_at_ms"]) > cut], cut)


def study(records, lookbacks=(1, 4, 8, 24), horizons=(1, 4, 8, 24),
          modes=("momentum", "reversal"), selection_cost=12,
          stress_costs=(9, 12, 15, 18), min_trades=40,
          train_fraction=.7, capital=10_000, min_assets=6):
    train, test, cut = split(records, train_fraction); grid = []
    for mode in modes:
        for lookback in lookbacks:
            for horizon in horizons:
                stats = summarize(trades(train, lookback, horizon, mode, selection_cost, min_assets))
                grid.append({"mode": mode, "lookback_hours": lookback,
                             "horizon_hours": horizon, "roundtrip_bps": selection_cost, **stats})
    eligible = [r for r in grid if r["trades"] >= min_trades]
    eligible.sort(key=lambda r: (r["mean_lcb95_pct"], r["mean_net_return_pct"]), reverse=True)
    selected = eligible[0] if eligible else None
    oos = (trades(test, selected["lookback_hours"], selected["horizon_hours"],
                  selected["mode"], selection_cost, min_assets) if selected else [])
    portfolio = (simulate(oos, capital, max_positions=2, risk_fraction=1,
                          max_trade_notional=capital / 2, max_coin_positions=1) if selected else None)
    stats = summarize(oos); enough = stats["trades"] >= max(20, min_trades // 3)
    sensitivity = {str(cost): summarize([
        {**row, "net_return_pct": row["net_return_pct"] - (cost - selection_cost) / 100}
        for row in oos]) for cost in stress_costs}
    robust = all(x["mean_net_return_pct"] > 0 for x in sensitivity.values()) if oos else False
    verdict = ("PROMISING" if selected and enough and stats["mean_lcb95_pct"] > 0
               and portfolio["return_pct"] > 0 and robust else
               "REJECT_OR_REWORK" if selected else "INSUFFICIENT_DATA")
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "records": len(records),
              "breadth": breadth(records), "min_assets_required": min_assets,
              "split_at_ms": cut, "selection_cost_bps": selection_cost,
              "cost_policy": "fixed before selection; stress-tested separately",
              "selected": selected, "out_of_sample": stats,
              "cost_sensitivity_bps": sensitivity,
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
    p.add_argument("--min-assets", type=int, default=6)
    p.add_argument("--roundtrip-bps", type=float, default=12)
    p.add_argument("--capital", type=float, default=10_000)
    a = p.parse_args()
    report, rows, ledger = study(load(a.path), selection_cost=a.roundtrip_bps,
                                 min_trades=a.min_trades, capital=a.capital,
                                 min_assets=a.min_assets)
    write(a.out, report); write_jsonl(a.trades_out, rows); write_jsonl(a.ledger_out, ledger)
    print(json.dumps({"out": a.out, "verdict": report["verdict"], "breadth": report["breadth"],
                      "selected": report["selected"], "out_of_sample": report["out_of_sample"],
                      "portfolio": report["portfolio"]}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
