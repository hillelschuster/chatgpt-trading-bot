#!/usr/bin/env python3
"""Validate and securely extract a prospective GitHub Actions artifact ZIP."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import stat
import tempfile
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


def _read_bundle(zip_path: Path) -> bytes:
    raw = zip_path.read_bytes()
    if len(raw) > MAX_TOTAL_BYTES:
        raise ValueError("compressed_bundle_too_large")
    return raw


def _inspect_archive(archive: zipfile.ZipFile, required: set[str]) -> tuple[dict, list[zipfile.ZipInfo]]:
    members: dict[str, dict] = {}
    files: list[zipfile.ZipInfo] = []
    total = 0
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
        files.append(info)
    missing = sorted(required - set(members))
    if missing:
        raise ValueError("missing_required:" + ",".join(missing))
    return {
        "status": "VALID",
        "schema_version": 3,
        "member_count": len(members),
        "total_uncompressed_bytes": total,
        "members": dict(sorted(members.items())),
    }, files


def inspect_bundle(zip_path: Path, required: set[str]) -> dict:
    raw = _read_bundle(zip_path)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        report, _ = _inspect_archive(archive, required)
    report["zip_sha256"] = hashlib.sha256(raw).hexdigest()
    return report


def _stage_members(
    archive: zipfile.ZipFile,
    files: list[zipfile.ZipInfo],
    stage_root: Path,
    report: dict,
) -> list[str]:
    names: list[str] = []
    for info in files:
        name = _safe_name(info.filename)
        staged = stage_root / name
        staged.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        written = 0
        with staged.open("wb") as output, archive.open(info) as source:
            while chunk := source.read(1024 * 1024):
                written += len(chunk)
                if written > info.file_size:
                    raise ValueError(f"member_size_exceeded:{name}")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if written != info.file_size:
            raise ValueError(f"member_size_mismatch:{name}")
        os.chmod(staged, 0o600)
        report["members"][name]["sha256"] = digest.hexdigest()
        names.append(name)
    return names


def _commit_staged_members(stage_root: Path, destination: Path, names: list[str]) -> None:
    backup_root = Path(tempfile.mkdtemp(prefix=".crossvenue-restore-backup.", dir=destination))
    replaced: list[tuple[Path, Path | None]] = []
    try:
        for name in names:
            target = destination / name
            staged = stage_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            backup: Path | None = None
            if target.exists():
                backup = backup_root / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
            try:
                os.replace(staged, target)
            except Exception:
                if backup is not None:
                    os.replace(backup, target)
                raise
            replaced.append((target, backup))
    except Exception:
        for target, backup in reversed(replaced):
            try:
                if target.exists():
                    target.unlink()
                if backup is not None and backup.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, target)
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(backup_root, ignore_errors=True)


def extract_bundle(zip_path: Path, destination: Path, required: set[str]) -> dict:
    raw = _read_bundle(zip_path)
    destination.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=".crossvenue-restore-stage.", dir=destination))
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            report, files = _inspect_archive(archive, required)
            names = _stage_members(archive, files, stage_root, report)
        _commit_staged_members(stage_root, destination, names)
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    report["zip_sha256"] = hashlib.sha256(raw).hexdigest()
    report["extraction"] = "transactional_bundle_replace"
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
        report = {"status": "INVALID", "schema_version": 3, "error": str(exc)}
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
