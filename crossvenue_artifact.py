#!/usr/bin/env python3
"""Restore only a completed successful prospective artifact from the approved workflow."""
import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ALLOWED_EVENTS = {"schedule", "workflow_dispatch"}


def run_is_approved(run, branch=None, workflow_path=None):
    """Require a successful approved event and, when configured, exact provenance."""
    if not (run.get("status") == "completed" and run.get("conclusion") == "success"
            and run.get("event") in ALLOWED_EVENTS):
        return False
    if branch and run.get("head_branch") != branch:
        return False
    if workflow_path and run.get("path") != workflow_path:
        return False
    return True


def choose_artifact(artifacts, runs, branch=None, workflow_path=None):
    """Return newest non-expired artifact produced by an approved workflow run."""
    ordered = sorted(
        (a for a in artifacts if not a.get("expired")),
        key=lambda a: (a.get("created_at") or "", int(a.get("id") or 0)),
        reverse=True,
    )
    for artifact in ordered:
        run_id = int((artifact.get("workflow_run") or {}).get("id") or 0)
        run = runs.get(run_id) or {}
        if run_is_approved(run, branch, workflow_path):
            return artifact
    return None


def request_json(url, token):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "crossvenue-artifact-restorer",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def download(url, token, path):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "crossvenue-artifact-restorer",
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        Path(path).write_bytes(response.read())


def find(repository, artifact_name, token, max_pages=10, branch=None, workflow_path=None):
    base = f"https://api.github.com/repos/{repository}"
    for page in range(1, max_pages + 1):
        payload = request_json(
            f"{base}/actions/artifacts?name={artifact_name}&per_page=100&page={page}", token)
        artifacts = sorted(
            (a for a in payload.get("artifacts") or [] if not a.get("expired")),
            key=lambda a: (a.get("created_at") or "", int(a.get("id") or 0)),
            reverse=True,
        )
        for artifact in artifacts:
            run_id = int((artifact.get("workflow_run") or {}).get("id") or 0)
            if not run_id:
                continue
            try:
                run = request_json(f"{base}/actions/runs/{run_id}", token)
            except urllib.error.HTTPError:
                continue
            if choose_artifact([artifact], {run_id: run}, branch, workflow_path):
                return artifact
        if len(payload.get("artifacts") or []) < 100:
            break
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--artifact-name", default="crossvenue-series")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--workflow-path", default=".github/workflows/crossvenue-probe.yml")
    parser.add_argument("--out", required=True)
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN"))
    parser.add_argument("--required", action="store_true")
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("GitHub token missing")
    artifact = find(args.repository, args.artifact_name, args.token,
                    branch=args.branch, workflow_path=args.workflow_path)
    if not artifact:
        if args.required:
            raise SystemExit("no approved completed successful prospective artifact found")
        print(json.dumps({"status": "not_found", "artifact_name": args.artifact_name,
                          "branch": args.branch, "workflow_path": args.workflow_path}))
        return
    download(artifact["archive_download_url"], args.token, args.out)
    print(json.dumps({
        "status": "downloaded",
        "artifact_id": artifact["id"],
        "workflow_run_id": (artifact.get("workflow_run") or {}).get("id"),
        "created_at": artifact.get("created_at"),
        "branch": args.branch,
        "workflow_path": args.workflow_path,
        "out": args.out,
    }))


if __name__ == "__main__":
    main()
