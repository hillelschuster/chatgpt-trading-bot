import hashlib
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from crossvenue_bundle import extract_bundle, inspect_bundle


class BundleTests(unittest.TestCase):
    def make_zip(self, root: Path, entries: list[tuple[object, bytes]]) -> Path:
        path = root / "bundle.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries:
                archive.writestr(name, payload)
        return path

    def test_valid_bundle_is_transactionally_extracted_and_content_bound(self):
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
            self.assertEqual(report["schema_version"], 3)
            self.assertEqual(report["member_count"], 2)
            self.assertEqual(report["extraction"], "transactional_bundle_replace")
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
            report = extract_bundle(bundle, out, {"data/one", "reports/two"})
            self.assertEqual(report["status"], "VALID")
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

    def test_commit_failure_removes_new_targets_created_before_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self.make_zip(root, [("data/one", b"new1"), ("reports/two", b"new2")])
            out = root / "out"
            second = out / "reports/two"
            real_replace = os.replace

            def fail_second_stage(src, dst):
                src_path = Path(src)
                dst_path = Path(dst)
                if ".crossvenue-restore-stage." in str(src_path) and dst_path == second:
                    raise OSError("injected_commit_failure")
                return real_replace(src, dst)

            with mock.patch("crossvenue_bundle.os.replace", side_effect=fail_second_stage):
                with self.assertRaisesRegex(OSError, "injected_commit_failure"):
                    extract_bundle(bundle, out, set())

            self.assertFalse((out / "data/one").exists())
            self.assertFalse(second.exists())
            self.assertFalse(list(out.glob(".crossvenue-restore-*")))

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


if __name__ == "__main__":
    unittest.main()
