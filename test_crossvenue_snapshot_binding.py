import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from crossvenue_snapshot import DEFAULT_CADENCE_MS, SCHEMA_VERSION
from crossvenue_snapshot_binding import verify
from crossvenue_snapshot_health import FUTURE_TOLERANCE_MS, RECENT_WINDOW_MS, audit


def snapshot(slot, coin="BTC"):
    captured = slot + 1_000
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


def write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(row) + "\n" for row in rows))


class SnapshotBindingTest(unittest.TestCase):
    def fixture(self, root):
        now = 20 * DEFAULT_CADENCE_MS
        rows = [snapshot(now - DEFAULT_CADENCE_MS, coin) for coin in ("BTC", "ETH")]
        snapshots = Path(root) / "snapshots.jsonl"
        report = Path(root) / "report.json"
        write_jsonl(snapshots, rows)
        report.write_text(json.dumps(audit(rows, now_ms=now)))
        return snapshots, report, now

    def test_accepts_report_recomputed_from_exact_series(self):
        with tempfile.TemporaryDirectory() as root:
            snapshots, report, _ = self.fixture(root)
            result = verify(snapshots, report)
            self.assertTrue(result["valid"])
            self.assertEqual([], result["mismatched_fields"])
            self.assertEqual(RECENT_WINDOW_MS, result["audit_window_ms"])
            self.assertEqual(FUTURE_TOLERANCE_MS, result["future_tolerance_ms"])
            self.assertEqual(hashlib.sha256(snapshots.read_bytes()).hexdigest(),
                             result["snapshot_sha256"])

    def test_rejects_report_after_snapshot_series_changes(self):
        with tempfile.TemporaryDirectory() as root:
            snapshots, report, now = self.fixture(root)
            rows = [snapshot(now - DEFAULT_CADENCE_MS, "BTC")]
            write_jsonl(snapshots, rows)
            result = verify(snapshots, report)
            self.assertFalse(result["valid"])
            self.assertIn("recent_rows", result["mismatched_fields"])
            self.assertIn("snapshot_health_evidence_mismatch", result["blockers"])

    def test_rejects_tampered_healthy_report(self):
        with tempfile.TemporaryDirectory() as root:
            snapshots, report, _ = self.fixture(root)
            value = json.loads(report.read_text())
            value["invalid_rows"] = 99
            report.write_text(json.dumps(value))
            result = verify(snapshots, report)
            self.assertFalse(result["valid"])
            self.assertIn("invalid_rows", result["mismatched_fields"])

    def test_rejects_report_controlled_window(self):
        with tempfile.TemporaryDirectory() as root:
            snapshots, report, now = self.fixture(root)
            rows = [snapshot(now - 10 * RECENT_WINDOW_MS, coin) for coin in ("BTC", "ETH")]
            write_jsonl(snapshots, rows)
            forged = audit(rows, now_ms=now, window_ms=20 * RECENT_WINDOW_MS)
            report.write_text(json.dumps(forged))
            result = verify(snapshots, report)
            self.assertFalse(result["valid"])
            self.assertIn("window_minutes", result["mismatched_fields"])

    def test_rejects_report_controlled_future_tolerance(self):
        with tempfile.TemporaryDirectory() as root:
            snapshots, report, now = self.fixture(root)
            future_slot = now + 2 * FUTURE_TOLERANCE_MS
            rows = [snapshot(future_slot, coin) for coin in ("BTC", "ETH")]
            write_jsonl(snapshots, rows)
            forged = audit(rows, now_ms=now, future_tolerance_ms=10 * FUTURE_TOLERANCE_MS)
            report.write_text(json.dumps(forged))
            result = verify(snapshots, report)
            self.assertFalse(result["valid"])
            self.assertIn("future_tolerance_ms", result["mismatched_fields"])

    def test_rejects_report_without_generation_time(self):
        with tempfile.TemporaryDirectory() as root:
            snapshots, report, _ = self.fixture(root)
            value = json.loads(report.read_text())
            value.pop("generated_at_ms")
            report.write_text(json.dumps(value))
            result = verify(snapshots, report)
            self.assertEqual(["snapshot_health_generated_at_missing"], result["blockers"])


if __name__ == "__main__":
    unittest.main()
