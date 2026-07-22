#!/usr/bin/env python3
"""Chronologically evaluate funding fades after realistic costs."""
import argparse, json, math, statistics
from collections import defaultdict
from pathlib import Path

HOUR = 3_600_000


def load(path):
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    records.sort(key=lambda r: r["captured_at_ms"])
    return records


def observations(records, horizon_hours=1, min_funding_bps=0.5, roundtrip_bps=12.0,
                 tolerance_minutes=20):
    by_coin = defaultdict(list)
    for record in records:
        ts = int(record["captured_at_ms"])
        for asset in record.get("assets", []):
            if asset.get("mark") and asset.get("funding_1h_pct") is not None:
                by_coin[asset["coin"]].append(
                    (ts, float(asset["mark"]), float(asset["funding_1h_pct"])))
    target_ms, tolerance_ms = horizon_hours * HOUR, tolerance_minutes * 60_000
    out = []
    for coin, points in by_coin.items():
        points.sort()
        for i, (ts, mark, signal_funding_pct) in enumerate(points):
            if abs(signal_funding_pct) * 100 < min_funding_bps:
                continue
            target = ts + target_ms
            candidates = [p for p in points[i + 1:] if p[0] >= target - tolerance_ms][:2]
            if not candidates:
                continue
            future = min(candidates, key=lambda x: abs(x[0] - target))
            if abs(future[0] - target) > tolerance_ms:
                continue
            side = -1 if signal_funding_pct > 0 else 1
            raw_return = future[1] / mark - 1
            # Enter after funding at `ts`; exit at `future[0]`. Exclude both ambiguous boundary prints.
            held_rates = [rate / 100 for t, _, rate in points if ts < t < future[0]]
            funding_return = sum(-side * rate for rate in held_rates)
            net = side * raw_return + funding_return - roundtrip_bps / 10_000
            out.append({
                "coin": coin, "time": ts, "exit_time": future[0],
                "side": "SHORT" if side < 0 else "LONG",
                "signal_funding_bps": signal_funding_pct * 100,
                "funding_return_pct": funding_return * 100,
                "forward_return_pct": raw_return * 100,
                "net_return_pct": net * 100,
            })
    return sorted(out, key=lambda r: (r["time"], r["coin"]))


def summarize(rows):
    returns = [r["net_return_pct"] for r in rows]
    wins, losses = [x for x in returns if x > 0], [x for x in returns if x <= 0]
    by_side = {side: [r["net_return_pct"] for r in rows if r["side"] == side]
               for side in ("LONG", "SHORT")}
    equity = peak = drawdown = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    stdev = statistics.stdev(returns) if len(returns) > 1 else 0
    mean = statistics.fmean(returns) if returns else 0
    return {
        "trades": len(rows),
        "win_rate_pct": 100 * len(wins) / len(rows) if rows else 0,
        "mean_net_return_pct": mean,
        "median_net_return_pct": statistics.median(returns) if returns else 0,
        "stdev_net_return_pct": stdev,
        "mean_lcb95_pct": mean - 1.96 * stdev / math.sqrt(len(returns)) if returns else 0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses and sum(losses)
                         else (math.inf if wins else 0),
        "max_additive_drawdown_pct": drawdown,
        "by_side": {k: {"trades": len(v),
                        "mean_net_return_pct": statistics.fmean(v) if v else 0}
                    for k, v in by_side.items()},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", default="data/snapshots.jsonl")
    p.add_argument("--horizon", type=int, choices=(1, 4, 8, 24), default=1)
    p.add_argument("--min-funding-bps", type=float, default=.5)
    p.add_argument("--roundtrip-bps", type=float, default=12)
    p.add_argument("--trades-out")
    args = p.parse_args()
    rows = observations(load(args.path), args.horizon, args.min_funding_bps, args.roundtrip_bps)
    if args.trades_out:
        Path(args.trades_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.trades_out).write_text(
            "\n".join(json.dumps(r, separators=(",", ":")) for r in rows)
            + ("\n" if rows else ""))
    print(json.dumps(summarize(rows), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
