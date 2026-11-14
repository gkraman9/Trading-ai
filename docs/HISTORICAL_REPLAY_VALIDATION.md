# Offline historical analytical pipeline validation

Base: draft PR #9, `feat/iat2-market-context-v1`, commit
`bc6ef4dc15d8cdee26294f478d67a70b553f4694`.

This milestone validates causal analytical calculations and evidence bookkeeping.
It is not a profitability backtest. Every record retains READ_ONLY_SHADOW,
signal WAIT, execution_allowed=false. The runner never downloads market data,
imports MT5, connects to a broker, accesses an account or submits an order.
Existing Exness verification holds remain enforced; no profile is approved here.

**Historical validation is PENDING.** No independently sourced historical dataset
was supplied or found. The bundled CSV files are explicitly SYNTHETIC fixtures,
not real XAUUSD observations or broker evidence. A successful software test is
not historical/terminal validation, and a source declaration is not authenticated
proof of its origin.

## Stable events versus contextual versions

Phase 8's Evidence.id remains the contextual evidence version fingerprint, so
existing hypothesis references and score explanations remain compatible. The
additive nullable `Evidence.event_id` identifies a CHoCH occurrence independently
of its surrounding interpretation. Old non-CHoCH records have null event_id.

The stable CHoCH identity includes symbol, timeframe, event type/direction,
confirmed price level, canonical pivot identity, actual break-candle identity,
confirmation timestamp and confirmation policy. It excludes alignment labels,
current contextual evidence, heuristic weights, window-relative indexes and
contextual configuration hashes. A different occurrence, policy or corrected
source OHLC produces a different event; identical facts under a changed alignment
do not. Threshold/prior structure/alignment remain visible in contextual details.

The source registry now contains a CHOCH_EVENT record referencing the confirmed
pivot and break candle. Contextual evidence references that occurrence plus its
supporting context. Replay tracks stable events and contextual versions separately:

- new_events: first occurrences of stable event IDs.
- unique_event_count: number of stable occurrences seen so far, not revisions.
- event_revisions: event_id, previous_evidence_id (null on first observation),
  evidence_id, revision_index. Unchanged repeated context adds no revision.
- unique_evidence_count: contextual evidence-version count (including revisions),
  never a number of independent votes or physical market events.

A regression recalculates contextual evidence with a changed Phase 7 alignment:
the evidence version changes, revision index becomes 2, and the underlying event
set/count stays identical. Phase 8's opposing-CHoCH and rolling-window regressions
remain intact. Canonical timestamps/content still replace Phase 7's local IDs.

## Modules and contracts

- `iat/replay_dataset.py`: strict, bounded local manifest and CSV import.
- `iat/historical_replay.py`: inherited quality/session preflight, cross-frame
  consistency, chronological replay, summary and report validation.
- `iat/intelligence/decision_log.py`: Decision and DecisionLog v1 models.
- `diagnostics/historical_replay.py`: offline CLI and atomic publication.
- `config/historical-dataset-v1.schema.json`: manifest structure.
- `config/decision-log-v1.schema.json`: deterministic chronological log.
- `config/historical-replay-report-v1.schema.json`: report envelope.

Schemas are structural contracts. Runtime additionally checks checksums, safe
paths/source URLs, UTC/time ordering, temporal evidence availability, safety flags,
synthetic/pending restrictions and DecisionLog checksum consistency. jsonschema
remains test-only; production requirements are unchanged.

## Curated dataset format

Supply a LOCAL manifest and two LOCAL CSV files; the runner never fetches a URL.
Only the exact symbol XAUUSD and M1/M5 are accepted. Suffixes or another instrument
require a separately reviewed future interface, not silent reinterpretation.

The bundled `config/examples/replay.synthetic/manifest.json` is an executable,
explicitly synthetic shape example. A real curated manifest has exactly:

```json
{
  "version": 1,
  "symbol": "XAUUSD",
  "dataset_kind": "INDEPENDENT_HISTORICAL",
  "source": {
    "name": "PUBLIC SOURCE TITLE TO BE REVIEWED",
    "reference": "https://example.org/replace-with-actual-public-source",
    "retrieved_at_utc": "2026-11-13T00:00:00Z",
    "curation_id": "replace-with-reviewed-dataset-id",
    "independent_review": "PENDING"
  },
  "utc_range": {"start": "2026-11-12T08:00:00Z", "end": "2026-11-12T08:30:00Z"},
  "frames": {
    "M1": {"file": "reviewed-m1.csv", "sha256": "REPLACE_WITH_ACTUAL_FILE_SHA256"},
    "M5": {"file": "reviewed-m5.csv", "sha256": "REPLACE_WITH_ACTUAL_FILE_SHA256"}
  },
  "calendar": {"file": "reviewed-sessions-v2.json", "sha256": "REPLACE_WITH_ACTUAL_FILE_SHA256"},
  "finality_attested": false
}
```

