#!/usr/bin/env python3
"""Collect one pre-entry Hyperliquid/Bybit funding-basis snapshot from public APIs."""
import argparse, json, time, urllib.parse, urllib.request
from pathlib import Path

HL_INFO = "https://api.hyperliquid.xyz/info"
BYBIT_API = "https://api.bybit.com"
SCHEMA_VERSION = 2


def get_json(url, params=None, timeout=20):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "crossvenue-research/2"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def post_hl(payload, timeout=20):
    req = urllib.request.Request(HL_INFO, json.dumps(payload).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "crossvenue-research/2"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _float(value):
    return None if value in (None, "") else float(value)


def hl_predicted_map(rows):
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
                    "funding_interval_hours": data.get("fundingIntervalHours"),
                }
        out[str(coin)] = normalized
    return out


def hl_context_map(meta_and_contexts):
    meta, contexts = meta_and_contexts
    return {asset["name"]: {
        "mark_price": _float(ctx.get("markPx")), "oracle_price": _float(ctx.get("oraclePx")),
        "current_funding_rate": _float(ctx.get("funding")),
        "open_interest_base": _float(ctx.get("openInterest")),
        "day_notional_volume": _float(ctx.get("dayNtlVlm")),
    } for asset, ctx in zip(meta.get("universe", []), contexts) if not asset.get("isDelisted")}


def hl_book(book):
    levels = book.get("levels") or [[], []]
    return {"bid": _float(levels[0][0].get("px")) if levels[0] else None,
            "ask": _float(levels[1][0].get("px")) if len(levels) > 1 and levels[1] else None,
            "book_time_ms": book.get("time")}


def bybit_result(response):
    if response.get("retCode") != 0:
        raise ValueError(f"Bybit retCode={response.get('retCode')}: {response.get('retMsg')}")
    return response.get("result") or {}


def bybit_symbol(coin):
    return f"{coin.upper()}USDT"


def collect_coin(coin, now_ms=None, hl_post=post_hl, http_get=get_json):
    now_ms = now_ms or int(time.time() * 1000)
    predicted = hl_predicted_map(hl_post({"type": "predictedFundings"}))
    contexts = hl_context_map(hl_post({"type": "metaAndAssetCtxs"}))
    hbook = hl_book(hl_post({"type": "l2Book", "coin": coin}))
    rates = predicted.get(coin, {})
    hl_rate = rates.get("HlPerp") or {}
    bybit_prediction = rates.get("BybitPerp") or {}

    symbol = bybit_symbol(coin)
    ticker_result = bybit_result(http_get(f"{BYBIT_API}/v5/market/tickers",
                                          {"category": "linear", "symbol": symbol}))
    ticker_rows = ticker_result.get("list") or []
    if len(ticker_rows) != 1:
        raise ValueError(f"Bybit ticker missing for {symbol}")
    ticker = ticker_rows[0]
    orderbook = bybit_result(http_get(f"{BYBIT_API}/v5/market/orderbook",
                                      {"category": "linear", "symbol": symbol, "limit": 1}))

    return {
        "schema_version": SCHEMA_VERSION, "captured_at_ms": now_ms, "coin": coin,
        "symbol_map": {"hyperliquid": coin, "bybit_linear": symbol},
        "hyperliquid": {**contexts.get(coin, {}), **hbook,
            "predicted_funding_rate": hl_rate.get("funding_rate"),
            "next_funding_time_ms": hl_rate.get("next_funding_time_ms"),
            "funding_interval_hours": hl_rate.get("funding_interval_hours")},
        "bybit_linear": {
            "mark_price": _float(ticker.get("markPrice")), "index_price": _float(ticker.get("indexPrice")),
            "current_funding_rate": _float(ticker.get("fundingRate")),
            "predicted_funding_rate_from_hl": bybit_prediction.get("funding_rate"),
            "next_funding_time_ms": int(ticker["nextFundingTime"]) if ticker.get("nextFundingTime") else None,
            "funding_interval_hours_from_hl": bybit_prediction.get("funding_interval_hours"),
            "bid": _float(orderbook.get("b", [[None]])[0][0]) if orderbook.get("b") else None,
            "ask": _float(orderbook.get("a", [[None]])[0][0]) if orderbook.get("a") else None,
            "book_time_ms": orderbook.get("cts") or orderbook.get("ts"),
        },
        "semantics": {"decision_input_only": True, "no_realized_future_funding_used": True,
                      "hyperliquid_prediction_source": "predictedFundings"},
    }


def validate(snapshot, max_skew_ms=60_000):
    errors = []
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version")
    now = int(snapshot.get("captured_at_ms") or 0)
    for venue in ("hyperliquid", "bybit_linear"):
        row = snapshot.get(venue) or {}
        bid, ask, stamp = row.get("bid"), row.get("ask"), row.get("book_time_ms")
        if bid is None or ask is None or bid <= 0 or ask <= 0 or bid >= ask:
            errors.append(f"{venue}.book")
        if stamp is None or abs(now - int(stamp)) > max_skew_ms:
            errors.append(f"{venue}.book_time_skew")
        if row.get("next_funding_time_ms") is None:
            errors.append(f"{venue}.next_funding_time")
    return errors


def append_jsonl(path, rows):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--coins", default="BTC,ETH"); p.add_argument("--out", default="data/crossvenue_snapshots.jsonl")
    p.add_argument("--max-skew-ms", type=int, default=60_000); a = p.parse_args()
    rows = [collect_coin(c.strip().upper()) for c in a.coins.split(",") if c.strip()]
    failures = {r["coin"]: validate(r, a.max_skew_ms) for r in rows}
    failures = {c: e for c, e in failures.items() if e}
    if failures: raise SystemExit(json.dumps({"invalid": failures}, sort_keys=True))
    append_jsonl(a.out, rows)
    print(json.dumps({"out": a.out, "coins": [r["coin"] for r in rows], "rows": len(rows)}, indent=2))


if __name__ == "__main__": main()
