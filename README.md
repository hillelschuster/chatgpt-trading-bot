# Crypto Trading Bot

Compact Hyperliquid perpetual research code. **No deployable edge or live bot exists yet.**

## Current verdict

Corrected fixed-universe 180-day run `29949365810` used eleven assets with complete history (`AAVE,BTC,ETH,HYPE,LIT,NEAR,ONDO,PUMP,SOL,XRP,ZEC`), 4,320 hourly records, and 100% panel coverage.

- Funding fade: the single split had a small positive portfolio result, but the selected training rule was negative and untouched confidence remained negative. Anchored walk-forward mean was `-0.1452%`, LCB95 `-0.3107%`, and finite-capital return `-17.74%`.
- Cross-sectional momentum/reversal: untouched mean was `-0.1315%`, LCB95 `-0.1791%`, and finite-capital return `-81.99%`; it remained negative from 9 to 18 bps costs.

**Both strategies are retired.** Do not retune them on this sample or build execution around them.

The corrected pipeline:

- uses the hourly candle **open** at timestamp `t`, not the future close;
- fixes round-trip cost at a predeclared 12 bps instead of optimizing the cost assumption;
- excludes ambiguous entry/exit funding-boundary payments;
- includes held funding in cross-sectional perp returns;
- uses past-only selection, non-overlapping pairs, and finite-capital exit-time accounting;
- requires all eleven fixed assets at every retained hour;
- calls portfolio drawdown `realized` because intratrade mark-to-market/liquidation risk is not modeled.

```bash
python -m unittest -v
python bootstrap_history.py \
  --coins AAVE,BTC,ETH,HYPE,LIT,NEAR,ONDO,PUMP,SOL,XRP,ZEC \
  --min-assets 11 --days 180 --request-delay 2.6 \
  --out data/history.jsonl --meta-out reports/universe.json
python research.py data/history.jsonl --roundtrip-bps 12
python walkforward.py data/history.jsonl --roundtrip-bps 12
python xsection.py data/history.jsonl --roundtrip-bps 12 --min-assets 11
```

Fast tests run on code pushes. The expensive study runs manually or weekly on Monday and uploads one immutable artifact; it does not write generated results to `main` or cancel an active run.

A strategy may proceed only when aggregate walk-forward LCB95 is positive, at least three of four OOS folds have positive means, performance remains positive at 18 bps, the finite-capital portfolio is positive, and no single asset supplies over half of profit.

The fixed list still reflects assets known to survive the full sampled period, candle-open fills remain approximate, and intratrade liquidation is not modeled. No execution adapter, paper loop, or live trading is implemented or authorized.
