import unittest
from xsection import HOUR, breadth, trades, study


def panel(hours, prices):
    return [{"captured_at_ms": i * HOUR,
             "assets": [{"coin": coin, "mark": values[i]} for coin, values in prices.items()]}
            for i in range(hours)]


class XSectionTest(unittest.TestCase):
    def test_requires_real_cross_section_and_records_breadth(self):
        rows = panel(3, {"A": [100, 110, 121], "B": [100, 100, 100], "C": [100, 90, 81]})
        self.assertEqual([], trades(rows, 1, 1, "momentum", 10, min_assets=4))
        self.assertEqual(3, breadth(rows)["unique_assets"])

    def test_momentum_ranks_extremes_and_charges_cost(self):
        prices = {chr(65+i): [100, 100 + i, 100 + 2*i] for i in range(6)}
        got = trades(panel(3, prices), 1, 1, "momentum", 10, min_assets=6)
        self.assertEqual(2, len(got)); self.assertTrue(all("cross_section_size" in x for x in got))

    def test_reversal_flips_sides(self):
        prices = {"A": [100, 110, 100], "B": [100, 100, 100], "C": [100, 90, 100],
                  "D": [100, 101, 100], "E": [100, 99, 100], "F": [100, 100.5, 100]}
        got = trades(panel(3, prices), 1, 1, "reversal", 0, min_assets=6)
        self.assertEqual({("A", "SHORT"), ("C", "LONG")}, {(x["coin"], x["side"]) for x in got})

    def test_study_selects_without_future_leakage(self):
        prices = {chr(65+j): [100 * ((1 + (j-2.5)/1000) ** i) for i in range(90)] for j in range(6)}
        report, rows, ledger = study(panel(90, prices), lookbacks=(1,), horizons=(1,),
                                     modes=("momentum", "reversal"), costs=(0,),
                                     min_trades=20, min_assets=6)
        self.assertEqual("momentum", report["selected"]["mode"])
        self.assertEqual("PROMISING", report["verdict"])
        self.assertEqual(6, report["breadth"]["unique_assets"])
        self.assertEqual(len(rows), len(ledger))


if __name__ == "__main__":
    unittest.main()
