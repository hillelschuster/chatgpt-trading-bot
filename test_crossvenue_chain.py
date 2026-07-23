import json
import tempfile
import unittest
from pathlib import Path

from crossvenue_chain import audit


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def snapshot(slot=0, coin="BTC"):
    return {"cadence_slot_ms": slot, "coin": coin, "value": slot + 1}


def event(status="pending"):
    return {
        "event_id": "BTC:100:200", "schema_version": 1, "coin": "BTC",
        "status": status, "signal_time_ms": 1, "entry_target_ms": 2,
        "exit_target_ms": 201, "hyperliquid_funding_time_ms": 100,
        "okx_funding_time_ms": 200, "predicted_funding": {"hyperliquid": .001},
        "direction": {"long_venue": "hyperliquid"}, "signal_books": {},
        "entry": {"long_entry_price": 100}, "exit": {"long_exit_price": 101},
    }


def settlement(status="pending", observation=None, attempts=1):
    return {
        **event("complete"), "settlement_status": status,
        "settlement_observations": {"hyperliquid": observation, "okx_swap": None},
        "settlement_attempts": attempts,
    }


def manifest(schema="v2", frozen=100, cutoff=0):
    return {"schema": schema, "frozen_at_ms": frozen, "evidence_cutoff_ms": cutoff,
            "files": {"crossvenue_pnl.py": "abc"}}


def pnl(status="pending", freeze=None, value=None):
    row = {**event("complete"), "pnl_status": status,
           "experiment_freeze": freeze or {"sha256": "abc"}}
    if value is not None:
        row["base_net_return_pct"] = value
    return row


class ChainTest(unittest.TestCase):
    def dirs(self):
        root = tempfile.TemporaryDirectory()
        return root, Path(root.name) / "previous", Path(root.name) / "current"

    def test_append_and_pending_transition_are_valid(self):
        root, old, new = self.dirs()
        write_json(old / "crossvenue_experiment_freeze.json", manifest())
        write_json(new / "crossvenue_experiment_freeze.json", manifest())
        write(old / "crossvenue_snapshots.jsonl", [snapshot()])
        write(new / "crossvenue_snapshots.jsonl", [snapshot(), snapshot(300)])
        write(old / "crossvenue_events.jsonl", [event("pending")])
        write(new / "crossvenue_events.jsonl", [event("complete")])
        obs = {"time_ms": 100, "rate": .001}
        write(old / "crossvenue_settled_events.jsonl", [settlement("pending", obs, 1)])
        write(new / "crossvenue_settled_events.jsonl", [
            {**settlement("complete", obs, 2),
             "settlement_observations": {"hyperliquid": obs,
                                         "okx_swap": {"time_ms": 200, "rate": .002}}}])
        write(old / "crossvenue_pnl_events.jsonl", [pnl("pending")])
        write(new / "crossvenue_pnl_events.jsonl", [pnl("complete", value=.1)])
        report = audit(old, new, True)
        self.assertTrue(report["valid"])
        self.assertEqual(1, report["new_snapshots"])
        self.assertEqual(1, report["newly_settled"])
        self.assertEqual(1, report["newly_scored"])
        root.cleanup()

    def test_removed_snapshot_fails(self):
        root, old, new = self.dirs()
        write(old / "crossvenue_snapshots.jsonl", [snapshot()])
        write(new / "crossvenue_snapshots.jsonl", [])
        report = audit(old, new)
        self.assertFalse(report["valid"])
        self.assertTrue(report["errors"][0].startswith("snapshot_removed"))
        root.cleanup()

    def test_exact_observation_cannot_change(self):
        root, old, new = self.dirs()
        write(old / "crossvenue_settled_events.jsonl",
              [settlement("pending", {"time_ms": 100, "rate": .001})])
        write(new / "crossvenue_settled_events.jsonl",
              [settlement("pending", {"time_ms": 100, "rate": .009}, 2)])
        report = audit(old, new)
        self.assertIn("settlement_observation_changed:BTC:100:200:hyperliquid",
                      report["errors"])
        root.cleanup()

    def test_terminal_pnl_cannot_be_removed_or_changed(self):
        root, old, new = self.dirs()
        old_row = pnl("complete", value=.1)
        write(old / "crossvenue_pnl_events.jsonl", [old_row])
        write(new / "crossvenue_pnl_events.jsonl", [{**old_row, "base_net_return_pct": 9}])
        report = audit(old, new)
        self.assertIn("pnl_terminal_changed:BTC:100:200:complete:complete", report["errors"])
        write(new / "crossvenue_pnl_events.jsonl", [])
        self.assertIn("pnl_removed:BTC:100:200", audit(old, new)["errors"])
        root.cleanup()

    def test_freeze_change_fails_after_complete_pnl(self):
        root, old, new = self.dirs()
        write_json(old / "crossvenue_experiment_freeze.json", manifest("v1", 100, 10))
        write_json(new / "crossvenue_experiment_freeze.json", manifest("v2", 200, 20))
        write(old / "crossvenue_pnl_events.jsonl", [pnl("complete", value=.1)])
        write(new / "crossvenue_pnl_events.jsonl", [pnl("complete", value=.1)])
        report = audit(old, new)
        self.assertIn("freeze_manifest_mutated", report["errors"])
        root.cleanup()

    def test_safe_pre_evidence_freeze_upgrade_is_reported(self):
        root, old, new = self.dirs()
        write_json(old / "crossvenue_experiment_freeze.json", manifest("v1", 100, 10))
        write_json(new / "crossvenue_experiment_freeze.json", manifest("v2", 200, 20))
        write(old / "crossvenue_pnl_events.jsonl", [pnl("pending")])
        write(new / "crossvenue_pnl_events.jsonl", [pnl("pending", {"sha256": "new"})])
        report = audit(old, new)
        self.assertTrue(report["valid"])
        self.assertTrue(report["freeze_manifest_upgraded"])
        root.cleanup()

    def test_scheduled_run_can_require_restored_artifact(self):
        root, old, new = self.dirs()
        report = audit(old, new, True)
        self.assertEqual(["previous_artifact_missing"], report["errors"])
        root.cleanup()


if __name__ == "__main__":
    unittest.main()
