#!/usr/bin/env python3
"""Select a funding-fade configuration in-sample and verify it out-of-sample."""
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from evaluate import load, observations, summarize


def split(records, train_fraction=.7):
    if not records:
        return [], [], None
    times = sorted({int(r["captured_at_ms"]) for r in records})
    cut = times[min(len(times) - 1, max(0, int(len(times) * train_fraction) - 1))]
    return ([r for r in records if int(r["captured_at_ms"]) <= cut],
            [r for r in records if int(r["captured_at_ms"]) > cut], cut)


def run_grid(records, horizons, thresholds, costs, min_trades=30):
    rows = []
    for horizon in horizons:
        for threshold in thresholds:
            for cost in costs:
                stats = summarize(observations(records, horizon, threshold, cost))
                rows.append({"horizon_hours": horizon, "min_funding_bps": threshold,
                             "roundtrip_bps": cost, **stats})
    eligible = [r for r in rows if r["trades"] >= min_trades]
    eligible.sort(key=lambda r: (r["mean_lcb95_pct"], r["mean_net_return_pct"]), reverse=True)
    return rows, eligible


def study(records, horizons=(1, 4, 8, 24), thresholds=(.25, .5, 1, 2, 5),
          costs=(3, 6, 9), min_trades=30, train_fraction=.7):
    train, test, cut = split(records, train_fraction)
    _, ranked = run_grid(train, horizons, thresholds, costs, min_trades)
    selected = ranked[0] if ranked else None
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": len(records), "train_records": len(train), "test_records": len(test),
        "split_at_ms": cut, "selection_rule": "highest train 95% lower confidence bound",
        "min_train_trades": min_trades, "selected": selected,
        "out_of_sample": None, "verdict": "INSUFFICIENT_DATA",
        "top_train": ranked[:10],
    }
    if selected:
        test_rows = observations(test, selected["horizon_hours"],
                                 selected["min_funding_bps"], selected["roundtrip_bps"])
        out["out_of_sample"] = summarize(test_rows)
        stats = out["out_of_sample"]
        out["verdict"] = ("PROMISING" if stats["trades"] >= max(10, min_trades // 3)
                          and stats["mean_lcb95_pct"] > 0 else "REJECT_OR_REWORK")
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", default="data/history.jsonl")
    p.add_argument("--out", default="reports/funding_fade.json")
    p.add_argument("--min-trades", type=int, default=30)
    p.add_argument("--train-fraction", type=float, default=.7)
    args = p.parse_args()
    result = study(load(args.path), min_trades=args.min_trades,
                   train_fraction=args.train_fraction)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"out": str(path), "verdict": result["verdict"],
                      "selected": result["selected"],
                      "out_of_sample": result["out_of_sample"]}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
