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
    def test_windows_are_anchored(self):
        rows = windows(records(40), folds=3, min_train_fraction=.4)
        self.assertEqual(len(rows), 3)

    def test_reports_fixed_cost_and_sensitivity(self):
        result, _, ledger = validate(
            records(), horizons=(1,), thresholds=(1,), selection_cost=12,
            stress_costs=(12, 15), min_trades=5, folds=3,
            min_train_fraction=.4, max_positions=2)
        self.assertEqual(12, result["selection_cost_bps"])
        self.assertEqual(set(result["cost_sensitivity_bps"]), {"12", "15"})
        self.assertEqual(result["portfolio"]["accepted_trades"], len(ledger))

    def test_bad_edge_is_rejected(self):
        result, _, _ = validate(
            records(profitable=False), horizons=(1,), thresholds=(1,),
            selection_cost=12, stress_costs=(12,), min_trades=5,
            folds=3, min_train_fraction=.4)
        self.assertEqual(result["verdict"], "REJECT_OR_REWORK")

    def test_by_coin(self):
        stats = by_coin([{"coin": "BTC", "side": "LONG", "net_return_pct": 1}])
        self.assertEqual(stats["BTC"]["trades"], 1)


if __name__ == "__main__":
    unittest.main()