This placeholder example is intentionally not loadable as reviewed evidence.
Replace it only with actual independently reviewed source records/checksums and
coverage; do not set attestations merely to obtain a passing status. A public
source reference must be HTTPS with no user/password, query or fragment. It is
recorded, never fetched. Do not put credentials, account/server identifiers,
private token URLs or personal details into dataset/source metadata.

SYNTHETIC_FIXTURE requires a synthetic: reference and independent_review=PENDING.
INDEPENDENT_HISTORICAL requires an operator ATTESTED independent review, a supplied
v2 calendar matching XAUUSD, and a finality attestation before analytical replay.
Declarations are explicitly labeled OPERATOR_DECLARATION_NOT_AUTHENTICATED. They
cannot approve a calendar or clear its own schedule/holiday/finality holds.

CSV header must be exactly `timestamp,open,high,low,close`. Values must be numeric
OHLC and UTC ISO timestamps (Z or zero UTC offset); non-UTC wall times and naive
values are rejected rather than silently assigned a broker timezone. Candles
must be fully closed and timeframe aligned. Range end is an exclusive candle
interval bound: every open and scheduled close must fit the declared range.

Limits: 4 MiB per manifest/config/CSV and 5,000 rows per timeframe, at least three
rows each. No extra/missing fields, duplicate JSON keys, unsupported versions,
absolute/member traversal paths, or symlinks escaping the manifest directory.
Dataset member paths use relative forward-slash syntax on both platforms.
The manifest itself may be supplied at a normal local Windows absolute path.

Report provenance records source/curation declarations, symbol, declared UTC
range, actual per-frame first open/final close/count, exact manifest/file SHA-256,
normalized OHLC SHA-256 and session-file SHA-256. File hashes bind exact bytes;
line endings matter. Bundled fixture bytes are pinned to LF in `.gitattributes`.
Effective context and Phase 7 configuration hashes plus replay policy hash record
window, M1-close evaluation, alignment policy and tolerance. Full resolved
analytical configurations and window are also included in the report.

## Validation and causal replay

Whole-dataset preflight validates all input rows BEFORE replay, using the existing
quality engine at the declared historical end (never current wall-clock time).
No sorting, filling, rounding or repair. Duplicate/out-of-order/malformed/unclosed/
stale/misaligned data and unexpected gaps fail closed. Supplied session calendars
always apply, including synthetic runs; phase/finality/partial-candle/expiry holds
are preserved. Missing calendars are allowed only for explicitly synthetic
continuity checks and never imply verified session eligibility.

Coverage must include the historical end and relevant sessions. Existing current-
session/freshness rules still apply at that evaluation instant: a session-close
or expired calendar can block preflight. The runner does not shift broker
boundaries or invent exceptional closures to make archived data pass.

For every M5 interval with all five constituent M1 bars, compare first open,
maximum high, minimum low and final close using Phase 7 epsilon as absolute
price tolerance. Mismatches fail with M1_M5_OHLC_MISMATCH; no comparable full M5
interval fails with M1_M5_ALIGNMENT_UNESTABLISHED. Uncovered M5 intervals (for
example preceding history before M1 coverage) are counted, not fabricated. All
rows must first pass independent timeframe validation. These stricter checks
are for same-dataset consistency, not a claim about a broker's tick source.

Replay emits at each M1 CLOSE and uses only M5 candles closed by that timestamp.
The configured rolling window applies after causal prefix selection. Warm-up
snapshots may be blocked or abstain; they remain in the log instead of being
filtered into success. A full-dataset integrity failure produces no analytical
DecisionLog; it is a rejected input run, not a retrospective directional decision.

The whole-input checksums/preflight belong to run provenance, NOT evidence
available to earlier analytical decisions. Each DecisionLog row derives solely
from its causal prefix and fixed configurations. Full-source and truncated-prefix
runs are compared for identical overlapping decisions. Repeated runs are identical,
including their DecisionLog SHA-256; no random IDs or wall-clock generation times
are injected into the log. Historical data revisions require a new checksummed
run, not backfilling an earlier log with future outcomes.

## DecisionLog v1

The log contains log_version=1, configuration_hashes, and chronological entries.
Each Decision version 1 records:

- timestamp_utc and data-quality VALID/BLOCKED status.
- Selected research hypothesis or NO_CLEAR_DIRECTIONAL_HYPOTHESIS and abstained.
- Supporting/contradictory evidence references and all current contextual evidence.
- reason_codes (including informative quality context) and separate actual
  abstention_reasons, so SESSION_NOT_CHECKED is not miscounted as an abstention cause.
- Current/new contextual evidence IDs, stable new events/counts and evidence
  revision chains, with hypothesis revisions and withdrawals.
- Exact M1/M5 as-of context, plus READ_ONLY_SHADOW / WAIT / false.

References must resolve within the current evidence, and no evidence/frame
availability may exceed the decision timestamp. Unsafe flags, unknown versions
and nonchronological logs are rejected. DecisionLog SHA-256 hashes canonical JSON
of the complete log, independently of report path or run metadata.

