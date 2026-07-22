import unittest
from scout import rank


class RankTest(unittest.TestCase):
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
        self.assertAlmostEqual(rows[0]["funding_apr_pct"], -175.2)


if __name__ == "__main__":
    unittest.main()
