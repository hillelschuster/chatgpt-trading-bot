# Crypto Trading Bot

Compact research-to-execution bot, initially targeting Hyperliquid perpetuals.

## Current v0 thesis

Measure whether liquid hourly funding extremes predict profitable price reversion after realistic trading costs. `scout.py` collects a chronological cross-sectional panel; `evaluate.py` converts completed horizons into explicit contrarian trades and reports net performance. This remains an experiment, not a trading signal.

```bash
python scout.py --out data/snapshots.jsonl
python evaluate.py data/snapshots.jsonl --horizon 1 --min-funding-bps 0.5 --roundtrip-bps 9 --trades-out data/trades-1h.jsonl
python evaluate.py data/snapshots.jsonl --horizon 4 --min-funding-bps 0.5 --roundtrip-bps 9
python -m unittest -v
```

The evaluator only pairs observations near the requested future horizon, adds the funding received by fading the paying side, subtracts configurable round-trip costs, and exposes trade-level JSONL for diagnosis.

No live trading is implemented or authorized.
