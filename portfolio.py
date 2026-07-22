#!/usr/bin/env python3
"""Simulate overlapping trades with finite capital and exit-time accounting."""
import argparse, json, math, statistics
from pathlib import Path


def load_trades(path):
    rows = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    return sorted(rows, key=lambda r: (int(r["time"]), int(r["exit_time"]), r["coin"]))


def simulate(rows, capital=10_000, max_positions=3, risk_fraction=1.0,
             max_trade_notional=5_000, max_coin_positions=1):
    if min(capital, max_positions, risk_fraction, max_trade_notional, max_coin_positions) <= 0:
        raise ValueError("capital and limits must be positive")
    if risk_fraction > 1:
        raise ValueError("risk_fraction cannot exceed 1")

    equity = peak = float(capital)
    max_dd = 0.0
    active, ledger = [], []
    rejected = {"slots": 0, "coin": 0, "capacity": 0}
    max_concurrent = 0
    max_gross_notional = 0.0

    def settle(until):
        nonlocal equity, peak, max_dd, active
        due = sorted((p for p in active if p["exit_time"] <= until),
                     key=lambda p: (p["exit_time"], p["time"], p["coin"]))
        for position in due:
            position["equity_before_exit"] = equity
            equity += position["pnl"]
            position["equity_after_exit"] = equity
            peak = max(peak, equity)
            max_dd = min(max_dd, equity / peak - 1)
            ledger.append(position)
        active = [p for p in active if p["exit_time"] > until]

    for row in rows:
        now = int(row["time"])
        settle(now)
        if int(row["exit_time"]) <= now:
            rejected["capacity"] += 1; continue
        if len(active) >= max_positions:
            rejected["slots"] += 1; continue
        if sum(p["coin"] == row["coin"] for p in active) >= max_coin_positions:
            rejected["coin"] += 1; continue

        gross = sum(p["notional"] for p in active)
        allocation = equity * risk_fraction / max_positions
        available = max(0.0, equity * risk_fraction - gross)
        notional = min(allocation, available, max_trade_notional)
        if notional <= 0:
            rejected["capacity"] += 1; continue

        position = {**row, "time": now, "exit_time": int(row["exit_time"]),
                    "notional": notional,
                    "pnl": notional * float(row["net_return_pct"]) / 100}
        active.append(position)
        max_concurrent = max(max_concurrent, len(active))
        max_gross_notional = max(max_gross_notional, gross + notional)

    settle(math.inf)
    pnls = [x["pnl"] for x in ledger]
    returns = [float(x["net_return_pct"]) for x in ledger]
    mean = statistics.fmean(returns) if returns else 0.0
    stdev = statistics.stdev(returns) if len(returns) > 1 else 0.0
    return {
        "starting_capital": capital, "ending_equity": equity,
        "return_pct": 100 * (equity / capital - 1),
        "accepted_trades": len(ledger), "rejected": rejected,
        "max_concurrent_positions": max_concurrent,
        "max_gross_notional": max_gross_notional,
        "max_capital_utilization_pct": 100 * max_gross_notional / capital,
        "win_rate_pct": 100 * sum(x > 0 for x in pnls) / len(pnls) if pnls else 0,
        "mean_trade_return_pct": mean,
        "mean_lcb95_pct": mean - 1.96 * stdev / math.sqrt(len(returns)) if returns else 0,
        "max_realized_drawdown_pct": 100 * max_dd,
        "gross_profit": sum(x for x in pnls if x > 0),
        "gross_loss": sum(x for x in pnls if x <= 0),
        "ledger": ledger,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", default="data/trades.jsonl")
    p.add_argument("--capital", type=float, default=10_000)
    p.add_argument("--max-positions", type=int, default=3)
    p.add_argument("--risk-fraction", type=float, default=1.0)
    p.add_argument("--max-trade-notional", type=float, default=5_000)
    p.add_argument("--max-coin-positions", type=int, default=1)
    p.add_argument("--ledger-out")
    a = p.parse_args()
    result = simulate(load_trades(a.path), a.capital, a.max_positions,
                      a.risk_fraction, a.max_trade_notional, a.max_coin_positions)
    if a.ledger_out:
        path = Path(a.ledger_out); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(x, separators=(",", ":")) for x in result["ledger"])
                        + ("\n" if result["ledger"] else ""))
    print(json.dumps({k: v for k, v in result.items() if k != "ledger"}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
