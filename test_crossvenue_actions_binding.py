import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from crossvenue_actions_binding import MAX_REPORT_AGE_MS, verify
from crossvenue_actions_health import summarize
from crossvenue_scheduler_health import merge

NOW = 2_000_000_000_000


def run(id_, minutes_ago, event="schedule"):
    ts = datetime.fromtimestamp((NOW - minutes_ago * 60_000) / 1000, timezone.utc)
    text = ts.isoformat().replace("+00:00", "Z")
    return {
        "id": id_,
        "head_branch": "main",
        "event": event,
        "status": "completed",
        "conclusion": "success",
        "created_at": text,
        "updated_at": text,
    }


class ActionsBindingTest(unittest.TestCase):
    def fixture(self, root):
        root = Path(root)
        runs = [run(i, minutes) for i, minutes in enumerate(range(5, 61, 5), 1)]
        runs_path = root / "runs.json"
        restoration_path = root / "restoration.json"
        report_path = root / "actions.json"
        runs_path.write_text(json.dumps({"workflow_runs": runs}))
        restoration = {"status": "downloaded", "workflow_run_id": 1}
        restoration_path.write_text(json.dumps(restoration))
        report = merge(summarize(runs, restoration, NOW), runs, NOW)
        report_path.write_text(json.dumps(report))
        return runs_path, restoration_path, report_path

    def test_exact_inputs_pass(self):
        with tempfile.TemporaryDirectory() as root:
            runs, restoration, report = self.fixture(root)
            result = verify(runs, restoration, report, NOW + 1_000)
            self.assertTrue(result["valid"])
            self.assertEqual([], result["mismatched_fields"])

    def test_tampered_report_fails(self):
        with tempfile.TemporaryDirectory() as root:
            runs, restoration, report = self.fixture(root)
            value = json.loads(report.read_text())
            value["status"] = "INVALID"
            report.write_text(json.dumps(value))
            result = verify(runs, restoration, report, NOW)
            self.assertIn("actions_health_evidence_mismatch", result["blockers"])

    def test_changed_runs_fail(self):
        with tempfile.TemporaryDirectory() as root:
            runs, restoration, report = self.fixture(root)
            value = json.loads(runs.read_text())
            value["workflow_runs"] = value["workflow_runs"][1:]
            runs.write_text(json.dumps(value))
            self.assertFalse(verify(runs, restoration, report, NOW)["valid"])

    def test_stale_replay_fails(self):
        with tempfile.TemporaryDirectory() as root:
            runs, restoration, report = self.fixture(root)
            result = verify(runs, restoration, report, NOW + MAX_REPORT_AGE_MS + 1)
            self.assertIn("actions_health_report_stale", result["blockers"])


if __name__ == "__main__":
    unittest.main()
