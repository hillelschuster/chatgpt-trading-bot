import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from crossvenue_actions_binding import verify
from crossvenue_actions_health import summarize
from crossvenue_actions_gate import apply_gate
from crossvenue_scheduler_health import merge


def write_json(path, value):
    Path(path).write_text(json.dumps(value) + "\n")


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


class ActionsGateTest(unittest.TestCase):
    NOW = 1_800_000_000_000

    def fixture(self, root):
        root = Path(root)
        health = root / "health.json"
        binding = root / "binding.json"
        runs = root / "runs.json"
        restoration = root / "restoration.json"
        actions = root / "actions.json"
        write_json(health, {
            "status": "ACCUMULATING_SNAPSHOTS",
            "operations": {"status": "HEALTHY"},
            "integrity": {"blockers": []},
        })
        run_rows = []
        for index, minutes_ago in enumerate(range(0, 61, 5), start=1):
            timestamp = self.NOW - minutes_ago * 60_000
            run_rows.append({
                "id": index,
                "head_branch": "main",
                "event": "schedule",
                "status": "completed",
                "conclusion": "success",
                "created_at": iso(timestamp),
                "updated_at": iso(timestamp),
            })
        write_json(runs, {"workflow_runs": run_rows})
        write_json(restoration, {"status": "downloaded", "workflow_run_id": 1})
        report = merge(
            summarize(run_rows, {"status": "downloaded", "workflow_run_id": 1}, now_ms=self.NOW),
            run_rows,
            self.NOW,
        )
        write_json(actions, report)
        write_json(binding, verify(runs, restoration, actions, now_ms=self.NOW + 1_000))
        return health, binding, runs, restoration, actions

    def test_valid_exact_fresh_binding_preserves_accumulation(self):
        with tempfile.TemporaryDirectory() as root:
            paths = self.fixture(root)
            result = apply_gate(*paths, now_ms=self.NOW + 2_000)
            self.assertEqual("ACCUMULATING_SNAPSHOTS", result["status"])
            self.assertTrue(result["integrity"]["actions_binding_valid"])
            self.assertTrue(result["operations"]["binding"]["exact_recomputation_match"])
            self.assertTrue(result["operations"]["binding"]["fresh"])

    def test_tampered_healthy_binding_fails_even_with_same_input_digests(self):
        with tempfile.TemporaryDirectory() as root:
            health, binding, runs, restoration, actions = self.fixture(root)
            value = json.loads(binding.read_text())
            value["mismatched_fields"] = []
            value["report_age_ms"] = 0
            write_json(binding, value)
            result = apply_gate(health, binding, runs, restoration, actions, now_ms=self.NOW + 2_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("actions_binding_evidence_mismatch", result["integrity"]["blockers"])

    def test_stale_exact_binding_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            paths = self.fixture(root)
            result = apply_gate(*paths, now_ms=self.NOW + 11 * 60_000)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("actions_binding_stale_or_future", result["integrity"]["blockers"])

    def test_future_exact_binding_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            paths = self.fixture(root)
            result = apply_gate(*paths, now_ms=self.NOW)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("actions_binding_stale_or_future", result["integrity"]["blockers"])

    def test_changed_actions_report_fails_recomputation(self):
        with tempfile.TemporaryDirectory() as root:
            health, binding, runs, restoration, actions = self.fixture(root)
            value = json.loads(actions.read_text())
            value["status"] = "INVALID"
            write_json(actions, value)
            result = apply_gate(health, binding, runs, restoration, actions, now_ms=self.NOW + 2_000)
            self.assertEqual("INVALID", result["status"])
            self.assertFalse(result["integrity"]["actions_binding_exact_recomputation_match"])

    def test_missing_binding_preserves_existing_blocker(self):
        with tempfile.TemporaryDirectory() as root:
            health, binding, runs, restoration, actions = self.fixture(root)
            write_json(health, {
                "status": "INVALID",
                "operations": {},
                "integrity": {"blockers": ["collection_stale"]},
            })
            binding.unlink()
            result = apply_gate(health, binding, runs, restoration, actions, now_ms=self.NOW + 2_000)
            self.assertEqual(
                ["collection_stale", "actions_binding_missing"],
                result["integrity"]["blockers"],
            )


if __name__ == "__main__":
    unittest.main()
