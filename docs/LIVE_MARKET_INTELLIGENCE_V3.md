# Live Market Intelligence V3 presentation

This integration extends the existing read-only observer and dashboard. It adds
no acquisition engine, orders, strategy evaluation, calendar approval or default
AI calls. Exness remains BLOCKED, qualification DATA_NOT_QUALIFIED, historical
validation PENDING, comparisons NOT_RUN, signal WAIT and execution_allowed false.
Cloud evidence below uses invented OHLC and mocked MT5, never the operator's
terminal or a qualified historical export.

## Why formal intelligence can be unavailable

The existing observer calls `context_at(..., provenance='VALIDATED_LIVE')` using
completed M1/M5 candles. Without a reviewed calendar, it returns the expected
SESSION_CALENDAR_UNAVAILABLE gate. The Exness V2 candidate also deliberately has
unverified declarations and finite coverage. Its flags and dates are unchanged.
The operator's transitional M1 / bearish M5 observations do not establish formal
eligibility or explain away either restriction.

There is another independent restriction: the reviewed V3 adapter's adaptive
contract admits SYNTHETIC_RESEARCH and HISTORICAL_RESEARCH, not VALIDATED_LIVE.
Even a quality-valid live ContextReport is therefore BLOCKED by that adapter.
This integration preserves the actual typed context, calls the unchanged
adapter, validates its source binding and displays its actual blocked report.
It adds V3_LIVE_PROVENANCE_UNSUPPORTED as a presentation explanation when
applicable. It never substitutes an offline label to get a positive assessment.

The dedicated panel and `/live/intelligence/v3/snapshot` separate:

- Provider-observed Bid/Ask, broker point and spread in points (unavailable if
  Ask or point was not supplied; no guessed precision).
- Descriptive, unqualified observations: closed cutoffs, structure, confirmed
  swings, BOS/CHoCH, patterns, zones, liquidity, momentum, volatility, original
  confluence and evidence references. V1 window IDs are explicitly scoped to
  the current source and are not claimed as stable lifecycle identities.
- Typed formal context availability, actual V3 adapter status and restrictions.
  No formal fields are reconstructed from the descriptive layer.
- Safe runtime booleans, quote age, source fingerprint, processing time, cache
  counters and explicit WAIT reasons. Permission booleans describe the last
  observation, not a new terminal query on every HTTP request.

The old chart and V1/V2/AI-V3/shadow endpoints remain intact. The added panel
uses a separate endpoint so it cannot invalidate existing envelope checksums.
Its own SHA-256 covers the final presentation including runtime diagnostics;
processing latency and quote time naturally change that presentation hash.
The underlying unchanged formal artifact retains its own deterministic hash.
HTTP remains loopback-only, GET-only, no-store, rejects query strings, and uses
the existing CSP. DOM rendering uses textContent rather than HTML injection.

## Refresh and cache contract

Every existing observation interval still performs DEMO, connectivity, visibility,
terminal trading-disabled and external API trading-disabled checks, quotes,
position-1 native M1/M5 reads, clock, acquisition latency, candle completeness,
alignment, chronology, OHLC, gap and freshness checks. No cached bars replace
fresh acquisition. The existing overlapping M1/native M5 diagnostic still
compares complete groups and never substitutes aggregated M5.

One in-memory closed-analysis cache holds at most 500 M1 and 100 M5 normalized
OHLC rows plus their analysis. Its fingerprint binds those exact consumed rows,
closed cutoff, intelligence/context configuration, calendar bytes, current
calendar gate/phase, provider timestamp basis and VALIDATED_LIVE provenance.
Quote time/price and receipt time alone do not force expensive analysis to repeat.
No change is made to strategy predicates, ranking, scores or confluence settings.
Rows changing at the same cutoff still encounter the existing revision guard.
A binding failure is not reusable. Acquisition, permission, clock, serialization
or journal failure clears the cache; recovery recomputes it. The prior closed
report is withheld after failure.

HTTP reads do not touch MT5 or rerun analytical engines. They recheck source
snapshot binding, guarded clock, quote freshness, closed-bar quality/freshness
and current calendar fingerprint. A changed phase/expiry withholds presentation
until the next successful observation, rather than displaying an old gate.
A publication race also fails closed. Descriptive observations may remain
available with an explicitly blocked formal context, never as eligible V3.

The legacy observer's 30-second quote maximum and existing -2-second provider
allowance are unchanged. The separate B.2 ShadowFeed retains its strict
0..2-second policy and post-read clock protocol; no B.2/B.3 journals or services
are changed. The new presentation uses each provider's declared existing maximum
and additionally withholds **any future timestamp**, including timestamps inside
the legacy allowance. Neither policy gains a silent tolerance increase.
Repeated unchanged ticks retain their original timestamp and eventually expire.

## PR #44 lifecycle review

