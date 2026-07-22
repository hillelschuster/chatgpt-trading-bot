import json
import tempfile
import unittest
from pathlib import Path

from bootstrap_history import HOUR, candles, liquid_universe, paged_funding, panel, quality, write_jsonl


class HistoryTest(unittest.TestCase):
    def test_universe_ranks_liquid_active_assets(self):
        def fetch(_):
            return (
                {"universe": [{"name": "A"}, {"name": "B"}, {"name": "DEAD", "isDelisted": True}]},
                [{"dayNtlVlm": "20", "openInterest": "3", "markPx": "2"},
                 {"dayNtlVlm": "50", "openInterest": "1", "markPx": "4"},
                 {"dayNtlVlm": "100", "openInterest": "9", "markPx": "1"}],
            )

        got = liquid_universe(2, 10, fetch)
        self.assertEqual(["B", "A"], [x["coin"] for x in got])
        self.assertEqual(6, got[1]["open_interest_usd"])

    def test_funding_paginates_without_duplicates(self):
        calls = []

        def fetch(payload):
            calls.append(payload["startTime"])
            return ([{"time": i, "fundingRate": "0.0001"} for i in range(500)]
                    if len(calls) == 1 else [{"time": 500, "fundingRate": "-0.0002"}])

        rows = paged_funding("BTC", 0, 1000, fetch)
        self.assertEqual(501, len(rows))
        self.assertEqual([0, 500], calls)

    def test_candles_use_observable_open_and_chunk(self):
        calls = []

        def fetch(payload):
            req = payload["req"]
            calls.append((req["startTime"], req["endTime"]))
            return [{"t": req["startTime"], "o": "99", "c": "101"}]

        rows = candles("BTC", 0, 5_001 * HOUR, fetch)
        self.assertEqual(99, rows[0])
        self.assertEqual(2, len(rows))
        self.assertEqual((0, 4_999 * HOUR), calls[0])

    def test_panel_filters_sparse_hours_and_reports_quality(self):
        def fetch(payload):
            coin = payload.get("coin") or payload["req"]["coin"]
            if payload["type"] == "fundingHistory":
                return [] if coin == "C" else [{"time": HOUR + 123, "fundingRate": "0.0002"}]
            return [{"t": HOUR, "o": "100.5", "c": "101.5"}]

        records = panel(["A", "B", "C"], 0, 2 * HOUR, fetch, min_assets=2)
        self.assertEqual(100.5, records[0]["assets"][0]["mark"])
        self.assertEqual(66.66666666666667, quality(records, ["A", "B", "C"])["coverage_pct"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            self.assertEqual(1, write_jsonl(path, records))
            self.assertEqual(records[0], json.loads(path.read_text().strip()))


if __name__ == "__main__":
    unittest.main()
