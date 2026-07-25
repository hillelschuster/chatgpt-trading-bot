#!/usr/bin/env python3
"""Restore the newest canonical prospective artifact produced by a scheduled run."""
from __future__ import annotations

import argparse
import json
import os
import urllib.error

from crossvenue_artifact import _write_report, download, request_json

CANONICAL_EVENT = "schedule"


def run_is_canonical(run: dict, branch: str, workflow_path: str) -> bool:
    """Require exact successful scheduled-run provenance for canonical evidence."""
    return bool(
        run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("event") == CANONICAL_EVENT
        and run.get("head_branch") == branch
        and run.get("path") == workflow_path
    )


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
        if run_id and run_is_canonical(runs.get(run_id) or {}, branch, workflow_path):
            return artifact
    return None


def find_canonical(
    repository: str,
    artifact_name: str,
    token: str,
    branch: str,
    workflow_path: str,
    max_pages: int = 10,
) -> dict | None:
    """Search backward until a non-expired scheduled artifact is found."""
    base = f"https://api.github.com/repos/{repository}"
    for page in range(1, max_pages + 1):
        payload = request_json(
            f"{base}/actions/artifacts?name={artifact_name}&per_page=100&page={page}",
            token,
        )
        artifacts = payload.get("artifacts") or []
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
            if not run_id:
                continue
            try:
                run = request_json(f"{base}/actions/runs/{run_id}", token)
            except urllib.error.HTTPError:
                continue
            if run_is_canonical(run, branch, workflow_path):
                return artifact
        if len(artifacts) < 100:
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
        }
        _write_report(args.report, report)
        print(json.dumps(report, sort_keys=True))
        if args.required:
            raise SystemExit("no completed successful scheduled prospective artifact found")
        return 0

    identity = download(artifact["archive_download_url"], args.token, args.out)
    report = {
        "status": "downloaded",
        "schema_version": 5,
        "artifact_id": artifact["id"],
        "workflow_run_id": (artifact.get("workflow_run") or {}).get("id"),
        "created_at": artifact.get("created_at"),
        "branch": args.branch,
        "workflow_path": args.workflow_path,
        "allowed_events": [CANONICAL_EVENT],
        "out": args.out,
        **identity,
    }
    _write_report(args.report, report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
