import json, tempfile, unittest
from pathlib import Path
from bootstrap_history import HOUR, candles, paged_funding, panel, write_jsonl


class HistoryTest(unittest.TestCase):
    def test_funding_paginates_without_duplicates(self):
        calls = []

        def fetch(payload):
            calls.append(payload["startTime"])
            if len(calls) == 1:
                return [{"time": i, "fundingRate": "0.0001"} for i in range(500)]
            return [{"time": 500, "fundingRate": "-0.0002"}]

        rows = paged_funding("BTC", 0, 1000, fetch)
        self.assertEqual(501, len(rows))
        self.assertEqual([0, 500], calls)

    def test_candles_chunks_at_api_limit(self):
        calls = []

        def fetch(payload):
            req = payload["req"]
            calls.append((req["startTime"], req["endTime"]))
            return [{"t": req["startTime"], "c": "100"}]

        end = 5_001 * HOUR
        rows = candles("BTC", 0, end, fetch)
        self.assertEqual(2, len(rows))
        self.assertEqual((0, 4_999 * HOUR), calls[0])

    def test_panel_joins_funding_to_hourly_close_and_writes_jsonl(self):
        def fetch(payload):
            coin = payload.get("coin") or payload["req"]["coin"]
            if payload["type"] == "fundingHistory":
                return [{"time": HOUR + 123, "fundingRate": "0.0002"}]
            return [{"t": HOUR, "c": "101.5", "s": coin}]

        records = panel(["BTC", "ETH"], 0, 2 * HOUR, fetch)
        self.assertEqual(1, len(records))
        self.assertEqual(["BTC", "ETH"], [a["coin"] for a in records[0]["assets"]])
        self.assertAlmostEqual(.02, records[0]["assets"][0]["funding_1h_pct"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "history.jsonl"
            self.assertEqual(1, write_jsonl(path, records))
            self.assertEqual(records[0], json.loads(path.read_text().strip()))


if __name__ == "__main__":
    unittest.main()
