# Crypto Trading Bot

Compact crypto market research code. **No deployable edge or live bot exists yet.**

## Current verdict

Corrected fixed-universe 180-day run `29949365810` used eleven assets with complete history (`AAVE,BTC,ETH,HYPE,LIT,NEAR,ONDO,PUMP,SOL,XRP,ZEC`), 4,320 hourly records, and 100% panel coverage.

- Funding fade: anchored walk-forward mean was `-0.1452%`, LCB95 `-0.3107%`, and finite-capital return `-17.74%`.
- Cross-sectional momentum/reversal: untouched mean was `-0.1315%`, LCB95 `-0.1791%`, and finite-capital return `-81.99%`; it remained negative from 9 to 18 bps costs.

**Both strategies are retired.** Do not retune them on this sample or build execution around them.

## Current experiment

`CROSS_VENUE_EXPERIMENT.md` freezes a prospective BTC/ETH funding/basis experiment using Hyperliquid and OKX public data. It collects only pre-entry predictions/current-period funding and executable books; historical realized funding is not treated as a historical prediction.

Live Actions probe `29966052184` verified the original collector and produced valid BTC/ETH rows. Binance USD-M and Bybit were rejected for GitHub-hosted collection after reproducible HTTP 451 and HTTP 403 responses; no proxy workaround is used.

Schema v4 preserves Hyperliquid's reported funding boundary and derives a strictly future effective boundary from its documented hourly interval when the reported value is stale. The collector runs every five minutes, restores the latest artifact, resumes by unique `(cadence_slot_ms, coin)` keys, and publishes continuity diagnostics. Missing schedule slots remain explicit gaps; they are never backfilled from future observations. **No profitability inference is permitted during collection.**

`crossvenue_events.py` builds deterministic candidate event windows from the prospective series. It freezes the last signal at least ten minutes before funding, applies a 60-second delayed entry, uses adverse bid/ask prices, requires five-second two-book coordination, preserves pending windows, and does not calculate returns or inspect a final holdout.

`crossvenue_settlements.py` joins complete windows to exact venue-published realized funding. Restored observations are monotonic: completed settlements are never refetched or downgraded, partial venue observations are retained, only missing legs are queried, duplicate boundaries share one API request, and transient endpoint failures remain explicit pending evidence rather than destroying the artifact chain.

`crossvenue_chain.py` compares the exact restored artifact with the newly generated series. Scheduled runs fail closed if the freeze manifest disappears or changes after complete evidence, a prior snapshot/event/settlement/P&L row disappears, duplicate keys appear, immutable event or P&L fields change, terminal statuses regress, exact settlement observations change, or settlement-attempt history decreases. A pre-evidence freeze upgrade is allowed only with nondecreasing freeze/cutoff timestamps and is explicitly reported.

`crossvenue_pnl.py` applies the frozen two-leg accounting contract only to exact settled events. Base costs are 4.5 bps Hyperliquid taker, 5 bps OKX taker, 2 bps slippage per fill and 2 bps rebalancing across total capital, for a 15.5 bps total-capital reserve. Stress cost is 20 bps. Rejected coordinated attempts receive the predeclared one-leg unwind reserve. Pending or invalid events are never scored, and the report forbids profitability inference before the frozen validation gate has 200 independent complete funding periods spanning at least 56 days.

`crossvenue_freeze.py` hashes the experiment specification and every module that can affect collection, eligibility, accounting, integrity, coverage, validation, or the authoritative promotion verdict. The first persistent run records the latest existing evidence timestamp as a cutoff. Later scheduled runs fail closed if any frozen file changes. Only attempts strictly after that cutoff are eligible for promotion, so code developed while observing earlier rows cannot claim them as prospective evidence. Coverage and promotion logic are part of the immutable contract; missing-data or verdict gates cannot be loosened without a visible pre-evidence re-freeze.

`crossvenue_validate.py` uses a fixed, non-moving partition by synchronized funding period: the first 140 post-freeze complete periods plus intervening failed attempts are development; all later periods are holdout. A complete period is one funding boundary with at least one exact complete attempt, so simultaneous BTC/ETH attempts never count as independent samples. Holdout metrics and ledgers remain suppressed until 60 complete holdout periods and at least 56 elapsed collection days exist. Every simultaneous attempt sizes from the same pre-period equity, same-time returns are aggregated before compounding, and block-bootstrap inference operates on period returns. Promotion also requires a valid append-only chain report from the same run; missing or invalid chain evidence makes the study `INVALID` before any holdout metric is exposed. The remaining gates enforce the frozen 70% positive-P&L concentration ceiling and below-5% failed-attempt rate, plus bootstrap, stress and finite-capital requirements.

`crossvenue_coverage.py` prevents outage-driven selection bias. After the freeze cutoff it requires at least 95% of expected five-minute coin-slots, at least 95% fully synchronized BTC/ETH slots, no duplicate coin-slot rows, and an event record for every funding opportunity observed with the required signal lead. `crossvenue_promote.py` is the authoritative verdict: profitability may be claimed only when both the frozen validation report and the 56-day coverage report pass. A profitable subset of surviving observations is never sufficient.

```bash
python -m unittest -v test_crossvenue_snapshot.py test_crossvenue_events.py \
  test_crossvenue_settlements.py test_crossvenue_chain.py test_crossvenue_pnl.py \
  test_crossvenue_freeze.py test_crossvenue_validate.py test_crossvenue_coverage.py
python crossvenue_snapshot.py --coins BTC,ETH --cadence-seconds 300 \
  --out data/crossvenue_snapshots.jsonl
python crossvenue_events.py data/crossvenue_snapshots.jsonl \
  --out data/crossvenue_events.jsonl --report reports/crossvenue_events.json
python crossvenue_coverage.py --snapshots data/crossvenue_snapshots.jsonl \
  --events data/crossvenue_events.jsonl --report reports/crossvenue_coverage.json
python crossvenue_settlements.py data/crossvenue_events.jsonl \
  --existing data/crossvenue_settled_events.jsonl \
  --out data/crossvenue_settled_events.jsonl \
  --report reports/crossvenue_settlements.json
python crossvenue_pnl.py data/crossvenue_settled_events.jsonl \
  --out data/crossvenue_pnl_events.jsonl --report reports/crossvenue_pnl.json
python crossvenue_freeze.py --evidence data/crossvenue_pnl_events.jsonl
python crossvenue_chain.py --previous-dir /tmp/crossvenue-prior \
  --current-dir data --report reports/crossvenue_chain.json
python crossvenue_validate.py data/crossvenue_pnl_events.jsonl \
  --chain-report reports/crossvenue_chain.json
python crossvenue_promote.py --validation reports/crossvenue_validation.json \
  --coverage reports/crossvenue_coverage.json
```

Passing the authoritative promotion gate permits shadow signals only, not orders.

## Retired research pipeline

The corrected historical pipeline:

- uses the hourly candle **open** at timestamp `t`, not the future close;
- fixes round-trip cost at a predeclared 12 bps instead of optimizing the cost assumption;
- excludes ambiguous entry/exit funding-boundary payments;
- includes held funding in cross-sectional perp returns;
- uses past-only selection, non-overlapping pairs, and finite-capital exit-time accounting;
- requires all eleven fixed assets at every retained hour;
- calls portfolio drawdown `realized` because intratrade mark-to-market/liquidation risk is not modeled.

The fixed list still reflects assets known to survive the sampled period. No execution adapter, paper loop, or live trading is implemented or authorized.
