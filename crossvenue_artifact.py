#!/usr/bin/env python3
"""Small helpers for selecting and downloading GitHub Actions evidence artifacts."""
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ZIP_MEMBERS = 1_000
MAX_ZIP_COMPRESSION_RATIO = 200.0
SENSITIVE_REDIRECT_HEADERS = {"authorization", "x-github-api-version"}


class SafeArtifactRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme.lower() != "https" or not target.hostname:
            raise urllib.error.HTTPError(newurl, code, "unsafe_artifact_redirect", headers, fp)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        source = urllib.parse.urlsplit(req.full_url)
        if (source.scheme.lower(), source.hostname, source.port) != (
            target.scheme.lower(), target.hostname, target.port
        ):
            for header in list(redirected.headers):
                if header.lower() in SENSITIVE_REDIRECT_HEADERS:
                    redirected.remove_header(header)
        return redirected


def request_json(url, token):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "crossvenue-artifact-restorer",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def inspect_zip(path, max_uncompressed_bytes=MAX_ZIP_UNCOMPRESSED_BYTES,
                max_members=MAX_ZIP_MEMBERS,
                max_compression_ratio=MAX_ZIP_COMPRESSION_RATIO):
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if not members:
                raise ValueError("artifact_zip_has_no_members")
            if len(members) > max_members:
                raise ValueError("artifact_zip_too_many_members")
            total = 0
            for member in members:
                if member.flag_bits & 0x1:
                    raise ValueError(f"artifact_zip_encrypted_member:{member.filename}")
                total += member.file_size
                if total > max_uncompressed_bytes:
                    raise ValueError("artifact_zip_uncompressed_too_large")
                if member.file_size:
                    ratio = member.file_size / max(member.compress_size, 1)
                    if ratio > max_compression_ratio:
                        raise ValueError(f"artifact_zip_extreme_compression:{member.filename}")
            corrupt = archive.testzip()
            if corrupt is not None:
                raise ValueError(f"artifact_zip_crc_failure:{corrupt}")
            return {
                "zip_member_count": len(members),
                "zip_uncompressed_bytes": total,
                "zip_crc_verified": True,
            }
    except zipfile.BadZipFile as exc:
        raise ValueError("artifact_not_valid_zip") from exc


def download(url, token, path, max_bytes=MAX_ARCHIVE_BYTES, opener=None):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "crossvenue-artifact-restorer",
    })
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    size = 0
    safe_opener = opener or urllib.request.build_opener(SafeArtifactRedirectHandler())
    try:
        with os.fdopen(descriptor, "wb") as output:
            with safe_opener.open(request, timeout=60) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and int(declared) > max_bytes:
                    raise ValueError("artifact_content_length_too_large")
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("artifact_download_too_large")
                    digest.update(chunk)
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size == 0:
            raise ValueError("empty_artifact_download")
        zip_identity = inspect_zip(temporary)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"archive_sha256": digest.hexdigest(), "archive_bytes": size, **zip_identity}


def _write_report(path, report):
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
