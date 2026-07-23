import json
import tempfile
import unittest
from pathlib import Path

from crossvenue_health import DAY_MS, summarize


def write_json(path, value):
    Path(path).write_text(json.dumps(value))


def write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(x) + "\n" for x in rows))


class HealthTest(unittest.TestCase):
    def fixture(self, root, complete=False):
        data = Path(root) / "data"
        reports = Path(root) / "reports"
        data.mkdir()
        reports.mkdir()
        cutoff = 1_000
        write_json(data / "crossvenue_experiment_freeze.json", {
            "schema": "crossvenue-experiment-freeze-v2", "frozen_at_ms": cutoff,
            "evidence_cutoff_ms": cutoff, "files": {"x": "abc"}})
        write_jsonl(data / "crossvenue_snapshots.jsonl", [
            {"captured_at_ms": cutoff + 300_000, "cadence_slot_ms": cutoff + 300_000, "coin": "BTC"},
            {"captured_at_ms": cutoff + 300_000, "cadence_slot_ms": cutoff + 300_000, "coin": "ETH"},
        ])
        write_jsonl(data / "crossvenue_events.jsonl", [
            {"event_id": "e1", "signal_time_ms": cutoff + 1}])
        write_jsonl(data / "crossvenue_settled_events.jsonl", [{
            "event_id": "e1", "signal_time_ms": cutoff + 1,
            "settlement_status": "complete" if complete else "pending"}])
        pnl = [] if not complete else [{
            "event_id": "e1", "pnl_status": "complete",
            "funding_boundary_ms": cutoff + DAY_MS}]
        write_jsonl(data / "crossvenue_pnl_events.jsonl", pnl)
        write_json(reports / "crossvenue_chain.json", {"valid": True, "errors": []})
        write_json(reports / "crossvenue_coverage.json", {
            "status": "COLLECTING", "collection_span_days": 1,
            "slot_coverage": 1, "complete_slot_coverage": 1, "event_accounting": 1,
            "duplicate_rows": 0})
        write_json(reports / "crossvenue_validation.json", {"status": "COLLECTING"})
        write_json(reports / "crossvenue_promotion.json", {"status": "COLLECTING"})
        return data, reports, cutoff

    def test_reports_noninvasive_accumulation_progress(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual("ACCUMULATING_EVENTS", result["status"])
            self.assertEqual(2, result["counts"]["post_freeze_snapshots"])
            self.assertEqual(200, result["progress"]["periods_remaining"])
            self.assertFalse(result["integrity"]["blockers"])

    def test_complete_rows_count_unique_periods(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root, complete=True)
            write_jsonl(data / "crossvenue_pnl_events.jsonl", [
                {"event_id": "btc", "pnl_status": "complete",
                 "funding_boundary_ms": cutoff + DAY_MS},
                {"event_id": "eth", "pnl_status": "complete",
                 "funding_boundary_ms": cutoff + DAY_MS},
            ])
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual(2, result["counts"]["complete_pnl_rows"])
            self.assertEqual(1, result["counts"]["complete_periods"])
            self.assertEqual("ACCUMULATING_PNL", result["status"])

    def test_invalid_chain_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            write_json(reports / "crossvenue_chain.json", {"valid": False, "errors": ["mutation"]})
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("artifact_chain_invalid", result["integrity"]["blockers"])

    def test_stale_collection_is_invalid(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            result = summarize(data, reports, now_ms=cutoff + 2_000_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("collection_stale", result["integrity"]["blockers"])


if __name__ == "__main__":
    unittest.main()
