#!/usr/bin/env python3
"""Chronologically evaluate whether funding extremes predict net forward returns."""
import argparse, json, math, statistics
from collections import defaultdict
from pathlib import Path


def load(path):
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    records.sort(key=lambda r: r["captured_at_ms"])
    return records


def observations(records, horizon_hours=1, min_funding_bps=0.5, roundtrip_bps=9.0, tolerance_minutes=20):
    by_coin = defaultdict(list)
    for record in records:
        ts = int(record["captured_at_ms"])
        for asset in record.get("assets", []):
            if asset.get("mark") and asset.get("funding_1h_pct") is not None:
                by_coin[asset["coin"]].append((ts, float(asset["mark"]), float(asset["funding_1h_pct"])))
    target_ms, tolerance_ms = horizon_hours * 3_600_000, tolerance_minutes * 60_000
    out = []
    for coin, points in by_coin.items():
        points.sort()
        j = 0
        for ts, mark, funding_pct in points:
            if abs(funding_pct) * 100 < min_funding_bps:
                continue
            target = ts + target_ms
            while j < len(points) and points[j][0] < target - tolerance_ms:
                j += 1
            candidates = points[max(0, j - 1):min(len(points), j + 2)]
            if not candidates:
                continue
            future = min(candidates, key=lambda x: abs(x[0] - target))
            if abs(future[0] - target) > tolerance_ms:
                continue
            raw_return = future[1] / mark - 1
            side = -1 if funding_pct > 0 else 1
            funding_received = abs(funding_pct) / 100
            net = side * raw_return + funding_received - roundtrip_bps / 10_000
            out.append({"coin": coin, "time": ts, "side": "SHORT" if side < 0 else "LONG", "funding_bps": funding_pct * 100,
                        "forward_return_pct": raw_return * 100, "net_return_pct": net * 100})
    return out


def summarize(rows):
    returns = [r["net_return_pct"] for r in rows]
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x <= 0]
    by_side = {side: [r["net_return_pct"] for r in rows if r["side"] == side] for side in ("LONG", "SHORT")}
    return {
        "trades": len(rows),
        "win_rate_pct": 100 * len(wins) / len(rows) if rows else 0,
        "mean_net_return_pct": statistics.fmean(returns) if returns else 0,
        "median_net_return_pct": statistics.median(returns) if returns else 0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses and sum(losses) else (math.inf if wins else 0),
        "by_side": {k: {"trades": len(v), "mean_net_return_pct": statistics.fmean(v) if v else 0} for k, v in by_side.items()},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", default="data/snapshots.jsonl")
    p.add_argument("--horizon", type=int, choices=(1, 4, 8, 24), default=1)
    p.add_argument("--min-funding-bps", type=float, default=.5)
    p.add_argument("--roundtrip-bps", type=float, default=9)
    p.add_argument("--trades-out")
    args = p.parse_args()
    rows = observations(load(args.path), args.horizon, args.min_funding_bps, args.roundtrip_bps)
    if args.trades_out:
        Path(args.trades_out).write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + ("\n" if rows else ""))
    print(json.dumps(summarize(rows), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
