#!/usr/bin/env python3
"""Bootstrap a broad Hyperliquid hourly panel from official public endpoints."""
import argparse, json, time, urllib.error, urllib.request
from pathlib import Path

URL = "https://api.hyperliquid.xyz/info"
HOUR = 3_600_000


def post(payload, attempts=6):
    req = urllib.request.Request(URL, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if attempt + 1 == attempts:
                raise
            retry_after = float(error.headers.get("Retry-After") or 0)
            time.sleep(max(retry_after, min(30, 2 ** attempt)))
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(min(30, 2 ** attempt))


def liquid_universe(limit=12, min_day_volume=10_000_000, fetch=post):
    meta, contexts = fetch({"type": "metaAndAssetCtxs"})
    rows = []
    for asset, ctx in zip(meta["universe"], contexts):
        if asset.get("isDelisted"):
            continue
        volume = float(ctx.get("dayNtlVlm") or 0)
        mark = float(ctx.get("markPx") or 0)
        oi = float(ctx.get("openInterest") or 0) * mark
        if volume >= min_day_volume and mark > 0:
            rows.append({"coin": asset["name"], "day_volume_usd": volume,
                         "open_interest_usd": oi, "mark": mark})
    rows.sort(key=lambda x: (x["day_volume_usd"], x["open_interest_usd"]), reverse=True)
    return rows[:limit]


def paged_funding(coin, start_ms, end_ms, fetch=post, request_delay=0):
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
        if request_delay:
            time.sleep(request_delay)
    return {int(r["time"]): float(r["fundingRate"]) for r in rows}


def candles(coin, start_ms, end_ms, fetch=post, request_delay=0):
    out, cursor = {}, start_ms
    while cursor <= end_ms:
        page_end = min(end_ms, cursor + 4_999 * HOUR)
        page = fetch({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": "1h", "startTime": cursor, "endTime": page_end}})
        for row in page:
            ts = int(row["t"])
            if start_ms <= ts <= end_ms:
                # `t` is candle open time; the open is observable at `t`. Using `c` here leaks the next hour.
                out[ts] = float(row["o"])
        if page_end == end_ms:
            break
        cursor = page_end + HOUR
        if request_delay:
            time.sleep(request_delay)
    return out


def panel(coins, start_ms, end_ms, fetch=post, min_assets=3, request_delay=0):
    by_time = {}
    for coin in coins:
        funding = paged_funding(coin, start_ms, end_ms, fetch, request_delay)
        prices = candles(coin, start_ms, end_ms, fetch, request_delay)
        for ts, rate in funding.items():
            hour = ts - ts % HOUR
            mark = prices.get(hour)
            if mark is not None:
                by_time.setdefault(hour, []).append({
                    "coin": coin, "mark": mark, "funding_1h_pct": rate * 100,
                    "open_interest_usd": None, "day_volume_usd": None})
    return [{"captured_at_ms": ts, "assets": sorted(assets, key=lambda x: x["coin"])}
            for ts, assets in sorted(by_time.items()) if len(assets) >= min_assets]


def quality(records, requested):
    counts = [len(r["assets"]) for r in records]
    return {"records": len(records), "requested_assets": len(requested),
            "min_assets": min(counts) if counts else 0,
            "median_assets": sorted(counts)[len(counts) // 2] if counts else 0,
            "max_assets": max(counts) if counts else 0,
            "coverage_pct": 100 * sum(counts) / (len(counts) * len(requested)) if counts and requested else 0}


def write_jsonl(path, records):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))
    return len(records)


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--coins", help="comma-separated fixed universe; overrides auto-selection")
    p.add_argument("--auto-coins", type=int, default=12)
    p.add_argument("--min-day-volume", type=float, default=10_000_000)
    p.add_argument("--min-assets", type=int, default=6)
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--request-delay", type=float, default=2.6,
                   help="seconds between paginated requests; avoids public API rate-limit bursts")
    p.add_argument("--out", default="data/history.jsonl")
    p.add_argument("--meta-out", default="reports/universe.json")
    args = p.parse_args()
    selected = ([{"coin": c.strip().upper()} for c in args.coins.split(",") if c.strip()]
                if args.coins else liquid_universe(args.auto_coins, args.min_day_volume))
    coins = [x["coin"] for x in selected]
    if len(coins) < args.min_assets:
        raise SystemExit(f"only {len(coins)} eligible assets; need {args.min_assets}")
    end = int(time.time() * 1000) // HOUR * HOUR
    start = end - args.days * 24 * HOUR
    records = panel(coins, start, end, min_assets=args.min_assets, request_delay=args.request_delay)
    stats = quality(records, coins)
    write_jsonl(args.out, records)
    write_json(args.meta_out, {"selected_at_ms": int(time.time() * 1000), "assets": selected,
                               "start_ms": start, "end_ms": end, "price_source": "hourly_candle_open",
                               "request_delay_seconds": args.request_delay, "quality": stats})
    print(json.dumps({"out": args.out, "meta_out": args.meta_out, "coins": coins, **stats}, indent=2))


if __name__ == "__main__":
    main()
