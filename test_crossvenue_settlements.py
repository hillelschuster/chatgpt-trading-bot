import unittest

from crossvenue_settlements import enrich_events, nearest


def event(status="complete", event_id="BTC:1000:2000"):
    return {"event_id": event_id, "coin": "BTC", "status": status,
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
            [event()], [],
            lambda coin, boundary: {"time_ms": boundary, "rate": .0002},
            lambda inst, boundary: {"time_ms": boundary, "rate": -.0001}, now_ms=10)
        self.assertEqual("complete", rows[0]["settlement_status"])
        self.assertAlmostEqual(.0003,
                               rows[0]["realized_funding"]["difference_hl_minus_okx"])
        self.assertEqual(1, rows[0]["settlement_attempts"])
        self.assertEqual(1, summary["newly_settled"])

    def test_missing_venue_preserves_partial_observation(self):
        rows, summary = enrich_events(
            [event()], [], lambda *_: {"time_ms": 1000, "rate": .0002},
            lambda *_: None, now_ms=10)
        self.assertEqual("pending", rows[0]["settlement_status"])
        self.assertEqual(.0002, rows[0]["settlement_observations"]["hyperliquid"]["rate"])
        self.assertIsNone(rows[0]["settlement_observations"]["okx_swap"])
        self.assertEqual(1, summary["pending"])

    def test_resume_queries_only_missing_leg(self):
        first, _ = enrich_events(
            [event()], [], lambda *_: {"time_ms": 1000, "rate": .0002},
            lambda *_: None, now_ms=10)
        calls = []
        rows, summary = enrich_events(
            [event()], first,
            lambda *_: (_ for _ in ()).throw(AssertionError("HL refetched")),
            lambda *args: calls.append(args) or {"time_ms": 2000, "rate": -.0001}, now_ms=20)
        self.assertEqual(1, len(calls))
        self.assertEqual("complete", rows[0]["settlement_status"])
        self.assertEqual({"okx_swap": 1}, summary["api_queries"])
        self.assertEqual(2, rows[0]["settlement_attempts"])

    def test_settled_event_is_monotonic_across_api_failure(self):
        prior, _ = enrich_events(
            [event()], [], lambda *_: {"time_ms": 1000, "rate": .0002},
            lambda *_: {"time_ms": 2000, "rate": -.0001}, now_ms=10)
        def fail(*_):
            raise AssertionError("settled event refetched")
        rows, summary = enrich_events([event()], prior, fail, fail, now_ms=20)
        self.assertEqual("complete", rows[0]["settlement_status"])
        self.assertEqual(1, summary["reused_complete"])
        self.assertEqual({}, summary["api_queries"])
        self.assertEqual(1, rows[0]["settlement_attempts"])

    def test_fetch_failure_is_explicit_without_destroying_series(self):
        def fail(*_):
            raise TimeoutError("temporary")
        rows, summary = enrich_events([event()], [], fail,
                                      lambda *_: {"time_ms": 2000, "rate": 0}, now_ms=10)
        self.assertEqual("pending", rows[0]["settlement_status"])
        self.assertEqual("hyperliquid_fetch_error", rows[0]["settlement_reason"])
        self.assertEqual(1, summary["reasons"]["hyperliquid_fetch_error"])

    def test_duplicate_boundaries_share_api_queries(self):
        second = event(event_id="BTC:1000:2000:duplicate")
        calls = []
        rows, summary = enrich_events(
            [event(), second], [],
            lambda *args: calls.append(("hl", args)) or {"time_ms": 1000, "rate": 1},
            lambda *args: calls.append(("okx", args)) or {"time_ms": 2000, "rate": 2}, now_ms=10)
        self.assertEqual(2, len(calls))
        self.assertEqual(2, summary["settled"])
        self.assertEqual({"hyperliquid": 1, "okx_swap": 1}, summary["api_queries"])

    def test_incomplete_event_does_not_call_apis(self):
        def fail(*_):
            raise AssertionError("API called")
        rows, summary = enrich_events([event("pending")], [], fail, fail)
        self.assertEqual("not_eligible", rows[0]["settlement_status"])
        self.assertEqual(1, summary["not_eligible"])


if __name__ == "__main__":
    unittest.main()
