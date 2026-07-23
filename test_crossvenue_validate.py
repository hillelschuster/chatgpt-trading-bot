import unittest
from crossvenue_validate import DAY, finite_capital, moving_block_lcb, period_returns, validate

FREEZE = {"schema": "crossvenue-experiment-freeze-v2", "frozen_at_ms": 1,
          "evidence_cutoff_ms": 0, "sha256": "freeze-a"}
VALID_CHAIN = {"valid": True, "errors": [], "previous_artifact_present": True,
               "freeze_manifest_upgraded": False}


def row(i, value=.4, stress=.2, coin="BTC", status="complete", digest="freeze-a", boundary=None, spacing=DAY):
    return {"event_id": f"e{i}-{coin}", "boundary_ms": (i if boundary is None else boundary) * spacing + 1,
            "coin": coin, "pnl_status": status, "base_net_return_pct": value,
            "stress_net_return_pct": stress, "experiment_freeze": {"sha256": digest}}


class CrossVenueValidateTest(unittest.TestCase):
    def test_collecting_until_fixed_holdout_is_complete(self):
        report, base, stress = validate([row(i) for i in range(199)], FREEZE, VALID_CHAIN)
        self.assertEqual("COLLECTING", report["verdict"])
        self.assertEqual(140, report["development_complete_periods"])
        self.assertEqual(59, report["holdout_complete_periods_collected"])
        self.assertEqual(0, report["holdout_attempts_evaluated"])
        self.assertEqual([], base); self.assertEqual([], stress)

    def test_positive_diversified_fixed_holdout_passes(self):
        rows = []
        for i in range(200):
            rows.extend([row(2 * i, coin="BTC", boundary=i), row(2 * i + 1, coin="ETH", boundary=i)])
        report, base, stress = validate(rows, FREEZE, VALID_CHAIN)
        self.assertEqual("PASS", report["verdict"])
        self.assertTrue(all(report["gates"].values()))
        self.assertEqual(60, report["holdout_periods_evaluated"])
        self.assertEqual(120, len(base)); self.assertEqual(len(base), len(stress))

    def test_simultaneous_attempts_do_not_halve_minimum_sample(self):
        rows = []
        for i in range(100):
            rows.extend([row(2 * i, coin="BTC", boundary=i), row(2 * i + 1, coin="ETH", boundary=i)])
        report, _, _ = validate(rows, FREEZE, VALID_CHAIN)
        self.assertEqual("COLLECTING", report["verdict"])
        self.assertEqual(200, report["complete_attempts"])
        self.assertEqual(100, report["complete_periods"])
        self.assertEqual(100, report["development_complete_periods"])

    def test_manifest_mismatch_invalidates_whole_study(self):
        rows = [row(i, coin="BTC" if i % 2 else "ETH") for i in range(200)]
        rows[-1] = row(199, coin="BTC", digest="other-freeze")
        report, base, stress = validate(rows, FREEZE, VALID_CHAIN)
        self.assertEqual("INVALID", report["verdict"])
        self.assertEqual(1, report["manifest_mismatched_attempts"])
        self.assertFalse(report["gates"]["manifest_binding_valid"])
        self.assertEqual([], base); self.assertEqual([], stress)

    def test_invalid_or_missing_chain_blocks_promotion(self):
        rows = []
        for i in range(200):
            rows.extend([row(2 * i, coin="BTC", boundary=i), row(2 * i + 1, coin="ETH", boundary=i)])
        bad = {"valid": False, "errors": ["snapshot_mutated:1:BTC"]}
        report, base, stress = validate(rows, FREEZE, bad)
        self.assertEqual("INVALID", report["verdict"])
        self.assertFalse(report["profitability_claim_permitted"])
        self.assertFalse(report["gates"]["append_only_chain_valid"])
        self.assertEqual(["snapshot_mutated:1:BTC"], report["artifact_chain"]["errors"])
        self.assertEqual([], base); self.assertEqual([], stress)
        missing, _, _ = validate(rows, FREEZE, None)
        self.assertEqual("INVALID", missing["verdict"])
        self.assertEqual(["chain_report_missing"], missing["artifact_chain"]["errors"])

    def test_failures_do_not_move_partition_boundary(self):
        rows = [row(i) for i in range(221)]
        rows[20] = row(20, value=-.05, stress=-.05, status="failed_attempt")
        report, _, _ = validate(rows, FREEZE, VALID_CHAIN)
        self.assertEqual(141, report["development_attempts"])
        self.assertEqual(80, report["holdout_attempts_collected"])
        self.assertEqual(140, report["development_complete_periods"])

    def test_concentrated_edge_rejected(self):
        report, _, _ = validate([row(i, coin="BTC") for i in range(200)], FREEZE, VALID_CHAIN)
        self.assertEqual("REJECT", report["verdict"])
        self.assertFalse(report["gates"]["positive_pnl_concentration_at_most_70pct"])

    def test_failures_are_charged_and_delay_readiness(self):
        rows = [row(i, coin="BTC" if i % 2 else "ETH") for i in range(200)]
        for i in range(160, 180):
            rows[i] = row(i, value=-.05, stress=-.05, coin="ETH", status="failed_attempt")
        report, _, _ = validate(rows, FREEZE, VALID_CHAIN)
        self.assertEqual("COLLECTING", report["verdict"])
        self.assertEqual(40, report["holdout_complete_periods_collected"])

    def test_bootstrap_is_deterministic_and_capital_compounds(self):
        values = [.1, .2, -.1, .3] * 20
        self.assertEqual(moving_block_lcb(values), moving_block_lcb(values))
        result = finite_capital([row(0, value=10), row(1, value=-10)], "base_net_return_pct")
        self.assertAlmostEqual(9999.0, result["ending_equity"])

    def test_same_boundary_is_one_order_independent_portfolio_period(self):
        rows = [row(0, value=10, coin="BTC", boundary=0), row(1, value=-10, coin="ETH", boundary=0)]
        reverse = list(reversed(rows))
        self.assertEqual([0.0], period_returns(rows, "base_net_return_pct"))
        first = finite_capital(rows, "base_net_return_pct")
        second = finite_capital(reverse, "base_net_return_pct")
        self.assertEqual(1, first["periods"])
        self.assertAlmostEqual(10_000, first["ending_equity"])
        self.assertEqual(first["ending_equity"], second["ending_equity"])
        self.assertEqual(first["ledger"][0]["notional"], first["ledger"][1]["notional"])

    def test_minimum_sample_cannot_bypass_eight_week_collection(self):
        rows = [row(i, coin="BTC" if i % 2 else "ETH", spacing=3_600_000) for i in range(200)]
        report, base, stress = validate(rows, FREEZE, VALID_CHAIN)
        self.assertEqual("COLLECTING", report["verdict"])
        self.assertTrue(report["gates"]["minimum_complete_periods"])
        self.assertFalse(report["gates"]["minimum_collection_span_56_days"])
        self.assertLess(report["collection_span_days"], 9)
        self.assertEqual([], base); self.assertEqual([], stress)

    def test_five_percent_failure_gate_is_enforced(self):
        rows = []
        for i in range(200):
            rows.extend([row(2 * i, coin="BTC", boundary=i), row(2 * i + 1, coin="ETH", boundary=i)])
        for i in range(7):
            index = 2 * (140 + i)
            rows[index] = row(index, value=-.05, stress=-.05, coin="BTC", status="failed_attempt", boundary=140 + i)
        report, _, _ = validate(rows, FREEZE, VALID_CHAIN)
        self.assertEqual("REJECT", report["verdict"])
        self.assertGreater(report["holdout_failed_attempt_rate"], .05)
        self.assertFalse(report["gates"]["failed_attempt_rate_below_5pct"])

    def test_rejects_impossible_simultaneous_capital_allocation(self):
        rows = [row(i, boundary=0) for i in range(11)]
        with self.assertRaises(ValueError):
            finite_capital(rows, "base_net_return_pct")


if __name__ == "__main__": unittest.main()
