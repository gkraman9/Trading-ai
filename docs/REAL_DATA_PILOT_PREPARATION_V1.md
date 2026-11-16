# Real XAUUSD Data Pilot Preparation v1

Prepare a **bounded pilot window** from large authorized local M1/M5 archives,
without changing input files or qualification rules. This bridge reuses PR #21's
qualification assistant and PR #20's closed-only blinded-review workflow. It
never downloads data, requests credentials, initializes MT5 or places live/demo
orders. Exness remains BLOCKED, signal WAIT, execution_allowed=false. Historical
validation stays PENDING; historical comparisons stay NOT_RUN.

## The reported M5 file is not verified here

`XAUUSD_M5_IAT_normalized.csv` is a supported user-selected filename, not a trusted
schema or source declaration. The reported 40,610 rows and April 1–October 26,
2026 coverage remain **unverified**: the real file was not supplied/inspected in
this work. No matching native M1 is assumed. Do not upload raw exports or broker
credentials; run inspection locally and keep reports/packages private.

The automated large-file regression uses a separately generated, explicitly
synthetic 40,610-row M5 CSV larger than 4 MiB. Its dates and prices are test
inputs, not a reconstruction or verification of the user's file.

## Streaming and claim boundaries

`iat.pilot_preparation.stream_archive` hashes in 1 MiB chunks, scans CSV rows and
uses a temporary on-disk SQLite timestamp index for adjacent and nonadjacent
duplicates. Memory does not grow with archive row count: SQLite cache is bounded,
physical lines are capped at 1 MiB characters, and examples/gaps are capped at 25.
The CSV parser's existing field-size bound also applies. Up to 10 million rows
are scanned; limits or malformed input block completion. The timestamp index is
deleted after inspection. No sorting, filling, interpolation, deduplication or
native-M5 replacement occurs. Sources are rehashed to detect edits during the run.
Freeze the files/documents before preparation; this is detection, not a filesystem
lock against another writer.

With an explicit PR #21 import spec, the full archive audit checks UTC opening
syntax, timeframe boundaries, chronology, duplicates, finite consistent OHLC,
optional volume, mapped symbol/feed/basis and supplied completion flags. Bars
cannot close after the declared export/retrieval time. Unfinished, malformed or
out-of-order bars anywhere in an inspected archive block preparation. Corrected
flat exports retain provider declarations and checksums; appended correction rows
with duplicate timestamps are rejected, never automatically reconciled.

A structural scan PASS is **not** full archive session completeness, source
qualification or native-feed proof. Raw gaps across the full archive are reported
without calling weekends, breaks or unknown source closures missing candles.
Session-calendar distinction and M1/M5 alignment are established only inside the
explicit selected window, using the existing dated calendar and quality engine.
No calendar coverage or matching M1 coverage is claimed for the rest of a large
M5 archive. Without mappings/UTC declarations, inspection verifies only headers,
record counts and source bytes/hash; timestamp range stays unknown.

## Explicit window, bounded normalization

The caller selects five-minute UTC-aligned start, evaluation start and end, with
`start < evaluation_start < end`. Start includes warm-up. Both source paths are
explicit; omitting M1 reports MISSING_NATIVE_M1 even if a similarly named file or
a metadata path exists. The native frame/feed/basis declarations come from the
strict existing [import spec](HISTORICAL_QUALIFICATION_ASSISTANT_V1.md), not a filename
or prices. Unknown/derived M5 is never silently promoted to native.

Select only original rows satisfying `opening >= start` and `close <= end`.
Retain original value strings/column order in the selected source projection;
quote/line encoding is deterministic UTF-8 CSV. Full original bytes/hashes are
recorded separately, so a selected CSV is never described as the full original.
The bounded selection then goes through the unchanged assistant, including its
5,000-row/4-MiB-per-frame limits, declared session/holiday/exception/maintenance
coverage, supported finality/correction contracts and existing pilot warm-up
lookbacks. Choose a smaller reviewed interval if limits are exceeded. Boundaries
must correspond to available eligible first bars; do not adjust broker hours to
make a window pass.

M1-to-native-M5 OHLC aggregation is a **diagnostic comparison only**, at unchanged
tolerance. Its report includes comparable/uncovered M5 counts, mismatch counts,
evaluation coverage and warm-up/session diagnostics. Both native input streams
stay intact; a mismatch needs provider investigation, not replacing M5 with
aggregated prices. Other provider finality contracts remain unsupported until a
validated adapter exists; the existing MT5_POSITION_1_ELAPSED requirement is not waived.

## Generated private artifacts

Each invocation requires a fresh output directory, separate from source files:

