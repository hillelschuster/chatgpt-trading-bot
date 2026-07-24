import hashlib
import io
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from crossvenue_artifact import SafeArtifactRedirectHandler, download
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


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.request = None

    def open(self, request, timeout=None):
        self.request = request
        return self.response


def zip_payload(files=None):
    if files is None:
        files = {"data/crossvenue_snapshots.jsonl": b"{}\n"}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return output.getvalue()


class ArtifactDownloadBindingTest(unittest.TestCase):
    def test_atomic_download_records_exact_zip_identity(self):
        payload = zip_payload({"data/a": b"abc", "reports/b": b"12345"})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "series.zip"
            opener = FakeOpener(FakeResponse(payload, len(payload)))
            identity = download("https://api.github.com/artifact", "token", target, opener=opener)
            self.assertEqual(payload, target.read_bytes())
            self.assertEqual(hashlib.sha256(payload).hexdigest(), identity["archive_sha256"])
            self.assertEqual(len(payload), identity["archive_bytes"])
            self.assertEqual(2, identity["zip_member_count"])
            self.assertEqual(8, identity["zip_uncompressed_bytes"])
            self.assertIs(identity["zip_crc_verified"], True)
            self.assertEqual("https_cross_origin_credentials_stripped", identity["redirect_policy"])
            self.assertEqual("Bearer token", opener.request.get_header("Authorization"))
            self.assertEqual([], list(target.parent.glob(f".{target.name}.*.tmp")))

    def test_cross_origin_redirect_strips_credentials(self):
        request = urllib.request.Request("https://api.github.com/repos/x/actions/artifacts/1/zip", headers={
            "Authorization": "Bearer secret",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "test",
        })
        redirected = SafeArtifactRedirectHandler().redirect_request(
            request, None, 302, "Found", {}, "https://objects.githubusercontent.com/signed.zip"
        )
        self.assertIsNone(redirected.get_header("Authorization"))
        self.assertIsNone(redirected.get_header("X-Github-Api-Version"))

    def test_same_origin_redirect_preserves_credentials(self):
        request = urllib.request.Request("https://api.github.com/a", headers={
            "Authorization": "Bearer secret",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        redirected = SafeArtifactRedirectHandler().redirect_request(
            request, None, 302, "Found", {}, "https://api.github.com/b"
        )
        self.assertEqual("Bearer secret", redirected.get_header("Authorization"))

    def test_non_https_redirect_is_rejected(self):
        request = urllib.request.Request("https://api.github.com/a")
        with self.assertRaisesRegex(urllib.error.HTTPError, "unsafe_artifact_redirect"):
            SafeArtifactRedirectHandler().redirect_request(
                request, None, 302, "Found", {}, "http://example.com/file.zip"
            )

    def test_oversized_download_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "series.zip"
            target.write_bytes(b"old")
            opener = FakeOpener(FakeResponse(b"12345"))
            with self.assertRaisesRegex(ValueError, "artifact_download_too_large"):
                download("https://api.github.com/artifact", "token", target, max_bytes=4, opener=opener)
            self.assertEqual(b"old", target.read_bytes())
            self.assertEqual([], list(target.parent.glob(f".{target.name}.*.tmp")))

    def test_declared_oversize_fails_before_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "series.zip"
            target.write_bytes(b"old")
            opener = FakeOpener(FakeResponse(b"x", declared=100))
            with self.assertRaisesRegex(ValueError, "artifact_content_length_too_large"):
                download("https://api.github.com/artifact", "token", target, max_bytes=10, opener=opener)
            self.assertEqual(b"old", target.read_bytes())

    def test_invalid_or_empty_zip_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "series.zip"
            target.write_bytes(b"old")
            for payload, error in ((b"not-a-zip", "artifact_not_valid_zip"),
                                   (zip_payload({}), "artifact_zip_has_no_members")):
                with self.subTest(error=error):
                    opener = FakeOpener(FakeResponse(payload, len(payload)))
                    with self.assertRaisesRegex(ValueError, error):
                        download("https://api.github.com/artifact", "token", target, opener=opener)
                    self.assertEqual(b"old", target.read_bytes())
                    self.assertEqual([], list(target.parent.glob(f".{target.name}.*.tmp")))

    def test_binding_rejects_changed_or_unverified_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "series.zip"
            payload = zip_payload()
            archive.write_bytes(payload)
            restoration = {
                "status": "downloaded", "schema_version": 4,
                "archive_sha256": hashlib.sha256(payload).hexdigest(),
                "archive_bytes": len(payload), "artifact_id": 7, "workflow_run_id": 8,
                "created_at": "2026-07-24T20:00:00Z", "branch": "main",
                "workflow_path": ".github/workflows/crossvenue-probe.yml",
                "redirect_policy": "https_cross_origin_credentials_stripped",
                "zip_member_count": 1, "zip_uncompressed_bytes": 3,
                "zip_crc_verified": True,
            }
            self.assertEqual("VALID", verify(archive, restoration)["status"])
            restoration["zip_member_count"] = 2
            report = verify(archive, restoration)
            self.assertEqual("INVALID", report["status"])
            self.assertIn("archive_zip_member_count_mismatch", report["blockers"])
            archive.write_bytes(b"changed")
            report = verify(archive, restoration)
            self.assertEqual("INVALID", report["status"])
            self.assertIn("archive_sha256_mismatch", report["blockers"])
            self.assertIn("archive_size_mismatch", report["blockers"])
            self.assertIn("artifact_not_valid_zip", report["blockers"])

    def test_binding_requires_complete_and_safe_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "series.zip"
            payload = zip_payload()
            archive.write_bytes(payload)
            restoration = {
                "status": "downloaded", "schema_version": 4,
                "archive_sha256": hashlib.sha256(payload).hexdigest(),
                "archive_bytes": len(payload),
                "zip_member_count": 1, "zip_uncompressed_bytes": 3,
                "zip_crc_verified": True,
            }
            report = verify(archive, restoration)
            self.assertEqual("INVALID", report["status"])
            self.assertIn("unsafe_or_missing_redirect_policy", report["blockers"])
            self.assertIn("missing_restoration_artifact_id", report["blockers"])
            self.assertIn("missing_restoration_workflow_run_id", report["blockers"])


if __name__ == "__main__":
    unittest.main()
