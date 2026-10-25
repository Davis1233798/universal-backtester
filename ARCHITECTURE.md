# Large-scale cross-venue architecture / 大規模多交易所回測設計

## User requirements (non-negotiable)
- Full available market history, not 1,500 candles and not a fixed number of API pages.
- One saved strategy evaluated independently on thousands of CEX/DEX instruments; identical time windows, venue-specific fees, funding, gas, quote currency and fill logic.
- Candlesticks remain interactive at 100M+ data points by loading **only visible data**. Backtests never consume downsampled K lines.
- User-supplied Pine must run efficiently and must fail loudly on unsupported language constructs. Do not misrepresent a partial interpreter as full TradingView Pine.
- Resource budgets manage *running jobs*, not arbitrarily truncate market history.

## What is shipped now (2026-10-25)
- Python multiprocess parallel batch endpoint `POST /api/backtests/batch` for trusted/private deployments.
- Each market gets its own strategy instance, risk parameters and accounting; independent failures are returned as errors.
- `GET /api/candles` streams SQLite rows by requested time range and returns OHLCV time buckets sized to visible-resolution; in-memory demo previews follow the same display-only principle.
- Web display uses Lightweight Charts v5 from a CDN (requires CDN availability).
- Historical CCXT/funding pagination is end-time governed rather than cut off at 2,000 pages, though provider retention and rate limits still apply.
- The *public synthetic demo only* has configurable `UBT_PUBLIC_DEMO_MAX_BARS` default 50,000; it is not a cap on the real historical engine.

**NOT shipped yet:** Native Rust backtest kernel, distributed workers/queues, native Parquet lake, full Pine v5/v6 compiler, full DEX on-chain fill/gas/L2 simulator, production-grade authentication, or synchronized cross-exchange portfolio ledger. CPU-heavy Python execution currently loads full series in each worker. A 1-billion-bar task cannot yet be considered supported or benchmarked. Avoid marketing these as finished.

## Data pipeline (target)
```text
CEX/DEX/Equity adapters + archive vendors + chain RPC/indexers
  -> rate limited, checkpointed collectors (exchange-agnostic, source trace)
  -> canonical schema:
     venue, market_id, native_symbol, instrument_type, base, quote, settle,
     contract_size, tick_size, lot_size, timezone, session/calendar,
     open_time_utc, OHLCV, trades, bid/ask, funding, gas, corporate actions,
     source, source_version, ingestion_time, completeness flag
  -> deduplication by unique venue/market/timeframe/timestamp
  -> gap detection, outlier reports, source revision history
  -> hot cache / Parquet partitions / DuckDB or ClickHouse for discovery
  -> read-only Arrow RecordBatch streams into Rust replay engine
  -> results persisted separately (metrics, fills, equity checkpoints)
  -> downsampled/render-only tile API (viewport zoom dependent)
```
Use partition keys that match the workload, e.g. venue + asset + interval + year/month.
Preserve exact timestamps and contract multipliers; do not fill missing OHLCV silently.
For multi-exchange alignment, use a canonical UTC grid and explicit missing/misaligned
bars rather than interpolating prices. Contract funding and DEX fee accounting
must be venue-specific. Maintain reproducibility with source snapshots and strategy hashes.

## Engine (target)
1. Rust core with typed columnar input and linear event replay: fill at next open,
   liquidation/fees/funding, entry/exit bookkeeping and execution assumptions.
2. Strategy parser/adapter: Pine source -> validated typed IR -> bytecode/compiled
   kernels; compile **once per strategy revision**, not once per candle. Maintain
   incremental rolling state for EMA/SMA/RSI; O(1) updates for fixed windows where
   mathematically possible. No arbitrary Python call per candle on the hot path.
3. Parallelism: one task per (venue, instrument, strategy, interval, parameter
   scenario); a bounded work-stealing scheduler (Rust Rayon or equivalent) runs
   independent books in parallel. Cross-venue *shared capital* mode requires
   synchronized events across all streams; independent books are not a portfolio.
4. Pine features such as request.security must use only last CLOSED higher-timeframe
   bar unless explicitly configured otherwise, with golden reference tests against
   TradingView. Unsupported constructs must return an error rather than silently
   generating misleading trades. Sandbox untrusted custom code (e.g., WebAssembly)
   with CPU/memory/time bounds; do not directly execute user Python/JS on public workers.
5. Use floating-point (or fixed-decimal for fee/contract precision) according to
   instrument specification, and test numerical stability over long histories.
6. Stream strategy computation while persisting fills and equity checkpoints;
   do not send millions of rows over one HTTP response.

## K-line charting (target)
- Lightweight Charts or a WebGL canvas renders only current viewport, normally
  hundreds/thousands of bars, NOT every stored point.
- Viewport queries `/api/candles?start=...&end=...&max_points=...` return
  min/max-preserving time buckets and exact bars when zoomed in. Each display bucket
  includes the number of underlying bars. The current API supports range queries;
  automatic infinite historical scroll and a persistent resolution pyramid
  still need implementation.
- Overlays/strategy markers should be indexed by time in a separate layer; request
  visible markers only and avoid creating 100M DOM nodes.
- Every analytical calculation reads original raw-resolution bars; never reuse
  display-aggregated candles for strategy evaluation or report metrics.

## Historical coverage / realism
- CCXT pagination is exchange-dependent; absence of older candles is not a
  software timeout. Archive data that cannot be queried again, and allow
  licensed data suppliers and user CSV/Parquet imports.
- Hyperliquid's candleSnapshot returns a rolling history (about 5,000 bars);
  long periods need a historical archive. DEX simulations need chain indexer
  events/gas/network effects; a DEX OHLCV is not equivalent to an order-book fill.
- Stock markets differ in corporate actions, currency, trading sessions and
  market holidays; canonical timestamps must not erase these distinctions.

## Quality and performance acceptance gates
- Golden backtests comparing fees, funding, liquidation, entry/exit and R units
  against the existing Python behavior. Differences must be documented before any
  engine substitution.
- Test 1e5, 1e6, 1e7, 1e8 bars on cold/hot caches, and 1/8/32 simultaneous markets;
  publish bars/s, peak RSS, disk throughput, startup time, end-to-end runtime.
- Parallel comparisons must be deterministic for a fixed source snapshot/strategy
  hash and input configuration, including error isolation and the seed for random
  strategies.
- Check chart rendering latency and memory in Chromium with huge stored histories.
- Measure Pine complexity per bar and the compiled-vs-interpreted throughput.
  No performance multiplier should be claimed without replicable benchmarks.

## Deployment
Keep public Render demo isolated from private market/strategy execution.
Run CPU-intensive workload workers on dedicated compute (including Rust-native worker
containers) rather than Render free web instance. Keep the web API for job submission,
progress/status, partial result streaming and visualization. Backtest jobs must
be cancellable/resumable and support checkpoint + idempotency; this is not implemented yet.
