import unittest
from xsection import HOUR, trades, study


def panel(hours, prices):
    return [{"captured_at_ms": i * HOUR,
             "assets": [{"coin": coin, "mark": values[i]}
                        for coin, values in prices.items()]}
            for i in range(hours)]


class XSectionTest(unittest.TestCase):
    def test_momentum_ranks_extremes_and_charges_cost(self):
        rows = panel(3, {"A": [100, 110, 121], "B": [100, 100, 100],
                         "C": [100, 90, 81]})
        got = trades(rows, 1, 1, "momentum", 10)
        self.assertEqual({(x["coin"], x["side"]) for x in got},
                         {("A", "LONG"), ("C", "SHORT")})
        self.assertTrue(all(round(x["net_return_pct"], 6) == 9.9 for x in got))

    def test_reversal_flips_sides(self):
        rows = panel(3, {"A": [100, 110, 100], "B": [100, 100, 100],
                         "C": [100, 90, 100]})
        got = trades(rows, 1, 1, "reversal", 0)
        self.assertEqual({(x["coin"], x["side"]) for x in got},
                         {("A", "SHORT"), ("C", "LONG")})
        self.assertTrue(all(x["net_return_pct"] > 9 for x in got))

    def test_study_selects_without_future_leakage(self):
        prices = {"A": [], "B": [], "C": []}
        for i in range(90):
            prices["A"].append(100 * (1.01 ** i))
            prices["B"].append(100)
            prices["C"].append(100 * (.99 ** i))
        report, rows, ledger = study(panel(90, prices), lookbacks=(1,), horizons=(1,),
                                     modes=("momentum", "reversal"), costs=(0,),
                                     min_trades=20)
        self.assertEqual(report["selected"]["mode"], "momentum")
        self.assertEqual(report["verdict"], "PROMISING")
        self.assertEqual(len(rows), len(ledger))


if __name__ == "__main__":
    unittest.main()
