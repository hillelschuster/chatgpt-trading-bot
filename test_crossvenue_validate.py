import unittest
from crossvenue_validate import finite_capital, moving_block_lcb, validate

FREEZE = {"schema": "crossvenue-experiment-freeze-v2", "frozen_at_ms": 1,
          "evidence_cutoff_ms": 0, "sha256": "freeze-a"}


def row(i, value=.4, stress=.2, coin="BTC", status="complete", digest="freeze-a"):
    return {"event_id": f"e{i}", "boundary_ms": i * 3_600_000 + 1, "coin": coin,
            "pnl_status": status, "base_net_return_pct": value,
            "stress_net_return_pct": stress,
            "experiment_freeze": {"sha256": digest}}


class CrossVenueValidateTest(unittest.TestCase):
    def test_collecting_until_fixed_holdout_is_complete(self):
        report, base, stress = validate([row(i) for i in range(199)], FREEZE)
        self.assertEqual("COLLECTING", report["verdict"])
        self.assertEqual(140, report["development_complete_events"])
        self.assertEqual(59, report["holdout_complete_events_collected"])
        self.assertEqual(0, report["holdout_attempts_evaluated"])
        self.assertEqual([], base); self.assertEqual([], stress)

    def test_positive_diversified_fixed_holdout_passes(self):
        rows = [row(i, coin="BTC" if i % 2 else "ETH") for i in range(200)]
        report, base, stress = validate(rows, FREEZE)
        self.assertEqual("PASS", report["verdict"])
        self.assertTrue(all(report["gates"].values()))
        self.assertEqual(60, len(base)); self.assertEqual(len(base), len(stress))

    def test_manifest_mismatch_invalidates_whole_study(self):
        rows = [row(i, coin="BTC" if i % 2 else "ETH") for i in range(200)]
        rows[-1] = row(199, coin="BTC", digest="other-freeze")
        report, base, stress = validate(rows, FREEZE)
        self.assertEqual("INVALID", report["verdict"])
        self.assertEqual(1, report["manifest_mismatched_attempts"])
        self.assertFalse(report["gates"]["manifest_binding_valid"])
        self.assertEqual([], base); self.assertEqual([], stress)

    def test_failures_do_not_move_partition_boundary(self):
        rows = [row(i) for i in range(221)]
        rows[20] = row(20, value=-.05, stress=-.05, status="failed_attempt")
        report, _, _ = validate(rows, FREEZE)
        self.assertEqual(141, report["development_attempts"])
        self.assertEqual(80, report["holdout_attempts_collected"])

    def test_concentrated_edge_rejected(self):
        report, _, _ = validate([row(i, coin="BTC") for i in range(200)], FREEZE)
        self.assertEqual("REJECT", report["verdict"])
        self.assertFalse(report["gates"]["positive_pnl_concentration_at_most_50pct"])

    def test_failures_are_charged_and_delay_readiness(self):
        rows = [row(i, coin="BTC" if i % 2 else "ETH") for i in range(200)]
        for i in range(160, 180):
            rows[i] = row(i, value=-.05, stress=-.05, coin="ETH", status="failed_attempt")
        report, _, _ = validate(rows, FREEZE)
        self.assertEqual("COLLECTING", report["verdict"])
        self.assertEqual(40, report["holdout_complete_events_collected"])

    def test_bootstrap_is_deterministic_and_capital_compounds(self):
        values = [.1, .2, -.1, .3] * 20
        self.assertEqual(moving_block_lcb(values), moving_block_lcb(values))
        result = finite_capital([row(0, value=10), row(1, value=-10)], "base_net_return_pct")
        self.assertAlmostEqual(9999.0, result["ending_equity"])


if __name__ == "__main__": unittest.main()
