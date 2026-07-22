# Crypto Trading Bot

Compact research-to-execution bot, initially targeting Hyperliquid perpetuals.

## Current v0 thesis

Measure whether liquid hourly funding extremes predict profitable price reversion after realistic trading costs. `bootstrap_history.py` builds an immediate chronological panel from Hyperliquid's official funding-history and hourly-candle endpoints; `scout.py` keeps collecting live cross-sectional snapshots; `evaluate.py` converts completed horizons into explicit contrarian trades and reports net performance. This remains an experiment, not a trading signal.

```bash
python bootstrap_history.py --coins BTC,ETH,SOL --days 180 --out data/history.jsonl
python evaluate.py data/history.jsonl --horizon 1 --min-funding-bps 0.5 --roundtrip-bps 9 --trades-out data/trades-1h.jsonl
python evaluate.py data/history.jsonl --horizon 4 --min-funding-bps 0.5 --roundtrip-bps 9
python scout.py --out data/snapshots.jsonl
python -m unittest -v
```

The bootstrapper paginates funding history, chunks candle requests below Hyperliquid's 5,000-candle limit, aligns each funding event to its hourly close, and emits the same JSONL schema consumed by the evaluator. The evaluator only pairs observations near the requested future horizon, adds funding received by fading the paying side, subtracts configurable round-trip costs, and exposes trade-level JSONL for diagnosis.

No live trading is implemented or authorized.
