import tempfile
import unittest
import zipfile
from pathlib import Path

from crossvenue_restored_inventory import MANAGED_MEMBERS, verify_restored_inventory


class RestoredInventoryTests(unittest.TestCase):
    def _fixture(self, members):
        root = Path(tempfile.mkdtemp())
        archive = root / "series.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for name, body in members.items():
                bundle.writestr(name, body)
        for name, body in members.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        return root, archive

    def test_exact_restored_inventory_passes(self):
        members = {name: name for name in MANAGED_MEMBERS}
        root, archive = self._fixture(members)
        report = verify_restored_inventory(archive, root)
        self.assertEqual("VALID", report["status"])
        self.assertEqual([], report["blockers"])

    def test_stale_managed_file_from_prior_artifact_fails(self):
        omitted = "data/crossvenue_pnl_events.jsonl"
        members = {name: name for name in MANAGED_MEMBERS if name != omitted}
        root, archive = self._fixture(members)
        target = root / omitted
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("old generation")
        report = verify_restored_inventory(archive, root)
        self.assertEqual("INVALID", report["status"])
        self.assertIn(omitted, report["stale_managed_members"])

    def test_missing_extracted_member_fails(self):
        members = {name: name for name in MANAGED_MEMBERS}
        root, archive = self._fixture(members)
        missing = "reports/crossvenue_chain.json"
        (root / missing).unlink()
        report = verify_restored_inventory(archive, root)
        self.assertIn(missing, report["missing_restored_members"])

    def test_post_restore_mutation_fails(self):
        members = {name: name for name in MANAGED_MEMBERS}
        root, archive = self._fixture(members)
        altered = "data/crossvenue_snapshots.jsonl"
        (root / altered).write_text("altered")
        report = verify_restored_inventory(archive, root)
        self.assertIn(altered, report["digest_mismatches"])


if __name__ == "__main__":
    unittest.main()