Summary records declared/actual coverage, snapshot/valid/blocked counts,
abstentions and cause counts, blocked cause counts, selected-hypothesis counts,
hypothesis changes (initial selection is not a change), current evidence
appearances, unique contextual versions, unique CHoCH occurrences, and subsequent
CHoCH context revisions. Appearance/version counts are NOT independent evidence
votes. Scores continue to use current-snapshot category caps only.

## Commands

From the reviewed repository root, with the existing Python 3.11 x64 environment:

```powershell
# No independent data supplied: honest BLOCKED / PENDING, exit 3.
python .\diagnostics\historical_replay.py --report-path '.\replay-pending.json'

# Bundled invented software fixture only: WARN / PENDING, exit 2.
python .\diagnostics\historical_replay.py `
  --manifest '.\config\examples\replay.synthetic\manifest.json' `
  --window 25 --report-path '.\synthetic-replay.json'

# Actual locally curated files, only after independent review:
python .\diagnostics\historical_replay.py `
  --manifest 'E:\IAT2\private-datasets\reviewed-manifest.json' `
  --window 100 --report-path '.\reviewed-pipeline-replay.json'
```

Optional `--context-config` and `--intelligence-config` accept strict versioned
analytical JSON; omitted values use the existing defaults. Every output filename
must be new. Existing files are never overwritten. No dependency installation,
credential prompts, execution-policy changes, terminal enabling or data download
occurs. Normal software tests use requirements-dev.txt and
`python -m unittest discover -s tests -v`.

The CLI reserves RUN_INCOMPLETE/FAIL before input processing, then atomically
publishes a completed report at that NEW path. A crash/publication failure leaves
FAIL, never a stale success. Input/interrupt errors have fixed codes; raw exception
strings, CSV contents and private file paths are not printed. A path/reservation
failure can leave no new report; always check the process exit code.

Exit codes: PASS 0, WARN 2, BLOCKED 3, FAIL 1. Synthetic data ALWAYS leaves
historical_validation=PENDING. Missing independent input is BLOCKED/PENDING.
DATASET_PIPELINE_CHECKS_PASSED means only the declared historical dataset passed
these software/preflight checks and yielded eligible snapshots; it does not
verify source authenticity, terminal behavior, predictive accuracy or profitability.
Blocked warm-up snapshots still produce WARN and explicit coverage counts.

Inspect the result without exposing raw dataset/provider objects:

```powershell
$r = Get-Content '.\synthetic-replay.json' -Raw | ConvertFrom-Json
$r.status
$r.historical_validation
$r.dataset.coverage
$r.configurations.hashes
$r.summary
$r.decision_log.entries | Select-Object timestamp_utc, selected_hypothesis, abstained, reason_codes
```

## Executed software evidence and pending work

The bundled SYNTHETIC fixture contains 30 M1 and six M5 bars over
2026-11-12 08:00–08:30 UTC. Running the documented window-25 command produced:
30 snapshots, 16 valid, 14 blocked for early history warm-up; 30 abstentions;
zero selected-hypothesis changes; 141 evidence appearances, 86 contextual
versions and four distinct synthetic CHoCH occurrences. No context revision was
needed in this fixed-label replay; the alignment-change regression separately
verifies revision bookkeeping. These numbers are software-fixture results only.

No independently sourced historical dataset is available here. Historical
validation therefore remains PENDING; actual broker calendar/holiday/maintenance/
finality evidence and real-terminal validation also remain pending. The default
short fixture intentionally lacks enough M5 structure/indicator history for a
confident directional scenario. Do not manufacture more observations or relax
calendar holds to change that outcome.

Next: supply a separately curated, checksummed dataset and reviewed finite v2
calendar/finality contract; inspect blocked/abstention coverage and independent
review results before broadening validation. Profitability testing is a later
milestone. Full prefix replay can be expensive near 5,000 rows; it is a bounded
research reference, not a low-latency production service or durable global market
state store. All PRs remain draft/unmerged and all execution remains disabled.

## Software regression results

All **488 tests pass, 0 fail**, locally on Python **3.11.9** and **3.12.14**:
450 inherited and 38 new tests. New coverage includes stable event/context
revision separation, strict dataset ingestion/checksums/path/source rules,
chronology/gaps/OHLC/M1-M5 consistency, session/partial/finality/expiry/Exness
blocking, causal DecisionLogs, repeatability/prefix equivalence, schema and safety
contracts, pending/synthetic outcomes, interrupted runs and atomic report failure.
CI runs the complete suite on Linux/Windows × Python 3.11.9/3.12, plus an offline
runner smoke check proving absent/synthetic datasets never certify history.
Check the draft PR's latest commit checks for the final CI result.

## Source-backed evaluation pilot

See [source and evaluation-window review](SOURCE_EVALUATION_PILOT.md) for the
actual pinned source, private-file hashes, explicit v2 warm-up/evaluation scope,
claim limits and blocked preflight attempts. Real analytical replay remains PENDING.
