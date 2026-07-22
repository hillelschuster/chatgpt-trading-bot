# Cross-venue funding/basis experiment v1

Status: **frozen prospective feasibility specification; no edge claim**.

## Mechanism

Hold equal USD notionals in opposite directions on Hyperliquid and Bybit linear perpetuals when the *pre-entry* predicted funding differential plus executable basis convergence can exceed all two-leg costs. Direction is long on the venue expected to pay less funding and short on the venue expected to pay more. BTC and ETH only.

Historical realized funding is insufficient for a valid backtest because the decision requires the prediction and executable books known before entry. Hyperliquid exposes current cross-venue predicted funding but not a historical prediction series; Bybit exposes current ticker funding, realized funding history, instruments, marks and books. Therefore v1 is prospective shadow collection, not reconstructed historical performance.

Binance USD-M was tested first and rejected operationally for this runtime: GitHub-hosted runners received HTTP 451 from both premium-index and depth endpoints. The venue was replaced rather than hidden behind an unreliable proxy.

## Frozen data contract

Capture every 5 minutes:

- timestamp from the collector and exchange book timestamps;
- Hyperliquid: coin, best bid/ask, mark, oracle, current funding, predicted funding, interval and next funding time;
- Bybit linear: symbol, best bid/ask, mark, index, current funding, Hyperliquid-reported Bybit prediction, interval and next funding time;
- schema version and explicit symbol mapping.

Reject a snapshot when either book is missing/crossed, a book timestamp differs by more than 60 seconds, price is non-positive, symbol mapping fails, or required funding timestamps are absent. Store raw JSONL append-only; never revise observations after outcomes are known.

## Entry and exit

- Observe at least 10 minutes before the earliest next funding timestamp.
- Simulated entry occurs 60 seconds after the signal using adverse executable prices: buy at ask, sell at bid, plus fixed slippage.
- Require both legs to be executable within a 5-second coordination window; otherwise record a failed attempt and charge one-leg unwind cost.
- Hold through one common funding event, then exit 60 seconds after both venues publish the event using adverse executable prices.
- No transfers during a position. Capital is pre-funded 50/50 between venues.

## Costs

Predeclared base case per round trip:

- each venue: taker fee from the documented base/user tier, never optimized;
- slippage: 2 bps per fill per leg;
- one-leg failure reserve: 10 bps on affected notional;
- rebalancing reserve: 2 bps per completed trade across total capital;
- funding cash flows from the actual observed settlement on each leg.

Stress case doubles slippage and applies the higher applicable taker fee. Maker assumptions are forbidden in v1.

## Evaluation

- Minimum prospective collection: 8 weeks and 200 complete candidate funding events across BTC/ETH combined.
- Development period: first 70% chronologically; final 30% remains quarantined until rules are frozen.
- Parameter scope: one entry threshold selected from a predeclared small grid; no asset-specific thresholds.
- Use non-overlapping event returns and block-bootstrap 95% confidence intervals by UTC day.
- Finite-capital simulation enforces 50/50 prefunding, one position per coin, and no reuse of occupied collateral.

## Promotion gate

All must pass on the quarantined period:

1. net mean return and block-bootstrap LCB95 are positive;
2. positive return under stress costs;
3. finite-capital return is positive with realized and mark-to-market drawdown below 10%;
4. neither coin contributes over 70% of positive P&L;
5. failed/partial two-leg attempts remain below 5%;
6. no timestamp, continuity, leakage, or symbol-mapping violation;
7. at least 60 independent completed events.

Failure retires v1 without threshold rescue on the same holdout. Success permits live public-data shadow signals only, not orders.

## Official API basis

- Hyperliquid public `info`: `predictedFundings`, `metaAndAssetCtxs`, `l2Book`, and historical `fundingHistory`; time-range responses paginate at 500 items and candles are limited to the latest 5,000 bars.
- Bybit V5 public market APIs: `/v5/market/tickers`, `/v5/market/orderbook`, `/v5/market/instruments-info`, and `/v5/market/funding/history`; funding intervals are instrument-specific and must not be assumed.

The collector preserves raw timing and funding fields because venue semantics can change. Any schema change invalidates collection until reviewed.