Code review of `sr_rejection.py` and its inherited regressions found these
contract boundaries: source-bound synthetic evaluation; historical evaluation
only through manifest binding; setup identity includes symbol, direction, zone
and touch; frozen anchors; immediate following closed-M1 confirmation; distinct
eligible-close expiry; no progress on blocked snapshots; terminal setups cannot
re-arm under the same identity; opposing CHoCH / frozen-zone loss invalidate;
simultaneous paper events remain unresolved. Same-cutoff revisions and late or
corrected history are rejected atomically. These are research semantics, not
execution rules or broker validation.

The live integration imports neither evaluator nor ledger and calls neither.
It displays only the literal registered identity/version, SYNTHETIC_ONLY and
live NOT_RUN. An independent integration test makes the evaluator raise if
called. Historical and real-terminal strategy validation remain pending. This
code review is not independent human approval or certification of PR #44.

## Windows 10 / Python 3.11 operator procedure

Fetch and check out this integration PR's branch in the existing
`E:\IAT2\IAT3-Live-Test` worktree before running the helper. Preserve local
changes; do not merge any PR. Stop the old dashboard in its own PowerShell
window with Ctrl+C if it occupies port 8768. The helper refuses occupied ports
and never kills another process. Keep the already authenticated **DEMO** MT5
terminal connected with Algo Trading and external Python API trading disabled.
No credentials are passed to the script or written into source.

With the existing Python 3.11 environment and dependencies installed, start:

```powershell
powershell.exe -NoProfile -File 'E:\IAT2\IAT3-Live-Test\diagnostics\Start-IATLiveMarketView.ps1'
```

Then open `http://127.0.0.1:8768`. The helper creates a new GUID-named private
journal under `E:\IAT2\IAT3-LiveLogs` (sibling of the worktree), does not reuse a
journal, and calls the existing runner with interval 10. Do not publish those
journals. Startup performs no downloads. If dependencies are missing, explicitly
install the repository requirements and official optional MT5 package:

```powershell
Set-Location 'E:\IAT2\IAT3-Live-Test'
py -3.11 -m pip install -r requirements.txt MetaTrader5
```

A setup-only check, without MT5 import/attachment, port query, journal creation or
service startup:

```powershell
.\diagnostics\Start-IATLiveMarketView.ps1 -ValidateOnly
```

Optional `-SessionConfig 'C:\path\reviewed-session.json'` only loads and strictly
validates that file; it never changes its verification flags. Without it,
SESSION_CALENDAR_UNAVAILABLE is expected. A candidate or expired calendar is
not a workaround. `-PythonExe` accepts an explicit Python 3.11 executable;
`-LogParent` must remain outside the repository. The original runner CLI remains
compatible. AI stays disabled: the helper exposes no AI opt-in flag and never
starts B.2/B.3 services.

For operator verification, inspect the panel's connection, DEMO, disabled trading
permissions, current quote age, closed M1/M5 cutoffs, processing milliseconds,
cache counters, context/adapter restrictions and execution=false. A fresh quote
refresh should increase cache hits until closed source or a gate changes.
Disconnecting MT5 or enabling a permission must withhold observations on the
next poll. Do not enable a permission merely to test against a real terminal;
that failure is covered with mocks. If the panel is unavailable, inspect its
reason codes, correct connectivity/visibility/dependencies and rerun with a new
journal. Do not change calendar approval or quote tolerances to clear a gate.

Actual Windows terminal success is **not established** by cloud CI. The operator
must supply reviewed, redacted runtime evidence before such a claim is made.

## Offline validation and limitations

Run `python -m unittest discover -s tests -v` on supported Python versions.
The focused `test_live_market_view.py` covers synthetic DEMO acquisition,
unknown/blocked calendars, live provenance, stale/future quotes, unfinished bars,
gaps, source and configuration changes, permissions, journal failure, cache
invalidation, repeatable public reads, no strategy activation, API compatibility
and DOM rendering/failure clearing using Node with stubbed browser objects.
The inherited lifecycle, journal, scoring, replay and timing tests are retained.
Windows CI also runs the PowerShell helper with `-ValidateOnly`, without MT5.

`python tests/benchmark_live_market_view.py` measures a reproducible **flat
synthetic** 10-poll workload with tracemalloc. It checks two computations and
eight cache hits, a one-entry cache and bounded 500/100 row retention. Results
include startup/new-close/cached processing times and traced allocation peak.
This measures neither Windows/MT5/network latency nor process RSS; real varying
markets can produce more evidence and cost more. Use runtime panel latency for
operator observations. No throughput or production-readiness claim is made.

No private source export was available or consumed. Historical validation is
PENDING and comparisons NOT_RUN. The V3 live-provenance contract and independently
verified dated broker calendar remain blockers to formal live intelligence;
this presentation integration does not authorize either. Review/approval of
those contracts belongs in a separate task with evidence and regression tests.

Measured example on Linux Python 3.11.9 (flat synthetic fixture, tracing enabled):
first poll 431.163 ms; eight cached polls 278.479–294.185 ms; new M1 close
415.020 ms; peak traced allocations 5,554,632 bytes; two computations / eight
hits / one cache entry. Reproduce with the benchmark command above; timings and
allocation counts vary by interpreter and host. These are not broker observations.
