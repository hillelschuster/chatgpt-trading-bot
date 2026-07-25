import hashlib
import io
import unittest
import zipfile

from taker_flow_feasibility import Trade, parse_archive, parse_checksum, summarize, verify_checksum


def archive(rows: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("BTCUSDT-aggTrades-2026-07-23.csv", rows)
    return buffer.getvalue()


class TakerFlowFeasibilityTests(unittest.TestCase):
    def test_parse_and_summarize_valid_archive(self):
        payload = archive(
            "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
            "1,100.0,2.0,10,11,1000,false\n"
            "2,101.0,1.0,12,12,2000,true\n"
            "3,102.0,3.0,13,15,7000,false\n"
        )
        trades = parse_archive(payload)
        self.assertEqual(3, len(trades))
        report = summarize(trades)
        self.assertEqual(2, report["unique_buckets"])
        self.assertEqual(0, report["empty_bucket_gaps"])
        self.assertAlmostEqual(607.0, report["total_quote_notional"])
        self.assertAlmostEqual(306.0, report["max_abs_signed_quote_notional_5s"])

    def test_exact_duplicate_is_deduplicated(self):
        payload = archive(
            "1,100,2,10,11,1000,false\n"
            "1,100,2,10,11,1000,false\n"
        )
        self.assertEqual(1, len(parse_archive(payload)))

    def test_conflicting_duplicate_fails(self):
        payload = archive(
            "1,100,2,10,11,1000,false\n"
            "1,101,2,10,11,1000,false\n"
        )
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            parse_archive(payload)

    def test_decreasing_order_fails(self):
        payload = archive(
            "2,100,1,2,2,2000,false\n"
            "1,100,1,1,1,1000,false\n"
        )
        with self.assertRaisesRegex(ValueError, "decreasing"):
            parse_archive(payload)

    def test_checksum_validation(self):
        payload = b"archive"
        digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual(digest, parse_checksum(digest + "  file.zip\n"))
        verify_checksum(payload, digest)
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            verify_checksum(payload + b"x", digest)

    def test_invalid_archive_shape_fails(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("a.csv", "1,100,1,1,1,1000,false\n")
            zf.writestr("b.csv", "2,100,1,2,2,2000,false\n")
        with self.assertRaisesRegex(ValueError, "exactly one CSV"):
            parse_archive(buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
