import hashlib
import io
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from crossvenue_artifact import SafeArtifactRedirectHandler, download, inspect_zip


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


class ArtifactDownloadTest(unittest.TestCase):
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
            self.assertEqual("Bearer token", opener.request.get_header("Authorization"))
            self.assertEqual([], list(target.parent.glob(f".{target.name}.*.tmp")))

    def test_zip_limits_are_checked_before_crc_decompression(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "series.zip"
            archive.write_bytes(zip_payload({"data/a": b"a" * 4096, "data/b": b"b"}))
            with self.assertRaisesRegex(ValueError, "artifact_zip_uncompressed_too_large"):
                inspect_zip(archive, max_uncompressed_bytes=1024, max_compression_ratio=10_000)
            with self.assertRaisesRegex(ValueError, "artifact_zip_too_many_members"):
                inspect_zip(archive, max_members=1, max_compression_ratio=10_000)
            with self.assertRaisesRegex(ValueError, "artifact_zip_extreme_compression"):
                inspect_zip(archive, max_compression_ratio=2)

    def test_cross_origin_redirect_strips_credentials(self):
        request = urllib.request.Request("https://api.github.com/a", headers={
            "Authorization": "Bearer secret", "X-GitHub-Api-Version": "2022-11-28"
        })
        redirected = SafeArtifactRedirectHandler().redirect_request(
            request, None, 302, "Found", {}, "https://objects.githubusercontent.com/file.zip"
        )
        self.assertIsNone(redirected.get_header("Authorization"))

    def test_non_https_redirect_is_rejected(self):
        request = urllib.request.Request("https://api.github.com/a")
        with self.assertRaisesRegex(urllib.error.HTTPError, "unsafe_artifact_redirect"):
            SafeArtifactRedirectHandler().redirect_request(
                request, None, 302, "Found", {}, "http://example.com/file.zip"
            )

    def test_streamed_oversize_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "series.zip"
            target.write_bytes(b"old")
            opener = FakeOpener(FakeResponse(b"12345"))
            with self.assertRaisesRegex(ValueError, "artifact_download_too_large"):
                download("https://api.github.com/artifact", "token", target,
                         max_bytes=4, opener=opener)
            self.assertEqual(b"old", target.read_bytes())

    def test_declared_oversize_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "series.zip"
            target.write_bytes(b"old")
            opener = FakeOpener(FakeResponse(b"x", declared=100))
            with self.assertRaisesRegex(ValueError, "artifact_content_length_too_large"):
                download("https://api.github.com/artifact", "token", target,
                         max_bytes=10, opener=opener)
            self.assertEqual(b"old", target.read_bytes())

    def test_invalid_zip_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "series.zip"
            target.write_bytes(b"old")
            opener = FakeOpener(FakeResponse(b"not-a-zip", len(b"not-a-zip")))
            with self.assertRaisesRegex(ValueError, "artifact_not_valid_zip"):
                download("https://api.github.com/artifact", "token", target, opener=opener)
            self.assertEqual(b"old", target.read_bytes())


if __name__ == "__main__":
    unittest.main()
