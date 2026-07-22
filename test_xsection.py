import unittest

from xsection import HOUR, breadth, trades, study


def make_panel(hours, prices, funding=None):
    funding = funding or {}
    return [{
        "captured_at_ms": i * HOUR,
        "assets": [{
            "coin": coin,
            "mark": values[i],
            "funding_1h_pct": funding.get(coin, [0] * hours)[i],
        } for coin, values in prices.items() if values[i] is not None],
    } for i in range(hours)]


class XSectionTest(unittest.TestCase):
    def test_requires_breadth(self):
        rows = make_panel(3, {"A": [100, 110, 121], "B": [100, 100, 100], "C": [100, 90, 81]})
        self.assertEqual([], trades(rows, 1, 1, "momentum", 10, min_assets=4))
        self.assertEqual(3, breadth(rows)["unique_assets"])

    def test_momentum_charges_cost_and_held_funding(self):
        prices = {chr(65 + i): [100, 100 + i, 100 + 2 * i, 100 + 3 * i] for i in range(6)}
        funding = {coin: [0, .01, .01, 0] for coin in prices}
        got = trades(make_panel(4, prices, funding), 1, 2, "momentum", 10, min_assets=6)
        self.assertEqual(2, len(got))
        short = next(x for x in got if x["side"] == "SHORT")
        self.assertAlmostEqual(short["funding_return_pct"], .01)

    def test_future_availability_does_not_change_ranking(self):
        prices = {
            "A": [100, 120, None], "B": [100, 110, 111], "C": [100, 105, 106],
            "D": [100, 100, 100], "E": [100, 95, 94], "F": [100, 90, 89],
        }
        self.assertEqual([], trades(make_panel(3, prices), 1, 1, "momentum", 12, min_assets=6))

    def test_non_overlapping_pairs_and_pair_statistics(self):
        prices = {chr(65 + j): [100 * ((1 + (j - 2.5) / 1000) ** i) for i in range(10)]
                  for j in range(6)}
        got = trades(make_panel(10, prices), 1, 2, "momentum", 12, min_assets=6)
        self.assertEqual(8, len(got))
        self.assertEqual(4, len({x["time"] for x in got}))

    def test_study_selects_fixed_cost(self):
        prices = {chr(65 + j): [100 * ((1 + (j - 2.5) / 1000) ** i) for i in range(120)]
                  for j in range(6)}
        report, rows, ledger = study(
            make_panel(120, prices), lookbacks=(1,), horizons=(1,),
            modes=("momentum", "reversal"), selection_cost=12,
            stress_costs=(12,), min_trades=20, min_assets=6)
        self.assertEqual(12, report["selected"]["roundtrip_bps"])
        self.assertEqual("momentum", report["selected"]["mode"])
        self.assertEqual(len(rows), len(ledger))


if __name__ == "__main__":
    unittest.main()
