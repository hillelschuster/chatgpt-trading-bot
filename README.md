# Crypto Trading Bot

Compact research-to-execution bot, initially targeting Hyperliquid perpetuals.

## Current v0 thesis

Funding fade is rejected by the first live train/test evidence. The active benchmark now tests cost-aware cross-sectional momentum and reversal across a current liquid-perpetual universe rather than only BTC/ETH/SOL.

```bash
python bootstrap_history.py --auto-coins 12 --min-day-volume 10000000 \
  --min-assets 6 --days 180 --out data/history.jsonl --meta-out reports/universe.json
python research.py data/history.jsonl \
  --out reports/funding_fade.json \
  --trades-out reports/oos_trades.jsonl \
  --ledger-out reports/portfolio_ledger.jsonl \
  --min-trades 30 --capital 10000 --max-positions 3 --max-trade-notional 5000
python walkforward.py data/history.jsonl \
  --out reports/walkforward.json \
  --trades-out reports/walkforward_trades.jsonl \
  --ledger-out reports/walkforward_ledger.jsonl \
  --folds 4 --min-trades 30 --capital 10000
python xsection.py data/history.jsonl \
  --out reports/xsection.json \
  --trades-out reports/xsection_trades.jsonl \
  --ledger-out reports/xsection_ledger.jsonl \
  --min-trades 40 --min-assets 6 --capital 10000
python scout.py --out data/snapshots.jsonl
python -m unittest -v
```

`bootstrap_history.py` selects the most liquid active perps from official `metaAndAssetCtxs`, records the selection and current liquidity in `reports/universe.json`, downloads official funding/candle history with retries, filters sparse hours, and reports panel coverage. Pass `--coins` to force a fixed universe.

`research.py` performs a single train/test funding-fade selection. `walkforward.py` is the stricter repeated past-only gate. `xsection.py` benchmarks 1/4/8/24-hour momentum and reversal only when at least six assets share the entry, lookback, and exit timestamps; it reports actual breadth, charges 3–12 bps round-trip costs, selects only on training data, exports untouched trades, and simulates two-sided finite-capital deployment.

The portfolio simulator settles P&L only at exit, sizes from then-available equity, rejects excess overlap, caps notional, and reports utilization and drawdown. The automated workflow tests the repository, downloads 180 days for twelve currently liquid perps, runs all validation paths, and commits compact reports, raw untouched trades, accepted ledgers, and universe metadata.

Current-universe selection introduces survivorship bias, so a positive result is exploratory rather than deployable evidence. The next validation must use historical universe membership or repeated archived selections.

No live trading is implemented or authorized.
