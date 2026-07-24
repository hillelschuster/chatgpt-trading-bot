#!/usr/bin/env python3
"""Audit live GitHub Actions health for the frozen prospective collector."""
import argparse
import json
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ALLOWED_EVENTS = {"schedule", "workflow_dispatch"}
TERMINAL_FAILURES = {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
MAX_SUCCESS_AGE_MINUTES = 30
MAX_ACTIVE_AGE_MINUTES = 15
MAX_CONSECUTIVE_FAILURES = 2
RUN_CADENCE_MINUTES = 5
RUN_GAP_WINDOW_MINUTES = 60
MAX_RUN_GAP_MINUTES = 15


def parse_time_ms(value):
    if not value:
        return 0
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def request_json(url, token):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "crossvenue-actions-health",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def approved(run):
    return run.get("head_branch") == "main" and run.get("event") in ALLOWED_EVENTS


def cadence_health(relevant, now_ms):
    window_start = now_ms - RUN_GAP_WINDOW_MINUTES * 60_000
    times = sorted({parse_time_ms(r.get("created_at")) for r in relevant
                    if parse_time_ms(r.get("created_at")) >= window_start})
    gaps = []
    for left, right in zip(times, times[1:]):
        gaps.append((right - left) / 60_000)
    if times:
        gaps.append((now_ms - times[-1]) / 60_000)
    max_gap = max(gaps) if gaps else None
    return {
        "expected_cadence_minutes": RUN_CADENCE_MINUTES,
        "window_minutes": RUN_GAP_WINDOW_MINUTES,
        "approved_run_count": len(times),
        "max_gap_minutes": max_gap,
        "gap_limit_minutes": MAX_RUN_GAP_MINUTES,
        "healthy": max_gap is None or max_gap <= MAX_RUN_GAP_MINUTES,
    }


def summarize(runs, restoration=None, now_ms=None):
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    relevant = sorted(
        (r for r in runs if approved(r)),
        key=lambda r: (parse_time_ms(r.get("created_at")), int(r.get("id") or 0)),
        reverse=True,
    )
    completed = [r for r in relevant if r.get("status") == "completed"]
    active = [r for r in relevant if r.get("status") in {"queued", "in_progress", "waiting", "pending"}]
    successes = [r for r in completed if r.get("conclusion") == "success"]
    failures = [r for r in completed if r.get("conclusion") in TERMINAL_FAILURES]
    latest = relevant[0] if relevant else {}
    latest_success = successes[0] if successes else {}
    cadence = cadence_health(relevant, now_ms)

    consecutive_failures = 0
    for run in completed:
        if run.get("conclusion") in TERMINAL_FAILURES:
            consecutive_failures += 1
        else:
            break

    success_age_minutes = (
        (now_ms - parse_time_ms(latest_success.get("updated_at") or latest_success.get("created_at"))) / 60_000
        if latest_success else None
    )
    oldest_active_age_minutes = (
        max((now_ms - parse_time_ms(r.get("created_at"))) / 60_000 for r in active)
        if active else None
    )
    restored_run_id = int((restoration or {}).get("workflow_run_id") or 0)
    latest_success_id = int(latest_success.get("id") or 0)

    blockers = []
    if not relevant:
        blockers.append("approved_runs_missing")
    if not latest_success:
        blockers.append("successful_run_missing")
    elif success_age_minutes > MAX_SUCCESS_AGE_MINUTES:
        blockers.append("successful_run_stale")
    if consecutive_failures > MAX_CONSECUTIVE_FAILURES:
        blockers.append("repeated_collector_failures")
    if oldest_active_age_minutes is not None and oldest_active_age_minutes > MAX_ACTIVE_AGE_MINUTES:
        blockers.append("collector_run_stuck")
    if not cadence["healthy"]:
        blockers.append("collector_schedule_gap")
    if restoration:
        if restoration.get("status") != "downloaded":
            blockers.append("restoration_not_downloaded")
        elif restored_run_id != latest_success_id:
            blockers.append("restoration_not_latest_success")

    return {
        "status": "INVALID" if blockers else "HEALTHY",
        "generated_at_ms": now_ms,
        "latest_run": {
            "id": latest.get("id"), "status": latest.get("status"),
            "conclusion": latest.get("conclusion"), "event": latest.get("event"),
            "created_at": latest.get("created_at"),
        },
        "latest_success": {
            "id": latest_success.get("id"), "updated_at": latest_success.get("updated_at"),
            "age_minutes": success_age_minutes,
        },
        "active": {"count": len(active), "oldest_age_minutes": oldest_active_age_minutes},
        "failures": {"completed_failure_count": len(failures), "consecutive": consecutive_failures},
        "cadence": cadence,
        "restoration": {
            "workflow_run_id": restored_run_id or None,
            "matches_latest_success": bool(restoration) and restored_run_id == latest_success_id,
        },
        "blockers": blockers,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repository", required=True)
    p.add_argument("--workflow", default="crossvenue-probe.yml")
    p.add_argument("--restoration", default="reports/crossvenue_restoration.json")
    p.add_argument("--out", default="reports/crossvenue_actions_health.json")
    p.add_argument("--token", default=os.environ.get("GH_TOKEN"))
    a = p.parse_args()
    if not a.token:
        raise SystemExit("GitHub token missing")
    url = (f"https://api.github.com/repos/{a.repository}/actions/workflows/"
           f"{a.workflow}/runs?branch=main&per_page=100")
    runs = request_json(url, a.token).get("workflow_runs") or []
    restoration_path = Path(a.restoration)
    restoration = json.loads(restoration_path.read_text()) if restoration_path.exists() else None
    report = summarize(runs, restoration)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    if report["status"] == "INVALID":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
