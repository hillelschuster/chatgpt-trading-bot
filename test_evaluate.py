import json, tempfile, unittest
from pathlib import Path
from evaluate import load, observations, summarize
from research import split, study

HOUR = 3_600_000


class EvaluateTest(unittest.TestCase):
    def fixture(self):
        return [
            {"captured_at_ms": 0, "assets": [
                {"coin": "BTC", "mark": 100, "funding_1h_pct": .02},
                {"coin": "ETH", "mark": 100, "funding_1h_pct": -.02}]},
            {"captured_at_ms": HOUR, "assets": [
                {"coin": "BTC", "mark": 99, "funding_1h_pct": .01},
                {"coin": "ETH", "mark": 101, "funding_1h_pct": -.01}]},
            {"captured_at_ms": 4 * HOUR, "assets": [
                {"coin": "BTC", "mark": 96, "funding_1h_pct": 0},
                {"coin": "ETH", "mark": 104, "funding_1h_pct": 0}]},
        ]

    def test_funding_is_earned_only_after_entry(self):
        rows = observations(self.fixture(), horizon_hours=1, min_funding_bps=1,
                            roundtrip_bps=9)
        self.assertEqual([r["side"] for r in rows], ["SHORT", "LONG"])
        self.assertAlmostEqual(rows[0]["funding_return_pct"], .01)
        self.assertAlmostEqual(rows[0]["net_return_pct"], .92)
        self.assertEqual(summarize(rows)["win_rate_pct"], 100)

    def test_horizon_requires_nearby_snapshot(self):
        self.assertEqual(observations(self.fixture(), horizon_hours=4,
                                      tolerance_minutes=5)[0]["coin"], "BTC")
        self.assertEqual(len(observations(self.fixture()[:2], horizon_hours=4)), 0)

    def test_load_sorts_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in reversed(self.fixture())))
            self.assertEqual(load(p)[0]["captured_at_ms"], 0)


class ResearchTest(unittest.TestCase):
    def records(self, n=100):
        return [{"captured_at_ms": i * HOUR, "assets": [{
            "coin": "BTC", "mark": 200 - i, "funding_1h_pct": .02}]}
                for i in range(n)]

    def test_split_is_chronological(self):
        train, test, cut = split(self.records(10), .7)
        self.assertTrue(max(r["captured_at_ms"] for r in train) <= cut)
        self.assertTrue(min(r["captured_at_ms"] for r in test) > cut)

    def test_study_exports_selected_oos_trades_and_portfolio(self):
        result, trades = study(self.records(), horizons=(1,), thresholds=(1,),
                               costs=(3,), min_trades=10, max_positions=2)
        self.assertEqual(result["selected"]["horizon_hours"], 1)
        self.assertEqual(result["verdict"], "PROMISING")
        self.assertEqual(result["out_of_sample"]["trades"], len(trades))
        self.assertEqual(result["portfolio"]["accepted_trades"], len(trades))
        self.assertGreater(result["portfolio"]["return_pct"], 0)
        self.assertNotIn("ledger", result["portfolio"])


if __name__ == "__main__":
    unittest.main()
