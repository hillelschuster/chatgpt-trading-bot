import json
import tempfile
import unittest
from pathlib import Path

from crossvenue_health import DAY_MS, CADENCE_MS, recent_snapshot_cadence, summarize


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
        write_json(reports / "crossvenue_actions_health.json", {
            "status": "HEALTHY", "latest_run": {"id": 10, "status": "completed"},
            "latest_success": {"id": 10, "age_minutes": 2},
            "active": {"count": 0}, "failures": {"consecutive": 0},
            "restoration": {"workflow_run_id": 10, "matches_latest_success": True},
            "blockers": []})
        write_json(reports / "crossvenue_snapshot_health.json", {
            "status": "HEALTHY", "healthy": True, "recent_rows": 2,
            "invalid_rows": 0, "duplicate_rows": 0, "blockers": []})
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
            self.assertTrue(result["integrity"]["required_data_present"])
            self.assertTrue(result["integrity"]["required_reports_present"])
            self.assertTrue(result["integrity"]["snapshot_health_valid"])
            self.assertEqual("HEALTHY", result["collection"]["snapshot_integrity"]["status"])
            self.assertEqual("HEALTHY", result["operations"]["status"])
            self.assertTrue(result["operations"]["restoration"]["matches_latest_success"])
            self.assertEqual("WARMING_UP", result["collection"]["recent_cadence"]["status"])

    def test_complete_rows_count_unique_periods(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root, complete=True)
            write_jsonl(data / "crossvenue_pnl_events.jsonl", [
                {"event_id": "btc", "pnl_status": "complete",
                 "funding_boundary_ms": cutoff + DAY_MS},
                {"event_id": "eth", "pnl_status": "complete",
                 "funding_boundary_ms": cutoff + DAY_MS},
            ])
            write_jsonl(data / "crossvenue_settled_events.jsonl", [
                {"event_id": "btc", "settlement_status": "complete"},
                {"event_id": "eth", "settlement_status": "complete"},
            ])
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual(2, result["counts"]["complete_pnl_rows"])
            self.assertEqual(1, result["counts"]["complete_periods"])
            self.assertEqual("ACCUMULATING_PNL", result["status"])

    def test_unhealthy_collector_fails_combined_health_closed(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            write_json(reports / "crossvenue_actions_health.json", {
                "status": "INVALID", "blockers": ["successful_run_stale"]})
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("collector_workflow_unhealthy", result["integrity"]["blockers"])
            self.assertEqual(["successful_run_stale"], result["operations"]["blockers"])

    def test_invalid_snapshot_payload_report_fails_combined_health_closed(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            write_json(reports / "crossvenue_snapshot_health.json", {
                "status": "INVALID", "healthy": False, "recent_rows": 2,
                "invalid_rows": 1, "duplicate_rows": 0,
                "blockers": ["recent_snapshot_payload_invalid"]})
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("snapshot_payload_unhealthy", result["integrity"]["blockers"])
            self.assertEqual(["recent_snapshot_payload_invalid"],
                             result["integrity"]["snapshot_health_blockers"])
            self.assertEqual(1, result["collection"]["snapshot_integrity"]["invalid_rows"])

    def test_missing_snapshot_payload_report_fails_combined_health_closed(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            (reports / "crossvenue_snapshot_health.json").unlink()
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("required_reports_missing", result["integrity"]["blockers"])
            self.assertIn("snapshot_health_missing", result["integrity"]["blockers"])
            self.assertEqual(["crossvenue_snapshot_health.json"],
                             result["integrity"]["missing_reports"])

    def test_snapshot_status_cannot_claim_healthy_with_false_boolean(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            write_json(reports / "crossvenue_snapshot_health.json", {
                "status": "HEALTHY", "healthy": False, "recent_rows": 2,
                "invalid_rows": 0, "duplicate_rows": 0, "blockers": []})
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("snapshot_payload_unhealthy", result["integrity"]["blockers"])

    def test_missing_actions_health_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            (reports / "crossvenue_actions_health.json").unlink()
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("required_reports_missing", result["integrity"]["blockers"])
            self.assertIn("actions_health_missing", result["integrity"]["blockers"])
            self.assertEqual(["crossvenue_actions_health.json"], result["integrity"]["missing_reports"])

    def test_invalid_chain_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            write_json(reports / "crossvenue_chain.json", {"valid": False, "errors": ["mutation"]})
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("artifact_chain_invalid", result["integrity"]["blockers"])

    def test_missing_required_report_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            (reports / "crossvenue_chain.json").unlink()
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("required_reports_missing", result["integrity"]["blockers"])
            self.assertIn("artifact_chain_missing", result["integrity"]["blockers"])
            self.assertEqual(["crossvenue_chain.json"], result["integrity"]["missing_reports"])

    def test_missing_required_data_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            (data / "crossvenue_events.jsonl").unlink()
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("required_data_missing", result["integrity"]["blockers"])
            self.assertEqual(["crossvenue_events.jsonl"], result["integrity"]["missing_data"])

    def test_impossible_pnl_settlement_counts_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            write_jsonl(data / "crossvenue_pnl_events.jsonl", [{
                "event_id": "orphan", "pnl_status": "complete",
                "funding_boundary_ms": cutoff + DAY_MS}])
            result = summarize(data, reports, now_ms=cutoff + 600_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("pnl_settlement_count_inconsistent", result["integrity"]["blockers"])

    def test_stale_collection_is_invalid(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, cutoff = self.fixture(root)
            result = summarize(data, reports, now_ms=cutoff + 2_000_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("collection_stale", result["integrity"]["blockers"])

    def test_recent_data_plane_cadence_accepts_complete_btc_eth_slots(self):
        now = 20 * CADENCE_MS
        cutoff = now - 2 * 3_600_000
        first = ((now - 3_600_000) // CADENCE_MS + 1) * CADENCE_MS
        last = ((now - 120_000) // CADENCE_MS) * CADENCE_MS
        rows = [
            {"cadence_slot_ms": slot, "coin": coin}
            for slot in range(first, last + 1, CADENCE_MS)
            for coin in ("BTC", "ETH")
        ]
        result = recent_snapshot_cadence(rows, cutoff, now)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["expected_rows"], result["observed_rows"])
        self.assertEqual(1.0, result["complete_slot_coverage"])

    def test_recent_data_plane_cadence_rejects_fresh_but_one_sided_series(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports, _ = self.fixture(root)
            now = 20 * CADENCE_MS
            cutoff = now - 2 * 3_600_000
            write_json(data / "crossvenue_experiment_freeze.json", {
                "schema": "crossvenue-experiment-freeze-v2", "frozen_at_ms": cutoff,
                "evidence_cutoff_ms": cutoff, "files": {"x": "abc"}})
            first = ((now - 3_600_000) // CADENCE_MS + 1) * CADENCE_MS
            last = ((now - 120_000) // CADENCE_MS) * CADENCE_MS
            rows = [{"captured_at_ms": slot, "cadence_slot_ms": slot, "coin": "BTC"}
                    for slot in range(first, last + 1, CADENCE_MS)]
            write_jsonl(data / "crossvenue_snapshots.jsonl", rows)
            result = summarize(data, reports, now_ms=now)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("recent_snapshot_cadence_unhealthy", result["integrity"]["blockers"])
            self.assertEqual(0.0, result["collection"]["recent_cadence"]["complete_slot_coverage"])
            self.assertLess(result["collection"]["recent_cadence"]["row_coverage"], 0.90)

    def test_recent_data_plane_cadence_rejects_duplicate_rows(self):
        now = 20 * CADENCE_MS
        cutoff = now - 2 * 3_600_000
        first = ((now - 3_600_000) // CADENCE_MS + 1) * CADENCE_MS
        last = ((now - 120_000) // CADENCE_MS) * CADENCE_MS
        rows = [
            {"cadence_slot_ms": slot, "coin": coin}
            for slot in range(first, last + 1, CADENCE_MS)
            for coin in ("BTC", "ETH")
        ]
        rows.append(dict(rows[-1]))
        result = recent_snapshot_cadence(rows, cutoff, now)
        self.assertFalse(result["healthy"])
        self.assertEqual(1, result["duplicate_rows"])


if __name__ == "__main__":
    unittest.main()
