# Cross-venue funding/basis experiment v1

Status: **frozen prospective feasibility specification; no edge claim**.

## Mechanism

Hold equal USD notionals in opposite directions on Hyperliquid and OKX USDT swaps when the *pre-entry* predicted funding differential plus executable basis convergence can exceed all two-leg costs. Direction is long on the venue expected to pay less funding and short on the venue expected to pay more. BTC and ETH only.

Historical realized funding is insufficient for a valid backtest because the decision requires the prediction and executable books known before entry. Hyperliquid exposes current predicted funding; OKX exposes the current-period funding rate, funding timestamp, settled rate, premium and executable public swap book. Therefore v1 is prospective shadow collection, not reconstructed historical performance.

Binance USD-M and Bybit were both tested and rejected operationally for GitHub-hosted collection: Binance returned HTTP 451 and Bybit returned CloudFront HTTP 403. OKX public endpoints succeeded from the same runner. No proxy workaround is permitted.

## Frozen data contract

Capture every 5 minutes:

- collector timestamp and exchange book timestamps;
- Hyperliquid: coin, best bid/ask, mark, oracle, current/predicted funding, interval and next funding time;
- OKX: swap instrument, best bid/ask, last price, current-period predicted funding, premium, funding time, next funding time and settled rate;
- schema version and explicit symbol mapping.

Reject a snapshot when either book is missing/crossed, a book timestamp differs by more than 60 seconds, price is non-positive, symbol mapping fails, or required funding fields are absent. Store raw JSONL append-only; never revise observations after outcomes are known.

## Entry and exit

- Observe at least 10 minutes before the earliest relevant funding timestamp.
- Simulated entry occurs 60 seconds after the signal using adverse executable prices: buy at ask, sell at bid, plus fixed slippage.
- Require both legs to be executable within a 5-second coordination window; otherwise record a failed attempt and charge one-leg unwind cost.
- Hold through one funding event, then exit 60 seconds after both venues publish settlement using adverse executable prices.
- No transfers during a position. Capital is pre-funded 50/50 between venues.

## Costs

Predeclared base case per round trip:

- each venue: taker fee from the documented base/user tier, never optimized;
- slippage: 2 bps per fill per leg;
- one-leg failure reserve: 10 bps on affected notional;
- rebalancing reserve: 2 bps per completed trade across total capital;
- actual funding cash flows on both legs.

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

- Hyperliquid public `info`: `predictedFundings`, `metaAndAssetCtxs`, `l2Book`, and historical `fundingHistory`.
- OKX public APIs: `/api/v5/market/ticker`, `/api/v5/market/books`, `/api/v5/public/funding-rate`, and funding-rate history for swap instruments.

The collector preserves raw timing and funding fields because venue semantics can change. Any schema change invalidates collection until reviewed.
