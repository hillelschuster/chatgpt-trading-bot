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
JOURNAL_SCHEMA_VERSION = 2


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_restore_root(destination: Path) -> None:
    destination_stat = _lstat(destination)
    if destination_stat is None:
        raise RuntimeError("missing_restore_destination")
    if stat.S_ISLNK(destination_stat.st_mode):
        raise RuntimeError("symlink_restore_destination")
    if not stat.S_ISDIR(destination_stat.st_mode):
        raise RuntimeError("invalid_restore_destination")


def _validate_destination_path(destination: Path, name: str) -> None:
    """Reject redirects and special files before any evidence path is mutated."""
    _validate_restore_root(destination)
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


def _regular_digest(path: Path, label: str) -> str | None:
    path_stat = _lstat(path)
    if path_stat is None:
        return None
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise RuntimeError(f"invalid_restore_recovery_file:{label}")
    return _sha256_file(path)


def _load_journal(backup_root: Path) -> dict:
    path = backup_root / JOURNAL_NAME
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"unrecoverable_restore_journal:{backup_root.name}:{exc}") from exc
    schema_version = journal.get("schema_version")
    if schema_version not in {1, JOURNAL_SCHEMA_VERSION}:
        raise RuntimeError(f"unsupported_restore_journal_schema:{backup_root.name}")
    if journal.get("state") not in {"prepared", "committed"}:
        raise RuntimeError(f"invalid_restore_journal:{backup_root.name}")
    entries = journal.get("entries")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"invalid_restore_journal_entries:{backup_root.name}")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("existed"), bool):
            raise RuntimeError(f"invalid_restore_journal_entry:{backup_root.name}")
        entry["name"] = _safe_name(str(entry.get("name", "")))
        if entry["name"] in seen:
            raise RuntimeError(f"duplicate_restore_journal_entry:{backup_root.name}:{entry['name']}")
        seen.add(entry["name"])
        if schema_version == 1:
            target = backup_root.parent / entry["name"]
            backup = backup_root / entry["name"]
            target_digest = _regular_digest(target, f"legacy_target:{entry['name']}")
            backup_digest = _regular_digest(backup, f"legacy_backup:{entry['name']}")
            entry["old_sha256"] = backup_digest if entry["existed"] else None
            entry["new_sha256"] = target_digest or ("0" * 64)
            if entry["existed"] and backup_digest is None and target_digest is None:
                raise RuntimeError(
                    f"unrecoverable_legacy_restore_entry:{backup_root.name}:{entry['name']}"
                )
        if not _valid_sha256(entry.get("new_sha256")):
            raise RuntimeError(f"invalid_restore_journal_new_digest:{backup_root.name}:{entry['name']}")
        old_digest = entry.get("old_sha256")
        if entry["existed"]:
            if not _valid_sha256(old_digest):
                if schema_version == 1 and journal["state"] == "prepared":
                    legacy_target_digest = _regular_digest(
                        backup_root.parent / entry["name"],
                        f"legacy_target:{entry['name']}",
                    )
                    if legacy_target_digest:
                        entry["old_sha256"] = legacy_target_digest
                    else:
                        raise RuntimeError(
                            f"invalid_restore_journal_old_digest:{backup_root.name}:{entry['name']}"
                        )
                else:
                    raise RuntimeError(
                        f"invalid_restore_journal_old_digest:{backup_root.name}:{entry['name']}"
                    )
        elif old_digest is not None:
            raise RuntimeError(
                f"unexpected_restore_journal_old_digest:{backup_root.name}:{entry['name']}"
            )
    journal["loaded_schema_version"] = schema_version
    return journal


def _verify_committed_transaction(destination: Path, backup_root: Path, journal: dict) -> None:
    _validate_destination_entries(destination, [entry["name"] for entry in journal["entries"]])
    for entry in journal["entries"]:
        name = entry["name"]
        target_digest = _regular_digest(destination / name, f"target:{name}")
        if target_digest != entry["new_sha256"]:
            raise RuntimeError(f"committed_restore_target_mismatch:{name}")
        backup_digest = _regular_digest(backup_root / name, f"backup:{name}")
        if entry["existed"]:
            if backup_digest != entry["old_sha256"]:
                raise RuntimeError(f"committed_restore_backup_mismatch:{name}")
        elif backup_digest is not None:
            raise RuntimeError(f"unexpected_committed_restore_backup:{name}")


