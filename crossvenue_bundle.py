#!/usr/bin/env python3
"""Validate and crash-safely restore a prospective GitHub Actions artifact ZIP."""

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
BACKUP_PREFIX = ".crossvenue-restore-backup."
STAGE_PREFIX = ".crossvenue-restore-stage."
JOURNAL_NAME = "journal.json"


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


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _validate_destination_path(destination: Path, name: str) -> None:
    """Reject redirects and special files before any evidence path is mutated."""
    destination_stat = _lstat(destination)
    if destination_stat is None or not stat.S_ISDIR(destination_stat.st_mode):
        raise RuntimeError("invalid_restore_destination")
    if stat.S_ISLNK(destination_stat.st_mode):
        raise RuntimeError("symlink_restore_destination")

    relative = PurePosixPath(name)
    current = destination
    for part in relative.parts[:-1]:
        current = current / part
        current_stat = _lstat(current)
        if current_stat is None:
            continue
        if stat.S_ISLNK(current_stat.st_mode):
            raise RuntimeError(f"symlink_destination_parent:{name}")
        if not stat.S_ISDIR(current_stat.st_mode):
            raise RuntimeError(f"non_directory_destination_parent:{name}")

    target = destination / name
    target_stat = _lstat(target)
    if target_stat is None:
        return
    if stat.S_ISLNK(target_stat.st_mode):
        raise RuntimeError(f"symlink_destination_target:{name}")
    if not stat.S_ISREG(target_stat.st_mode):
        raise RuntimeError(f"non_regular_destination_target:{name}")


def _validate_destination_entries(destination: Path, names: list[str]) -> None:
    for name in names:
        _validate_destination_path(destination, name)


def _write_journal(backup_root: Path, journal: dict) -> None:
    path = backup_root / JOURNAL_NAME
    temporary = backup_root / f".{JOURNAL_NAME}.tmp"
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(journal, output, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    _fsync_directory(backup_root)


def _load_journal(backup_root: Path) -> dict:
    path = backup_root / JOURNAL_NAME
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"unrecoverable_restore_journal:{backup_root.name}:{exc}") from exc
    if journal.get("schema_version") != 1 or journal.get("state") not in {"prepared", "committed"}:
        raise RuntimeError(f"invalid_restore_journal:{backup_root.name}")
    entries = journal.get("entries")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"invalid_restore_journal_entries:{backup_root.name}")
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("existed"), bool):
            raise RuntimeError(f"invalid_restore_journal_entry:{backup_root.name}")
        entry["name"] = _safe_name(str(entry.get("name", "")))
    return journal


def _rollback_transaction(destination: Path, backup_root: Path, journal: dict) -> None:
    _validate_destination_entries(destination, [entry["name"] for entry in journal["entries"]])
    errors: list[str] = []
    for entry in reversed(journal["entries"]):
        name = entry["name"]
        target = destination / name
        backup = backup_root / name
        try:
            if entry["existed"]:
                if backup.exists():
                    if target.exists():
                        target.unlink()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, target)
                    _fsync_directory(target.parent)
            elif target.exists():
                target.unlink()
                _fsync_directory(target.parent)
        except OSError as exc:
            errors.append(f"{name}:{exc}")
    if errors:
        raise RuntimeError("restore_rollback_failed:" + "|".join(errors))
    shutil.rmtree(backup_root)
    _fsync_directory(destination)


def recover_interrupted_restores(destination: Path) -> int:
    """Recover incomplete transactions before any new artifact is inspected."""
    if not destination.exists():
        return 0
    recovered = 0
    for stage_root in sorted(destination.glob(f"{STAGE_PREFIX}*")):
        if stage_root.is_dir():
            shutil.rmtree(stage_root)
            recovered += 1
    for backup_root in sorted(destination.glob(f"{BACKUP_PREFIX}*")):
        if not backup_root.is_dir():
            continue
        journal = _load_journal(backup_root)
        if journal["state"] == "committed":
            shutil.rmtree(backup_root)
            _fsync_directory(destination)
        else:
            _rollback_transaction(destination, backup_root, journal)
        recovered += 1
    return recovered


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
        "schema_version": 4,
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
    _validate_destination_entries(destination, names)
    backup_root = Path(tempfile.mkdtemp(prefix=BACKUP_PREFIX, dir=destination))
    journal = {
        "schema_version": 1,
        "state": "prepared",
        "entries": [
            {"name": name, "existed": (destination / name).exists()}
            for name in names
        ],
    }
    _write_journal(backup_root, journal)
    try:
        for entry in journal["entries"]:
            name = entry["name"]
            target = destination / name
            staged = stage_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = backup_root / name
            if entry["existed"]:
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
                _fsync_directory(target.parent)
            os.replace(staged, target)
            _fsync_directory(target.parent)
        journal["state"] = "committed"
        _write_journal(backup_root, journal)
    except Exception:
        _rollback_transaction(destination, backup_root, journal)
        raise
    shutil.rmtree(backup_root)
    _fsync_directory(destination)


def extract_bundle(zip_path: Path, destination: Path, required: set[str]) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    recovered = recover_interrupted_restores(destination)
    raw = _read_bundle(zip_path)
    stage_root = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=destination))
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            report, files = _inspect_archive(archive, required)
            names = _stage_members(archive, files, stage_root, report)
        _commit_staged_members(stage_root, destination, names)
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    report["zip_sha256"] = hashlib.sha256(raw).hexdigest()
    report["extraction"] = "crash_recoverable_transactional_bundle_replace"
    report["destination_path_policy"] = "no_symlink_or_special_file_components"
    report["recovered_interrupted_transactions"] = recovered
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
    except (OSError, RuntimeError, zipfile.BadZipFile, ValueError) as exc:
        report = {"status": "INVALID", "schema_version": 4, "error": str(exc)}
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
