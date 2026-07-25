# Crypto Profit Research

A compact research repository for finding an executable crypto edge. **No profitable strategy or live bot is established yet.**

## Current evidence

Corrected 180-day fixed-universe research rejected both previous strategies:

- funding fade: walk-forward mean `-0.1452%`, LCB95 `-0.3107%`, finite-capital return `-17.74%`;
- hourly cross-sectional momentum/reversal: OOS mean `-0.1315%`, LCB95 `-0.1791%`, finite-capital return `-81.99%`.

Those strategies are retired. Their implementations were removed; results remain in Git history.

## Active experiment

`CROSS_VENUE_EXPERIMENT.md` defines one prospective, delta-neutral BTC/ETH funding-and-basis experiment using Hyperliquid and OKX public data.

The five-minute scheduled workflow:

1. restores the latest successful scheduled series;
2. collects synchronized executable books and pre-entry funding fields;
3. builds delayed-entry event windows;
4. joins exact realized funding after settlement;
5. computes two-leg P&L with frozen base and stress costs;
6. checks append-only evidence and coverage;
7. applies the fixed development/holdout gate.

Profitability cannot be claimed before at least 200 independent completed funding periods spanning 56 days, including 60 untouched holdout periods. Passing permits shadow signals only—not orders.

## Active code

Market and research logic:

- `crossvenue_snapshot.py` — Hyperliquid/OKX public-data collector.
- `crossvenue_events.py` — leakage-safe signal, entry, and exit windows.
- `crossvenue_settlements.py` — exact realized-funding joins.
- `crossvenue_pnl.py` — two-leg costs and trade P&L.
- `crossvenue_validate.py` — fixed prospective development/holdout validation.
- `crossvenue_coverage.py` — missing-opportunity and duplicate detection.
- `crossvenue_promote.py` — authoritative keep/reject/wait verdict.
- `crossvenue_freeze.py` — immutable experiment contract and cutoff.
- `crossvenue_chain.py` — append-only evidence check.

Minimal persistence:

- `crossvenue_scheduled_artifact.py` — selects the latest successful scheduled artifact.
- `crossvenue_artifact.py` — bounded credential-safe download.
- `crossvenue_bundle.py` — one safe staged extractor.

Workflows:

- `ci.yml` tests active research code only when code changes.
- `crossvenue-probe.yml` collects evidence every five minutes; it does not rerun the full test suite.

## Profit-first rules

- Spend development effort on market mechanisms, real data, cost modeling, and decisive experiments—not infrastructure decoration.
- Do not add health, binding, provenance, transport-gate, or security layers without a reproduced failure that threatens evidence correctness.
- Do not alter the frozen cross-venue contract while it is collecting unless a demonstrated defect makes its evidence invalid.
- Keep at most one additional discovery hypothesis active at a time.
- Before coding a new strategy, predeclare its mechanism, data, executable entry/exit, full costs, leakage controls, and rejection gate.
- Prefer strategies that can reach a credible verdict quickly with public historical data or short prospective collection.
- Reject weak ideas rather than repeatedly retuning them.
- Do not build order execution until a strategy passes research and prospective shadow gates.

## Immediate objective

Let the cross-venue experiment accumulate untouched. In parallel, research exactly one economically distinct, fast-feedback opportunity and implement it only after its data and execution assumptions are verified. The next milestone must improve edge discovery or produce market evidence—not another layer around GitHub artifacts.
