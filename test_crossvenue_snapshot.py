import tempfile
import unittest
from pathlib import Path

from crossvenue_snapshot import (
    append_jsonl,
    best_bid_ask,
    collect_coin,
    hl_context_map,
    hl_predicted_map,
    validate,
)


class CrossVenueSnapshotTest(unittest.TestCase):
    def test_normalizes_hyperliquid_contracts(self):
        predicted = [["BTC", [["HlPerp", {"fundingRate": "0.00001", "nextFundingTime": 123}],
                               ["BinPerp", {"fundingRate": "0.00002", "nextFundingTime": 456}]]]]
        self.assertEqual(0.00001, hl_predicted_map(predicted)["BTC"]["HlPerp"]["funding_rate"])
        contexts = ({"universe": [{"name": "BTC"}]}, [{"markPx": "100", "oraclePx": "99",
                                                          "funding": "0.00001", "openInterest": "2",
                                                          "dayNtlVlm": "1000"}])
        self.assertEqual(100.0, hl_context_map(contexts)["BTC"]["mark_price"])
        self.assertEqual({"bid": 99.0, "ask": 101.0, "book_time_ms": 10},
                         best_bid_ask({"time": 10, "levels": [[{"px": "99"}], [{"px": "101"}]]}))

    def test_collects_only_preentry_public_values(self):
        def hl_post(payload):
            if payload["type"] == "predictedFundings":
                return [["BTC", [["HlPerp", {"fundingRate": "0.00001", "nextFundingTime": 2000}]]]]
            if payload["type"] == "metaAndAssetCtxs":
                return ({"universe": [{"name": "BTC"}]}, [{"markPx": "100", "oraclePx": "99",
                                                              "funding": "0.00001", "openInterest": "2",
                                                              "dayNtlVlm": "1000"}])
            return {"time": 1000, "levels": [[{"px": "99"}], [{"px": "101"}]]}

        def get(url, params):
            if url.endswith("premiumIndex"):
                return {"markPrice": "100.5", "indexPrice": "100", "lastFundingRate": "0.00002",
                        "nextFundingTime": 2000, "time": 1000}
            return {"T": 1000, "bids": [["100", "1"]], "asks": [["101", "1"]]}

        row = collect_coin("BTC", now_ms=1000, hl_post=hl_post, http_get=get)
        self.assertEqual("BTCUSDT", row["symbol_map"]["binance_usdm"])
        self.assertTrue(row["semantics"]["decision_input_only"])
        self.assertEqual([], validate(row))

    def test_validation_rejects_crossed_or_stale_data(self):
        row = {"schema_version": 1, "captured_at_ms": 100_000,
               "hyperliquid": {"bid": 101, "ask": 100},
               "binance_usdm": {"bid": 99, "ask": 100, "event_time_ms": 0}}
        self.assertEqual(["hyperliquid.book", "binance_usdm.event_time_skew"], validate(row))

    def test_append_is_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.jsonl"
            append_jsonl(path, [{"a": 1}, {"a": 2}])
            self.assertEqual(2, len(path.read_text().splitlines()))


if __name__ == "__main__":
    unittest.main()
