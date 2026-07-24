import hashlib
import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from crossvenue_bundle import (
    BACKUP_PREFIX,
    JOURNAL_NAME,
    extract_bundle,
    inspect_bundle,
    recover_interrupted_restores,
)


class BundleTests(unittest.TestCase):
    def make_zip(self, root: Path, entries: list[tuple[object, bytes]]) -> Path:
        path = root / "bundle.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries:
                archive.writestr(name, payload)
        return path

    def test_valid_bundle_is_crash_recoverable_and_content_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = b"{}\n"
            chain = b'{"valid":true}\n'
            bundle = self.make_zip(root, [
                ("data/crossvenue_snapshots.jsonl", snapshots),
                ("reports/crossvenue_chain.json", chain),
            ])
            out = root / "out"
            report = extract_bundle(bundle, out, {"data/crossvenue_snapshots.jsonl"})
            self.assertEqual(report["status"], "VALID")
            self.assertEqual(report["schema_version"], 4)
            self.assertEqual(report["member_count"], 2)
            self.assertEqual(report["extraction"], "crash_recoverable_transactional_bundle_replace")
            self.assertEqual(report["destination_path_policy"], "no_symlink_or_special_file_components")
            self.assertEqual(report["recovered_interrupted_transactions"], 0)
            self.assertEqual(
                report["members"]["data/crossvenue_snapshots.jsonl"]["sha256"],
                hashlib.sha256(snapshots).hexdigest(),
            )
            self.assertEqual((out / "data/crossvenue_snapshots.jsonl").read_bytes(), snapshots)
            self.assertEqual((out / "data/crossvenue_snapshots.jsonl").stat().st_mode & 0o777, 0o600)
            self.assertFalse(list(out.glob(".crossvenue-restore-*")))

    def test_existing_targets_are_replaced_after_all_members_are_staged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self.make_zip(root, [("data/one", b"new1"), ("reports/two", b"new2")])
            out = root / "out"
            first = out / "data/one"
            second = out / "reports/two"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(b"old1")
            second.write_bytes(b"old2")
            extract_bundle(bundle, out, {"data/one", "reports/two"})
            self.assertEqual(first.read_bytes(), b"new1")
            self.assertEqual(second.read_bytes(), b"new2")

    def test_commit_failure_rolls_back_every_previously_replaced_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self.make_zip(root, [("data/one", b"new1"), ("reports/two", b"new2")])
            out = root / "out"
            first = out / "data/one"
            second = out / "reports/two"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(b"old1")
            second.write_bytes(b"old2")
            real_replace = os.replace

            def fail_second_stage(src, dst):
                src_path = Path(src)
                dst_path = Path(dst)
                if ".crossvenue-restore-stage." in str(src_path) and dst_path == second:
                    raise OSError("injected_commit_failure")
                return real_replace(src, dst)

            with mock.patch("crossvenue_bundle.os.replace", side_effect=fail_second_stage):
                with self.assertRaisesRegex(OSError, "injected_commit_failure"):
                    extract_bundle(bundle, out, {"data/one", "reports/two"})

            self.assertEqual(first.read_bytes(), b"old1")
            self.assertEqual(second.read_bytes(), b"old2")
            self.assertFalse(list(out.glob(".crossvenue-restore-*")))

    def test_interrupted_prepared_transaction_is_recovered_before_new_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            target = out / "data/one"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"partial-new")
            backup_root = out / f"{BACKUP_PREFIX}crashed"
            backup = backup_root / "data/one"
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b"old")
            (backup_root / JOURNAL_NAME).write_text(json.dumps({
                "schema_version": 1,
                "state": "prepared",
                "entries": [{"name": "data/one", "existed": True}],
            }))
            bundle = self.make_zip(root, [("data/one", b"new")])

            report = extract_bundle(bundle, out, {"data/one"})

            self.assertEqual(report["recovered_interrupted_transactions"], 1)
            self.assertEqual(target.read_bytes(), b"new")
            self.assertFalse(backup_root.exists())

    def test_interrupted_transaction_removes_new_partial_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            target = out / "reports/new"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"partial")
            backup_root = out / f"{BACKUP_PREFIX}crashed"
            backup_root.mkdir()
            (backup_root / JOURNAL_NAME).write_text(json.dumps({
                "schema_version": 1,
                "state": "prepared",
                "entries": [{"name": "reports/new", "existed": False}],
            }))

            self.assertEqual(recover_interrupted_restores(out), 1)
            self.assertFalse(target.exists())
            self.assertFalse(backup_root.exists())

    def test_committed_transaction_cleanup_keeps_new_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            target = out / "data/one"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"new")
            backup_root = out / f"{BACKUP_PREFIX}committed"
            backup = backup_root / "data/one"
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b"old")
            (backup_root / JOURNAL_NAME).write_text(json.dumps({
                "schema_version": 1,
                "state": "committed",
                "entries": [{"name": "data/one", "existed": True}],
            }))

            self.assertEqual(recover_interrupted_restores(out), 1)
            self.assertEqual(target.read_bytes(), b"new")
            self.assertFalse(backup_root.exists())

    def test_malformed_recovery_journal_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            backup_root = out / f"{BACKUP_PREFIX}broken"
            backup_root.mkdir(parents=True)
            (backup_root / JOURNAL_NAME).write_text("not-json")
            with self.assertRaisesRegex(RuntimeError, "unrecoverable_restore_journal"):
                recover_interrupted_restores(out)
            self.assertTrue(backup_root.exists())

    def test_path_traversal_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self.make_zip(root, [("../escape", b"bad")])
            with self.assertRaisesRegex(ValueError, "unsafe_member"):
                extract_bundle(bundle, root / "out", set())
            self.assertFalse((root / "escape").exists())

    def test_unexpected_root_and_missing_required_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self.make_zip(root, [("other/file", b"bad")])
            with self.assertRaisesRegex(ValueError, "unexpected_root"):
                inspect_bundle(bundle, set())
            bundle = self.make_zip(root, [("data/one", b"ok")])
            with self.assertRaisesRegex(ValueError, "missing_required"):
                inspect_bundle(bundle, {"data/two"})

    def test_duplicate_normalized_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self.make_zip(root, [("data/x", b"a"), ("data/./x", b"b")])
            with self.assertRaisesRegex(ValueError, "duplicate_member"):
                inspect_bundle(bundle, set())

    def test_symlink_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "bundle.zip"
            info = zipfile.ZipInfo("data/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(info, "target")
            with self.assertRaisesRegex(ValueError, "symlink_member"):
                inspect_bundle(path, set())

    def test_symlink_destination_root_is_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            out = root / "out"
            out.symlink_to(outside, target_is_directory=True)
            bundle = self.make_zip(root, [("data/one", b"new")])

            with self.assertRaisesRegex(RuntimeError, "symlink_restore_destination"):
                extract_bundle(bundle, out, {"data/one"})

            self.assertFalse(list(outside.glob(".crossvenue-restore-*")))
            self.assertFalse((outside / "data/one").exists())

    def test_symlink_destination_parent_is_rejected_without_external_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            out = root / "out"
            out.mkdir()
            (out / "data").symlink_to(outside, target_is_directory=True)
            bundle = self.make_zip(root, [("data/one", b"new")])

            with self.assertRaisesRegex(RuntimeError, "symlink_destination_parent"):
                extract_bundle(bundle, out, {"data/one"})

            self.assertFalse((outside / "one").exists())
            self.assertFalse(list(out.glob(".crossvenue-restore-*")))

    def test_symlink_destination_target_is_rejected_without_touching_link_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.write_bytes(b"old")
            out = root / "out"
            target = out / "data/one"
            target.parent.mkdir(parents=True)
            target.symlink_to(outside)
            bundle = self.make_zip(root, [("data/one", b"new")])

            with self.assertRaisesRegex(RuntimeError, "symlink_destination_target"):
                extract_bundle(bundle, out, {"data/one"})

            self.assertEqual(outside.read_bytes(), b"old")
            self.assertTrue(target.is_symlink())

    def test_non_directory_parent_and_special_target_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            (out / "data").write_bytes(b"not-a-directory")
            bundle = self.make_zip(root, [("data/one", b"new")])
            with self.assertRaisesRegex(RuntimeError, "non_directory_destination_parent"):
                extract_bundle(bundle, out, {"data/one"})

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                out = root / "out"
                target = out / "data/one"
                target.parent.mkdir(parents=True)
                os.mkfifo(target)
                bundle = self.make_zip(root, [("data/one", b"new")])
                with self.assertRaisesRegex(RuntimeError, "non_regular_destination_target"):
                    extract_bundle(bundle, out, {"data/one"})

    def test_recovery_fails_closed_if_destination_path_became_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (out / "data").symlink_to(outside, target_is_directory=True)
            backup_root = out / f"{BACKUP_PREFIX}crashed"
            backup = backup_root / "data/one"
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b"old")
            (backup_root / JOURNAL_NAME).write_text(json.dumps({
                "schema_version": 1,
                "state": "prepared",
                "entries": [{"name": "data/one", "existed": True}],
            }))

            with self.assertRaisesRegex(RuntimeError, "symlink_destination_parent"):
                recover_interrupted_restores(out)

            self.assertTrue(backup_root.exists())
            self.assertFalse((outside / "one").exists())


if __name__ == "__main__":
    unittest.main()
