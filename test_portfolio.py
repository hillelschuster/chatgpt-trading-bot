import unittest

from portfolio import simulate

HOUR = 3_600_000


class PortfolioTest(unittest.TestCase):
    def rows(self):
        return [
            {"coin": "BTC", "time": 0, "exit_time": 4 * HOUR, "net_return_pct": 2},
            {"coin": "BTC", "time": HOUR, "exit_time": 2 * HOUR, "net_return_pct": 9},
            {"coin": "ETH", "time": HOUR, "exit_time": 3 * HOUR, "net_return_pct": -1},
            {"coin": "SOL", "time": 2 * HOUR, "exit_time": 5 * HOUR, "net_return_pct": 1},
        ]

    def test_overlap_and_coin_limits(self):
        result = simulate(self.rows(), capital=10_000, max_positions=2,
                          risk_fraction=1, max_trade_notional=10_000)
        self.assertEqual(result["accepted_trades"], 2)
        self.assertEqual(result["rejected"], {"slots": 1, "coin": 1, "capacity": 0})
        self.assertAlmostEqual(result["ending_equity"], 10_050)

    def test_pnl_is_realized_at_exit(self):
        rows = [
            {"coin": "BTC", "time": 0, "exit_time": 2 * HOUR, "net_return_pct": -10},
            {"coin": "ETH", "time": HOUR, "exit_time": 3 * HOUR, "net_return_pct": 10},
        ]
        result = simulate(rows, capital=10_000, max_positions=2,
                          risk_fraction=1, max_trade_notional=10_000)
        self.assertEqual(result["ending_equity"], 10_000)
        self.assertAlmostEqual(result["max_realized_drawdown_pct"], -5)


if __name__ == "__main__":
    unittest.main()
