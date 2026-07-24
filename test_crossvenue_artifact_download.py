import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crossvenue_artifact import download
from crossvenue_artifact_binding import verify


class FakeResponse(io.BytesIO):
    def __init__(self, payload, declared=None):
        super().__init__(payload)
        self.headers = {}
        if declared is not None:
            self.headers["Content-Length"] = str(declared)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ArtifactDownloadBindingTest(unittest.TestCase):
    def test_atomic_download_records_exact_identity(self):
        payload = b"prospective-artifact"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "series.zip"
            with patch("urllib.request.urlopen", return_value=FakeResponse(payload, len(payload))):
                identity = download("https://example.invalid/artifact", "token", target)
            self.assertEqual(payload, target.read_bytes())
            self.assertEqual(hashlib.sha256(payload).hexdigest(), identity["archive_sha256"])
            self.assertEqual(len(payload), identity["archive_bytes"])
            self.assertEqual([], list(target.parent.glob(f".{target.name}.*.tmp")))

    def test_oversized_download_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "series.zip"
            target.write_bytes(b"old")
            with patch("urllib.request.urlopen", return_value=FakeResponse(b"12345")):
                with self.assertRaisesRegex(ValueError, "artifact_download_too_large"):
                    download("https://example.invalid/artifact", "token", target, max_bytes=4)
            self.assertEqual(b"old", target.read_bytes())
            self.assertEqual([], list(target.parent.glob(f".{target.name}.*.tmp")))

    def test_declared_oversize_fails_before_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "series.zip"
            target.write_bytes(b"old")
            with patch("urllib.request.urlopen", return_value=FakeResponse(b"x", declared=100)):
                with self.assertRaisesRegex(ValueError, "artifact_content_length_too_large"):
                    download("https://example.invalid/artifact", "token", target, max_bytes=10)
            self.assertEqual(b"old", target.read_bytes())

    def test_binding_rejects_changed_or_truncated_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "series.zip"
            archive.write_bytes(b"exact")
            restoration = {
                "status": "downloaded", "schema_version": 2,
                "archive_sha256": hashlib.sha256(b"exact").hexdigest(),
                "archive_bytes": 5, "artifact_id": 7, "workflow_run_id": 8,
                "created_at": "2026-07-24T20:00:00Z", "branch": "main",
                "workflow_path": ".github/workflows/crossvenue-probe.yml",
            }
            self.assertEqual("VALID", verify(archive, restoration)["status"])
            archive.write_bytes(b"changed")
            report = verify(archive, restoration)
            self.assertEqual("INVALID", report["status"])
            self.assertIn("archive_sha256_mismatch", report["blockers"])
            self.assertIn("archive_size_mismatch", report["blockers"])

    def test_binding_requires_complete_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "series.zip"
            archive.write_bytes(b"x")
            restoration = {
                "status": "downloaded", "schema_version": 2,
                "archive_sha256": hashlib.sha256(b"x").hexdigest(), "archive_bytes": 1,
            }
            report = verify(archive, restoration)
            self.assertEqual("INVALID", report["status"])
            self.assertIn("missing_restoration_artifact_id", report["blockers"])
            self.assertIn("missing_restoration_workflow_run_id", report["blockers"])


if __name__ == "__main__":
    unittest.main()
