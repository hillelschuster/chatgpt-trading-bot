import tempfile, unittest
from pathlib import Path
from crossvenue_snapshot import append_jsonl, bybit_result, collect_coin, hl_context_map, hl_predicted_map, validate

class CrossVenueSnapshotTest(unittest.TestCase):
    def test_normalizes_hyperliquid_contracts(self):
        rows = [["BTC", [["HlPerp", {"fundingRate":"0.00001","nextFundingTime":123,"fundingIntervalHours":1}],
                          ["BybitPerp", {"fundingRate":"0.00002","nextFundingTime":456,"fundingIntervalHours":8}]]]]
        got = hl_predicted_map(rows)["BTC"]
        self.assertEqual(1, got["HlPerp"]["funding_interval_hours"])
        self.assertEqual(0.00002, got["BybitPerp"]["funding_rate"])

    def test_bybit_contract_and_collection(self):
        self.assertEqual({}, bybit_result({"retCode":0,"result":{}}))
        with self.assertRaises(ValueError): bybit_result({"retCode":10001,"retMsg":"bad"})
        def hl_post(payload):
            if payload["type"] == "predictedFundings":
                return [["BTC", [["HlPerp", {"fundingRate":"0.00001","nextFundingTime":2000,"fundingIntervalHours":1}],
                                  ["BybitPerp", {"fundingRate":"0.00002","nextFundingTime":2000,"fundingIntervalHours":4}]]]]
            if payload["type"] == "metaAndAssetCtxs":
                return ({"universe":[{"name":"BTC"}]}, [{"markPx":"100","oraclePx":"99","funding":".00001","openInterest":"2","dayNtlVlm":"1000"}])
            return {"time":1000,"levels":[[{"px":"99"}],[{"px":"101"}]]}
        def get(url, params):
            if url.endswith("tickers"):
                return {"retCode":0,"result":{"list":[{"markPrice":"100.5","indexPrice":"100","fundingRate":".00002","nextFundingTime":"2000"}]}}
            return {"retCode":0,"result":{"b":[["100","1"]],"a":[["101","1"]],"cts":1000}}
        row = collect_coin("BTC", now_ms=1000, hl_post=hl_post, http_get=get)
        self.assertEqual("BTCUSDT", row["symbol_map"]["bybit_linear"])
        self.assertEqual([], validate(row))

    def test_validation_rejects_crossed_stale_or_missing_funding(self):
        row={"schema_version":2,"captured_at_ms":100000,
             "hyperliquid":{"bid":101,"ask":100,"book_time_ms":100000,"next_funding_time_ms":1},
             "bybit_linear":{"bid":99,"ask":100,"book_time_ms":0,"next_funding_time_ms":None}}
        self.assertEqual(["hyperliquid.book","bybit_linear.book_time_skew","bybit_linear.next_funding_time"], validate(row))

    def test_append_is_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.jsonl"; append_jsonl(p,[{"a":1},{"a":2}]); self.assertEqual(2,len(p.read_text().splitlines()))

if __name__ == "__main__": unittest.main()