- `source-inspection.json`: full-source fingerprints, row/range observations,
  declarations, scan limits/completion, bounded gap/error examples and claim scope.
- `original-import-spec.json`: exact supplied metadata, if valid.
- `selection/`: selected source projections and explicit window metadata/documents
  (absent in dry-run). Never the full large archive.
- `candidate-package/`: PR #21's unchanged bounded evidence package and pending
  candidate manifest/sign-off template (absent when intake cannot proceed).
- `alignment-audit.json`: selected-window frame quality and M1/native-M5 comparison,
  or NOT_RUN with no invented zero metrics when inputs are unavailable.
- `evidence-checklist.json`: provenance/usage, calendar, finality/corrections,
  independent approval and blind-review requirements; supplied, missing and still
  unverified documents are listed separately. No item is automatically approved.
- `review-readiness.json`: BLOCKED/DATA_NOT_QUALIFIED with explicit reasons and
  `review_packets_created=false` until independent qualification succeeds.
- `preparation-manifest.json`, written last: hashes of every generated artifact,
  source paths/fingerprints, archive_binding_id, selected_dataset_id, window and
  safety state. Its presence means the reports were completely published, not
  that the data qualified.

Source paths in the private manifest are needed for later rechecking; they may
identify the operator's machine. Do not publish that manifest, real data, source
documents or the full candidate package. Atomic no-overwrite publication is used.
A failed/interrupted run can leave a partial output directory without a manifest;
inspect it and choose a new destination. No source files are ever opened to write.

The selected dataset ID binds the canonical window under the existing manifest
contract. Full archive identity is separately frozen by archive_binding_id and
the preparation manifest; a larger/new archive with the same selected candles can
have the same selected dataset ID but a different archive/provenance binding.
Appended future bars therefore do not change an earlier chart packet, while
reusing a frozen preparation after source edits is correctly rejected. New archive
versions require a new preparation/evidence review, not silently editing the lock.

## Exact Windows 10 / Python 3.11 commands

From the checked-out repository root, use the **existing** Python 3.11 interpreter.
There is no installer or network dependency in the runner. Paths are parameters;
no personal Windows location is hardcoded. For example, set these to your local
private paths (M1 must be genuinely available, not inferred from the M5 filename):

```powershell
$PythonExe = (Get-Command python).Source
& $PythonExe --version
$M5Csv = Read-Host 'Full path to authorized XAUUSD_M5_IAT_normalized.csv'
$M1Csv = Read-Host 'Full path to matching native M1 CSV, or leave blank if missing'
$ImportSpec = Read-Host 'Full path to PR21 import spec, or leave blank for header-only inspection'
$PrivateOutputParent = Read-Host 'Existing private output parent directory'
```

Declare a prospective window from provider-verified UTC coverage. The dates below
are **illustrative**, not a claim that the user's file or broker calendar covers
them. A metadata-free inspection does not parse dates or normalize anything.

```powershell
$StartUtc = '2026-04-01T00:00:00Z'
$EvaluationStartUtc = '2026-04-01T02:00:00Z'
$EndUtc = '2026-04-01T04:00:00Z'
& .\diagnostics\Prepare-IATRealDataPilot.ps1 `
  -M5Csv $M5Csv -M1Csv $M1Csv -ImportSpec $ImportSpec `
  -StartUtc $StartUtc -EndUtc $EndUtc -EvaluationStartUtc $EvaluationStartUtc `
  -OutputDirectory (Join-Path $PrivateOutputParent 'inspection-001') `
  -PythonExe $PythonExe -DryRun
```

Inspect the private source report for **actual** row counts, first/last UTC
openings (only with mappings), hashes and source errors. Do not copy the previously
reported count/date range into metadata as verification. Obtain actual native M1
and the required source declarations/documents if missing. Correct the **export or
evidence**, not prices in place; do not hide incomplete bars or assume local time.
Then use a new destination to prepare a suitably small shared window:

```powershell
& .\diagnostics\Prepare-IATRealDataPilot.ps1 `
  -M5Csv $M5Csv -M1Csv $M1Csv -ImportSpec $ImportSpec `
  -StartUtc $StartUtc -EndUtc $EndUtc -EvaluationStartUtc $EvaluationStartUtc `
  -OutputDirectory (Join-Path $PrivateOutputParent 'preparation-001') `
  -PythonExe $PythonExe
Get-Content (Join-Path $PrivateOutputParent 'preparation-001\alignment-audit.json')
Get-Content (Join-Path $PrivateOutputParent 'preparation-001\review-readiness.json')
```

