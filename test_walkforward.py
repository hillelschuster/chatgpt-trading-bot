import unittest

from walkforward import by_coin, validate, windows

HOUR = 3_600_000


def records(n=120, profitable=True):
    out = []
    for i in range(n):
        block = i // 6
        funding = -.02 if block % 2 == 0 else .02
        drift = .8 if profitable else -.8
        direction = 1 if funding < 0 else -1
        mark = 100 + direction * drift * i + (i % 3) * .01
        out.append({"captured_at_ms": i * HOUR, "assets": [{
            "coin": "BTC", "mark": mark, "funding_1h_pct": funding}]})
    return out


class WalkForwardTest(unittest.TestCase):
    def test_windows_are_anchored_and_non_overlapping(self):
        rows = windows(records(40), folds=3, min_train_fraction=.4)
        self.assertEqual(len(rows), 3)
        previous_test_end = None
        for train, test, train_cut, test_cut in rows:
            self.assertLessEqual(max(r["captured_at_ms"] for r in train), train_cut)
            self.assertGreater(min(r["captured_at_ms"] for r in test), train_cut)
            self.assertLessEqual(max(r["captured_at_ms"] for r in test), test_cut)
            if previous_test_end is not None:
                self.assertGreater(min(r["captured_at_ms"] for r in test), previous_test_end)
            previous_test_end = test_cut

    def test_validate_reports_stability_costs_and_coin_breakdown(self):
        result, trades, ledger = validate(
            records(), horizons=(1,), thresholds=(1,), selection_cost=3,
            stress_costs=(3, 6), min_trades=5, folds=3,
            min_train_fraction=.4, max_positions=2)
        self.assertEqual(len(result["folds"]), 3)
        self.assertEqual(result["parameter_stability"]["most_common"], (1, 1))
        self.assertEqual(result["parameter_stability"]["folds_selected"], 3)
        self.assertEqual(set(result["cost_sensitivity_bps"]), {"3", "6"})
        self.assertEqual(result["aggregate_oos"]["trades"], len(trades))
        self.assertEqual(result["portfolio"]["accepted_trades"], len(ledger))
        self.assertIn("BTC", result["by_coin"])

    def test_bad_edge_is_rejected(self):
        result, _, _ = validate(
            records(profitable=False), horizons=(1,), thresholds=(1,),
            selection_cost=3, stress_costs=(3, 6), min_trades=5,
            folds=3, min_train_fraction=.4)
        self.assertEqual(result["verdict"], "REJECT_OR_REWORK")

    def test_by_coin_separates_assets(self):
        rows = [{"coin": "BTC", "net_return_pct": 1},
                {"coin": "ETH", "net_return_pct": -1}]
        stats = by_coin(rows)
        self.assertEqual(stats["BTC"]["trades"], 1)
        self.assertEqual(stats["ETH"]["trades"], 1)


if __name__ == "__main__":
    unittest.main()
