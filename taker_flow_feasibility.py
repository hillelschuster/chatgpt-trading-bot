#!/usr/bin/env python3
"""Probe official Binance USD-M aggTrades archives for experiment feasibility.

This module deliberately stops at data validity and descriptive bucket counts. It
never computes strategy P&L, so running it cannot leak the frozen holdout result.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Trade:
    agg_id: int
    price: float
    quantity: float
    timestamp_ms: int
    buyer_is_maker: bool

    @property
    def signed_notional(self) -> float:
        sign = -1.0 if self.buyer_is_maker else 1.0
        return sign * self.price * self.quantity


def archive_url(symbol: str, day: date) -> str:
    filename = f"{symbol}-aggTrades-{day.isoformat()}.zip"
    return f"{BASE}/{symbol}/{filename}"


def parse_checksum(text: str) -> str:
    token = text.strip().split()[0].lower()
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("invalid SHA-256 checksum payload")
    return token


def verify_checksum(payload: bytes, expected: str) -> None:
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError(f"checksum mismatch: expected {expected}, got {actual}")


def _bool(value: str) -> bool:
    value = value.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"invalid boolean: {value}")


def parse_archive(payload: bytes) -> list[Trade]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != 1 or not names[0].endswith(".csv"):
            raise ValueError("archive must contain exactly one CSV file")
        text = io.TextIOWrapper(archive.open(names[0]), encoding="utf-8", newline="")
        rows = csv.reader(text)
        trades: list[Trade] = []
        previous_key: tuple[int, int] | None = None
        seen: dict[int, tuple[float, float, int, bool]] = {}
        for line_no, row in enumerate(rows, 1):
            if line_no == 1 and row and not row[0].strip().lstrip("-").isdigit():
                continue
            if len(row) < 7:
                raise ValueError(f"line {line_no}: expected at least 7 columns")
            trade = Trade(int(row[0]), float(row[1]), float(row[2]), int(row[5]), _bool(row[6]))
            if trade.price <= 0 or trade.quantity <= 0 or trade.timestamp_ms <= 0:
                raise ValueError(f"line {line_no}: non-positive market field")
            signature = (trade.price, trade.quantity, trade.timestamp_ms, trade.buyer_is_maker)
            prior = seen.get(trade.agg_id)
            if prior is not None:
                if prior != signature:
                    raise ValueError(f"line {line_no}: conflicting duplicate aggregate trade ID")
                continue
            key = (trade.timestamp_ms, trade.agg_id)
            if previous_key is not None and key < previous_key:
                raise ValueError(f"line {line_no}: decreasing timestamp/ID order")
            previous_key = key
            seen[trade.agg_id] = signature
            trades.append(trade)
    if not trades:
        raise ValueError("archive contains no trades")
    return trades


def summarize(trades: Iterable[Trade], bucket_ms: int = 5_000) -> dict:
    items = list(trades)
    buckets: dict[int, dict[str, float | int]] = {}
    for trade in items:
        start = trade.timestamp_ms // bucket_ms * bucket_ms
        bucket = buckets.setdefault(start, {"trades": 0, "total_notional": 0.0, "signed_notional": 0.0})
        bucket["trades"] = int(bucket["trades"]) + 1
        notional = trade.price * trade.quantity
        bucket["total_notional"] = float(bucket["total_notional"]) + notional
        bucket["signed_notional"] = float(bucket["signed_notional"]) + trade.signed_notional
    starts = sorted(buckets)
    gaps = sum(1 for a, b in zip(starts, starts[1:]) if b - a > bucket_ms)
    return {
        "trades": len(items),
        "unique_buckets": len(starts),
        "first_timestamp_ms": items[0].timestamp_ms,
        "last_timestamp_ms": items[-1].timestamp_ms,
        "empty_bucket_gaps": gaps,
        "total_quote_notional": sum(float(v["total_notional"]) for v in buckets.values()),
        "max_abs_signed_quote_notional_5s": max(abs(float(v["signed_notional"])) for v in buckets.values()),
    }


def download(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "chatgpt-trading-bot-research/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def probe(symbol: str, days: list[date]) -> dict:
    results = []
    for day in days:
        url = archive_url(symbol, day)
        payload = download(url)
        checksum = parse_checksum(download(url + ".CHECKSUM").decode("utf-8"))
        verify_checksum(payload, checksum)
        summary = summarize(parse_archive(payload))
        results.append({"date": day.isoformat(), "url": url, "sha256": checksum, **summary})
    return {"schema_version": SCHEMA_VERSION, "symbol": symbol, "days": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--end-date", required=True, help="last complete UTC day, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--out", default="reports/taker_flow_feasibility.json")
    args = parser.parse_args()
    if args.days < 1 or args.days > 42:
        raise SystemExit("--days must be between 1 and 42")
    end = date.fromisoformat(args.end_date)
    dates = [end - timedelta(days=offset) for offset in range(args.days - 1, -1, -1)]
    report = probe(args.symbol.upper(), dates)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
