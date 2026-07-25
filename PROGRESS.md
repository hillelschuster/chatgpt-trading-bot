# Progress

Historical implementation detail remains available in Git history. This file records only current evidence, decisions, and the next profit-relevant milestone.

## 2026-07-25 — Repository structure reset

- **Thesis:** active research must be easy to inspect, run, and delete; flat root files and speculative candidate branches make the project harder to reason about without improving the chance of finding an edge.
- **Completed:** moved all preserved implementation into `src/`, all focused tests into `tests/`, and the frozen experiment contract into `docs/`; simplified CI and workflow paths; removed the unverified taker-flow candidate, its probe, its test, and its specification because no real archive had been successfully inspected.
- **Preserved:** the prospective Hyperliquid–OKX BTC/ETH collector, event construction, realized funding joins, two-leg P&L, coverage, append-only evidence, frozen validation, promotion verdict, and minimal artifact restoration required by the five-minute workflow.
- **Evidence:** the two completed historical strategy families remain rejected. The cross-venue experiment remains prospective and has not established profitability.
- **Verification:** the move reuses unchanged Git blobs for all preserved Python and test files; CI runs the complete active test discovery and Python compilation from the new structure before merge.
- **Verdict:** one active experiment only; no second candidate exists in the repository until real-data feasibility succeeds outside the tree.
- **Next:** inspect the newest cross-venue artifact for elapsed days, completed independent periods, failed attempts, base/stress returns, concentration, and exact remaining promotion gates.
