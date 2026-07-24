import unittest
from datetime import datetime, timezone

from crossvenue_actions_health import summarize

NOW = 2_000_000_000_000


def run(id_, minutes_ago, status="completed", conclusion="success",
        event="schedule", branch="main"):
    ts = datetime.fromtimestamp((NOW - minutes_ago * 60_000) / 1000, timezone.utc)
    text = ts.isoformat().replace("+00:00", "Z")
    return {"id": id_, "head_branch": branch, "event": event, "status": status,
            "conclusion": conclusion, "created_at": text, "updated_at": text}


class ActionsHealthTest(unittest.TestCase):
    def dense(self):
        return [run(i, minutes) for i, minutes in enumerate(range(5, 61, 5), 1)]

    def test_healthy_and_restoration_matches(self):
        report = summarize(self.dense(), {"status": "downloaded", "workflow_run_id": 1}, NOW)
        self.assertEqual("HEALTHY", report["status"])
        self.assertTrue(report["restoration"]["matches_latest_success"])
        self.assertTrue(report["cadence"]["healthy"])
        self.assertEqual(12, report["cadence"]["approved_run_count"])

    def test_skips_unapproved_runs(self):
        rows = [run(99, 1, branch="feature"), run(98, 2, event="pull_request"), *self.dense()]
        report = summarize(rows, {"status": "downloaded", "workflow_run_id": 1}, NOW)
        self.assertEqual(1, report["latest_run"]["id"])

    def test_repeated_failures_fail_closed(self):
        rows = [run(4, 1, conclusion="failure"), run(3, 6, conclusion="failure"),
                run(2, 11, conclusion="cancelled"), run(1, 20)]
        report = summarize(rows, {"status": "downloaded", "workflow_run_id": 1}, NOW)
        self.assertIn("repeated_collector_failures", report["blockers"])

    def test_stale_success_and_stuck_active_fail_closed(self):
        rows = [run(3, 20, status="in_progress", conclusion=None), run(2, 40)]
        report = summarize(rows, {"status": "downloaded", "workflow_run_id": 2}, NOW)
        self.assertIn("successful_run_stale", report["blockers"])
        self.assertIn("collector_run_stuck", report["blockers"])

    def test_restoration_must_match_latest_success(self):
        report = summarize(self.dense(), {"status": "downloaded", "workflow_run_id": 2}, NOW)
        self.assertIn("restoration_not_latest_success", report["blockers"])

    def test_internal_schedule_gap_fails_closed(self):
        rows = [run(4, 5), run(3, 10), run(2, 35), run(1, 40), run(0, 60)]
        report = summarize(rows, {"status": "downloaded", "workflow_run_id": 4}, NOW)
        self.assertIn("collector_schedule_gap", report["blockers"])
        self.assertEqual(25, report["cadence"]["max_gap_minutes"])
        self.assertGreaterEqual(report["cadence"]["estimated_missed_runs"], 4)

    def test_leading_window_gap_fails_closed(self):
        rows = [run(4, 5), run(3, 10), run(2, 15), run(1, 35)]
        report = summarize(rows, {"status": "downloaded", "workflow_run_id": 4}, NOW)
        self.assertIn("collector_schedule_gap", report["blockers"])
        self.assertEqual(25, report["cadence"]["max_gap_minutes"])

    def test_empty_window_is_not_cadence_healthy(self):
        report = summarize([run(1, 70)], {"status": "downloaded", "workflow_run_id": 1}, NOW)
        self.assertFalse(report["cadence"]["healthy"])
        self.assertEqual(60, report["cadence"]["max_gap_minutes"])
        self.assertIn("collector_schedule_gap", report["blockers"])

    def test_dense_recent_runs_pass_cadence_gate(self):
        report = summarize(self.dense(), {"status": "downloaded", "workflow_run_id": 1}, NOW)
        self.assertNotIn("collector_schedule_gap", report["blockers"])
        self.assertEqual(5, report["cadence"]["max_gap_minutes"])
        self.assertEqual(0, report["cadence"]["estimated_missed_runs"])


if __name__ == "__main__":
    unittest.main()
