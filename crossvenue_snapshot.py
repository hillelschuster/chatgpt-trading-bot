#!/usr/bin/env python3
"""Collect one pre-entry cross-venue funding/basis snapshot from public APIs."""
import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

HL_INFO = "https://api.hyperliquid.xyz/info"
BINANCE_FAPI = "https://fapi.binance.com"
SCHEMA_VERSION = 1


def get_json(url, params=None, timeout=20):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "crossvenue-research/1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def post_hl(payload, timeout=20):
    req = urllib.request.Request(
        HL_INFO,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "crossvenue-research/1"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _float(value):
    return None if value in (None, "") else float(value)


def hl_predicted_map(rows):
    """Normalize Hyperliquid predictedFundings response by coin and venue."""
    out = {}
    for item in rows:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        coin, venues = item
        normalized = {}
        for venue_row in venues or []:
            if not isinstance(venue_row, (list, tuple)) or len(venue_row) != 2:
                continue
            venue, data = venue_row
            if isinstance(data, dict):
                normalized[str(venue)] = {
                    "funding_rate": _float(data.get("fundingRate")),
                    "next_funding_time_ms": data.get("nextFundingTime"),
                }
        out[str(coin)] = normalized
    return out


def hl_context_map(meta_and_contexts):
    meta, contexts = meta_and_contexts
    return {
        asset["name"]: {
            "mark_price": _float(ctx.get("markPx")),
            "oracle_price": _float(ctx.get("oraclePx")),
            "current_funding_rate": _float(ctx.get("funding")),
            "open_interest_base": _float(ctx.get("openInterest")),
            "day_notional_volume": _float(ctx.get("dayNtlVlm")),
        }
        for asset, ctx in zip(meta.get("universe", []), contexts)
        if not asset.get("isDelisted")
    }


def best_bid_ask(book):
    levels = book.get("levels") or [[], []]
    bid = _float(levels[0][0].get("px")) if len(levels) > 0 and levels[0] else None
    ask = _float(levels[1][0].get("px")) if len(levels) > 1 and levels[1] else None
    return {"bid": bid, "ask": ask, "book_time_ms": book.get("time")}


def binance_symbol(coin):
    return f"{coin.upper()}USDT"


def collect_coin(coin, now_ms=None, hl_post=post_hl, http_get=get_json):
    now_ms = now_ms or int(time.time() * 1000)
    predicted = hl_predicted_map(hl_post({"type": "predictedFundings"}))
    contexts = hl_context_map(hl_post({"type": "metaAndAssetCtxs"}))
    hl_book = best_bid_ask(hl_post({"type": "l2Book", "coin": coin}))

    symbol = binance_symbol(coin)
    premium = http_get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex", {"symbol": symbol})
    depth = http_get(f"{BINANCE_FAPI}/fapi/v1/depth", {"symbol": symbol, "limit": 5})
    binance_book = {
        "bid": _float(depth.get("bids", [[None]])[0][0]) if depth.get("bids") else None,
        "ask": _float(depth.get("asks", [[None]])[0][0]) if depth.get("asks") else None,
        "book_time_ms": depth.get("T") or depth.get("E"),
    }

    venue_rates = predicted.get(coin, {})
    hl_prediction = venue_rates.get("HlPerp") or venue_rates.get("hyperliquid") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at_ms": now_ms,
        "coin": coin,
        "symbol_map": {"hyperliquid": coin, "binance_usdm": symbol},
        "hyperliquid": {
            **contexts.get(coin, {}),
            **hl_book,
            "predicted_funding_rate": hl_prediction.get("funding_rate"),
            "next_funding_time_ms": hl_prediction.get("next_funding_time_ms"),
            "predicted_venues": venue_rates,
        },
        "binance_usdm": {
            "mark_price": _float(premium.get("markPrice")),
            "index_price": _float(premium.get("indexPrice")),
            "last_funding_rate": _float(premium.get("lastFundingRate")),
            "next_funding_time_ms": premium.get("nextFundingTime"),
            "event_time_ms": premium.get("time"),
            **binance_book,
        },
        "semantics": {
            "decision_input_only": True,
            "rates_are_current_predictions_or_latest_public_values": True,
            "no_realized_future_funding_used": True,
        },
    }


def validate(snapshot, max_skew_ms=60_000):
    errors = []
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version")
    for venue in ("hyperliquid", "binance_usdm"):
        row = snapshot.get(venue) or {}
        bid, ask = row.get("bid"), row.get("ask")
        if bid is None or ask is None or bid <= 0 or ask <= 0 or bid >= ask:
            errors.append(f"{venue}.book")
    event = snapshot.get("binance_usdm", {}).get("event_time_ms")
    if event is not None and abs(int(snapshot["captured_at_ms"]) - int(event)) > max_skew_ms:
        errors.append("binance_usdm.event_time_skew")
    return errors


def append_jsonl(path, rows):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coins", default="BTC,ETH")
    parser.add_argument("--out", default="data/crossvenue_snapshots.jsonl")
    parser.add_argument("--max-skew-ms", type=int, default=60_000)
    args = parser.parse_args()
    rows = [collect_coin(c.strip().upper()) for c in args.coins.split(",") if c.strip()]
    failures = {row["coin"]: validate(row, args.max_skew_ms) for row in rows}
    failures = {coin: errs for coin, errs in failures.items() if errs}
    if failures:
        raise SystemExit(json.dumps({"invalid": failures}, sort_keys=True))
    append_jsonl(args.out, rows)
    print(json.dumps({"out": args.out, "coins": [r["coin"] for r in rows], "rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
