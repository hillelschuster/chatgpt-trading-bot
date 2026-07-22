#!/usr/bin/env python3
"""Rank liquid Hyperliquid perps and persist real hourly snapshots."""
import argparse, json, math, time, urllib.request
from pathlib import Path

URL = "https://api.hyperliquid.xyz/info"


def post(payload):
    req = urllib.request.Request(URL, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def rank(data, min_oi=1_000_000, min_volume=5_000_000):
    meta, contexts = data
    rows = []
    for asset, context in zip(meta["universe"], contexts):
        oi, volume, funding = map(float, (context.get("openInterest", 0), context.get("dayNtlVlm", 0), context.get("funding", 0)))
        mark = float(context.get("markPx", 0))
        oi_usd = oi * mark
        if oi_usd < min_oi or volume < min_volume:
            continue
        rows.append({
            "coin": asset["name"], "mark": mark,
            "funding_1h_pct": funding * 100, "funding_apr_pct": funding * 24 * 365 * 100,
            "open_interest_usd": oi_usd, "day_volume_usd": volume,
            "side_paid": "longs" if funding > 0 else "shorts",
            "score": abs(funding) * math.sqrt(oi_usd * volume),
        })
    return sorted(rows, key=lambda row: row["score"], reverse=True)


def append_snapshot(path, rows, captured_at_ms=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"captured_at_ms": captured_at_ms or int(time.time() * 1000), "assets": rows}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/snapshots.jsonl")
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()
    rows = rank(post({"type": "metaAndAssetCtxs"}))
    append_snapshot(args.out, rows)
    print(json.dumps(rows[:args.top], indent=2))


if __name__ == "__main__":
    main()
