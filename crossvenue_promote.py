#!/usr/bin/env python3
"""Combine profitability validation and observation coverage into one promotion verdict."""
import argparse, json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def promote(validation, coverage):
    validation_verdict = validation.get("verdict")
    coverage_status = coverage.get("status")
    if validation_verdict == "INVALID" or coverage_status == "INVALID":
        verdict = "INVALID"
    elif validation_verdict == "PASS" and coverage_status == "PASS":
        verdict = "PASS"
    elif validation_verdict == "REJECT" and coverage_status == "PASS":
        verdict = "REJECT"
    else:
        verdict = "COLLECTING"
    return {
        "verdict": verdict,
        "profitability_claim_permitted": verdict == "PASS",
        "validation_verdict": validation_verdict,
        "coverage_status": coverage_status,
        "gates": {
            "profitability_validation_passed": validation_verdict == "PASS",
            "prospective_observation_coverage_passed": coverage_status == "PASS",
            "append_only_chain_valid": bool((validation.get("artifact_chain") or {}).get("valid")),
            "promotion_requires_both_validation_and_coverage": True,
        },
        "coverage": {k: coverage.get(k) for k in (
            "collection_span_days", "slot_coverage", "complete_slot_coverage",
            "eligible_event_opportunities", "accounted_events", "event_accounting",
            "duplicate_rows")},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--validation", default="reports/crossvenue_validation.json")
    p.add_argument("--coverage", default="reports/crossvenue_coverage.json")
    p.add_argument("--report", default="reports/crossvenue_promotion.json")
    a = p.parse_args()
    report = promote(read(a.validation), read(a.coverage))
    out = Path(a.report); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    if report["verdict"] == "INVALID":
        raise SystemExit(1)


if __name__ == "__main__": main()
