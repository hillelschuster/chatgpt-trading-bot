import json, tempfile, unittest
from pathlib import Path
from evaluate import load, observations, summarize


class EvaluateTest(unittest.TestCase):
    def fixture(self):
        hour = 3_600_000
        return [
            {"captured_at_ms": 0, "assets": [{"coin": "BTC", "mark": 100, "funding_1h_pct": .02}, {"coin": "ETH", "mark": 100, "funding_1h_pct": -.02}]},
            {"captured_at_ms": hour, "assets": [{"coin": "BTC", "mark": 99, "funding_1h_pct": .01}, {"coin": "ETH", "mark": 101, "funding_1h_pct": -.01}]},
            {"captured_at_ms": 4 * hour, "assets": [{"coin": "BTC", "mark": 96, "funding_1h_pct": 0}, {"coin": "ETH", "mark": 104, "funding_1h_pct": 0}]},
        ]

    def test_cost_aware_fade_and_summary(self):
        rows = observations(self.fixture(), horizon_hours=1, min_funding_bps=1, roundtrip_bps=9)
        self.assertEqual([r["side"] for r in rows], ["SHORT", "LONG"])
        self.assertAlmostEqual(rows[0]["net_return_pct"], .93)
        self.assertEqual(summarize(rows)["win_rate_pct"], 100)

    def test_horizon_requires_nearby_snapshot(self):
        self.assertEqual(observations(self.fixture(), horizon_hours=4, tolerance_minutes=5)[0]["coin"], "BTC")
        self.assertEqual(len(observations(self.fixture()[:2], horizon_hours=4)), 0)

    def test_load_sorts_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in reversed(self.fixture())))
            self.assertEqual(load(p)[0]["captured_at_ms"], 0)


if __name__ == "__main__":
    unittest.main()
