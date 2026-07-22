#!/usr/bin/env python3
"""Bootstrap Hyperliquid hourly funding/price panels from public official endpoints."""
import argparse, json, time, urllib.request
from pathlib import Path

URL = "https://api.hyperliquid.xyz/info"
HOUR = 3_600_000


def post(payload):
    req = urllib.request.Request(URL, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def paged_funding(coin, start_ms, end_ms, fetch=post):
    rows, cursor = [], start_ms
    while cursor <= end_ms:
        page = fetch({"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": end_ms})
        fresh = [r for r in page if cursor <= int(r["time"]) <= end_ms]
        rows.extend(fresh)
        if not fresh or len(page) < 500:
            break
        nxt = max(int(r["time"]) for r in fresh) + 1
        if nxt <= cursor:
            break
        cursor = nxt
    return {int(r["time"]): float(r["fundingRate"]) for r in rows}


def candles(coin, start_ms, end_ms, fetch=post):
    out, cursor = {}, start_ms
    while cursor <= end_ms:
        page_end = min(end_ms, cursor + 4_999 * HOUR)
        page = fetch({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": "1h", "startTime": cursor, "endTime": page_end}})
        for row in page:
            ts = int(row["t"])
            if start_ms <= ts <= end_ms:
                out[ts] = float(row["c"])
        if page_end == end_ms:
            break
        cursor = page_end + HOUR
    return out


def panel(coins, start_ms, end_ms, fetch=post):
    by_time = {}
    for coin in coins:
        funding = paged_funding(coin, start_ms, end_ms, fetch)
        prices = candles(coin, start_ms, end_ms, fetch)
        for ts, rate in funding.items():
            hour = ts - ts % HOUR
            mark = prices.get(hour)
            if mark is None:
                continue
            by_time.setdefault(hour, []).append({
                "coin": coin, "mark": mark, "funding_1h_pct": rate * 100,
                "open_interest_usd": None, "day_volume_usd": None})
    return [{"captured_at_ms": ts, "assets": sorted(assets, key=lambda x: x["coin"])}
            for ts, assets in sorted(by_time.items())]


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))
    return len(records)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--coins", default="BTC,ETH,SOL")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--out", default="data/history.jsonl")
    args = p.parse_args()
    end = int(time.time() * 1000) // HOUR * HOUR
    start = end - args.days * 24 * HOUR
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    records = panel(coins, start, end)
    print(json.dumps({"records": write_jsonl(args.out, records), "start_ms": start,
                      "end_ms": end, "coins": coins}, indent=2))


if __name__ == "__main__":
    main()
