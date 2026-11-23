# B.2 quote timing investigation — 23 November 2026

Based on PR #40 head `39142f94beca53bd5c841c92ab66f10a87cac52f` and its unchanged B.2 dependency. The Windows observations below were reported by the operator; no local Exness terminal or existing private journal was accessed in cloud validation.

## Finding and scope

There is a reproducible **pre-read UTC race**, independent of any real broker/PC clock offset. Previously `ShadowRuntime.step()` sampled UTC, then called `ShadowFeed.quote(now)`. That method performed the blocking `symbol_info_tick()` call and compared the returned tick against the earlier UTC. The B.2-backed `LiveObserver.step()` did the same at its initial and final quote reads. A newly arriving tick during that API call could be wrongly classified `QUOTE_FUTURE`.

Deterministic example, all timestamps UTC:

| Event | Time |
|---|---|
| Caller samples Python UTC | 12:00:10.000 |
| MT5 returns a tick generated during the read | 12:00:10.140 |
| Python UTC sampled after return | 12:00:10.140 |
| Old comparison against read start | age −140 ms: QUOTE_FUTURE |
| Correct comparison against read completion | age 0 ms: valid |

This explains a possible false future rejection; it **does not prove** the operator's measured 140 ms lead had this cause. If MT5 remains ahead of Python UTC sampled immediately **after** the read, clock alignment has not been established. That remains rejected, even for 1 ms or 140 ms. No automatic clock offset, timestamp clamp, second truncation, retry-until-fresh or skew allowance was added. A true cross-clock offset cannot safely be called legitimate from the supplied observations alone.

Ages 2.4–5.6 seconds exceed the existing two-second freshness rule and are correctly rejected. An unchanged tick can age while MT5 remains connected. B.2 also does substantial analysis/journal work before publishing, and its loop waits the configured interval after each step: total publication cadence is processing time plus that interval. A cached quote may become stale between polls or during processing. The change fixes read ordering, not all causes of intermittent stale snapshots. No freshness or acquisition-latency threshold changed.

## Exact code paths and clocks

1. **Timestamp decoding:** `iat/live_shadow/feed.py::observed_tick()` requires finite, integral MT5 `time` (UTC epoch seconds) and `time_msc` (UTC epoch milliseconds), with `time_msc // 1000 == time`. It derives the source timestamp from **milliseconds**, not rounded seconds. Bid/Ask must be finite and positive with Bid <= Ask. `age = validation_utc - source_tick_utc`; age < 0 raises `QUOTE_FUTURE`; age > 2 raises `QUOTE_STALE` for a current quote. Age exactly 0 or 2 is accepted. `historical=True` skips only current-quote staleness, not future rejection; capture timestamps must still lie within their requested/actual ranges.
2. **Acquisition failure:** `ShadowFeed.quote()` wraps those codes in `MarketDataError`. `ShadowRuntime.step()` starts each poll with local `quote=None`; a failure records the code and leaves that packet's quote null, never replacing it with an earlier successful quote. `LiveObserver` independently clears failed presentations. A connected terminal does not imply an eligible quote.
3. **Recorder times:** `capture.start/end` bound the actual historical tick interval; `received_at` is sampled later, after capture and precomputation. It is an observation/knowledge time, **not a replacement tick timestamp**. `iat/live_shadow/processor.py::reduce_packet()` independently requires source quote age in [0,2] at `received_at`, valid capture ordering and membership, and all existing quality/identity checks. Analysis taking too long can therefore still block a previously fresh quote.
4. **UI freshness:** `iat/live_shadow/runtime.py::ShadowRuntime.shadow_latest()` computes `observation_age_seconds = current_utc - last_received` and `quote_age_seconds = current_utc - quote.timestamp`. Negative recorder age, recorder age > `max(3, interval*2)`, null quote, or source quote age outside [0,2] produces `STALE_OR_UNAVAILABLE`, research `BLOCKED`, `CURRENT_QUOTE_OR_RECORDER_STALE`, and null unrealized PnL. This is a presentation check; it does not rewrite the frozen packet. `ReadOnlyJournalView` similarly checks source quote age.
5. **Repeated ticks:** the canonical quote ID hashes source timestamp, Bid, Ask, spread and fixed basis fields. It excludes local receipt time. `ShadowFeed.capture()` collapses exact duplicates within a batch; `iat/live_shadow/engine.py::quote_event()` ignores an already seen last quote ID. Different prices at the same millisecond are ambiguous and rejected. New local polls count as observations, not necessarily new market ticks. Same prices at a genuinely later MT5 timestamp represent a distinct provider observation. Re-polling an unchanged timestamp never resets its age or creates another fill.
6. **B.3:** `iat/three_engine/evidence.py::build()` rejects null, stale, future or malformed source quotes at its shared cutoff. `reducer.market()` independently validates source receipt/capture timestamps and tick coverage. `contracts.proposal()` rechecks quote age at actual decision availability; `runtime.latest()` withholds stale marks based on quote and capture-watermark ages. Source consumption advancing is not data eligibility or authorization. Even healthy data does not enable absent provider, costs/account/margin metadata, session eligibility, strategy candidates or execution permission.

B.2's `quote.timestamp` and the legacy presentation field `observed_at_utc` denote the **provider tick time**, not Python read completion. The original generic `ReadOnlyMarketData.quote(datetime)` API has its own legacy limits and remains unchanged; B.2 uses the stricter `ShadowFeed` implementation. MT5 UTC epoch values are not broker chart-local hours; no timezone/DST conversion or Exness calendar modification belongs in this correction.

## Minimal correction

