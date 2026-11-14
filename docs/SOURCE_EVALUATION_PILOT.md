# Initial XAUUSD source and evaluation-window review

Base: PR #10, `feat/iat2-historical-replay-validation`, commit
`fdc27e0ce60ca3605f826bf126e3eb3a73191433`.

**Historical analytical validation remains PENDING.** A real, independently
published source was acquired and a private sample prepared, but its dated
session calendar and capture-completeness/finality evidence are insufficient.
No historical DecisionLog or directional analytical result is claimed. This
milestone concerns historical pipeline behavior, not profitability or execution.
Exness stays BLOCKED; signal WAIT and execution_allowed=false remain fixed.

## Source selection and usage

Selected source: CarlosSilva1, *XAU/USD Tick Data (May 2021 – May 2026)*,
[pinned dataset card](https://huggingface.co/datasets/CarlosSilva1/xauusd-ticks/blob/d14fc64dc3b0452732e60662d94b500a6bb3d534/README.md).
The publisher declares CC-BY-4.0, spot XAU/USD, UTC millisecond tick times and
bid/ask columns, and describes reconstructed broker-feed data. The broker is
not identified. These are publisher declarations, not independent certification
of venue identity, capture completeness or upstream ownership.

[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) permits reuse with
attribution and indication of changes under its conditions. Attribution:
Silva, C. (2026), *XAU/USD Tick Data (May 2021 – May 2026)*, Hugging Face,
CarlosSilva1/xauusd-ticks. Changes here: select a finite historical interval,
use bid quotes only, aggregate interval-open M1, then aggregate M5 from M1.
The raw archive and generated OHLC remain outside GitHub despite the declared
license. Public review artifacts contain hashes, coverage, provenance and blocked
results only. The publisher's declaration does not authenticate upstream rights.
Source/terms reviewed on 2026-11-14; acquisition was at
2026-11-14T06:26:58.846523Z.

Exact pinned revision: `d14fc64dc3b0452732e60662d94b500a6bb3d534`.
Public source file: [pinned May 2021 Parquet](https://huggingface.co/datasets/CarlosSilva1/xauusd-ticks/resolve/d14fc64dc3b0452732e60662d94b500a6bb3d534/year=2021/month=05/XAUUSD-2021-05-part0000.parquet).
Downloaded size: 10,304,019 bytes. Archive SHA-256:
`6dd18367ceed4385424a69c7d4380455cb526a866af8d352a59d25520e123bec`.
It matched the pinned repository's published LFS object hash.

Alternative sources reviewed:

- [HistData FAQ](https://www.histdata.com/f-a-q/) documents XAU/USD M1 bid bars
  and fixed EST without DST. The ordinary January 2024 download form returned an
  empty HTTP 200 response, not a ZIP. No alternate access or credential path was
  attempted. Dated venue/session/finality evidence was also unavailable.
- [Dukascopy website terms](https://www.dukascopy.com/swiss/english/legal-pages/terms-of-use/)
  restrict automated acquisition without written consent; its feed was not used.
- [Pcitycrypto dataset card](https://huggingface.co/datasets/Pcitycrypto/xauusd)
  declares CC-BY-4.0 but did not establish the timestamp timezone/feed basis needed
  for this review. It was not selected or reinterpreted as UTC.

## Timestamp, basis, aggregation and finalized-bar limits

The selected Parquet column is Arrow timestamp[ms] without stored timezone;
its source card explicitly declares UTC. The source-specific adapter assigns
UTC on that documented basis, not from local OS timezone. The generic tick
aggregator requires aware UTC values and rejects backward order and invalid bids.
Equal-timestamp quotes retain file order; no intrabar ordering beyond the file is
claimed. Raw ticks are never sorted, filled or fabricated.

M1 is [t,t+1 minute), timestamped at interval OPEN. Open/close are first/last bid,
high/low are extrema. M5 uses exactly five complete M1 rows aligned on UTC
five-minute boundaries. No ask/mid or Exness prices enter the sample. Missing
quoted minutes fail preparation instead of producing flat synthetic bars.

A later archive tick beyond the sample end demonstrates elapsed interval geometry,
not completeness or irrevocable finality. Its exact timestamp is in the private
preparation audit and the public metadata review. The publisher supplies no
verified complete-capture/finalized-bar contract or dated source-venue calendar.
No future quote contributes to an earlier OHLC candle or analytical decision.
The existing v2 finality policy is MT5-specific and cannot simply be asserted true
for a reconstructed tick archive; provider-compatible finality needs review.

**M1/M5 consistency here is INTERNAL_AGGREGATION_ONLY.** A perfect match checks
our aggregation plumbing; it is not independent native M5 corroboration, source
accuracy, market-wide completeness, a broker-calendar validation, or a trading edge.

## Actual prepared scope and checksums

Warm-up, both frames: **2021-05-25 08:00–11:00 UTC**.
Evaluation: **2021-05-25 11:00–12:00 UTC**.
Input coverage: 240 M1 rows and 48 internally derived M5 rows, 08:00–12:00 UTC.
No source/session boundaries were moved to obtain these counts. This intraday
sample does not establish a full-day or holiday schedule.

| Artifact | SHA-256 |
|---|---|
| M1 CSV | `3fcb4eed61ce5a6cb773de8c686ca11a108134031068289ee18ca7e2e7070023` |
| M5 CSV | `362c82c850bb22946b2820265b32d561859b7431c1acf2e8c675424754904dc6` |
| Exact manifest | `dda3785de354bf93c66e7f1d47d2ff9bf31a4f4ddcaae4c7b68ec84f6b788992` |
| Effective ContextConfig | `d8bda7da1af47cc1f1f349682b71ca75f39bef89b7fb5d5873bc0bba5510d424` |
| Effective IntelligenceConfig | `0b1db8f78abc3801b23a2aec62ee6057a1b0b711a8244405bc5f77ff582653ff` |
| Scoped replay policy | `38215a56defc937b31ed30bf0ba05ca3e2817170ec1c7a4db2027b4a56c83f19` |

The normalized OHLC hashes and prefix input hashes are also recorded in the
[metadata-only review](source_reviews/xauusd-pilot-review.json).
The [prepared manifest](source_reviews/xauusd-pilot.manifest.json) references
private m1.csv/m5.csv files; their absence from the repository is intentional.
Both analytical configuration hashes are unchanged from PR #10. No strategy
threshold was tuned to change abstention behavior.

Evaluation-window counts, excluding all 36 warm-up M5 bars:

| Measure | Actual |
|---|---:|
| Expected UTC-grid M5 intervals | 12 |
| Provided evaluation M5 bars | 12 |
| Comparable evaluation M5 bars | 12 |
| Uncovered / missing / mismatching evaluation M5 bars | 0 / 0 / 0 |
| Provided / comparable / matching coverage | 100% / 100% / 100% |
| Cross-frame validation claim | NOT_ESTABLISHED |

The denominator is explicitly UTC_GRID_SESSION_COVERAGE_UNVERIFIED. These
percentages describe mechanical interval coverage, not a verified market session.
When a reviewed calendar applies, the denominator uses its expected fully eligible
M5 intervals, excluding legitimate closures. An empty denominator stays null,
never an invented 100%.

## Manifest v2, warm-up and evaluation semantics

v1 remains supported unchanged. Explicit v2 adds:

- evaluation: UTC start/end, both aligned to M5, positive range ending at input end.
- warmup.M1/M5: declared start through evaluation start, matching each file's
  actual first open; M5 may legitimately begin before M1.
- lineage: feed_id, BID/ASK/MID basis, interval-open convention, raw SHA-256 and
  NATIVE_SAME_FEED / AGGREGATED_FROM_M1 / UNKNOWN origin.
- evidence_review: usage, instrument, timestamp, price_basis, calendar and
  finality statuses/references/reason codes. VERIFIED needs a reference. Missing
  historical reviews block analysis; a declaration never authenticates itself.

See [v2 schema](../config/historical-dataset-v2.schema.json). No v1 minute or
source semantics are silently reinterpreted. The inherited unsupported-version
regression now uses version 3; version 2 has its own strict new contract/tests.

A DecisionLog row is WARMUP if its M1 close is ≤ evaluation start and EVALUATION
if the close lies in (evaluation start, evaluation end]. Thus evaluation M1 bars
are selected by their source intervals, not by treating the last warm-up close as
an extra evaluation observation. Logs preserve all causal warm-up decisions;
primary summary counters use evaluation rows only. Warm-up counters are separate.
Unique contextual-version and stable-event counts are computed within the chosen
summary scope, not copied from cumulative ledger counts that include warm-up.

Alignment retains legacy full-input counts and adds an evaluation object with
provided/comparable/uncovered/missing/mismatching counts and denominator-based
percentages. Uncovered warm-up M5 bars are counted separately and do not reduce
otherwise complete evaluation coverage. A single comparable M5 bar, even at 100%
of a five-minute evaluation, cannot establish a validation claim.

Initial claim policy: at least **12 comparable M5 bars**, complete expected
coverage, zero uncovered/missing/unexpected/mismatching evaluation bars, reviewed
source/basis/timestamps/calendar/finality, confirmed independent review and a
verified applicable calendar. This minimum is a transparent one-hour consistency
scope policy, not a statistical sample-size or predictive-confidence threshold.
It changes no analytical threshold. A native, same-feed comparison meeting every
condition may say SCOPED_SAME_FEED_CONSISTENCY; it still does not establish market
truth. Aggregated M5 NEVER gets that native claim, regardless of percentages.
Unknown lineage or incomplete review remains NOT_ESTABLISHED/PENDING.

Regression coverage explicitly includes (a) just one comparable evaluation bar
with preceding M5 warm-up, and (b) six legitimate uncovered warm-up M5 bars before
M1 begins, followed by 12 fully comparable evaluation bars. The former does not
qualify; the latter retains 100% evaluation coverage without counting warm-up as
independent validation evidence. Other tests cover gaps, scopes, percentages,
internal aggregation labels, phase-separated counts and preserved defaults.

## Executed attempts, comparisons and exact evidence gaps

Two full-window commands and one truncated prefix-only command were executed.
All returned **BLOCKED / PENDING, exit 3**, before DecisionLog generation.
Whole-input chronology/OHLC/continuity checks passed and mechanical coverage was
reported, but that is not authorization to bypass historical eligibility.

Missing requirements are recorded exactly:

- SESSION_CALENDAR_REQUIRED / EVIDENCE_CALENDAR_PENDING: no dated, reviewed
  source-venue XAUUSD v2 calendar for the covered warm-up/evaluation interval.
  Unidentified broker provenance prevents borrowing an Exness or generic schedule.
- CANDLE_FINALITY_UNCERTAIN / EVIDENCE_FINALITY_PENDING: no reviewed source capture
  completeness/finalized-bar contract applicable to these derived archive bars.
- INDEPENDENT_REVIEW_PENDING: these unresolved source/calendar/finality items
  prevent completion of the independent dataset review.

Actual analytical results: **0 executed snapshots**, valid/blocked snapshot counts
0/0 with execution_status=NOT_RUN; no selected hypotheses, abstention decisions
or measured stable events. Zero executed snapshots is NOT "all snapshots passed"
and is not a claim that 60 evaluation decisions abstained. Those fields remain
unmeasured because preflight stopped the run. No bars, calendar or finality evidence
were invented to produce an analysis.

The two full preflight reports are identical, but both DecisionLog hashes are
null. `compare_reports` reports repeatability=NOT_RUN and equal=null, not a false
PASS from comparing two absent hashes. The prefix retains 08:00 warm-up and
11:00 evaluation start, truncating at 11:30; it is also blocked. Prefix-equivalence
is NOT_RUN, compared_decisions=0, differences=null (not a claim of zero differences).
Synthetic regressions separately verify actual repeatability and zero prefix
DecisionLog differences on eligible software fixtures.

## Reproduce without publishing raw data

Use the pinned public file from the dataset's Files tab, retaining attribution and
reviewing the source/license. No credentials, account or terminal are required.
Raw files should live outside the checkout (or in ignored private-data/). The
source-specific preparer uses optional requirements-data.txt; replay itself and
CI need no Parquet dependency or network access.

```powershell
python -m pip install -r .\requirements-data.txt
python .\diagnostics\prepare_source_sample.py `
  --parquet 'E:\IAT2\private-data\XAUUSD-2021-05-part0000.parquet' `
  --output-directory 'E:\IAT2\private-data\pilot-new' `
  --start '2021-05-25T08:00:00Z' --evaluation-start '2021-05-25T11:00:00Z' `
  --end '2021-05-25T12:00:00Z' --retrieved-at 'ACTUAL_UTC_ACQUISITION_TIMESTAMP'

python .\diagnostics\historical_replay.py `
  --manifest 'E:\IAT2\private-data\pilot-new\manifest.json' `
  --report-path '.\pilot-attempt-one.json'
python .\diagnostics\historical_replay.py `
  --manifest 'E:\IAT2\private-data\pilot-new\manifest.json' `
  --report-path '.\pilot-attempt-two.json'
```

Replace the acquisition timestamp placeholder with the actual UTC value; future
values are rejected. Source preparation verifies the pinned archive hash, permits
no missing-quote candle filling, requires a later boundary tick, refuses an
existing output directory, and leaves calendar/finality/review PENDING. It cannot
authorize analysis. The local preparer contains no downloader or credentials.
Exact CSV hashes are deterministic; a new acquisition timestamp changes manifest
provenance/hash as expected.

Review `iat.replay_comparison.compare_reports(first, second, prefix)` for both
canonical DecisionLog-hash and full overlapping-row prefix checks. It refuses to
claim repeatability when logs are absent or analytical configurations differ.
The replay retains existing atomic/non-overwriting failure publication and all
read-only flags. Existing API/provider/session/Exness behavior is preserved.

Next: obtain dated source-venue calendar/holiday coverage and an applicable
archive-finality/completeness contract, finish independent review, then run twice
with these SAME analytical thresholds and inspect evaluation-only behavior.
Do not replace missing evidence with a synthetic verified calendar. Profitability,
execution, live demo validation and PR merges are outside this milestone.

## Recorded software checks

All **512 tests pass, 0 fail**, locally on Python **3.11.9** and **3.12.14**:
488 inherited tests and 24 new source/scope/comparison regressions. v1 support
remains covered; the invalid unsupported-version fixture was advanced to v3
because v2 now has an explicit contract. Tests cover both requested coverage
edge cases, native/internal claim labels, phase-scoped event counts, unchanged
analytical hashes, safe tick aggregation, strict review gating, absent-log
comparisons and real metadata-only audit/schema integrity.

Linux/Windows CI runs the complete suite on Python 3.11.9/3.12 and retains the
existing fail-closed/Exness/offline smoke checks. CI never downloads this real
archive, accesses a terminal, or uses real market data as a synthetic fixture.
The optional Parquet dependency is used only for local preparation. Check the
latest PR commit's CI result; prior checks do not certify a later revision.
