import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from crossvenue_actions_gate import apply_gate


def write_json(path, value):
    Path(path).write_text(json.dumps(value) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ActionsGateTest(unittest.TestCase):
    def fixture(self, root):
        root = Path(root)
        health = root / "health.json"
        binding = root / "binding.json"
        runs = root / "runs.json"
        restoration = root / "restoration.json"
        write_json(health, {
            "status": "ACCUMULATING_SNAPSHOTS",
            "operations": {"status": "HEALTHY"},
            "integrity": {"blockers": []},
        })
        write_json(runs, {"workflow_runs": [{"id": 10}]})
        write_json(restoration, {"workflow_run_id": 10})
        write_json(binding, {
            "status": "HEALTHY",
            "valid": True,
            "workflow_runs_sha256": digest(runs),
            "restoration_sha256": digest(restoration),
            "blockers": [],
        })
        return health, binding, runs, restoration

    def test_valid_exact_binding_preserves_accumulation(self):
        with tempfile.TemporaryDirectory() as root:
            paths = self.fixture(root)
            result = apply_gate(*paths)
            self.assertEqual("ACCUMULATING_SNAPSHOTS", result["status"])
            self.assertTrue(result["integrity"]["actions_binding_valid"])
            self.assertTrue(result["operations"]["binding"]["digest_matches"])
            self.assertFalse(result["integrity"]["blockers"])

    def test_false_valid_flag_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            health, binding, runs, restoration = self.fixture(root)
            value = json.loads(binding.read_text())
            value["valid"] = False
            write_json(binding, value)
            result = apply_gate(health, binding, runs, restoration)
            self.assertEqual("INVALID", result["status"])
            self.assertIn("actions_binding_invalid", result["integrity"]["blockers"])

    def test_digest_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            health, binding, runs, restoration = self.fixture(root)
            write_json(runs, {"workflow_runs": [{"id": 11}]})
            result = apply_gate(health, binding, runs, restoration)
            self.assertEqual("INVALID", result["status"])
            self.assertFalse(result["integrity"]["actions_binding_digest_matches"])

    def test_missing_binding_fails_closed_without_erasing_existing_blocker(self):
        with tempfile.TemporaryDirectory() as root:
            health, binding, runs, restoration = self.fixture(root)
            write_json(health, {
                "status": "INVALID",
                "operations": {},
                "integrity": {"blockers": ["collection_stale"]},
            })
            binding.unlink()
            result = apply_gate(health, binding, runs, restoration)
            self.assertEqual(
                ["collection_stale", "actions_binding_missing"],
                result["integrity"]["blockers"],
            )


if __name__ == "__main__":
    unittest.main()