- `ShadowFeed.quote_observed(clock)` opts live acquisition into a callable clock. Sample read start, perform one tick read, sample read completion, reject backward clock movement, then run the unchanged validator against completion UTC. The explicit `quote(datetime)` API retains its original fixed-cutoff semantics for compatibility.
- The legacy observer uses that optional capability when available. Its final acquired-at timestamp and common candle recheck follow the quote read. Providers without this capability retain their existing API and limits.
- B.2 uses the same post-read protocol and closes capture after acquisition, including failed reads, so a successfully acquired quote cannot lie outside its own capture end simply because the API call took time.

Production delta is confined to those acquisition paths. No validator limit, source quote ID format, B.2/B.3 reducer, strategy, risk setting, calendar, execution gate or journal schema changed. Existing journals were not modified or migrated. Historical error packets remain historical error packets; there is no retrospective reclassification.

## Deterministic evidence

`tests/test_shadow_quote_timing.py` contains 12 synthetic tests covering:

- Original +140 ms during-read failure (the original runtime returned null/QUOTE_FUTURE), then healthy observer/B.2 acquisition and replay after the fix.
- True post-read future timestamps at +1 ms, +140 ms, +1 s and +5.6 s remain rejected.
- Correct milliseconds across a second boundary; inconsistent `time`/`time_msc` remain invalid.
- Fresh quotes through the inclusive two-second boundary; 2.001 s, 2.4 s and 5.6 s remain stale.
- A quote fresh at call start but 2.04 s old at completion remains rejected.
- Backward clock movement during the read fails closed.
- Repeated unchanged tick identity, no duplicated engine event, no age reset, and eventual stale rejection.
- RECORDING → stale/null → recovery only after a genuinely new source timestamp.
- Stale cached views withhold unrealized PnL without changing journal bytes.
- B.3 consumes corrected fresh data but does not enable its provider or execution; genuine future data stays quality-blocked in all engines.

The standalone original-runtime regression failed before the correction with `None : ['QUOTE_FUTURE']`. Tests targeting the newly introduced capability naturally could not run against the old API. After correction all 12 pass. Existing B.2 (48), observer (43), and B.3 (50) focused suites also pass. Full-suite totals and Linux/Windows Python 3.11/3.12 CI results are recorded in the draft PR against the delivered commit; real MT5 is not used in CI.

## Windows follow-up without modifying existing journals

Keep both Algo Trading and external Python API trading disabled. Preserve original source/comparison directories. Use a new local checkout/branch and NEW private journal directories for any comparative capture; do not append a trial to existing evidence simply to hide prior rejections. Follow the existing Stage B.3 operator guide with the fix branch and unchanged reviewed configurations.

For a direct, read-only clock probe, first stop the source recorder so this process does not interfere with its terminal connection. Run from the checkout on Windows Python 3.11 with the already connected DEMO terminal. This prints only UTC timing fields and validation codes, uses no credentials, and writes no files:

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
@'
import json, sys, time
from datetime import datetime, timezone
import MetaTrader5 as mt5
from iat.live_shadow.feed import ShadowFeed, observed_tick
from iat.mt5_data import MarketDataError
if sys.platform != 'win32' or sys.version_info[:2] != (3, 11):
    raise SystemExit('Windows Python 3.11 required')
try:
    if mt5.initialize(timeout=10000) is not True:
        raise RuntimeError('Terminal unavailable')
    ShadowFeed(mt5).preflight()  # DEMO, XAUUSD visible, both trading permissions disabled
    for _ in range(5):
        before = datetime.now(timezone.utc)
        tick = mt5.symbol_info_tick('XAUUSD')
        after = datetime.now(timezone.utc)
        try:
            observed_tick(tick, after)
            status = 'FRESH_AT_READ_COMPLETION'
        except ValueError as error:
            status = str(error)
        if tick is None:
            raise RuntimeError('Tick unavailable')
        at = datetime.fromtimestamp(tick.time_msc / 1000, timezone.utc)
        print(json.dumps(dict(read_started_utc=before.isoformat(),
            read_completed_utc=after.isoformat(), mt5_time=int(tick.time),
            mt5_time_msc=int(tick.time_msc),
            read_duration_ms=(after-before).total_seconds()*1000,
            age_vs_start_ms=(before-at).total_seconds()*1000,
            age_vs_end_ms=(after-at).total_seconds()*1000,
            status=status, signal='WAIT', execution_allowed=False, orders_requested=0)))
        time.sleep(.25)
except MarketDataError as error:
    print(json.dumps(dict(status='BLOCKED', code=error.code)))
except Exception:
    print(json.dumps(dict(status='BLOCKED', code='PROBE_UNAVAILABLE')))
finally:
    mt5.shutdown()
'@ | py -3.11 -
```

Interpretation:

- Negative `age_vs_start_ms` but nonnegative `age_vs_end_ms` proves arrival during the read rather than a post-read future tick.
- Negative `age_vs_end_ms` indicates a future provider timestamp relative to the completion sample (or a local backward clock step). Keep blocked. Verify the PC's UTC synchronization and provider timestamp convention independently. Do not alter timestamps, apply a guessed offset, or increase a threshold to get PASS.
- Unchanged `mt5_time_msc` with increasing age shows no newly timestamped market observation. That is not an MT5 disconnection by itself; once over two seconds it remains ineligible.
- Fresh probe results with stale recorder views require profiling acquisition, analysis, capture and publication latency. A probe alone does not prove continuous tick-capture completeness or eligibility.

No real-terminal timing probe has been run here. Real offset, quiet-market update cadence and Windows processing latency remain unmeasured from the supplied evidence. Calendar/finality/independent historical qualification remain pending. Research-only WAIT; execution_allowed=false; orders_requested=0; Exness BLOCKED; historical comparisons NOT_RUN. No PR merges or trading permission changes.
