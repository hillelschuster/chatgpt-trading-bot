#!/usr/bin/env python3
"""Safely restore a prospective GitHub Actions artifact ZIP."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_MEMBERS = 1_000
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


def restore(zip_path: Path, destination: Path, required: set[str]) -> dict:
    if zip_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("compressed_bundle_too_large")
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or not destination.is_dir():
        raise ValueError("invalid_destination")

    zip_digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    members: dict[str, dict] = {}
    files: list[tuple[zipfile.ZipInfo, str]] = []
    total = 0

    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_MEMBERS:
                raise ValueError("invalid_member_count")
            for info in infos:
                name = _safe_name(info.filename)
                if name in members:
                    raise ValueError(f"duplicate_member:{name}")
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or info.flag_bits & 0x1:
                    raise ValueError(f"unsupported_member:{name}")
                if info.is_dir():
                    continue
                total += info.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("bundle_too_large")
                ratio = info.file_size / max(info.compress_size, 1)
                if ratio > MAX_COMPRESSION_RATIO:
                    raise ValueError(f"compression_ratio_exceeded:{name}")
                members[name] = {
                    "size": info.file_size,
                    "compressed_size": info.compress_size,
                    "crc32": f"{info.CRC:08x}",
                }
                files.append((info, name))

            missing = sorted(required - set(members))
            if missing:
                raise ValueError("missing_required:" + ",".join(missing))

            with tempfile.TemporaryDirectory(prefix="crossvenue-restore-") as tmp:
                stage = Path(tmp)
                for info, name in files:
                    staged = stage / name
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    written = 0
                    with archive.open(info) as source, staged.open("wb") as output:
                        while chunk := source.read(1024 * 1024):
                            output.write(chunk)
                            digest.update(chunk)
                            written += len(chunk)
                    if written != info.file_size:
                        raise ValueError(f"size_mismatch:{name}")
                    members[name]["sha256"] = digest.hexdigest()

                for _, name in files:
                    target = destination / name
                    if target.exists() and (target.is_symlink() or not target.is_file()):
                        raise ValueError(f"unsafe_target:{name}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(stage / name, target)
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid_zip") from exc

    return {
        "status": "VALID",
        "schema_version": 1,
        "extraction": "staged_atomic_file_replace",
        "zip_sha256": zip_digest,
        "member_count": len(members),
        "total_uncompressed_bytes": total,
        "members": dict(sorted(members.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("--destination", default=".")
    parser.add_argument("--report")
    parser.add_argument("--required-member", action="append", default=[])
    args = parser.parse_args()
    report = restore(Path(args.archive), Path(args.destination), set(args.required_member))
    if args.report:
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
