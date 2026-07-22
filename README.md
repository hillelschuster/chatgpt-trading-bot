# Crypto Trading Bot

Compact research-to-execution bot, initially targeting Hyperliquid perpetuals.

## Current v0 thesis

Test whether liquid hourly funding extremes predict profitable price reversion after realistic fees and funding paid or received *after* entry. `bootstrap_history.py` builds a chronological panel from Hyperliquid public history; `research.py` performs one train/test selection; `walkforward.py` is the decisive anchored walk-forward gate; `portfolio.py` models finite capital and overlapping positions; `scout.py` continues collecting live cross-sectional snapshots.

The first 180-day train/test report rejected deployment: the selected setup produced a negative 95% lower confidence bound and a negative deployable portfolio return. Funding fade remains a research hypothesis, not a trading signal. It must pass the stricter walk-forward gate before any paper executor is built.

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
python evaluate.py data/history.jsonl --horizon 4 --min-funding-bps 1 --roundtrip-bps 9 --trades-out data/trades.jsonl
python portfolio.py data/trades.jsonl --capital 10000 --max-positions 3 --max-trade-notional 5000 --ledger-out data/portfolio.jsonl
python scout.py --out data/snapshots.jsonl
python -m unittest -v
```

The bootstrapper paginates funding history, chunks candle requests below Hyperliquid's 5,000-candle limit, and aligns funding events to hourly closes. The evaluator never credits the funding payment that produced the entry signal; it includes only settlements occurring while the position is held, subtracts configurable round-trip costs, and reports uncertainty and drawdown.

The walk-forward validator repeatedly selects parameters using only past data, tests the next untouched period, reports parameter stability, per-coin results, aggregate confidence, deployable portfolio performance, and cost sensitivity from 3–12 bps. Its verdict is `PROMISING` only when confidence, portfolio return, fold consistency, sample size, and every tested cost remain positive.

The portfolio simulator settles P&L only at exit, sizes from then-available equity and capital, rejects excess portfolio/per-coin overlap, caps notional, and reports utilization and drawdown. The automated workflow tests the repository, downloads 180 days of BTC/ETH/SOL history, runs both validation paths, and commits compact reports, raw untouched trades, and accepted ledgers.

No live trading is implemented or authorized.
