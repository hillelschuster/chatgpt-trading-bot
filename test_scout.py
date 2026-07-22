import json, tempfile, unittest
from pathlib import Path
from scout import append_snapshot, rank


class ScoutTest(unittest.TestCase):
    def test_filters_and_orders(self):
        data = [
            {"universe": [{"name": "A"}, {"name": "B"}, {"name": "C"}]},
            [
                {"openInterest": "100", "markPx": "20000", "dayNtlVlm": "10000000", "funding": "0.0001"},
                {"openInterest": "200", "markPx": "10000", "dayNtlVlm": "20000000", "funding": "-0.0002"},
                {"openInterest": "1", "markPx": "10", "dayNtlVlm": "10", "funding": "0.1"},
            ],
        ]
        rows = rank(data)
        self.assertEqual([row["coin"] for row in rows], ["B", "A"])
        self.assertEqual(rows[0]["side_paid"], "shorts")
        self.assertEqual(rows[0]["mark"], 10000)
        self.assertAlmostEqual(rows[0]["funding_apr_pct"], -175.2)

    def test_appends_timestamped_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "snapshots.jsonl"
            append_snapshot(path, [{"coin": "BTC", "mark": 100}], 123)
            append_snapshot(path, [{"coin": "ETH", "mark": 10}], 456)
            records = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([record["captured_at_ms"] for record in records], [123, 456])
        self.assertEqual(records[1]["assets"][0]["coin"], "ETH")


if __name__ == "__main__":
    unittest.main()
