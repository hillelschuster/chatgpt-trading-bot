import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from crossvenue_bundle import restore


class BundleTest(unittest.TestCase):
    def make_zip(self, root: Path, entries: dict[str, bytes]) -> Path:
        path = root / "series.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        return path

    def required_entries(self):
        return {
            "data/crossvenue_experiment_freeze.json": b"{}\n",
            "data/crossvenue_snapshots.jsonl": b'{"coin":"BTC"}\n',
            "reports/crossvenue_chain.json": b'{"valid":true}\n',
        }

    def test_restores_required_files_and_hashes_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self.required_entries()
            archive = self.make_zip(root, entries)
            destination = root / "repo"
            report = restore(archive, destination, set(entries))
            self.assertEqual("VALID", report["status"])
            self.assertEqual("staged_atomic_file_replace", report["extraction"])
            for name, content in entries.items():
                self.assertEqual(content, (destination / name).read_bytes())
                self.assertEqual(64, len(report["members"][name]["sha256"]))

    def test_rejects_traversal_and_unexpected_roots(self):
        for name in ("../escape", "/absolute", "src/code.py"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                archive = self.make_zip(root, {name: b"x"})
                with self.assertRaises(ValueError):
                    restore(archive, root / "repo", set())

    def test_rejects_missing_required_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = self.make_zip(root, {"data/crossvenue_snapshots.jsonl": b""})
            with self.assertRaisesRegex(ValueError, "missing_required"):
                restore(archive, root / "repo", {"reports/crossvenue_chain.json"})

    def test_rejects_symlink_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "series.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                info = zipfile.ZipInfo("data/link")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "target")
            with self.assertRaisesRegex(ValueError, "unsupported_member"):
                restore(archive_path, root / "repo", set())

    def test_validation_finishes_before_existing_files_are_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "repo"
            target = destination / "data/crossvenue_snapshots.jsonl"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"old\n")
            archive = self.make_zip(root, {
                "data/crossvenue_snapshots.jsonl": b"new\n",
                "data/duplicate": b"x",
            })
            with self.assertRaises(ValueError):
                restore(archive, destination, {"reports/missing.json"})
            self.assertEqual(b"old\n", target.read_bytes())


if __name__ == "__main__":
    unittest.main()
