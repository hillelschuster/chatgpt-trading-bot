import tempfile, unittest
from pathlib import Path
from crossvenue_snapshot import append_jsonl, collect_coin, hl_predicted_map, okx_data, validate

class CrossVenueSnapshotTest(unittest.TestCase):
    def test_normalizes_hyperliquid_contracts(self):
        rows=[["BTC",[["HlPerp",{"fundingRate":".00001","nextFundingTime":123,"fundingIntervalHours":1}]]]]
        self.assertEqual(1,hl_predicted_map(rows)["BTC"]["HlPerp"]["funding_interval_hours"])
    def test_okx_contract_and_collection(self):
        self.assertEqual([],okx_data({"code":"0","data":[]}))
        with self.assertRaises(ValueError): okx_data({"code":"1","msg":"bad"})
        def hp(p):
            if p["type"]=="predictedFundings": return [["BTC",[["HlPerp",{"fundingRate":".00001","nextFundingTime":2000,"fundingIntervalHours":1}]]]]
            if p["type"]=="metaAndAssetCtxs": return ({"universe":[{"name":"BTC"}]},[{"markPx":"100","oraclePx":"99","funding":".00001","openInterest":"2","dayNtlVlm":"1000"}])
            return {"time":1000,"levels":[[{"px":"99"}],[{"px":"101"}]]}
        def get(url,params):
            if url.endswith("ticker"): return {"code":"0","data":[{"last":"100","ts":"1000"}]}
            if url.endswith("books"): return {"code":"0","data":[{"bids":[["99","1"]],"asks":[["101","1"]],"ts":"1000"}]}
            return {"code":"0","data":[{"fundingRate":".00002","fundingTime":"2000","nextFundingTime":"3000","settFundingRate":".00001","premium":".0001","ts":"1000","method":"current_period"}]}
        row=collect_coin("BTC",now_ms=1000,hl_post=hp,http_get=get)
        self.assertEqual("BTC-USDT-SWAP",row["symbol_map"]["okx_swap"]); self.assertEqual([],validate(row))
    def test_validation_rejects_bad_data(self):
        row={"schema_version":3,"captured_at_ms":100000,
             "hyperliquid":{"bid":101,"ask":100,"book_time_ms":100000,"next_funding_time_ms":1},
             "okx_swap":{"bid":99,"ask":100,"book_time_ms":0,"funding_time_ms":None,"predicted_funding_rate":None}}
        self.assertEqual(["hyperliquid.book","okx_swap.book_time_skew","okx_swap.funding"],validate(row))
    def test_append_is_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x";append_jsonl(p,[{"a":1},{"a":2}]);self.assertEqual(2,len(p.read_text().splitlines()))
if __name__=="__main__": unittest.main()
