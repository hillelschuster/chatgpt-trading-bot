# Crypto Trading Bot

Compact research-to-execution bot, initially targeting Hyperliquid perpetuals.

## Current v0 thesis

Start by measuring liquid funding dislocations. Hyperliquid settles funding hourly, exposes public market context through one API request, and has enough liquidity to test whether crowded positioning plus price behavior can produce a cost-aware edge. The first tool ranks liquid perps; it is a scout, not a trading signal.

```bash
python scout.py
python -m unittest -v
```

No live trading is implemented or authorized.
