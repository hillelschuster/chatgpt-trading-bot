# Progress

Historical detail remains available in Git history. This file records only current decisions and evidence.

## 2026-07-25 — Profit-focus cleanup

- **Thesis:** the repository had shifted from finding an edge to repeatedly hardening GitHub artifact and health-report plumbing.
- **Completed:** removed the retired funding-fade/cross-sectional pipeline and its weekly workflow; removed the separate cross-venue health/provenance subsystem; collapsed restoration to one scheduled-artifact selector, one bounded downloader, and one staged extractor; stopped rerunning all tests inside every five-minute collection slot; narrowed CI to active research code; rewrote repository guidance around profitability.
- **Preserved:** the prospective Hyperliquid–OKX BTC/ETH collector, event construction, realized funding, two-leg P&L, coverage, append-only evidence, frozen validation, and promotion verdict.
- **Evidence:** the only completed corrected strategies remain rejected. No profitable edge is currently established.
- **Verification:** simplified bundle extractor passed five focused local tests and Python compilation; workflow YAML parsed locally. Full active CI must pass on the cleanup branch before `main` is advanced.
- **Unresolved:** the cross-venue experiment still needs sufficient prospective periods; its contract should remain untouched unless a reproduced correctness failure appears.
- **Next:** while that evidence accumulates, select exactly one fast-feedback, economically distinct strategy candidate and obtain a real-data keep/reject result without adding infrastructure layers.

## 2026-07-25 — Taker-flow exhaustion candidate frozen

- **Thesis:** extreme one-sided BTCUSDT perpetual taker flow may briefly overshoot available passive liquidity and mean-revert after urgent flow decays.
- **Completed:** predeclared one fixed 42-day Binance USD-M experiment with delayed contrarian entry, 60-second exit, non-overlap, base/stress costs, untouched 14-day holdout, concentration limits, and deterministic rejection gates; added a checksum-verifying official `aggTrades` archive probe with strict schema/order/duplicate validation and focused tests.
- **Evidence:** Binance's official public-data archive documents daily USD-M `aggTrades` with transaction price, quantity, millisecond timestamp, and buyer-maker flag, sufficient to reconstruct signed aggressive notional. Historical book depth and liquidation identity are unavailable, so the claim is limited to taker-flow exhaustion.
- **Verification:** source and tests were committed and re-read. Local network access could not resolve the official archive host, so no real archive result or local test execution is claimed in this run.
- **Verdict:** candidate is feasible and predeclared, but completely unproven.
- **Next:** run the probe on two complete official daily archives, inspect schema/continuity/bucket coverage, then implement the frozen evaluator only if the data probe passes.
