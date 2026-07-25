# Binance Taker-Flow Exhaustion Experiment

## Status

Predeclared discovery candidate. No result has been inspected and no edge is claimed.

## Economic mechanism

A large one-sided USD-M perpetual taker burst can temporarily move price beyond immediately available passive liquidity. If the burst reflects forced or urgent execution rather than new information, the marginal aggressive flow should decay and passive liquidity should refill, producing short-horizon mean reversion. The candidate is economically distinct from funding fade, cross-sectional momentum/reversal, and the active Hyperliquid–OKX funding/basis experiment.

The falsifiable hypothesis is: after an unusually large, one-sided five-second BTCUSDT aggressive-notional shock accompanied by same-direction price impact, a delayed contrarian market entry earns positive net returns over 60 seconds after conservative taker fees and slippage.

## Primary-source feasibility

Binance's official public-data repository publishes daily and monthly USD-M Futures `aggTrades` ZIP files. The documented fields match `/fapi/v1/aggTrades`: aggregate trade ID, price, quantity, first/last trade IDs, millisecond timestamp, and whether the buyer was maker. Daily files are normally available the next day and have companion SHA-256 checksums.

Primary sources:

- https://github.com/binance/binance-public-data/blob/master/README.md
- https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Compressed-Aggregate-Trades-List

These fields are sufficient to reconstruct aggressive buy/sell notional and transaction prices. They do not provide historical order-book depth or liquidation identity, so the experiment tests taker-flow exhaustion—not liquidation-specific causality. Any positive result must survive conservative slippage without claiming queue-position or maker-fill advantages.

## Frozen scope

- Venue: Binance USD-M Futures.
- Instrument: BTCUSDT perpetual only.
- Source: official daily `aggTrades` archives and checksum files.
- Development sample: 28 consecutive complete UTC days ending at least two days before the download date.
- Final holdout: the immediately following 14 complete UTC days, selected before any result inspection.
- Maximum research scope: one signal definition, two fixed cost levels, one fixed holding period, and no parameter sweep.
- Stopping rule: reject after the first valid 42-day evaluation unless the pipeline itself is demonstrably incorrect.

## Data and timestamp semantics

For every aggregate trade retain:

- `agg_trade_id`;
- execution price and base quantity;
- quote notional = price × quantity;
- transaction timestamp in Unix milliseconds;
- aggressor sign: `+1` when `is_buyer_maker=false` and `-1` when `true`.

Sort by `(timestamp, agg_trade_id)`. Reject duplicate IDs with conflicting fields, decreasing timestamps, missing UTC days, malformed rows, non-positive price/quantity, or checksum mismatch. Five-second buckets are half-open `[t, t+5s)` UTC intervals.

## Signal available before entry

For each five-second bucket compute:

- signed aggressive quote notional;
- total aggressive quote notional;
- open and close transaction prices;
- signed bucket return.

Using only the previous 360 completed buckets (30 minutes), compute median and median absolute deviation of signed notional. A candidate shock occurs when:

1. absolute robust z-score of signed notional is at least 8;
2. total quote notional is at least USD 5 million;
3. bucket price return has the same sign as aggressive flow and absolute magnitude is at least 4 basis points;
4. no position or cooldown event is active.

Direction is contrarian to the shock. The shock bucket itself is never an executable entry.

## Execution and exit

- Decision time: shock-bucket close.
- Latency: skip the next complete five-second bucket.
- Entry: first aggregate-trade price in the following bucket, adversely shifted by 2 bps against the strategy.
- Exit: first aggregate-trade price at or after 60 seconds from entry, adversely shifted by 2 bps against the strategy.
- If no eligible entry appears within 10 seconds or no exit appears within 10 seconds of the target, mark the attempt failed and assign the stress loss described below.
- Only one position may be open. A 120-second cooldown begins after exit. This prevents overlapping dependent bets.
- Fixed notional: USD 1,000. No leverage benefit is credited; capital return uses the full USD 1,000 as occupied capital.

## Costs and failure assumptions

Base case:

- taker fee: 5 bps per side;
- slippage: 2 bps per side already embedded in executable prices;
- total explicit fee: 10 bps round trip;
- no maker rebates;
- no funding credit or debit because maximum holding time is approximately one minute and any funding-boundary trade is excluded.

Stress case:

- taker fee: 6 bps per side;
- slippage: 5 bps per side;
- each missing/failed exit is closed at the worst observed price during the next 120 seconds plus stress slippage;
- add 3 bps operational penalty per completed trade.

Exclude signals whose holding interval can cross a Binance funding timestamp. No transfer-cost assumption is needed for a single-venue, short-duration research trade; this does not authorize execution.

## Evaluation and leakage controls

- Compute features from completed prior buckets only.
- Use delayed future trades solely as simulated executable entry/exit prices.
- Freeze the development/holdout dates before reading P&L.
- Do not alter thresholds after development results are viewed.
- Report every signal and failed attempt in a trade ledger.
- Use non-overlapping positions and a stationary block bootstrap with 30-minute blocks for the mean net return confidence interval.
- Report daily and weekly concentration, long/short balance, worst-day contribution, and maximum drawdown.

## Deterministic verdict

The candidate passes research only if all conditions hold on the untouched 14-day holdout:

- at least 80 completed trades and at least 8 active UTC days;
- base net mean return > 0;
- 95% block-bootstrap lower confidence bound > 0;
- stress net mean return > 0;
- finite-capital cumulative return > 0 after sequential USD 1,000 occupancy;
- no single day contributes more than 30% of positive gross P&L;
- neither direction contributes more than 75% of trades;
- failed-entry/exit attempts are below 2%;
- result remains positive after removing the best UTC day.

Failure of any gate rejects the candidate. A pass permits only an independent prospective public-data shadow phase; it does not permit orders.