Exit **3 is expected** for a completely published preparation that is not qualified.
Read the report and its reason codes; the presence of canonical files, mechanical
PASS or a manifest does not authorize review or replay. The runner requires
Python 3.11, does not install packages, does not access credentials, and will not
reuse/overwrite an existing output directory. Its files are stdlib/project-only.
PowerShell reports fixed errors with recovery instructions; it never invokes
network or order functions.

If local policy prevents running a reviewed PowerShell file, use the Python CLI
without changing global execution policy:

```powershell
& $PythonExe .\diagnostics\prepare_real_data_pilot.py prepare `
  --spec $ImportSpec --m1 $M1Csv --m5 $M5Csv `
  --start-utc $StartUtc --end-utc $EndUtc --evaluation-start-utc $EvaluationStartUtc `
  --output-directory (Join-Path $PrivateOutputParent 'preparation-cli-001')
```

Use `inspect` instead of `prepare` for dry-run. Omit `--m1` when unavailable;
that intentionally produces blocked readiness rather than guessing a matching file.

## Independent qualification and blind-review handoff

Complete the existing [independent qualification procedure](HISTORICAL_QUALIFICATION_ASSISTANT_V1.md)
for `candidate-package`, including a separately created reviewed manifest and
independent approval record. The preparer cannot sign themselves off. Missing
permissions/provenance, source-specific calendar, supported finality/correction
proof or actual independent approval means DATA_NOT_QUALIFIED. Codes and hashes
are not proof of different people or truthful documents; oversight remains necessary.

Prepare the old pilot's preregistered fixed-UTC-grid spec with actual evaluation
closes, at least two consenting independent reviewers, regime goals and unchanged
rules/configuration hashes. No automatic reviewer or dataset approval is provided.
The handoff command rechecks frozen archive/artifact hashes, calls PR #21's strict
assessor and PR #20 registration, and **writes the frozen plan before IAT replay**:

```powershell
& $PythonExe .\diagnostics\prepare_real_data_pilot.py handoff `
  --preparation-directory (Join-Path $PrivateOutputParent 'preparation-001') `
  --reviewed-manifest (Join-Path $PrivateOutputParent 'preparation-001\candidate-package\reviewed-manifest.json') `
  --independent-review (Join-Path $PrivateOutputParent 'preparation-001\candidate-package\independent-review.json') `
  --pilot-spec (Join-Path $PrivateOutputParent 'pilot-spec.json') `
  --output-directory (Join-Path $PrivateOutputParent 'review-handoff-001')
```

If qualification is incomplete it publishes a blocked readiness report and **no
review packets**. Genuine success is READY_OPERATOR_ATTESTED, not historical
validation. The handoff reuses closed-only packets, retains all reviewer originals
and disagreements, and keeps IAT answers/future observations private. Only share
assigned reviewer-packets and individual private templates; never share the answer
key or other reviews before submission. Continue with the existing pilot's submit
and explicitly authorized reveal commands. Analyst agreement stays separate from
5/15-minute first-breach price outcomes; neither is profitability or accuracy proof.

## Synthetic audit and remaining blockers

[Example alignment](research_audits/pilot-preparation-synthetic-v1/alignment-audit.json),
[readiness](research_audits/pilot-preparation-synthetic-v1/review-readiness.json),
[checklist](research_audits/pilot-preparation-synthetic-v1/evidence-checklist.json) and
[audit](research_audits/pilot-preparation-synthetic-v1/audit.json) are SYNTHETIC_ONLY.
The small example has 150 M1/30 M5 rows, 90/18 warm-up rows and 12 comparable
native-shaped evaluation M5 bars at 100% scoped consistency with no mismatches.
Selected-window mechanics pass; qualification is DATA_NOT_QUALIFIED and readiness
BLOCKED. Repeated manifests agree for the same sources/output-independent paths.
The separate 40,610-row test exceeds the prior byte limit but selects only 30 M5
rows; this proves streaming/selection behavior, not the user's file characteristics.
Future-appended eligible sources preserve prior selected candles and packet hashes;
changed frozen sources are refused at handoff. No real independent humans reviewed
these fixtures, and no real historical replay or broker validation was performed.

Still needed: actual inspection of the user's authorized M5 archive, actual matching
native M1, explicit same-feed/instrument/basis/UTC documentation, offline-use and
upstream provenance rights, dated session/holiday/exception/maintenance evidence
for the selected warm-up/evaluation, supported finality and correction history,
checksummed independent approval, actual blinded annotations and qualified replay.
The reported April–October range cannot fill those gaps. Exness remains BLOCKED;
historical validation PENDING and historical comparisons NOT_RUN.
