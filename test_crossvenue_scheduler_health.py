import unittest
from datetime import datetime, timezone

from crossvenue_scheduler_health import merge, schedule_cadence

NOW = 2_000_000_000_000


def run(id_, minutes_ago, event="schedule", branch="main"):
    ts = datetime.fromtimestamp((NOW - minutes_ago * 60_000) / 1000, timezone.utc)
    return {"id": id_, "head_branch": branch, "event": event,
            "created_at": ts.isoformat().replace("+00:00", "Z")}


def dense():
    return [run(i, minute) for i, minute in enumerate(range(5, 61, 5), 1)]


class SchedulerHealthTest(unittest.TestCase):
    def base(self):
        return {"status": "HEALTHY", "generated_at_ms": NOW, "blockers": [],
                "cadence": {"healthy": True, "source_event": "mixed"}}

    def test_dense_schedule_is_healthy(self):
        got = schedule_cadence(dense(), NOW)
        self.assertTrue(got["healthy"])
        self.assertEqual(12, got["approved_run_count"])
        self.assertEqual("schedule", got["source_event"])

    def test_manual_dispatches_cannot_mask_cron_gap(self):
        rows = [run(100 + i, minute, "workflow_dispatch")
                for i, minute in enumerate(range(5, 31, 5))]
        rows += [run(2, 35), run(1, 60)]
        got = merge(self.base(), rows, NOW)
        self.assertEqual("INVALID", got["status"])
        self.assertIn("collector_schedule_gap", got["blockers"])
        self.assertEqual(2, got["cadence"]["approved_run_count"])
        self.assertEqual(35, got["cadence"]["max_gap_minutes"])

    def test_replaces_false_mixed_event_schedule_blocker(self):
        report = self.base()
        report["status"] = "INVALID"
        report["blockers"] = ["collector_schedule_gap"]
        got = merge(report, dense(), NOW)
        self.assertEqual("HEALTHY", got["status"])
        self.assertEqual([], got["blockers"])

    def test_preserves_unrelated_blockers(self):
        report = self.base()
        report["status"] = "INVALID"
        report["blockers"] = ["successful_run_stale", "collector_schedule_gap"]
        got = merge(report, dense(), NOW)
        self.assertEqual("INVALID", got["status"])
        self.assertEqual(["successful_run_stale"], got["blockers"])


if __name__ == "__main__":
    unittest.main()
