import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from crossvenue_bundle import BACKUP_PREFIX, JOURNAL_NAME, recover_interrupted_restores


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class ContentBoundJournalTests(unittest.TestCase):
    def write_journal(self, out: Path, state: str, entries: list[dict]) -> Path:
        backup_root = out / f"{BACKUP_PREFIX}test"
        backup_root.mkdir(parents=True)
        (backup_root / JOURNAL_NAME).write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "state": state,
                    "entries": entries,
                }
            )
        )
        return backup_root

    def test_prepared_transaction_restores_verified_old_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            target = out / "data/one"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"new")
            backup_root = self.write_journal(
                out,
                "prepared",
                [
                    {
                        "name": "data/one",
                        "existed": True,
                        "old_sha256": digest(b"old"),
                        "new_sha256": digest(b"new"),
                    }
                ],
            )
            backup = backup_root / "data/one"
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b"old")

            self.assertEqual(recover_interrupted_restores(out), 1)
            self.assertEqual(target.read_bytes(), b"old")
            self.assertFalse(backup_root.exists())

    def test_prepared_transaction_rejects_tampered_backup_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            target = out / "data/one"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"new")
            backup_root = self.write_journal(
                out,
                "prepared",
                [
                    {
                        "name": "data/one",
                        "existed": True,
                        "old_sha256": digest(b"old"),
                        "new_sha256": digest(b"new"),
                    }
                ],
            )
            backup = backup_root / "data/one"
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b"tampered")

            with self.assertRaisesRegex(RuntimeError, "restore_backup_digest_mismatch"):
                recover_interrupted_restores(out)
            self.assertEqual(target.read_bytes(), b"new")
            self.assertEqual(backup.read_bytes(), b"tampered")

    def test_prepared_new_target_rejects_unrecognized_bytes_before_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            target = out / "reports/new"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"unrelated")
            backup_root = self.write_journal(
                out,
                "prepared",
                [
                    {
                        "name": "reports/new",
                        "existed": False,
                        "old_sha256": None,
                        "new_sha256": digest(b"expected-new"),
                    }
                ],
            )

            with self.assertRaisesRegex(RuntimeError, "restore_new_target_digest_mismatch"):
                recover_interrupted_restores(out)
            self.assertEqual(target.read_bytes(), b"unrelated")
            self.assertTrue(backup_root.exists())

    def test_committed_transaction_requires_verified_new_and_backup_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            target = out / "data/one"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"wrong-new")
            backup_root = self.write_journal(
                out,
                "committed",
                [
                    {
                        "name": "data/one",
                        "existed": True,
                        "old_sha256": digest(b"old"),
                        "new_sha256": digest(b"new"),
                    }
                ],
            )
            backup = backup_root / "data/one"
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b"old")

            with self.assertRaisesRegex(RuntimeError, "committed_restore_target_mismatch"):
                recover_interrupted_restores(out)
            self.assertEqual(target.read_bytes(), b"wrong-new")
            self.assertTrue(backup_root.exists())

    def test_duplicate_journal_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            entry = {
                "name": "data/one",
                "existed": False,
                "old_sha256": None,
                "new_sha256": digest(b"new"),
            }
            self.write_journal(out, "prepared", [entry, dict(entry)])
            with self.assertRaisesRegex(RuntimeError, "duplicate_restore_journal_entry"):
                recover_interrupted_restores(out)


if __name__ == "__main__":
    unittest.main()
