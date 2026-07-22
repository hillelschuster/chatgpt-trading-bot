# Crypto Trading Bot

Compact research-to-execution bot, initially targeting Hyperliquid perpetuals.

## Current v0 thesis

Test whether liquid hourly funding extremes predict profitable price reversion after realistic fees and funding paid or received *after* entry. `bootstrap_history.py` builds a chronological panel from Hyperliquid public history; `research.py` selects parameters only on the first 70% of time and verifies them on the untouched final 30%; `scout.py` continues collecting live cross-sectional snapshots. This remains an experiment, not a trading signal.

```bash
python bootstrap_history.py --coins BTC,ETH,SOL --days 180 --out data/history.jsonl
python research.py data/history.jsonl --out reports/funding_fade.json --min-trades 30
python evaluate.py data/history.jsonl --horizon 4 --min-funding-bps 1 --roundtrip-bps 9 --trades-out data/trades.jsonl
python scout.py --out data/snapshots.jsonl
python -m unittest -v
```

The bootstrapper paginates funding history, chunks candle requests below Hyperliquid's 5,000-candle limit, and aligns funding events to hourly closes. The evaluator never credits the funding payment that produced the entry signal; it includes only settlements occurring while the position is held, subtracts configurable round-trip costs, and reports uncertainty and drawdown. The GitHub workflow runs tests, downloads 180 days of BTC/ETH/SOL history, performs the chronological study, and commits the compact result to `reports/funding_fade.json`.

No live trading is implemented or authorized.
