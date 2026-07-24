#!/usr/bin/env python3
"""Validate and securely extract a prospective GitHub Actions artifact ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path, PurePosixPath

MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200.0
ALLOWED_ROOTS = {"data", "reports"}


def _safe_name(raw: str) -> str:
    name = raw.replace("\\", "/")
    path = PurePosixPath(name)
    if not name or name.startswith("/") or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe_member:{raw}")
    if not path.parts or path.parts[0] not in ALLOWED_ROOTS:
        raise ValueError(f"unexpected_root:{raw}")
    return str(path)


def inspect_bundle(zip_path: Path, required: set[str]) -> dict:
    raw = zip_path.read_bytes()
    members: dict[str, dict] = {}
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = _safe_name(info.filename)
            if name in members:
                raise ValueError(f"duplicate_member:{name}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"symlink_member:{name}")
            if info.is_dir():
                continue
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("bundle_too_large")
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_COMPRESSION_RATIO:
                raise ValueError(f"compression_ratio_exceeded:{name}")
            members[name] = {
                "size": info.file_size,
                "compressed_size": info.compress_size,
                "crc32": f"{info.CRC:08x}",
            }
    missing = sorted(required - set(members))
    if missing:
        raise ValueError("missing_required:" + ",".join(missing))
    return {
        "status": "VALID",
        "schema_version": 1,
        "zip_sha256": hashlib.sha256(raw).hexdigest(),
        "member_count": len(members),
        "total_uncompressed_bytes": total,
        "members": dict(sorted(members.items())),
    }


def extract_bundle(zip_path: Path, destination: Path, required: set[str]) -> dict:
    report = inspect_bundle(zip_path, required)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = _safe_name(info.filename)
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
            os.chmod(target, 0o600)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--destination", type=Path, default=Path("."))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--required-member", action="append", default=[])
    args = parser.parse_args()
    required = {_safe_name(name) for name in args.required_member}
    try:
        report = extract_bundle(args.zip_path, args.destination, required)
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        report = {"status": "INVALID", "schema_version": 1, "error": str(exc)}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        return 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
