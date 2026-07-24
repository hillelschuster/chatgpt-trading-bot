#!/usr/bin/env python3
"""Restore only a completed successful prospective artifact from the approved workflow."""
import argparse
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ALLOWED_EVENTS = {"schedule", "workflow_dispatch"}
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
SENSITIVE_REDIRECT_HEADERS = {"authorization", "x-github-api-version"}


class SafeArtifactRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow HTTPS redirects without forwarding GitHub credentials cross-origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme.lower() != "https" or not target.hostname:
            raise urllib.error.HTTPError(
                newurl, code, "unsafe_artifact_redirect", headers, fp
            )
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        source = urllib.parse.urlsplit(req.full_url)
        if (source.scheme.lower(), source.hostname, source.port) != (
            target.scheme.lower(), target.hostname, target.port
        ):
            for header in SENSITIVE_REDIRECT_HEADERS:
                redirected.remove_header(header)
        return redirected


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


def download(url, token, path, max_bytes=MAX_ARCHIVE_BYTES, opener=None):
    """Atomically persist a bounded artifact and return its exact byte identity."""
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "crossvenue-artifact-restorer",
    })
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    size = 0
    safe_opener = opener or urllib.request.build_opener(SafeArtifactRedirectHandler())
    try:
        with os.fdopen(descriptor, "wb") as output:
            with safe_opener.open(request, timeout=60) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and int(declared) > max_bytes:
                    raise ValueError("artifact_content_length_too_large")
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("artifact_download_too_large")
                    digest.update(chunk)
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size == 0:
            raise ValueError("empty_artifact_download")
        os.replace(temporary, destination)
        directory_descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"archive_sha256": digest.hexdigest(), "archive_bytes": size,
            "redirect_policy": "https_cross_origin_credentials_stripped"}


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


def _write_report(path, report):
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--artifact-name", default="crossvenue-series")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--workflow-path", default=".github/workflows/crossvenue-probe.yml")
    parser.add_argument("--out", required=True)
    parser.add_argument("--report")
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN"))
    parser.add_argument("--required", action="store_true")
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("GitHub token missing")
    artifact = find(args.repository, args.artifact_name, args.token,
                    branch=args.branch, workflow_path=args.workflow_path)
    if not artifact:
        report = {"status": "not_found", "artifact_name": args.artifact_name,
                  "branch": args.branch, "workflow_path": args.workflow_path}
        _write_report(args.report, report)
        print(json.dumps(report))
        if args.required:
            raise SystemExit("no approved completed successful prospective artifact found")
        return
    identity = download(artifact["archive_download_url"], args.token, args.out)
    report = {
        "status": "downloaded",
        "schema_version": 3,
        "artifact_id": artifact["id"],
        "workflow_run_id": (artifact.get("workflow_run") or {}).get("id"),
        "created_at": artifact.get("created_at"),
        "branch": args.branch,
        "workflow_path": args.workflow_path,
        "out": args.out,
        **identity,
    }
    _write_report(args.report, report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
