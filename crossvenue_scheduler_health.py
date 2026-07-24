#!/usr/bin/env python3
"""Replace mixed-event cadence diagnostics with a schedule-only GitHub run audit."""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path

RUN_CADENCE_MINUTES = 5
RUN_GAP_WINDOW_MINUTES = 60
MAX_RUN_GAP_MINUTES = 15


def parse_time_ms(value):
    if not value:
        return 0
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def schedule_cadence(runs, now_ms):
    approved = [
        r for r in runs
        if r.get("head_branch") == "main" and r.get("event") == "schedule"
    ]
    window_start = now_ms - RUN_GAP_WINDOW_MINUTES * 60_000
    times = sorted({
        ts for r in approved
        if window_start <= (ts := parse_time_ms(r.get("created_at"))) <= now_ms
    })
    boundaries = [window_start, *times, now_ms]
    gaps = [(right - left) / 60_000 for left, right in zip(boundaries, boundaries[1:])]
    max_gap = max(gaps) if gaps else RUN_GAP_WINDOW_MINUTES
    excessive = [gap for gap in gaps if gap > MAX_RUN_GAP_MINUTES]
    missed = sum(max(0, math.ceil(gap / RUN_CADENCE_MINUTES) - 1) for gap in gaps)
    return {
        "source_event": "schedule",
        "expected_cadence_minutes": RUN_CADENCE_MINUTES,
        "window_minutes": RUN_GAP_WINDOW_MINUTES,
        "approved_run_count": len(times),
        "expected_run_count": RUN_GAP_WINDOW_MINUTES // RUN_CADENCE_MINUTES,
        "estimated_missed_runs": missed,
        "max_gap_minutes": max_gap,
        "gap_limit_minutes": MAX_RUN_GAP_MINUTES,
        "excessive_gap_count": len(excessive),
        "healthy": bool(times) and not excessive,
    }


def merge(actions_report, runs, now_ms):
    report = dict(actions_report)
    blockers = [x for x in report.get("blockers", []) if x != "collector_schedule_gap"]
    cadence = schedule_cadence(runs, now_ms)
    if not cadence["healthy"]:
        blockers.append("collector_schedule_gap")
    report["cadence"] = cadence
    report["blockers"] = blockers
    report["status"] = "INVALID" if blockers else "HEALTHY"
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", required=True)
    p.add_argument("--actions-report", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    runs_payload = json.loads(Path(a.runs).read_text())
    runs = runs_payload.get("workflow_runs") if isinstance(runs_payload, dict) else runs_payload
    actions = json.loads(Path(a.actions_report).read_text())
    now_ms = int(actions.get("generated_at_ms") or 0)
    if not now_ms:
        raise SystemExit("actions report generated_at_ms missing")
    report = merge(actions, runs or [], now_ms)
    Path(a.out).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    if report["status"] == "INVALID":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
