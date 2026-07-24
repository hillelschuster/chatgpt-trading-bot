import unittest

from crossvenue_snapshot import DEFAULT_CADENCE_MS, SCHEMA_VERSION
from crossvenue_snapshot_health import audit


def snapshot(slot, coin="BTC", captured=None):
    captured = slot + 1_000 if captured is None else captured
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at_ms": captured,
        "cadence_slot_ms": slot,
        "coin": coin,
        "hyperliquid": {
            "bid": 100.0,
            "ask": 101.0,
            "book_time_ms": captured,
            "effective_next_funding_time_ms": captured + 3_600_000,
        },
        "okx_swap": {
            "bid": 100.0,
            "ask": 101.0,
            "book_time_ms": captured,
            "funding_time_ms": captured + 3_600_000,
            "predicted_funding_rate": 0.0001,
        },
    }


class SnapshotHealthTest(unittest.TestCase):
    def test_accepts_valid_recent_btc_eth_payloads(self):
        now = 20 * DEFAULT_CADENCE_MS
        slot = now - DEFAULT_CADENCE_MS
        report = audit([snapshot(slot, "BTC"), snapshot(slot, "ETH")], now_ms=now)
        self.assertTrue(report["healthy"])
        self.assertEqual("HEALTHY", report["status"])
        self.assertEqual(2, report["recent_rows"])
        self.assertFalse(report["blockers"])

    def test_rejects_future_dated_capture(self):
        now = 20 * DEFAULT_CADENCE_MS
        future = now + 120_000
        slot = future // DEFAULT_CADENCE_MS * DEFAULT_CADENCE_MS
        report = audit([snapshot(slot, captured=future)], now_ms=now)
        self.assertFalse(report["healthy"])
        self.assertIn("captured_at_future", report["invalid_examples"][0]["errors"])

    def test_rejects_capture_outside_claimed_slot(self):
        now = 20 * DEFAULT_CADENCE_MS
        slot = now - 2 * DEFAULT_CADENCE_MS
        report = audit([snapshot(slot, captured=slot + DEFAULT_CADENCE_MS)], now_ms=now)
        self.assertFalse(report["healthy"])
        self.assertIn("captured_at_outside_cadence_slot",
                      report["invalid_examples"][0]["errors"])

    def test_rejects_invalid_book_payload(self):
        now = 20 * DEFAULT_CADENCE_MS
        row = snapshot(now - DEFAULT_CADENCE_MS)
        row["okx_swap"]["ask"] = row["okx_swap"]["bid"]
        report = audit([row], now_ms=now)
        self.assertFalse(report["healthy"])
        self.assertIn("okx_swap.book", report["invalid_examples"][0]["errors"])

    def test_rejects_duplicate_recent_key(self):
        now = 20 * DEFAULT_CADENCE_MS
        row = snapshot(now - DEFAULT_CADENCE_MS)
        report = audit([row, dict(row)], now_ms=now)
        self.assertFalse(report["healthy"])
        self.assertEqual(1, report["duplicate_rows"])
        self.assertIn("recent_snapshot_duplicates", report["blockers"])

    def test_rejects_empty_recent_window(self):
        now = 20 * DEFAULT_CADENCE_MS
        old = snapshot(now - 2 * 3_600_000)
        report = audit([old], now_ms=now)
        self.assertFalse(report["healthy"])
        self.assertEqual(["recent_snapshots_missing"], report["blockers"])


if __name__ == "__main__":
    unittest.main()
