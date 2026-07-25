# Crypto Profit Research

A compact research repository for finding an executable crypto edge. **No profitable strategy or live bot is established.**

## Repository layout

```text
.
├── README.md
├── PROGRESS.md
├── docs/
│   └── CROSS_VENUE_EXPERIMENT.md
├── src/
│   ├── crossvenue_snapshot.py
│   ├── crossvenue_events.py
│   ├── crossvenue_settlements.py
│   ├── crossvenue_pnl.py
│   ├── crossvenue_validate.py
│   ├── crossvenue_promote.py
│   ├── crossvenue_coverage.py
│   ├── crossvenue_freeze.py
│   ├── crossvenue_chain.py
│   ├── crossvenue_artifact.py
│   ├── crossvenue_scheduled_artifact.py
│   └── crossvenue_bundle.py
├── tests/
│   └── test_crossvenue_*.py
└── .github/workflows/
    ├── ci.yml
    └── crossvenue-probe.yml
```

Root policy: no Python implementation, tests, generated market data, reports, temporary experiment drafts, or abandoned strategies belong in the repository root.

## Established evidence

Corrected fixed-universe research rejected both prior strategy families:

- funding fade: walk-forward mean `-0.1452%`, LCB95 `-0.3107%`, finite-capital return `-17.74%`;
- hourly cross-sectional momentum/reversal: OOS mean `-0.1315%`, LCB95 `-0.1791%`, finite-capital return `-81.99%`.

They are retired and absent from the active tree. Their history remains in Git.

## Active experiment

`docs/CROSS_VENUE_EXPERIMENT.md` freezes one prospective, delta-neutral BTC/ETH funding-and-basis experiment using Hyperliquid and OKX public data.

The scheduled workflow restores the previous series, collects synchronized executable books and pre-entry funding fields, builds delayed-entry event windows, joins realized funding after settlement, computes two-leg P&L under frozen base and stress costs, checks evidence continuity and coverage, and applies the fixed development/holdout gate.

No profitability claim is permitted before at least 200 independent completed funding periods spanning 56 days, including 60 untouched holdout periods. A pass permits public-data shadow signals only—not orders.

## Commands

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
python -m py_compile src/*.py tests/*.py
```

## Profit-first rules

- Market evidence, realistic execution, complete costs, uncertainty, and decisive keep/reject results are the objective.
- Do not add infrastructure, monitoring, provenance, binding, or recovery layers without a reproduced evidence-critical failure.
- Do not alter the frozen experiment while it is collecting unless a demonstrated correctness defect invalidates its evidence.
- Do not create a strategy file or specification before real public-data feasibility has been successfully demonstrated.
- Keep at most one verified additional candidate active, and remove it immediately when rejected or blocked by unusable data.
- Do not build order execution until a strategy passes research and prospective shadow gates.

## Immediate objective

Keep the Hyperliquid–OKX experiment accumulating untouched evidence. Inspect completed artifacts for a valid keep/reject decision; otherwise perform research outside the repository until a second candidate has verified data access, measurable economics, and a compact predeclared experiment worthy of implementation.
