import tempfile, unittest
from pathlib import Path
from crossvenue_snapshot import (SCHEMA_VERSION, append_jsonl, collect_coin, continuity,
                                 effective_next_funding_time, hl_predicted_map,
                                 okx_data, read_jsonl, validate)


class CrossVenueSnapshotTest(unittest.TestCase):
    def fixture(self, now=3_700_000, slot=3_600_000, coin="BTC"):
        return {"schema_version": SCHEMA_VERSION, "captured_at_ms": now,
                "cadence_slot_ms": slot, "coin": coin,
                "hyperliquid": {"bid": 99, "ask": 101, "book_time_ms": now,
                    "effective_next_funding_time_ms": 7_200_000},
                "okx_swap": {"bid": 99, "ask": 101, "book_time_ms": now,
                    "funding_time_ms": 7_200_000, "predicted_funding_rate": .00002}}

    def test_advances_stale_hyperliquid_boundary(self):
        self.assertEqual(7_200_000, effective_next_funding_time(0, 3_700_000, 1))
        self.assertEqual(7_200_000, effective_next_funding_time(7_200_000, 3_700_000, 1))
        self.assertIsNone(effective_next_funding_time(None, 1, 1))

    def test_normalizes_and_collects_contract(self):
        rows = [["BTC", [["HlPerp", {"fundingRate": ".00001", "nextFundingTime": 0,
                                      "fundingIntervalHours": 1}]]]]
        self.assertEqual(1, hl_predicted_map(rows)["BTC"]["HlPerp"]["funding_interval_hours"])
        self.assertEqual([], okx_data({"code": "0", "data": []}))
        with self.assertRaises(ValueError):
            okx_data({"code": "1", "msg": "bad"})

        def hp(payload):
            if payload["type"] == "predictedFundings":
                return rows
            if payload["type"] == "metaAndAssetCtxs":
                return ({"universe": [{"name": "BTC"}]}, [{"markPx": "100", "oraclePx": "99",
                        "funding": ".00001", "openInterest": "2", "dayNtlVlm": "1000"}])
            return {"time": 3_700_000, "levels": [[{"px": "99"}], [{"px": "101"}]]}

        def get(url, params):
            if url.endswith("ticker"):
                return {"code": "0", "data": [{"last": "100", "ts": "3700000"}]}
            if url.endswith("books"):
                return {"code": "0", "data": [{"bids": [["99", "1"]], "asks": [["101", "1"]],
                                                  "ts": "3700000"}]}
            return {"code": "0", "data": [{"fundingRate": ".00002", "fundingTime": "7200000",
                    "nextFundingTime": "10800000", "settFundingRate": ".00001", "premium": ".0001",
                    "ts": "3700000", "method": "current_period"}]}

        row = collect_coin("BTC", now_ms=3_700_000, hl_post=hp, http_get=get)
        self.assertEqual(7_200_000, row["hyperliquid"]["effective_next_funding_time_ms"])
        self.assertEqual([], validate(row))

    def test_validation_rejects_stale_boundary_and_bad_book(self):
        row = self.fixture(); row["hyperliquid"]["bid"] = 102
        row["hyperliquid"]["effective_next_funding_time_ms"] = row["captured_at_ms"]
        self.assertEqual(["hyperliquid.book", "hyperliquid.effective_next_funding_time"], validate(row))

    def test_append_resumes_without_duplicate_slot_coin(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl"
            row = self.fixture()
            self.assertEqual(1, append_jsonl(path, [row]))
            self.assertEqual(0, append_jsonl(path, [row]))
            self.assertEqual(1, len(read_jsonl(path)))

    def test_continuity_detects_gaps_and_incomplete_slots(self):
        btc0 = self.fixture(100, 0, "BTC"); eth0 = self.fixture(100, 0, "ETH")
        btc2 = self.fixture(600_100, 600_000, "BTC"); eth2 = self.fixture(600_100, 600_000, "ETH")
        gap_report = continuity([btc0, eth0, btc2, eth2], ["BTC", "ETH"], 300_000)
        self.assertTrue(gap_report["valid"])
        self.assertFalse(gap_report["complete_cadence"])
        self.assertEqual(1, gap_report["gaps"][0]["missing_slots"])
        incomplete = continuity([btc0, eth0, btc2], ["BTC", "ETH"], 300_000)
        self.assertFalse(incomplete["valid"])
        self.assertEqual(["ETH"], incomplete["incomplete_slots"]["600000"])


if __name__ == "__main__":
    unittest.main()
