import unittest

from crossvenue_settlements import enrich_events, nearest


def event(status="complete"):
    return {"event_id": "BTC:1000:2000", "coin": "BTC", "status": status,
            "hyperliquid_funding_time_ms": 1000, "okx_funding_time_ms": 2000}


class SettlementTest(unittest.TestCase):
    def test_nearest_requires_exact_boundary_tolerance(self):
        rows = [{"time": 900, "fundingRate": "0.001"},
                {"time": 3000, "fundingRate": "0.9"}]
        self.assertEqual({"time_ms": 900, "rate": .001},
                         nearest(rows, 1000, "time", ("fundingRate",), 150))
        self.assertIsNone(nearest(rows, 1000, "time", ("fundingRate",), 50))

    def test_complete_event_gets_both_realized_rates(self):
        rows, summary = enrich_events(
            [event()],
            lambda coin, boundary: {"time_ms": boundary, "rate": .0002},
            lambda inst, boundary: {"time_ms": boundary, "rate": -.0001})
        self.assertEqual("complete", rows[0]["settlement_status"])
        self.assertAlmostEqual(.0003,
                               rows[0]["realized_funding"]["difference_hl_minus_okx"])
        self.assertEqual(1, summary["settled"])

    def test_missing_venue_is_pending_not_forward_filled(self):
        rows, summary = enrich_events(
            [event()], lambda *_: None,
            lambda *args: {"time_ms": 2000, "rate": 0})
        self.assertEqual("pending", rows[0]["settlement_status"])
        self.assertIsNone(rows[0]["realized_funding"])
        self.assertEqual(1, summary["pending"])

    def test_incomplete_event_does_not_call_apis(self):
        def fail(*_):
            raise AssertionError("API called")
        rows, summary = enrich_events([event("pending")], fail, fail)
        self.assertEqual("not_eligible", rows[0]["settlement_status"])
        self.assertEqual(1, summary["not_eligible"])


if __name__ == "__main__":
    unittest.main()
