#!/usr/bin/env python3
"""Collect resumable pre-entry Hyperliquid/OKX funding-basis snapshots."""
import argparse, json, time, urllib.parse, urllib.request
from pathlib import Path

HL_INFO = "https://api.hyperliquid.xyz/info"
OKX_API = "https://www.okx.com"
SCHEMA_VERSION = 4
DEFAULT_CADENCE_MS = 300_000


def get_json(url, params=None, timeout=20):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "crossvenue-research/4"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def post_hl(payload, timeout=20):
    req = urllib.request.Request(HL_INFO, json.dumps(payload).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "crossvenue-research/4"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _float(value):
    return None if value in (None, "") else float(value)


def effective_next_funding_time(reported_ms, captured_ms, interval_hours):
    """Advance a stale venue boundary to the first funding boundary after capture."""
    if reported_ms is None or interval_hours in (None, 0):
        return None
    reported_ms, captured_ms = int(reported_ms), int(captured_ms)
    interval_ms = int(float(interval_hours) * 3_600_000)
    if interval_ms <= 0:
        return None
    if reported_ms > captured_ms:
        return reported_ms
    jumps = (captured_ms - reported_ms) // interval_ms + 1
    return reported_ms + jumps * interval_ms


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


def okx_data(response):
    if str(response.get("code")) != "0":
        raise ValueError(f"OKX code={response.get('code')}: {response.get('msg')}")
    return response.get("data") or []


def okx_inst_id(coin):
    return f"{coin.upper()}-USDT-SWAP"


def collect_coin(coin, now_ms=None, cadence_ms=DEFAULT_CADENCE_MS,
                 hl_post=post_hl, http_get=get_json):
    now_ms = now_ms or int(time.time() * 1000)
    predicted = hl_predicted_map(hl_post({"type": "predictedFundings"}))
    contexts = hl_context_map(hl_post({"type": "metaAndAssetCtxs"}))
    hbook = hl_book(hl_post({"type": "l2Book", "coin": coin}))
    hl_rate = predicted.get(coin, {}).get("HlPerp") or {}
    reported_boundary = hl_rate.get("next_funding_time_ms")
    effective_boundary = effective_next_funding_time(
        reported_boundary, now_ms, hl_rate.get("funding_interval_hours"))

    inst_id = okx_inst_id(coin)
    ticker_rows = okx_data(http_get(f"{OKX_API}/api/v5/market/ticker", {"instId": inst_id}))
    book_rows = okx_data(http_get(f"{OKX_API}/api/v5/market/books", {"instId": inst_id, "sz": 1}))
    funding_rows = okx_data(http_get(f"{OKX_API}/api/v5/public/funding-rate", {"instId": inst_id}))
    if len(ticker_rows) != 1 or len(book_rows) != 1 or len(funding_rows) != 1:
        raise ValueError(f"OKX incomplete response for {inst_id}")
    ticker, book, funding = ticker_rows[0], book_rows[0], funding_rows[0]

    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at_ms": now_ms,
        "cadence_slot_ms": now_ms // cadence_ms * cadence_ms,
        "coin": coin,
        "symbol_map": {"hyperliquid": coin, "okx_swap": inst_id},
        "hyperliquid": {**contexts.get(coin, {}), **hbook,
            "predicted_funding_rate": hl_rate.get("funding_rate"),
            "reported_next_funding_time_ms": reported_boundary,
            "effective_next_funding_time_ms": effective_boundary,
            "funding_interval_hours": hl_rate.get("funding_interval_hours")},
        "okx_swap": {
            "last_price": _float(ticker.get("last")),
            "bid": _float(book.get("bids", [[None]])[0][0]) if book.get("bids") else None,
            "ask": _float(book.get("asks", [[None]])[0][0]) if book.get("asks") else None,
            "book_time_ms": int(book["ts"]) if book.get("ts") else None,
            "predicted_funding_rate": _float(funding.get("fundingRate")),
            "funding_time_ms": int(funding["fundingTime"]) if funding.get("fundingTime") else None,
            "next_funding_time_ms": int(funding["nextFundingTime"]) if funding.get("nextFundingTime") else None,
            "settled_funding_rate": _float(funding.get("settFundingRate")),
            "premium": _float(funding.get("premium")),
            "funding_event_time_ms": int(funding["ts"]) if funding.get("ts") else None,
        },
        "semantics": {"decision_input_only": True, "no_realized_future_funding_used": True,
                      "okx_funding_rate_method": funding.get("method"),
                      "hyperliquid_prediction_source": "predictedFundings",
                      "hyperliquid_boundary_rule": "advance reported boundary by interval until after capture"},
    }


