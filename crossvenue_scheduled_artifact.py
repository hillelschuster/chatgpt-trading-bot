#!/usr/bin/env python3
"""Restore the newest canonical prospective artifact produced by a scheduled run."""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
from datetime import datetime, timezone

from crossvenue_artifact import _write_report, download, request_json

CANONICAL_EVENT = "schedule"
MAX_ARTIFACT_AFTER_RUN_MS = 10 * 60 * 1000


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


def run_is_canonical(run: dict, branch: str, workflow_path: str) -> bool:
    """Require exact successful scheduled-run provenance for canonical evidence."""
    return bool(
        run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("event") == CANONICAL_EVENT
        and run.get("head_branch") == branch
        and run.get("path") == workflow_path
        and int(run.get("id") or 0) > 0
        and isinstance(run.get("head_sha"), str)
        and len(run.get("head_sha")) == 40
    )


def artifact_belongs_to_run(artifact: dict, run: dict) -> bool:
    """Bind an artifact to one exact run and reject impossible timestamps."""
    run_id = int(run.get("id") or 0)
    artifact_run_id = int((artifact.get("workflow_run") or {}).get("id") or 0)
    if not run_id or artifact_run_id != run_id:
        return False

    artifact_ms = _timestamp_ms(artifact.get("created_at"))
    run_created_ms = _timestamp_ms(run.get("created_at"))
    run_updated_ms = _timestamp_ms(run.get("updated_at"))
    if artifact_ms is None or run_created_ms is None or run_updated_ms is None:
        return False
    if run_updated_ms < run_created_ms:
        return False
    return run_created_ms <= artifact_ms <= run_updated_ms + MAX_ARTIFACT_AFTER_RUN_MS


def choose_canonical_artifact(
    artifacts: list[dict], runs: dict[int, dict], branch: str, workflow_path: str
) -> dict | None:
    """Choose the newest non-expired artifact from an exact scheduled run."""
    ordered = sorted(
        (artifact for artifact in artifacts if not artifact.get("expired")),
        key=lambda artifact: (
            artifact.get("created_at") or "",
            int(artifact.get("id") or 0),
        ),
        reverse=True,
    )
    for artifact in ordered:
        run_id = int((artifact.get("workflow_run") or {}).get("id") or 0)
        run = runs.get(run_id) or {}
        if (
            run_is_canonical(run, branch, workflow_path)
            and artifact_belongs_to_run(artifact, run)
        ):
            selected = dict(artifact)
            selected["_canonical_run"] = run
            return selected
    return None


def newest_named_artifact(payload: dict, artifact_name: str, run: dict) -> dict | None:
    """Return the newest exact-name artifact bound to one workflow run."""
    candidates = [
        artifact
        for artifact in payload.get("artifacts") or []
        if artifact.get("name") == artifact_name
        and not artifact.get("expired")
        and artifact_belongs_to_run(artifact, run)
    ]
    artifact = max(
        candidates,
        key=lambda item: (
            item.get("created_at") or "",
            int(item.get("id") or 0),
        ),
        default=None,
    )
    if artifact is None:
        return None
    selected = dict(artifact)
    selected["_canonical_run"] = run
    return selected


def find_canonical(
    repository: str,
    artifact_name: str,
    token: str,
    branch: str,
    workflow_path: str,
    max_pages: int = 300,
) -> dict | None:
    """Search successful scheduled workflow runs, then inspect only their artifacts.

    Querying the repository-wide artifact stream is unsafe during a prolonged outage:
    failed scheduled runs can emit thousands of same-name diagnostic artifacts and push
    the last successful baseline beyond a small arbitrary page cap. The workflow-runs
    endpoint filters to scheduled successes first, so the first usable artifact remains
    discoverable for the full artifact-retention horizon without scanning failed runs.
    """
    base = f"https://api.github.com/repos/{repository}"
    workflow_id = urllib.parse.quote(workflow_path, safe="")
    branch_query = urllib.parse.quote(branch, safe="")
    for page in range(1, max_pages + 1):
        runs_payload = request_json(
            f"{base}/actions/workflows/{workflow_id}/runs"
            f"?branch={branch_query}&event={CANONICAL_EVENT}&status=success"
            f"&per_page=100&page={page}",
            token,
        )
        runs = runs_payload.get("workflow_runs") or []
        for run in runs:
            if not run_is_canonical(run, branch, workflow_path):
                continue
            run_id = int(run.get("id") or 0)
            try:
                artifacts_payload = request_json(
                    f"{base}/actions/runs/{run_id}/artifacts"
                    f"?name={urllib.parse.quote(artifact_name, safe='')}&per_page=100",
                    token,
                )
            except urllib.error.HTTPError:
                continue
            artifact = newest_named_artifact(artifacts_payload, artifact_name, run)
            if artifact is not None:
                return artifact
        if len(runs) < 100:
            break
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--artifact-name", default="crossvenue-series")
    parser.add_argument("--branch", default="main")
    parser.add_argument(
        "--workflow-path", default=".github/workflows/crossvenue-probe.yml"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--report")
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN"))
    parser.add_argument("--required", action="store_true")
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("GitHub token missing")

    artifact = find_canonical(
        args.repository,
        args.artifact_name,
        args.token,
        args.branch,
        args.workflow_path,
    )
    if not artifact:
        report = {
            "status": "not_found",
            "artifact_name": args.artifact_name,
            "branch": args.branch,
            "workflow_path": args.workflow_path,
            "allowed_events": [CANONICAL_EVENT],
            "selection": "successful_scheduled_workflow_runs_then_bound_named_artifact",
        }
        _write_report(args.report, report)
        print(json.dumps(report, sort_keys=True))
        if args.required:
            raise SystemExit("no completed successful scheduled prospective artifact found")
        return 0

    run = artifact.pop("_canonical_run")
    identity = download(artifact["archive_download_url"], args.token, args.out)
    report = {
        "status": "downloaded",
        "schema_version": 7,
        "artifact_id": artifact["id"],
        "artifact_created_at": artifact.get("created_at"),
        "workflow_run_id": run["id"],
        "workflow_run_event": run["event"],
        "workflow_run_head_sha": run["head_sha"],
        "workflow_run_created_at": run.get("created_at"),
        "workflow_run_updated_at": run.get("updated_at"),
        "branch": args.branch,
        "workflow_path": args.workflow_path,
        "allowed_events": [CANONICAL_EVENT],
        "selection": "successful_scheduled_workflow_runs_then_bound_named_artifact",
        "artifact_run_binding": "exact_run_id_and_bounded_timestamps_v1",
        "out": args.out,
        **identity,
    }
    _write_report(args.report, report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())