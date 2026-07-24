import hashlib
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from crossvenue_bundle import extract_bundle, inspect_bundle


class BundleTests(unittest.TestCase):
    def make_zip(self, root: Path, entries: list[tuple[object, bytes]]) -> Path:
        path = root / "bundle.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries:
                archive.writestr(name, payload)
        return path

    def test_valid_bundle_is_atomically_extracted_and_content_bound(self):
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
            self.assertEqual(report["schema_version"], 2)
            self.assertEqual(report["member_count"], 2)
            self.assertEqual(report["extraction"], "atomic_member_replace")
            self.assertEqual(
                report["members"]["data/crossvenue_snapshots.jsonl"]["sha256"],
                hashlib.sha256(snapshots).hexdigest(),
            )
            self.assertEqual((out / "data/crossvenue_snapshots.jsonl").read_bytes(), snapshots)
            self.assertEqual((out / "data/crossvenue_snapshots.jsonl").stat().st_mode & 0o777, 0o600)
            self.assertFalse(list((out / "data").glob(".crossvenue_snapshots.jsonl.*")))

    def test_existing_target_is_replaced_only_after_complete_member_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self.make_zip(root, [("data/value", b"new")])
            out = root / "out"
            target = out / "data/value"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"old")
            report = extract_bundle(bundle, out, {"data/value"})
            self.assertEqual(report["status"], "VALID")
            self.assertEqual(target.read_bytes(), b"new")

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
