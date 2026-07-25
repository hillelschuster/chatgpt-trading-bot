import unittest

from crossvenue_coverage import CADENCE_MS, DAY_MS, coverage, first_slot_after_cutoff
from crossvenue_promote import promote


def snapshot(slot, coin="BTC", hl_boundary=None, okx_boundary=None):
    hl_boundary = slot + 3_600_000 if hl_boundary is None else hl_boundary
    okx_boundary = slot + 3_600_000 if okx_boundary is None else okx_boundary
    return {"captured_at_ms": slot + 1_000, "cadence_slot_ms": slot, "coin": coin,
            "hyperliquid": {"effective_next_funding_time_ms": hl_boundary},
            "okx_swap": {"funding_time_ms": okx_boundary}}


def event(coin, boundary):
    return {"coin": coin, "hyperliquid_funding_time_ms": boundary,
            "okx_funding_time_ms": boundary, "status": "complete"}


class CoverageTest(unittest.TestCase):
    def test_first_required_slot_is_strictly_after_cutoff(self):
        self.assertEqual(CADENCE_MS, first_slot_after_cutoff(0))
        self.assertEqual(2 * CADENCE_MS, first_slot_after_cutoff(CADENCE_MS))
        self.assertEqual(2 * CADENCE_MS, first_slot_after_cutoff(CADENCE_MS + 1))

    def test_complete_56_day_series_passes(self):
        rows = []
        cutoff = -1
        first = first_slot_after_cutoff(cutoff)
        slots = 56 * 24 * 12 + 1
        boundary = 60 * DAY_MS
        for i in range(slots):
            slot = first + i * CADENCE_MS
            rows.extend([snapshot(slot, "BTC", boundary, boundary),
                         snapshot(slot, "ETH", boundary, boundary)])
        report = coverage(rows, [event("BTC", boundary), event("ETH", boundary)],
                          {"evidence_cutoff_ms": cutoff})
        self.assertEqual("PASS", report["status"])
        self.assertEqual(1.0, report["slot_coverage"])
        self.assertEqual(1.0, report["event_accounting"])

    def test_missing_slots_fail_after_span_matures(self):
        rows = []
        cutoff = -1
        first = first_slot_after_cutoff(cutoff)
        slots = 56 * 24 * 12 + 1
        for i in range(slots):
            if i not in (0, slots - 1) and i % 10 == 0:
                continue
            slot = first + i * CADENCE_MS
            rows.extend([snapshot(slot, "BTC"), snapshot(slot, "ETH")])
        report = coverage(rows, [], {"evidence_cutoff_ms": cutoff})
        self.assertEqual("INVALID", report["status"])
        self.assertLess(report["slot_coverage"], 0.95)

    def test_leading_post_freeze_outage_is_counted(self):
        cutoff = 10 * CADENCE_MS + 1
        required = first_slot_after_cutoff(cutoff)
        delayed = required + 1_000 * CADENCE_MS
        last = required + 56 * DAY_MS
        rows = []
        for slot in range(delayed, last + 1, CADENCE_MS):
            rows.extend([snapshot(slot, "BTC"), snapshot(slot, "ETH")])
        report = coverage(rows, [], {"evidence_cutoff_ms": cutoff})
        self.assertEqual("INVALID", report["status"])
        self.assertEqual(1_000, report["leading_missing_slots"])
        self.assertEqual(required, report["required_first_slot_ms"])
        self.assertLess(report["slot_coverage"], 0.95)

    def test_duplicate_coin_slot_is_invalid(self):
        cutoff = -1
        first = first_slot_after_cutoff(cutoff)
        rows = [snapshot(first), snapshot(first), snapshot(first + 56 * DAY_MS)]
        report = coverage(rows, [], {"evidence_cutoff_ms": cutoff}, coins=("BTC",))
        self.assertEqual("INVALID", report["status"])
        self.assertEqual(1, report["duplicate_rows"])

    def test_promotion_requires_validation_and_coverage(self):
        validation = {"verdict": "PASS", "artifact_chain": {"valid": True}}
        collecting = promote(validation, {"status": "COLLECTING"})
        self.assertEqual("COLLECTING", collecting["verdict"])
        self.assertFalse(collecting["profitability_claim_permitted"])
        passed = promote(validation, {"status": "PASS"})
        self.assertEqual("PASS", passed["verdict"])


if __name__ == "__main__": unittest.main()
