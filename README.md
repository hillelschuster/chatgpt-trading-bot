# Crypto Trading Bot

Compact research-to-execution bot, initially targeting Hyperliquid perpetuals.

## Current v0 thesis

Test whether liquid hourly funding extremes predict profitable price reversion after realistic fees and funding paid or received *after* entry. `bootstrap_history.py` builds a chronological panel from Hyperliquid public history; `research.py` selects parameters only on the first 70% of time, exports untouched out-of-sample trades, and runs them through `portfolio.py`; `scout.py` continues collecting live cross-sectional snapshots. This remains an experiment, not a trading signal.

```bash
python bootstrap_history.py --coins BTC,ETH,SOL --days 180 --out data/history.jsonl
python research.py data/history.jsonl \
  --out reports/funding_fade.json \
  --trades-out reports/oos_trades.jsonl \
  --ledger-out reports/portfolio_ledger.jsonl \
  --min-trades 30 --capital 10000 --max-positions 3 --max-trade-notional 5000
python evaluate.py data/history.jsonl --horizon 4 --min-funding-bps 1 --roundtrip-bps 9 --trades-out data/trades.jsonl
python portfolio.py data/trades.jsonl --capital 10000 --max-positions 3 --max-trade-notional 5000 --ledger-out data/portfolio.jsonl
python scout.py --out data/snapshots.jsonl
python -m unittest -v
```

The bootstrapper paginates funding history, chunks candle requests below Hyperliquid's 5,000-candle limit, and aligns funding events to hourly closes. The evaluator never credits the funding payment that produced the entry signal; it includes only settlements occurring while the position is held, subtracts configurable round-trip costs, and reports uncertainty and drawdown.

The portfolio simulator processes exits chronologically, realizes P&L only at exit, sizes new positions from then-available equity and capital, rejects excess portfolio/per-coin overlap, caps notional, and reports capacity utilization and drawdown. The automated workflow tests the repository, downloads 180 days of BTC/ETH/SOL history, selects only on training data, and commits three reproducible artifacts: the compact study, raw out-of-sample trades, and the actual accepted portfolio ledger.

No live trading is implemented or authorized.
