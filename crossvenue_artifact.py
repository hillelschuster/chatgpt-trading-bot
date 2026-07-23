#!/usr/bin/env python3
"""Restore only a completed successful prospective artifact from GitHub Actions."""
import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ALLOWED_EVENTS = {"schedule", "workflow_dispatch"}


def choose_artifact(artifacts, runs):
    """Return newest non-expired artifact whose producing run completed successfully."""
    ordered = sorted(
        (a for a in artifacts if not a.get("expired")),
        key=lambda a: (a.get("created_at") or "", int(a.get("id") or 0)),
        reverse=True,
    )
    for artifact in ordered:
        run_id = int((artifact.get("workflow_run") or {}).get("id") or 0)
        run = runs.get(run_id) or {}
        if (run.get("status") == "completed" and run.get("conclusion") == "success"
                and run.get("event") in ALLOWED_EVENTS):
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


def find(repository, artifact_name, token):
    base = f"https://api.github.com/repos/{repository}"
    payload = request_json(
        f"{base}/actions/artifacts?name={artifact_name}&per_page=100", token)
    artifacts = payload.get("artifacts") or []
    runs = {}
    for artifact in artifacts:
        run_id = int((artifact.get("workflow_run") or {}).get("id") or 0)
        if run_id and run_id not in runs:
            try:
                runs[run_id] = request_json(f"{base}/actions/runs/{run_id}", token)
            except urllib.error.HTTPError:
                runs[run_id] = {}
    return choose_artifact(artifacts, runs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--artifact-name", default="crossvenue-series")
    parser.add_argument("--out", required=True)
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN"))
    parser.add_argument("--required", action="store_true")
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("GitHub token missing")
    artifact = find(args.repository, args.artifact_name, args.token)
    if not artifact:
        if args.required:
            raise SystemExit("no completed successful prospective artifact found")
        print(json.dumps({"status": "not_found", "artifact_name": args.artifact_name}))
        return
    download(artifact["archive_download_url"], args.token, args.out)
    print(json.dumps({
        "status": "downloaded",
        "artifact_id": artifact["id"],
        "workflow_run_id": (artifact.get("workflow_run") or {}).get("id"),
        "created_at": artifact.get("created_at"),
        "out": args.out,
    }))


if __name__ == "__main__":
    main()
