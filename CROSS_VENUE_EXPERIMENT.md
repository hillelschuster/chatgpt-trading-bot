# Cross-venue funding/basis experiment v1

Status: **frozen prospective feasibility specification; no edge claim**.

## Mechanism

Hold equal USD notionals in opposite directions on Hyperliquid and OKX USDT swaps when the *pre-entry* predicted funding differential plus executable basis convergence can exceed all two-leg costs. Direction is long on the venue expected to pay less funding and short on the venue expected to pay more. BTC and ETH only.

Historical realized funding is insufficient for a valid backtest because the decision requires the prediction and executable books known before entry. Hyperliquid exposes current predicted funding; OKX exposes the current-period funding rate, funding timestamp, settled rate, premium and executable public swap book. Therefore v1 is prospective shadow collection, not reconstructed historical performance.

Binance USD-M and Bybit were both tested and rejected operationally for GitHub-hosted collection: Binance returned HTTP 451 and Bybit returned CloudFront HTTP 403. OKX public endpoints succeeded from the same runner. No proxy workaround is permitted.

## Frozen data contract

Capture every 5 minutes:

- collector timestamp, five-minute cadence slot and exchange book timestamps;
- Hyperliquid: coin, best bid/ask, mark, oracle, current/predicted funding, reported boundary, effective boundary and interval;
- OKX: swap instrument, best bid/ask, last price, current-period predicted funding, premium, funding time, next funding time and settled rate;
- schema version and explicit symbol mapping.

Hyperliquid pays funding hourly. Its raw `predictedFundings.nextFundingTime` is preserved. When that value is not after capture, the effective boundary is derived by advancing the reported boundary by the documented funding interval until it is strictly after capture. This normalization is deterministic, versioned and never changes the reported value.

Reject a snapshot when either book is missing/crossed, a book timestamp differs by more than 60 seconds, price is non-positive, symbol mapping fails, or required funding fields are absent. Store JSONL append-only. A `(cadence_slot_ms, coin)` key is unique: reruns resume without duplicating observations. Every artifact records duplicate, invalid, incomplete-slot and missing-cadence diagnostics. Missing cadence slots are retained as explicit gaps rather than repaired with future data.

## Entry and exit

- Observe at least 10 minutes before the earliest relevant effective funding timestamp.
- Simulated entry occurs 60 seconds after the signal using adverse executable prices: buy at ask, sell at bid, plus fixed slippage.
- Require both legs to be executable within a 5-second coordination window; otherwise record a failed attempt and charge one-leg unwind cost.
- Hold through one funding event, then exit 60 seconds after both venues publish settlement using adverse executable prices.
- No transfers during a position. Capital is pre-funded 50/50 between venues.

## Frozen event-alignment contract

`crossvenue_events.py` converts schema-v4 snapshots into deterministic event windows without calculating profitability:

- event identity is `(coin, Hyperliquid effective funding boundary, OKX current funding boundary)`;
- the signal is the latest valid snapshot still at least 10 minutes before the earliest boundary;
- entry is the first stored snapshot at or after signal plus 60 seconds, with no more than one cadence interval of lag;
- exit is the first stored snapshot at or after the later venue boundary plus 60 seconds, with no more than one cadence interval of lag;
- entry uses ask for the long leg and bid for the short leg; exit uses bid for the long leg and ask for the short leg;
- entry and exit books must be timestamped within five seconds of one another;
- incomplete future windows remain `pending`; uncoordinated books are `rejected`; neither is silently dropped or forward-filled;
- predicted funding and direction are frozen from the signal snapshot. Realized funding enrichment and P&L belong to the later evaluator and may not alter event selection.

The builder may run during collection and may report zero complete events. It must not inspect or score the quarantined final period.

## Costs

Predeclared base case per round trip:

- Hyperliquid base-tier perp taker fee: 4.5 bps per fill-side notional;
- OKX Lv1 USDT perpetual taker fee: 5 bps per fill-side notional;
- slippage: 2 bps per fill per leg;
- one-leg failure reserve: 10 bps on affected notional;
- rebalancing reserve: 2 bps per completed trade across total capital;
- actual funding cash flows on both legs.

With equal notionals and total capital defined as the sum of both venue allocations, base completed-trade fixed cost is 15.5 bps: 9.5 bps round-trip taker fees, 4 bps four-fill slippage and 2 bps rebalancing. Stress cost is 20 bps: 5 bps taker on each venue, 4 bps slippage per fill and the same 2 bps rebalancing. Maker assumptions are forbidden in v1.

## Frozen P&L contract

`crossvenue_pnl.py` is deterministic and may consume only events with complete coordinated entry/exit books and exact realized funding from both venues.

- Each leg receives 50% of total capital; price and funding returns are weighted on total capital.
- Positive funding means longs pay shorts. Funding signs follow the frozen long/short venue direction.
- Pending events are not scored. Structurally invalid complete events fail closed as `invalid`.
- Rejected two-book attempts are retained and charged 5 bps of total capital, equal to the 10 bps reserve on one half-capital leg.
- Base and stress costs are fixed constants, never optimized.
- Event-level output and aggregate diagnostics may accumulate during collection, but `profitability_claim_permitted` remains false. Formal inference belongs to the frozen validation stage after the minimum sample is reached.

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
6. no timestamp, duplicate, invalid-row, incomplete-slot, leakage or symbol-mapping violation;
7. at least 60 independent completed events.

Missing five-minute cadence slots reduce sample size and are reported; they are never forward-filled. Failure retires v1 without threshold rescue on the same holdout. Success permits live public-data shadow signals only, not orders.

## Official API basis

- Hyperliquid public `info`: `predictedFundings`, `metaAndAssetCtxs`, `l2Book`, and historical `fundingHistory`; official funding documentation states that funding is paid every hour.
- Hyperliquid official fee schedule: base-tier perp taker rate 0.045%.
- OKX public APIs: `/api/v5/market/ticker`, `/api/v5/market/books`, `/api/v5/public/funding-rate`, and funding-rate history for swap instruments. OKX `method=current_period` identifies `fundingRate` as the current-period rate.
- OKX official contract fee documentation: Lv1 USDT perpetual taker rate 0.05%.

The collector preserves raw timing and funding fields because venue semantics can change. Any schema change invalidates collection until reviewed.
