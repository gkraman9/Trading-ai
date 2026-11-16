# Historical session-boundary research v1

See the [architecture and gap analysis](HISTORICAL_SESSION_BOUNDARY_GAP_ANALYSIS_V1.md), written before implementation. The gap is diagnostic visibility, not ordinary candle eligibility. Session Engine v2 already reaches historical preparation through `prepare_package()` and the existing quality gate. Ordinary cross-frame alignment intentionally requires five M1 candles.

## What changed

Preparation now writes `session-boundary-research.json` beside its existing alignment audit and includes it in the preparation manifest's hashes. Existing qualification report contracts, source data, session calendars, strategies, thresholds, finality and execution gates are unchanged. Unavailable normalization produces an explicit unavailable sidecar. A standalone offline CLI can inspect the actual CSV column layout without inventing a strict import specification.

The report calls the existing v2 classifier. Its six geometry classes are `FULL_SESSION_BAR`, `PARTIAL_SESSION_OPEN`, `PARTIAL_SESSION_CLOSE`, `CROSSES_SESSION_BREAK`, `OUTSIDE_SESSION` and `UNKNOWN_SESSION`. Geometry does not establish broker finality, historical provenance or eligibility. Phase membership (`UNKNOWN`, `CLOSE_ONLY`, `FULL_TRADING`, etc.) is reported separately; a bar can touch multiple phases, so membership counts need not sum to the bar count.

A scheduled 21:55–22:00 M5 bar has 180 seconds of quote-session geometry if the declared close is 21:58. This can explain a partial bar conditionally. It does not prove what the broker exported or whether the partial bar is final. The report never aggregates three M1 bars to certify that M5 bar. `partial_finality` stays `UNESTABLISHED`; ordinary eligibility stays false. Ordinary validation still rejects partial bars inside its requested scope.

For absence explanations, the wrapper additionally checks coverage, expiry and evidence chronology. Under verified declarations, off-quote minutes are distinguished from unexpected missing full-session minutes. Under the checked-in Exness candidate, missing 21:58/21:59 observations remain `MISSING_UNESTABLISHED_UNVERIFIED_CALENDAR`. Calendar declarations are not independent source approval. Expiry and missing holiday/maintenance evidence are never silently cleared. The historical scope's end is the explicit observation cutoff; this does not renew the calendar for current operation.

Full numeric M1/M5 comparisons require intact chronology/OHLC, an elapsed nominal full M5 interval and all five distinct M1 observations. They are mechanical diagnostics only, including when the calendar or source remains unverified. There is no replacement of native M5 data. Complete counts cover the selected population; per-frame geometry and M5 examples are bounded to 64 entries, prioritizing boundaries and discrepancies. Inspect `m5_interval_total` and the sample-limit fields before interpreting examples as exhaustive.

## Exact next Windows command

Run from the new feature branch with Windows 10 and Python 3.11. These paths and filenames are supplied by the operator; no local CSV was available in the cloud. This command scans and hashes the original files read-only, selects an explicit UTC opening-time window, and writes a separate private research report. It does not import MetaTrader5, access the network, request credentials or approve data.

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
New-Item -ItemType Directory -Force -Path 'E:\IAT2\Reports' | Out-Null
py -3.11 diagnostics/historical_session_boundaries.py `
  --m1 'E:\IAT2\Data\XAUUSD_M1_Exness_20261111_20261113.csv' `
  --m5 'E:\IAT2\Data\XAUUSD_M5_Exness_20261111_20261113.csv' `
  --calendar 'config/profiles/exness-xauusd-v2.candidate.json' `
  --timestamp-column timestamp_utc `
  --start-utc '2026-11-11T00:00:00Z' `
  --end-utc '2026-11-14T00:00:00Z' `
  --report-path 'E:\IAT2\Reports\historical-session-boundaries-001.json'
```

