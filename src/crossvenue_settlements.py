#!/usr/bin/env python3
"""Join prospective event windows to exact public realized-funding records."""
import argparse, json, time, urllib.parse, urllib.request
from collections import Counter
from pathlib import Path

HL_INFO = "https://api.hyperliquid.xyz/info"
OKX_API = "https://www.okx.com"
MATCH_TOLERANCE_MS = 60_000
QUERY_PADDING_MS = 5 * 60_000


def get_json(url, params=None, timeout=20):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "crossvenue-research/6"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def post_hl(payload, timeout=20):
    request = urllib.request.Request(
        HL_INFO, json.dumps(payload).encode(),
        {"Content-Type": "application/json", "User-Agent": "crossvenue-research/6"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def okx_data(response):
    if str(response.get("code")) != "0":
        raise ValueError(f"OKX code={response.get('code')}: {response.get('msg')}")
    return response.get("data") or []


def nearest(rows, boundary_ms, time_field, rate_fields, tolerance_ms=MATCH_TOLERANCE_MS):
    normalized = []
    for row in rows or []:
        if row.get(time_field) in (None, ""):
            continue
        rate = next((row.get(field) for field in rate_fields if row.get(field) not in (None, "")), None)
        if rate is None:
            continue
        normalized.append((abs(int(row[time_field]) - int(boundary_ms)), int(row[time_field]), float(rate)))
    if not normalized:
        return None
    distance, timestamp, rate = min(normalized)
    return {"time_ms": timestamp, "rate": rate} if distance <= tolerance_ms else None


def fetch_hl_settlement(coin, boundary_ms, hl_post=post_hl):
    rows = hl_post({"type": "fundingHistory", "coin": coin,
                    "startTime": int(boundary_ms) - QUERY_PADDING_MS,
                    "endTime": int(boundary_ms) + QUERY_PADDING_MS})
    return nearest(rows, boundary_ms, "time", ("fundingRate",))


def fetch_okx_settlement(inst_id, boundary_ms, http_get=get_json):
    response = http_get(f"{OKX_API}/api/v5/public/funding-rate-history", {
        "instId": inst_id, "before": int(boundary_ms) + QUERY_PADDING_MS,
        "after": int(boundary_ms) - QUERY_PADDING_MS, "limit": 100})
    return nearest(okx_data(response), boundary_ms, "fundingTime", ("realizedRate", "fundingRate"))


def valid_observation(value, boundary_ms):
    if not isinstance(value, dict) or value.get("time_ms") is None or value.get("rate") is None:
        return None
    if abs(int(value["time_ms"]) - int(boundary_ms)) > MATCH_TOLERANCE_MS:
        return None
    return {"time_ms": int(value["time_ms"]), "rate": float(value["rate"])}


def prior_by_id(existing):
    rows = {}
    for row in existing or []:
        event_id = row.get("event_id")
        if event_id:
            rows[event_id] = row
    return rows


def enrich_events(events, existing=None, hl_fetch=fetch_hl_settlement,
                  okx_fetch=fetch_okx_settlement, now_ms=None):
    """Enrich monotonically: exact observations persist and only missing legs are queried."""
    previous = prior_by_id(existing)
    output, reasons = [], Counter()
    hl_cache, okx_cache = {}, {}
    queries = Counter()
    reused_complete = newly_settled = 0
    attempted_at = int(time.time() * 1000) if now_ms is None else int(now_ms)

    def cached_fetch(cache, key, fetch, label):
        if key not in cache:
            queries[label] += 1
            try:
                cache[key] = (fetch(*key), None)
            except Exception as error:
                cache[key] = (None, f"{type(error).__name__}: {error}")
        return cache[key]

    for source in events:
        event = dict(source)
        old = previous.get(event.get("event_id"), {})
        if event.get("status") != "complete":
            event["settlement_status"] = "not_eligible"
            event["settlement_reason"] = "event_not_complete"
            event["settlement_observations"] = old.get("settlement_observations") or {}
            event["realized_funding"] = None
            event["settlement_attempts"] = int(old.get("settlement_attempts") or 0)
            output.append(event); reasons["event_not_complete"] += 1
            continue

        coin = event["coin"]
        hl_boundary = int(event["hyperliquid_funding_time_ms"])
        okx_boundary = int(event["okx_funding_time_ms"])
        old_obs = old.get("settlement_observations") or {}
        old_realized = old.get("realized_funding") or {}
        hl = valid_observation(old_obs.get("hyperliquid") or old_realized.get("hyperliquid"), hl_boundary)
        okx = valid_observation(old_obs.get("okx_swap") or old_realized.get("okx_swap"), okx_boundary)

        if old.get("settlement_status") == "complete" and hl and okx:
            reused_complete += 1
            errors = []
        else:
            errors = []
            if hl is None:
                value, error = cached_fetch(hl_cache, (coin, hl_boundary), hl_fetch, "hyperliquid")
                hl = valid_observation(value, hl_boundary)
                if error:
                    errors.append("hyperliquid_fetch_error")
            if okx is None:
                value, error = cached_fetch(okx_cache, (f"{coin}-USDT-SWAP", okx_boundary),
                                            okx_fetch, "okx_swap")
                okx = valid_observation(value, okx_boundary)
                if error:
                    errors.append("okx_fetch_error")

        complete = hl is not None and okx is not None
        reason = None
        if not complete:
            if errors:
                reason = "+".join(errors)
            elif hl is None:
                reason = "hyperliquid_settlement_missing"
            else:
                reason = "okx_settlement_missing"
        event["settlement_status"] = "complete" if complete else "pending"
        event["settlement_reason"] = reason
        event["settlement_observations"] = {"hyperliquid": hl, "okx_swap": okx}
        event["realized_funding"] = None if not complete else {
            "hyperliquid": hl, "okx_swap": okx,
            "difference_hl_minus_okx": hl["rate"] - okx["rate"],
            "source": {"hyperliquid": "fundingHistory", "okx_swap": "funding-rate-history"}}
        attempts = int(old.get("settlement_attempts") or 0)
        queried = (old.get("settlement_status") != "complete" or not old.get("realized_funding")) and (
            (coin, hl_boundary) in hl_cache or (f"{coin}-USDT-SWAP", okx_boundary) in okx_cache)
        event["settlement_attempts"] = attempts + int(queried)
        if queried:
            event["last_settlement_attempt_ms"] = attempted_at
        elif old.get("last_settlement_attempt_ms") is not None:
            event["last_settlement_attempt_ms"] = int(old["last_settlement_attempt_ms"])
        if complete and old.get("settlement_status") != "complete":
            newly_settled += 1
        if reason:
            reasons[reason] += 1
        output.append(event)

    summary = {"events": len(output),
               "settled": sum(e.get("settlement_status") == "complete" for e in output),
               "pending": sum(e.get("settlement_status") == "pending" for e in output),
               "not_eligible": sum(e.get("settlement_status") == "not_eligible" for e in output),
               "newly_settled": newly_settled, "reused_complete": reused_complete,
               "api_queries": dict(sorted(queries.items())),
               "reasons": dict(sorted(reasons.items()))}
    return output, summary


def read_jsonl(path):
    target = Path(path)
    return [] if not target.exists() else [json.loads(line) for line in target.read_text().splitlines() if line.strip()]


def write_jsonl(path, rows):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n" for row in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="data/crossvenue_events.jsonl")
    parser.add_argument("--out", default="data/crossvenue_settled_events.jsonl")
    parser.add_argument("--existing", help="prior settled JSONL; defaults to --out for artifact resume")
    parser.add_argument("--report", default="reports/crossvenue_settlements.json")
    args = parser.parse_args()
    existing_path = args.existing or args.out
    rows, summary = enrich_events(read_jsonl(args.path), read_jsonl(existing_path))
    write_jsonl(args.out, rows)
    report = Path(args.report); report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"out": args.out, "report": args.report, **summary}, indent=2))


if __name__ == "__main__":
    main()