def validate(snapshot, max_skew_ms=60_000):
    errors = []
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version")
    now = int(snapshot.get("captured_at_ms") or 0)
    for venue in ("hyperliquid", "okx_swap"):
        row = snapshot.get(venue) or {}
        bid, ask, stamp = row.get("bid"), row.get("ask"), row.get("book_time_ms")
        if bid is None or ask is None or bid <= 0 or ask <= 0 or bid >= ask:
            errors.append(f"{venue}.book")
        if stamp is None or abs(now - int(stamp)) > max_skew_ms:
            errors.append(f"{venue}.book_time_skew")
    boundary = snapshot.get("hyperliquid", {}).get("effective_next_funding_time_ms")
    if boundary is None or int(boundary) <= now:
        errors.append("hyperliquid.effective_next_funding_time")
    okx = snapshot.get("okx_swap", {})
    if okx.get("funding_time_ms") is None or okx.get("predicted_funding_rate") is None:
        errors.append("okx_swap.funding")
    if snapshot.get("cadence_slot_ms") is None:
        errors.append("cadence_slot")
    return errors


def read_jsonl(path):
    target = Path(path)
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text().splitlines() if line.strip()]


def append_jsonl(path, rows):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    existing = {(int(r.get("cadence_slot_ms", -1)), r.get("coin")) for r in read_jsonl(target)}
    written = 0
    with target.open("a", encoding="utf-8") as handle:
        for row in rows:
            key = (int(row["cadence_slot_ms"]), row["coin"])
            if key in existing:
                continue
            handle.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
            existing.add(key); written += 1
    return written


def continuity(rows, coins, cadence_ms=DEFAULT_CADENCE_MS):
    expected = sorted({coin.upper() for coin in coins})
    keys, duplicates, by_slot, invalid = set(), [], {}, []
    for row in rows:
        key = (int(row.get("cadence_slot_ms", -1)), row.get("coin"))
        if key in keys:
            duplicates.append(key)
        keys.add(key)
        by_slot.setdefault(key[0], set()).add(key[1])
        invalid.extend((key, error) for error in validate(row))
    slots = sorted(slot for slot in by_slot if slot >= 0)
    gaps = []
    for left, right in zip(slots, slots[1:]):
        if right - left > cadence_ms:
            gaps.append({"after_ms": left, "before_ms": right,
                         "missing_slots": (right - left) // cadence_ms - 1})
    incomplete = {str(slot): sorted(set(expected) - by_slot[slot])
                  for slot in slots if set(expected) != by_slot[slot]}
    return {"rows": len(rows), "slots": len(slots), "duplicates": duplicates,
            "gaps": gaps, "incomplete_slots": incomplete, "invalid": invalid,
            "complete_cadence": not gaps,
            "valid": not duplicates and not incomplete and not invalid}


def collect_once(coins, out, max_skew_ms, cadence_ms):
    rows = [collect_coin(coin, cadence_ms=cadence_ms) for coin in coins]
    failures = {row["coin"]: validate(row, max_skew_ms) for row in rows}
    failures = {coin: errors for coin, errors in failures.items() if errors}
    if failures:
        raise SystemExit(json.dumps({"invalid": failures}, sort_keys=True))
    return append_jsonl(out, rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--coins", default="BTC,ETH")
    p.add_argument("--out", default="data/crossvenue_snapshots.jsonl")
    p.add_argument("--max-skew-ms", type=int, default=60_000)
    p.add_argument("--cadence-seconds", type=int, default=300)
    p.add_argument("--samples", type=int, default=1)
    p.add_argument("--audit-only", action="store_true")
    a = p.parse_args()
    coins = [coin.strip().upper() for coin in a.coins.split(",") if coin.strip()]
    cadence_ms = a.cadence_seconds * 1000
    written = 0
    if not a.audit_only:
        for number in range(a.samples):
            written += collect_once(coins, a.out, a.max_skew_ms, cadence_ms)
            if number + 1 < a.samples:
                time.sleep(a.cadence_seconds)
    report = continuity(read_jsonl(a.out), coins, cadence_ms)
    if not report["valid"]:
        raise SystemExit(json.dumps({"continuity": report}, sort_keys=True))
    print(json.dumps({"out": a.out, "coins": coins, "written": written, **report}, indent=2))


if __name__ == "__main__":
    main()