Exit code **3 is expected for research-only results**, including successful inspection. The report must remain `DATA_NOT_QUALIFIED`, Exness `BLOCKED`, signal `WAIT` and execution false. `UNAVAILABLE` means inspect the files, schema, explicit UTC window and candidate validity before retrying. Existing output files are never overwritten; choose a fresh suffix. File hashes are checked before/after each scan. Scans stream at most ten million CSV records per source, select at most 5,000 rows per timeframe and allow at most 20,000 minutes per diagnostic window. Use multiple explicit smaller windows for larger archives; no truncated success is emitted. Malformed observations suppress trusted missing-bar and numeric-match conclusions. No source prices or sensitive account/server identifiers are copied into the report.

Inspect locally:

```powershell
$r = Get-Content -LiteralPath 'E:\IAT2\Reports\historical-session-boundaries-001.json' -Raw | ConvertFrom-Json
$r.frames.M5.classifications
$r.comparison_counts
$r.m1_slot_absence_counts
$r.m5_intervals | Where-Object { $_.geometry.classification -eq 'PARTIAL_SESSION_CLOSE' } | ConvertTo-Json -Depth 15
$r.qualification
$r.file_observations.sources
```

The reported 4,074 M1 / 816 M5 rows, 813 matches and three partial intervals remain **user-reported and unverified** until these actual files are inspected. The candidate schedule remains unverified. No real-terminal or real historical validation is claimed.

## Import worksheet and ordinary windows

[Operator worksheet](../config/examples/historical-session-boundary.operator-worksheet.json) records the known mapping: `timestamp_utc`, lowercase OHLC, `tick_volume`/`TICK`, null complete/symbol/basis/feed columns, and ignored spread/real-volume columns. Its unknown declarations are deliberate. It is **not an import spec** and must not be passed as `--spec` or `-ImportSpec`. The strict PR #21 schema requires declarations that the available evidence does not supply, including provider/feed identity and retrieval metadata. Creating a runnable valid-looking import would conceal those omissions. `DOCUMENTED_CLOSED_EXPORT` requires an actual referenced, checksummed finality document.

After truthful metadata and evidence become available, use the existing [pilot preparation workflow](REAL_DATA_PILOT_PREPARATION_V1.md). An operator can request a new explicit ordinary window ending at 21:55, rather than deleting partial rows inside an existing scope. Warm-up and evaluation limits still apply; inspect selected and archive row counts and preserve source hashes. The synthetic integration regression uses 19:00–21:55 UTC with evaluation beginning 20:30 on November 12. It passes mechanical alignment while remaining unqualified. This is an illustration, not a claim that the real export qualifies or that all real windows have sufficient history.

## Evidence still required

- Identifiable provider legal entity, feed, symbol/native-timeframe provenance, export/retrieval details and authorized offline-use evidence.
- Historical UTC interval-opening convention and price basis. A reported current BID chart mode does not independently verify historical BID prices.
- Dated broker quote/trade schedules, timezone/DST convention, holidays, exceptions and maintenance for the entire warm-up/evaluation period. Reconcile the candidate's schedule-conflict hold using authoritative evidence.
- Broker full-bar and partial-bar finality, export capture completeness and correction/revision policy, with actual referenced document hashes. Time passing and matching OHLC do not prove these facts.
- Genuine independent source/calendar/finality qualification and reviewer sign-off; no self-approval.
- Qualified replay and actual blinded annotations before historical comparisons or analyst agreement can be measured.

Raw source files and real-data journals remain private. Exness stays BLOCKED, signal WAIT, execution false, historical validation PENDING and historical comparisons NOT_RUN.

## Synthetic evidence and regression coverage

[Audit summary](research_audits/historical-session-boundary-synthetic-v1/audit.json) is explicitly synthetic; the two underlying report hashes are regenerated and checked by tests. Each case has 188 M1 and 38 M5 observations: 37 five-M1 matches and one partial close with unknown finality. The verified-declaration fixture identifies two configured off-quote slots; the unverified fixture leaves both unresolved. Neither qualifies data. These are generic test schedules, not manufactured Exness evidence.

Tests cover all six geometry classes, 21:58 closure, partial opening, restricted/unknown phase transitions, missing full-session candles, unverified schedules/finality, expiry, holiday/maintenance evidence, duplicates/order, OHLC disagreement, explicit-window selection, unchanged source bytes, actual-header mapping, malformed CSV, repeated report hashes and no execution authorization. Full-suite and CI results are recorded in the PR after execution.
