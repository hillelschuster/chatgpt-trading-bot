# Crypto Trading Bot

Compact research-to-execution bot, initially targeting Hyperliquid perpetuals.

## Current v0 thesis

Funding fade is currently rejected by the first live train/test evidence. The repository now compares that thesis against a cost-aware cross-sectional benchmark that ranks BTC/ETH/SOL by trailing return, then tests both momentum and reversal using untouched out-of-sample data and finite-capital portfolio simulation.

```bash
python bootstrap_history.py --coins BTC,ETH,SOL --days 180 --out data/history.jsonl
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
  --min-trades 40 --capital 10000
python scout.py --out data/snapshots.jsonl
python -m unittest -v
```

`bootstrap_history.py` builds a chronological hourly panel from official public Hyperliquid funding and candle endpoints. `research.py` performs a single train/test funding-fade selection. `walkforward.py` is the stricter repeated past-only gate. `xsection.py` independently benchmarks 1/4/8/24-hour momentum and reversal across the available coins, charges 3–12 bps round-trip costs, selects only on training data, exports untouched trades, and simulates two-sided finite-capital deployment.

The portfolio simulator settles P&L only at exit, sizes from then-available equity, rejects excess overlap, caps notional, and reports utilization and drawdown. The automated workflow tests the repository, downloads 180 days of BTC/ETH/SOL history, runs all three validation paths, and commits compact reports, raw untouched trades, and accepted ledgers.

No live trading is implemented or authorized.
