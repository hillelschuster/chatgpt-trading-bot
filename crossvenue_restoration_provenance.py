#!/usr/bin/env python3
"""Fail-closed verification of canonical scheduled artifact restoration metadata."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
EXPECTED_SELECTION = "successful_scheduled_workflow_runs_then_bound_named_artifact"
EXPECTED_BINDING = "exact_run_id_and_bounded_timestamps_v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


def _timestamp_ms(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def verify(report: dict, repository: str, branch: str, workflow_path: str) -> dict:
    """Validate every immutable provenance field emitted by the scheduled selector."""
    blockers: list[str] = []
    checks: dict[str, bool] = {}

    artifact_id = _positive_int(report.get("artifact_id"))
    run_id = _positive_int(report.get("workflow_run_id"))
    head_sha = report.get("workflow_run_head_sha")

    checks["downloaded_status"] = report.get("status") == "downloaded"
    checks["schema_version_7"] = report.get("schema_version") == 7
    checks["positive_artifact_id"] = artifact_id is not None
    checks["positive_workflow_run_id"] = run_id is not None
    checks["scheduled_event"] = report.get("workflow_run_event") == "schedule"
    checks["exact_branch"] = report.get("branch") == branch
    checks["exact_workflow_path"] = report.get("workflow_path") == workflow_path
    checks["exact_selection_policy"] = report.get("selection") == EXPECTED_SELECTION
    checks["exact_binding_policy"] = report.get("artifact_run_binding") == EXPECTED_BINDING
    checks["schedule_only_allowlist"] = report.get("allowed_events") == ["schedule"]
    checks["strict_lowercase_head_sha"] = isinstance(head_sha, str) and bool(
        _SHA40.fullmatch(head_sha)
    )

    run_created_ms = _timestamp_ms(report.get("workflow_run_created_at"))
    run_updated_ms = _timestamp_ms(report.get("workflow_run_updated_at"))
    artifact_created_ms = _timestamp_ms(report.get("artifact_created_at"))
    checks["valid_timestamps"] = all(
        value is not None for value in (run_created_ms, run_updated_ms, artifact_created_ms)
    )
    checks["monotonic_run_timestamps"] = bool(
        checks["valid_timestamps"] and run_created_ms <= run_updated_ms
    )
    checks["artifact_created_during_run"] = bool(
        checks["monotonic_run_timestamps"]
        and run_created_ms <= artifact_created_ms <= run_updated_ms + 10 * 60 * 1000
    )

    archive_sha = report.get("archive_sha256")
    checks["strict_archive_sha256"] = isinstance(archive_sha, str) and bool(
        _SHA64.fullmatch(archive_sha)
    )
    checks["positive_archive_size"] = _positive_int(report.get("archive_bytes")) is not None
    checks["zip_crc_verified"] = report.get("zip_crc_verified") is True
    checks["positive_zip_member_count"] = _positive_int(report.get("zip_member_count")) is not None
    checks["positive_zip_uncompressed_bytes"] = (
        _positive_int(report.get("zip_uncompressed_bytes")) is not None
    )
    checks["safe_redirect_policy"] = (
        report.get("redirect_policy") == "https_cross_origin_credentials_stripped"
    )
    checks["bounded_zip_policy"] = (
        report.get("zip_safety_policy") == "bounded_unencrypted_members_before_crc_v1"
    )

    for name, passed in checks.items():
        if not passed:
            blockers.append(f"restoration_provenance_{name}")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "VALID" if not blockers else "INVALID",
        "repository": repository,
        "expected_branch": branch,
        "expected_workflow_path": workflow_path,
        "artifact_id": artifact_id,
        "workflow_run_id": run_id,
        "checks": checks,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restoration", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--workflow-path", default=".github/workflows/crossvenue-probe.yml")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    report = json.loads(Path(args.restoration).read_text())
    result = verify(report, args.repository, args.branch, args.workflow_path)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
