# Historical session-boundary gap analysis v1

Analysis base: PR #22, `84f71f537926cb174a9964298aeef4ccf2a6dda3`.
Written before implementation. No real CSV was supplied in this environment.
The local filenames, 4,074/816 rows, 813 matches and three incomplete 21:55 M5
intervals are **user-reported observations**, not repository test results.
The demo server label is not needed in public outputs. Chart mode 0/digits 3
reported by the operator do not independently establish the historical price basis.

## Actual call path

1. `Prepare-IATRealDataPilot.ps1` checks Python 3.11 and calls
   `diagnostics/prepare_real_data_pilot.py` inspect/prepare. It has no MT5 calls.
2. `iat/pilot_preparation.prepare_pilot` validates the strict import spec, then
   `stream_archive` hashes full files and checks structural/row integrity. It
   reports raw gaps; it does **not** load/classify calendar geometry in that scan.
3. Preparation explicitly selects rows with open >= start and scheduled close <=
   end into a separate projection. Originals and whole-source hashes are preserved.
   This selection does not silently remove an interior partial interval.
4. The actual `prepare_package` is in `iat/qualification_assistant.py`. It calls
   `analyze_import`, copies original/normalized/evidence bytes and writes a lock
   last. `analyze_import` compiles the supplied v2 calendar and calls
   `assess_candles(...session_calendar=calendar, observed_finality=known)` separately
   for M1/M5. `known` is only the import's explicit completion/document declaration.
5. `assess_candles` calls `SessionCalendarV2.validate_history`, which first calls
   `validate_request` (coverage, expiry, evidence holds, current phase), then
   `classify_bar` for observed bars, rejecting partial/restricted/unknown inputs.
   Missing ordinary slots use `expected_opens`, excluding configured closures and
   non-FULL_TRADING slots. This **is** session-aware; it is not a five-row heuristic.
6. Only if both ordinary frame checks are valid does the assistant call
   `historical_replay.alignment_check`. Both it and `evaluation_window.coverage`
   require exactly five M1 openings per scheduled M5. Missing any leaves the M5
   uncovered. This is an ordinary full-bar consistency contract, not a defect.
7. The candidate manifest remains PENDING/finality_attested=false.
   `pilot_qualification.qualify_historical` invokes `dataset_preflight`: it repeats
   frame checks and only then alignment, plus all independent source/evidence gates.
   Preparation writes alignment/readiness reports; handoff independently assesses
   the locked package before registration and closed-only packets. No source or
   approval gate is bypassed by calendar schema validity.

## Findings and seven requested answers

| Question | Confirmed software behavior / conclusion |
| --- | --- |
| Partial close vs unexpected missing M1? | The v2 classifier distinguishes them, but ordinary preflight stops at its first failed gate and historical alignment is suppressed. The preparation report lacks per-M5 research explanation for the uncovered minutes. |
| M5 21:55–22:00 with quote close 21:58? | Existing v2 gives PARTIAL_SESSION_CLOSE with a nominal 180-second quote portion. Scheduled end remains 22:00. This is compatible with a native broker bar containing three quote minutes, but does not prove its OHLC/finality, actual last tick or finalized close time. |
| Five M1 rows required? | Yes for ordinary alignment/coverage. Do not aggregate three M1 rows into an eligible finalized M5 or revise the denominator to force PASS. |
| Reuse v2 for historical data? | Yes, it is already called through quality/preflight. Research can additionally call its existing classifier without changing semantics. Verification/expiry/phase/finality holds remain meaningful at the explicit historical as-of; current validity is not retroactively invented. |
| UNKNOWN/CLOSE_ONLY/FULL_TRADING? | Distinct v2 states and permissions exist. FULL_SESSION_BAR describes quote geometry, not permission; CLOSE_ONLY/UNKNOWN cannot authorize ordinary inputs. The archive scanner alone does not inspect phases. |
| Finality? | Only independently established MT5_POSITION_1_ELAPSED full-bar finality is supported. CSV complete=null supplies none. It does not establish partial-candle finality. Unknown remains unknown. |
| Safer explicit window? | A new declared window ending at/before the partial M5 opening can avoid that observation. A short window starting after a reviewed reopening can likewise avoid partial opening. Preserve full archive hashes and report excluded scope; do not delete/alter rows or round broker boundaries. Existing warm-up/minimum-coverage and source qualification still apply. |

## Genuine diagnostic gap and smallest correction

Add a separate, versioned **research sidecar**, available even when ordinary
validation is blocked. Reuse `SessionCalendarV2.classify_bar(research=True)` and
its nonresearch classification/verification metadata. Report all six classes,
phase states, scheduled bounds, nominal quote seconds, missing M1 slot geometry,
and five-M1-only numeric consistency where permitted. Finality/ordinary eligibility
remain unestablished; no ordinary candles are emitted. Candidate off-quote minutes
must be labeled unverified, not legitimate closures. Unknown/expired/evidence-held
calendars must not generate verified missing-bar claims.

Integrate the sidecar into PR #22's preparation report/manifest without changing
PR #21 package contents, report schema/hashes, source projection, alignment,
coverage, finality or qualification rules. Also provide a standalone read-only
research CLI: strict import requires declarations the operator has not supplied,
so a diagnostic must not manufacture them simply to reach the classifier.
The old generic timestamp research utility is separate from historical preparation;
its nominal missing counts are not independent broker verification and should not
be promoted to verified historical conclusions.

## Exness candidate facts and unresolved evidence

The existing candidate retains 21:58 closes, 23:00 weekday quote openings and
23:01 Sunday quotes, with UNKNOWN/close-only transitions after reopening. Quote,
trade, holiday, maintenance and finality verification flags are false; a schedule
conflict hold remains. Its sidecar explicitly says BLOCKED, not broker-certified
and not terminal-tested. Coverage is Nov 6 through exclusive Nov 16 UTC; current
requests after expiry are blocked. No flags, hashes, hours or expiry will be edited.
Historical research inside coverage may expose nominal geometry even when those
holds block all ordinary/qualification use. The existing source captures postdate
some reported bars; they do not independently prove dated feed applicability.

Still required: actual local source hashes/row inspection; provider legal entity,
feed and native-timeframe provenance; historical BID/ASK/MID evidence; UTC/opening
conventions; permission/upstream usage rights; dated quote/trade/holiday/maintenance
and exception coverage for warm-up/evaluation; resolution of reopening conflicts;
correction history; full-bar and partial-bar finality semantics; independent
qualification approval and real blinded observations. Matching 813 numeric
aggregations, if verified locally, would establish only scoped mechanical
consistency, not these missing facts or any trading edge.
