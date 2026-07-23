import unittest

from crossvenue_events import build_events, event_key
from crossvenue_snapshot import SCHEMA_VERSION


def row(t, hl_boundary=3_600_000, okx_boundary=3_600_000, coin="BTC",
        hl_rate=.0001, okx_rate=.0003, skew=1_000):
    return {"schema_version": SCHEMA_VERSION, "captured_at_ms": t,
            "cadence_slot_ms": t // 300_000 * 300_000, "coin": coin,
            "hyperliquid": {"bid": 99, "ask": 101, "book_time_ms": t,
                "predicted_funding_rate": hl_rate,
                "effective_next_funding_time_ms": hl_boundary},
            "okx_swap": {"bid": 199, "ask": 201, "book_time_ms": t + skew,
                "predicted_funding_rate": okx_rate, "funding_time_ms": okx_boundary}}


class CrossVenueEventsTest(unittest.TestCase):
    def test_event_key_uses_both_venue_boundaries(self):
        self.assertEqual(("BTC", 3_600_000, 7_200_000), event_key(row(0, okx_boundary=7_200_000)))

    def test_builds_complete_event_with_delayed_adverse_prices(self):
        rows = [row(2_700_000), row(3_000_000), row(3_300_000),
                row(3_900_000, 7_200_000, 7_200_000)]
        events, summary = build_events(rows)
        self.assertEqual(1, summary["complete"])
        event = events[0]
        self.assertEqual("hyperliquid", event["direction"]["long_venue"])
        self.assertEqual(101, event["entry"]["long_entry_price"])
        self.assertEqual(199, event["entry"]["short_entry_price"])
        self.assertEqual(201, event["exit"]["short_exit_price"])
        self.assertEqual(99, event["exit"]["long_exit_price"])

    def test_uses_latest_signal_with_ten_minute_lead(self):
        rows = [row(2_400_000), row(2_700_000), row(3_000_000), row(3_300_000),
                row(3_900_000, 7_200_000, 7_200_000)]
        events, _ = build_events(rows)
        self.assertEqual(3_000_000, events[0]["signal_time_ms"])

    def test_pending_event_is_preserved_without_future_fill(self):
        events, summary = build_events([row(3_000_000)])
        self.assertEqual("pending", events[0]["status"])
        self.assertEqual("entry_snapshot_missing", events[0]["reason"])
        self.assertEqual(1, summary["pending"])

    def test_rejects_uncoordinated_entry_books(self):
        rows = [row(3_000_000), row(3_300_000, skew=10_000),
                row(3_900_000, 7_200_000, 7_200_000)]
        events, summary = build_events(rows)
        self.assertEqual("rejected", events[0]["status"])
        self.assertEqual(1, summary["rejected"])


if __name__ == "__main__":
    unittest.main()