def _rollback_transaction(destination: Path, backup_root: Path, journal: dict) -> None:
    _validate_destination_entries(destination, [entry["name"] for entry in journal["entries"]])
    errors: list[str] = []
    for entry in reversed(journal["entries"]):
        name = entry["name"]
        target = destination / name
        backup = backup_root / name
        try:
            target_digest = _regular_digest(target, f"target:{name}")
            backup_digest = _regular_digest(backup, f"backup:{name}")
            if entry["existed"]:
                if backup_digest is None:
                    if target_digest != entry["old_sha256"]:
                        raise RuntimeError(f"missing_restore_backup:{name}")
                    continue
                if backup_digest != entry["old_sha256"]:
                    raise RuntimeError(f"restore_backup_digest_mismatch:{name}")
                if target_digest not in {None, entry["new_sha256"]}:
                    raise RuntimeError(f"restore_target_digest_mismatch:{name}")
                if target_digest is not None:
                    target.unlink()
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, target)
                _fsync_directory(target.parent)
            else:
                if backup_digest is not None:
                    raise RuntimeError(f"unexpected_restore_backup:{name}")
                if target_digest is None:
                    continue
                if target_digest != entry["new_sha256"]:
                    raise RuntimeError(f"restore_new_target_digest_mismatch:{name}")
                target.unlink()
                _fsync_directory(target.parent)
        except (OSError, RuntimeError) as exc:
            errors.append(f"{name}:{exc}")
    if errors:
        raise RuntimeError("restore_rollback_failed:" + "|".join(errors))
    shutil.rmtree(backup_root)
    _fsync_directory(destination)


def recover_interrupted_restores(destination: Path) -> int:
    """Recover incomplete transactions before any new artifact is inspected."""
    if not destination.exists():
        return 0
    _validate_restore_root(destination)
    recovered = 0
    for stage_root in sorted(destination.glob(f"{STAGE_PREFIX}*")):
        stage_stat = _lstat(stage_root)
        if stage_stat is None:
            continue
        if stat.S_ISLNK(stage_stat.st_mode) or not stat.S_ISDIR(stage_stat.st_mode):
            raise RuntimeError(f"invalid_restore_stage:{stage_root.name}")
        shutil.rmtree(stage_root)
        recovered += 1
    for backup_root in sorted(destination.glob(f"{BACKUP_PREFIX}*")):
        backup_stat = _lstat(backup_root)
        if backup_stat is None:
            continue
        if stat.S_ISLNK(backup_stat.st_mode) or not stat.S_ISDIR(backup_stat.st_mode):
            raise RuntimeError(f"invalid_restore_backup_root:{backup_root.name}")
        journal = _load_journal(backup_root)
        if journal["state"] == "committed":
            _verify_committed_transaction(destination, backup_root, journal)
            shutil.rmtree(backup_root)
            _fsync_directory(destination)
        else:
            _rollback_transaction(destination, backup_root, journal)
        recovered += 1
    return recovered


def _inspect_archive(
    archive: zipfile.ZipFile,
    required: set[str],
) -> tuple[dict, list[zipfile.ZipInfo]]:
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


def _commit_staged_members(
    stage_root: Path,
    destination: Path,
    names: list[str],
    member_reports: dict[str, dict],
) -> None:
    _validate_destination_entries(destination, names)
    entries = []
    for name in names:
        target = destination / name
        existed = target.exists()
        entries.append(
            {
                "name": name,
                "existed": existed,
                "old_sha256": _sha256_file(target) if existed else None,
                "new_sha256": member_reports[name]["sha256"],
            }
        )
    backup_root = Path(tempfile.mkdtemp(prefix=BACKUP_PREFIX, dir=destination))
    journal = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "state": "prepared",
        "entries": entries,
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
    _verify_committed_transaction(destination, backup_root, journal)
    shutil.rmtree(backup_root)
    _fsync_directory(destination)


def extract_bundle(zip_path: Path, destination: Path, required: set[str]) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    _validate_restore_root(destination)
    recovered = recover_interrupted_restores(destination)
    raw = _read_bundle(zip_path)
    stage_root = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=destination))
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            report, files = _inspect_archive(archive, required)
            names = _stage_members(archive, files, stage_root, report)
        _commit_staged_members(stage_root, destination, names, report["members"])
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    report["zip_sha256"] = hashlib.sha256(raw).hexdigest()
    report["extraction"] = "crash_recoverable_transactional_bundle_replace"
    report["destination_path_policy"] = "no_symlink_or_special_file_components"
    report["recovery_policy"] = "old_and_new_sha256_verified_before_mutation"
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
