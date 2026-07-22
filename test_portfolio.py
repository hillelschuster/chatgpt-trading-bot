import json, tempfile, unittest
from pathlib import Path
from portfolio import load_trades, simulate

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
        self.assertEqual(result["max_concurrent_positions"], 2)
        self.assertEqual(result["max_gross_notional"], 10_000)

    def test_pnl_is_realized_at_exit_not_entry(self):
        rows = [
            {"coin": "BTC", "time": 0, "exit_time": 2 * HOUR, "net_return_pct": -10},
            {"coin": "ETH", "time": HOUR, "exit_time": 3 * HOUR, "net_return_pct": 10},
        ]
        result = simulate(rows, capital=10_000, max_positions=2,
                          risk_fraction=1, max_trade_notional=10_000)
        self.assertEqual([x["notional"] for x in result["ledger"]], [5_000, 5_000])
        self.assertEqual(result["ledger"][0]["equity_before_exit"], 10_000)
        self.assertEqual(result["ledger"][1]["equity_before_exit"], 9_500)
        self.assertEqual(result["ending_equity"], 10_000)
        self.assertAlmostEqual(result["max_drawdown_pct"], -5)

    def test_notional_cap_and_utilization(self):
        result = simulate(self.rows()[:1] + [self.rows()[2]], capital=10_000,
                          max_positions=3, max_trade_notional=1_000)
        self.assertEqual([x["notional"] for x in result["ledger"]], [1_000, 1_000])
        self.assertAlmostEqual(result["ending_equity"], 10_010)
        self.assertEqual(result["max_capital_utilization_pct"], 20)
        self.assertLess(result["max_drawdown_pct"], 0)

    def test_load_orders_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "trades.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in reversed(self.rows())))
            self.assertEqual(load_trades(p)[0]["time"], 0)

    def test_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            simulate([], max_positions=0)
        with self.assertRaises(ValueError):
            simulate([], risk_fraction=1.1)


if __name__ == "__main__":
    unittest.main()
