import json
import tempfile
import unittest
from pathlib import Path

from crossvenue_freeze import DEFAULT_FILES, SCHEMA, verify_or_create
from crossvenue_validate import validate


def pnl_row(i, value=.4, status="complete"):
    return {"event_id": f"e{i}", "boundary_ms": i * 1000,
            "coin": "BTC" if i % 2 else "ETH", "pnl_status": status,
            "base_net_return_pct": value, "stress_net_return_pct": value / 2}


class CrossVenueFreezeTest(unittest.TestCase):
    def test_creation_records_latest_existing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "logic.py"; source.write_text("v1\n")
            evidence = root / "evidence.jsonl"
            evidence.write_text("\n".join(json.dumps(pnl_row(i)) for i in (1, 7, 3)) + "\n")
            manifest, created = verify_or_create(
                root / "freeze.json", (source,), (evidence,), now_ms=9000)
            self.assertTrue(created)
            self.assertEqual(SCHEMA, manifest["schema"])
            self.assertEqual(7000, manifest["evidence_cutoff_ms"])

    def test_unchanged_contract_reopens_and_mutation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "logic.py"; source.write_text("v1\n")
            path = root / "freeze.json"
            first, _ = verify_or_create(path, (source,), (), now_ms=1)
            second, created = verify_or_create(path, (source,), (), now_ms=2)
            self.assertFalse(created); self.assertEqual(first, second)
            source.write_text("v2\n")
            with self.assertRaises(ValueError):
                verify_or_create(path, (source,), (), now_ms=3)

    def test_safe_upgrade_moves_cutoff_before_complete_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "logic.py"; source.write_text("v1\n")
            evidence = root / "evidence.jsonl"
            evidence.write_text(json.dumps(pnl_row(7, status="pending")) + "\n")
            path = root / "freeze.json"
            verify_or_create(path, (source,), (), now_ms=1)
            source.write_text("v2\n")
            upgraded, changed = verify_or_create(
                path, (source,), (evidence,), now_ms=9, allow_safe_upgrade=True)
            self.assertTrue(changed)
            self.assertEqual(7000, upgraded["evidence_cutoff_ms"])
            self.assertEqual(9, upgraded["frozen_at_ms"])

    def test_safe_upgrade_fails_after_complete_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "logic.py"; source.write_text("v1\n")
            evidence = root / "evidence.jsonl"
            evidence.write_text(json.dumps(pnl_row(7)) + "\n")
            path = root / "freeze.json"
            verify_or_create(path, (source,), (), now_ms=1)
            source.write_text("v2\n")
            with self.assertRaises(ValueError):
                verify_or_create(path, (source,), (evidence,), now_ms=9, allow_safe_upgrade=True)

    def test_authoritative_coverage_and_promotion_logic_are_frozen(self):
        self.assertIn("crossvenue_coverage.py", DEFAULT_FILES)
        self.assertIn("crossvenue_promote.py", DEFAULT_FILES)

    def test_newly_added_contract_file_forces_safe_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "validation.py"; first.write_text("v1\n")
            added = root / "promotion.py"; added.write_text("v1\n")
            manifest_path = root / "freeze.json"
            verify_or_create(manifest_path, (first,), (), now_ms=1)
            manifest, upgraded = verify_or_create(
                manifest_path, (first, added), (), now_ms=2, allow_safe_upgrade=True)
            self.assertTrue(upgraded)
            self.assertEqual({str(first), str(added)}, set(manifest["files"]))

    def test_validation_excludes_all_prefreeze_attempts(self):
        rows = [pnl_row(i) for i in range(260)]
        report, _, _ = validate(rows, evidence_cutoff_ms=59000)
        self.assertEqual(200, report["complete_events"])
        self.assertEqual(60, report["excluded_prefreeze_attempts"])
        self.assertEqual(59000, report["evidence_cutoff_ms"])


if __name__ == "__main__":
    unittest.main()
