#!/usr/bin/env python3
"""Join prospective event windows to exact public realized-funding records."""
import argparse, json, urllib.parse, urllib.request
from collections import Counter
from pathlib import Path

HL_INFO = "https://api.hyperliquid.xyz/info"
OKX_API = "https://www.okx.com"
MATCH_TOLERANCE_MS = 60_000
QUERY_PADDING_MS = 5 * 60_000


def get_json(url, params=None, timeout=20):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "crossvenue-research/5"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def post_hl(payload, timeout=20):
    request = urllib.request.Request(
        HL_INFO, json.dumps(payload).encode(),
        {"Content-Type": "application/json", "User-Agent": "crossvenue-research/5"})
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


def enrich_events(events, hl_fetch=fetch_hl_settlement, okx_fetch=fetch_okx_settlement):
    output, reasons = [], Counter()
    for source in events:
        event = dict(source)
        if event.get("status") != "complete":
            event["settlement_status"] = "not_eligible"
            event["settlement_reason"] = "event_not_complete"
            output.append(event); reasons["event_not_complete"] += 1
            continue
        coin = event["coin"]
        hl_boundary = int(event["hyperliquid_funding_time_ms"])
        okx_boundary = int(event["okx_funding_time_ms"])
        hl = hl_fetch(coin, hl_boundary)
        okx = okx_fetch(f"{coin}-USDT-SWAP", okx_boundary)
        reason = None
        if hl is None:
            reason = "hyperliquid_settlement_missing"
        elif okx is None:
            reason = "okx_settlement_missing"
        event["settlement_status"] = "complete" if reason is None else "pending"
        event["settlement_reason"] = reason
        event["realized_funding"] = None if reason else {
            "hyperliquid": hl, "okx_swap": okx,
            "difference_hl_minus_okx": hl["rate"] - okx["rate"],
            "source": {"hyperliquid": "fundingHistory", "okx_swap": "funding-rate-history"}}
        if reason:
            reasons[reason] += 1
        output.append(event)
    summary = {"events": len(output),
               "settled": sum(e.get("settlement_status") == "complete" for e in output),
               "pending": sum(e.get("settlement_status") == "pending" for e in output),
               "not_eligible": sum(e.get("settlement_status") == "not_eligible" for e in output),
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
    parser.add_argument("--report", default="reports/crossvenue_settlements.json")
    args = parser.parse_args()
    rows, summary = enrich_events(read_jsonl(args.path))
    write_jsonl(args.out, rows)
    report = Path(args.report); report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"out": args.out, "report": args.report, **summary}, indent=2))


if __name__ == "__main__":
    main()
