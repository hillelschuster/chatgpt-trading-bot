import unittest

from crossvenue_pnl import fixed_cost_pct, score_event, summarize


def event(long_venue="hyperliquid"):
    return {
        "event_id": "BTC:1:2", "coin": "BTC", "status": "complete",
        "direction": {"long_venue": long_venue,
                      "short_venue": "okx_swap" if long_venue == "hyperliquid" else "hyperliquid"},
        "entry": {"long_entry_price": 100, "short_entry_price": 100, "coordinated": True},
        "exit": {"long_exit_price": 101, "short_exit_price": 99, "coordinated": True},
        "settlement_status": "complete",
        "realized_funding": {
            "hyperliquid": {"time_ms": 1, "rate": 0.0001},
            "okx_swap": {"time_ms": 2, "rate": 0.0003},
        },
    }


class PnlTest(unittest.TestCase):
    def test_frozen_costs_are_total_capital_costs(self):
        self.assertAlmostEqual(fixed_cost_pct(False), 0.155)
        self.assertAlmostEqual(fixed_cost_pct(True), 0.20)

    def test_long_hyperliquid_two_leg_price_and_funding(self):
        row = score_event(event())
        self.assertEqual(row["pnl_status"], "complete")
        self.assertAlmostEqual(row["price_return_pct"], 1.0)
        self.assertAlmostEqual(row["funding_return_pct"], 0.01)
        self.assertAlmostEqual(row["base_net_return_pct"], 0.855)

    def test_long_okx_reverses_funding_cash_flow(self):
        row = score_event(event("okx_swap"))
        self.assertAlmostEqual(row["funding_return_pct"], -0.01)
        self.assertAlmostEqual(row["base_net_return_pct"], 0.835)

    def test_pending_and_invalid_events_are_not_scored(self):
        pending = event(); pending["settlement_status"] = "pending"
        self.assertEqual(score_event(pending)["pnl_status"], "pending")
        invalid = event(); invalid["entry"]["coordinated"] = False
        self.assertEqual(score_event(invalid)["pnl_status"], "invalid")

    def test_failed_attempt_reserve_and_no_profit_claim(self):
        failed = {"event_id": "ETH:1:2", "coin": "ETH", "status": "rejected",
                  "reason": "entry_books_not_coordinated"}
        rows, report = summarize([event(), failed])
        self.assertEqual(rows[1]["pnl_status"], "failed_attempt")
        self.assertAlmostEqual(rows[1]["base_net_return_pct"], -0.05)
        self.assertEqual(report["inference_status"], "COLLECTING")
        self.assertFalse(report["profitability_claim_permitted"])
        self.assertEqual(report["complete_settled_events"], 1)


if __name__ == "__main__":
    unittest.main()
