# Crypto Trading Bot

Compact Hyperliquid perpetual research code. **No deployable edge or live bot exists yet.**

## Current verdict

The earlier funding-fade result is invalidated: historical candles were keyed by their opening timestamp but valued with the closing price, leaking one hour of future information. The only completed live report also rejected the strategy out of sample. Cross-sectional momentum/reversal has not yet produced a trustworthy live report.

The corrected pipeline now:

- uses the hourly candle **open** at timestamp `t`, not the future close;
- fixes round-trip cost at a predeclared conservative 12 bps instead of optimizing the cost assumption;
- excludes ambiguous entry/exit funding-boundary payments;
- includes held funding in cross-sectional perp returns;
- ranks from information available at entry, uses non-overlapping pairs, and measures pair returns rather than treating two legs as independent trades;
- rate-limits historical downloads;
- calls portfolio drawdown `realized` because intratrade mark-to-market/liquidation risk is not modeled.

```bash
python -m unittest -v
python bootstrap_history.py --auto-coins 12 --min-day-volume 10000000 \
  --min-assets 6 --days 180 --request-delay 2.6 \
  --out data/history.jsonl --meta-out reports/universe.json
python research.py data/history.jsonl --roundtrip-bps 12
python walkforward.py data/history.jsonl --roundtrip-bps 12
python xsection.py data/history.jsonl --roundtrip-bps 12
```

Fast tests run on code pushes. The expensive real-data study runs manually or once daily and uploads its full dataset and reports as one workflow artifact; it does not write research outputs back to `main` or cancel itself during multi-commit development.

Current-universe selection still creates survivorship bias. Candle-open fills and fixed slippage remain approximations. No execution adapter, paper loop, order-book fill model, liquidation model, or live trading is implemented or authorized.
