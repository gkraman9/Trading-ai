# Private Exness historical export intake v1

This offline workflow prepares local mechanical evidence and feeds the unchanged
PR #31 provenance assessment. It never connects to MT5, downloads data, requests
credentials, places orders, grants qualification or runs historical replay.
Your two Windows files are not available to Codex Cloud and have not been read
here. Reported hashes/counts are operator assertions to reproduce locally.

## Architecture and the metadata-only reference conflict

Base: corrected PR #31 commit `52754bfbba6d44235a8c12b92a1c90b60d8453e3`,
including PR #29 diagnostics. PR #30 remains a sibling, referenced through PR #31's
redacted hash-pinned snapshot of `09cf0f13c649b522447e1f5a1796bf52e2ff2519`.
No existing PR is merged or rebased.

`config/examples/historical-evidence/operator-manifest-v1.json` has
`kind=HISTORICAL_EVIDENCE_MANIFEST`. It is an evidence record, not a prepared
market dataset. Passing it to PR #31 follows this exact path:

1. `assess_historical_provenance()` records its actual file hash in
   `refs['manifest']`, initially with `binding=UNVERIFIED`.
2. `load_dataset()` intentionally rejects this `kind` with
   `EVIDENCE_MANIFEST_NOT_REPLAY_ELIGIBLE` before loading any CSV.
3. The assessor records that error under scope `manifest`.
4. Its existing `ref_bad` condition finds an error for a supplied reference,
   producing `EVIDENCE_REFERENCES=CONTRADICTED` and `EVIDENCE_REFERENCE_CONFLICT`.

This reproduces the reported 0 VERIFIED / 0 PARTIALLY_VERIFIED / 15 UNVERIFIED /
1 CONTRADICTED result. The conflict is using an ineligible artifact as the dataset
reference. It does not establish corruption of either original export. This
behavior and legitimate checksum/reference conflicts remain unchanged.

Use `diagnostics/intake_exness_exports.py` for these eight-column exports.
The tick-specific `prepare_source_sample.py` is for the older publisher Parquet
pilot, not Exness CSVs. `prepare_real_data_pilot.py` remains the streaming archive
and qualified handoff tool. `qualification_assistant.py` supplies the bounded
normalizer/package builder used here; it is not replaced.

The input headers are not the replay loader's canonical five-column header:
`timestamp,open,high,low,close`. Even if timestamps/prices already look normalized,
the eight-column originals must be preserved and converted into new files under
the existing import-v1 runtime contract and `historical-dataset-v2.schema.json`.
No new dataset/qualification schema or validator is introduced.

## What the intake does

The caller supplies both local files, expected SHA-256/byte/row counts, explicit
UTC window, warm-up/evaluation split, an actual retrieval timestamp, provider
reference and local-use authorization. Paths may contain spaces. UNC/network
paths, symlink inputs/output ancestry and existing output directories are refused.
Inputs are bounded by the existing 4 MiB and 5,000-row/frame prepared-data limits;
this is not the large-archive selection tool.

The wrapper reuses `stream_archive()` and the existing row contract for strict
UTC, chronology, unique timestamps, timeframe boundaries, finite positive OHLC,
OHLC ordering and nominal close relative to the declared retrieval timestamp.
It additionally requires this exact header order and nonempty fields:

```text
timestamp_utc,open,high,low,close,tick_volume,spread,real_volume
```

All three auxiliary numeric fields must be finite and nonnegative. Tick volumes
are compared with exact decimal sums; no tolerance is silently added. Spread
units, feed identity and Bid/Ask interpretation are not established by validating
these numeric fields. Empty rows/fields, extra fields and duplicated headers are
not repaired. No sorting, deduplication, interpolation or price changes occur.

Exact originals are privately copied with the same hashes. The unchanged import
assistant creates a pending dataset-v2 manifest and volume sidecars. Its lineage
binds the exact source-file hash pair; PR #31 re-runs normalization from those
copies and checks it against canonical OHLC hashes. Original files are rehashed
before inspection, after inspection, during copying and after provenance analysis.
A detected change blocks the final intake report. Actual original hashes and
normalized-file hashes remain distinct.

`broker=EXNESS` is an explicit declaration made by using this Exness-specific
workflow, bound to the dataset ID and manifest hash. It is not authenticated feed
identity. Generated metadata deliberately retains `feed_id=UNKNOWN`,
`price_basis=UNKNOWN`, `m5_origin=UNKNOWN`, unknown finality/corrections, no dated
calendar, `finality_attested=false`, and PENDING evidence reviews. Independently
supplied M5 is never regenerated from M1. The classification name
`INDEPENDENT_HISTORICAL` is the existing schema's historical-input category, not
an assertion that independent review occurred. No preparer approval is generated.

The existing OHLC comparison uses `IntelligenceConfig().epsilon` unchanged.
Supplemental tick-volume checks compare only groups with all five distinct M1
openings. Both are arithmetic diagnostics on supplied bars, not proof of finality
or ordinary replay eligibility. Partial/incomplete groups have null OHLC/volume
comparison results and are not filled. Missing UTC grid slots remain distinct
from missing broker-session bars; the latter denominator stays null without
verified dated calendar evidence. OHLC/volume mismatches remain visible even when
the package can otherwise be prepared.

PR #31's pinned operator-relayed note explains conditional 21:58–23:00 breaks,
23:00–23:02 close-only quotations and possible three-minute 21:55 M5 intervals.
It never installs a production calendar. Friday reopening, new-position
permission at/after 23:02, exact CSV Bid mapping, support authentication and
finality/corrections remain unresolved. Chart Bid convention does not overwrite
UNKNOWN export basis. No observation grants IAT execution permission.

## Exact Windows 10 / Python 3.11 commands

Run from the new branch's repository root using the existing Python 3.11
environment and installed project dependencies. No MT5 package is needed. Keep
all outputs local; do not commit or upload originals or private evidence reports.

```powershell
$m1 = 'E:\IAT2\Data\XAUUSD_M1_Exness_20261111_20261113.csv'
$m5 = 'E:\IAT2\Data\XAUUSD_M5_Exness_20261111_20261113.csv'
$out = 'E:\IAT2\Data\exness-intake-001'
if (Test-Path -LiteralPath $out) { throw 'Choose a NEW output directory, for example exness-intake-002.' }

# Optional independent byte inspection; this does not grant qualification.
Get-Item -LiteralPath $m1, $m5 | Select-Object Name, Length
Get-FileHash -LiteralPath $m1, $m5 -Algorithm SHA256

$permission = Read-Host 'Do you have authorization for local offline inspection of these exports? Type YES'
if ($permission -cne 'YES') { throw 'Do not inspect without authorization.' }
$retrieved = Read-Host 'Enter the actual export/acquisition UTC timestamp (ISO8601 ending Z); do not invent a date'

py -3.11 diagnostics/intake_exness_exports.py `
  --m1 $m1 --m5 $m5 --output-directory $out `
  --m1-sha256 'c98944d8de6251efecc4e75071517030e3ae1fea9cabb71f22f498a29097e54f' `
  --m1-bytes 274778 --m1-rows 4074 `
  --m5-sha256 'd6b54a12956b7acade014d907957923640a995de905fb40f72805111cc67dc9f' `
  --m5-bytes 55446 --m5-rows 816 `
  --start-utc '2026-11-11T00:00:00Z' --end-utc '2026-11-14T00:00:00Z' `
  --evaluation-start-utc '2026-11-11T12:00:00Z' `
  --retrieved-at-utc $retrieved --source-reference 'https://www.exness.com/' `
  --authorized-local-use
$code = $LASTEXITCODE
if ($code -ne 3) { throw "Intake blocked (exit $code). Inspect intake-report.json if present; preserve outputs and retry in a NEW directory." }

$report = Get-Content -LiteralPath (Join-Path $out 'intake-report.json') -Raw | ConvertFrom-Json
$report | Select-Object status, mechanical_status, dataset_id, qualification, historical_validation, historical_comparisons, exness
Get-Content -LiteralPath (Join-Path $out 'alignment-audit.json') -Raw
Get-Content -LiteralPath (Join-Path $out 'provenance-assessment.txt')
Get-FileHash -LiteralPath $m1, $m5 -Algorithm SHA256
```

The provider homepage above is only an operator-declared provider reference; it
is not a dated calendar, evidence of offline-use rights or source authentication.
The noon evaluation start explicitly declares preceding warm-up; it is a proposed
split, not a finding that history is eligible/sufficient. Check the existing
assistant's warm-up findings. The tool does not read or promote
`E:\IAT2\Data\inspection-001\preparation-manifest.json`.

To reproduce the provenance assessment with the unchanged CLI in fresh files:

```powershell
py -3.11 diagnostics/provenance_assessment.py `
  --manifest (Join-Path $out 'candidate-package\candidate-manifest.json') `
  --import-spec (Join-Path $out 'candidate-package\import-spec.json') `
  --broker-binding (Join-Path $out 'broker-binding.json') `
  --json-output (Join-Path $out 'provenance-recheck.json') `
  --text-output (Join-Path $out 'provenance-recheck.txt')
if ($LASTEXITCODE -ne 3) { throw 'Provenance recheck failed; preserve reports and investigate.' }
```

## Exit codes, artifacts and recovery

* **3:** evidence artifacts were prepared, always DATA_NOT_QUALIFIED. Even a
  `mechanical_status=CONFLICTS` comparison can produce reports with this code;
  inspect the actual findings. It never means historical validation PASS.
* **1:** invalid/missing/changed input, rejected output path or publication error.
  An `intake-report.json` with `status=BLOCKED` is produced when possible.
* **2:** argparse rejected missing/invalid command syntax.

`intake-report.json` is the completion record written last. Require
`status=EVIDENCE_PREPARED` and verify its `artifact_hashes` before using the package.
If missing/BLOCKED, treat all partial output as incomplete. Files are individually
published without overwrite, not a directory transaction. No existing output is
replaced; preserve failed output for investigation and retry with a new name.
Do not edit a locked package or update expected hashes merely to suppress a
failure. Investigate source/provider corrections first.

| Private artifact | Meaning |
| --- | --- |
| `intake-report.json` | Actual-vs-expected source facts, scan diagnostics, completion state, artifact hashes and safety |
| `source/m1.csv`, `source/m5.csv` | Byte-identical snapshots of operator originals |
| `import-spec.json` | Existing import-v1 declarations, window and unresolved metadata |
| `candidate-package/source/*` | Importer's byte-preserving source snapshots |
| `candidate-package/m1.csv`, `m5.csv` | New canonical five-column OHLC files; original M5 preserved as source |
| `candidate-package/*.volume.json` | Existing tick-volume sidecars; no invented market prices |
| `candidate-package/candidate-manifest.json` | Existing dataset-v2 pending manifest, exact checksums and lineage |
| `candidate-package/report.json`, `package.lock.json` | Existing assistant checks, issues, frozen package hashes |
| `candidate-package/independent-review.template.json` | PENDING fields only; not a reviewer or approval |
| `broker-binding.json` | Exact dataset/manifest-bound Exness operator declaration |
| `alignment-audit.json` | Complete/partial groups, OHLC/volume mismatches, null session denominator and comparison assertions |
| `provenance-assessment.json`, `.txt` | Unchanged PR #31 gaps, original/canonical hashes and existing qualification results |

The reported **813 complete matches / 3 partial or session-uncertain M5 bars** are
assertions to reproduce. The report distinguishes them from observed counts and
marks MATCH/DIFFERS only for declared historical inputs in the exact reported
interval. Neither outcome authenticates the source. A mismatch requires review,
not silent deletion or repair of bars.

## Synthetic verification and remaining evidence gaps

`tests/test_exness_intake.py` tests both small cases and a clearly labeled
4,074-M1/816-M5 synthetic shape with constant synthetic prices and a hypothetical
Friday closure. It reproduces 813 complete arithmetic matches / 3 incomplete
21:55 groups in that fixture only. `docs/research_audits/exness-intake-synthetic-v1.json`
contains reproducible synthetic hashes/counts, not raw prices or real-data results.
The same suite exercises metadata-only rejection, genuine mismatches, source
mutation, chronology, numeric fields, path spaces, LF/CRLF, deterministic outputs
and safety. Windows/Linux CI runs focused and inherited full suites on 3.11/3.12.

Remaining blockers require authenticated acquisition/export-feed evidence,
dataset-specific UTC and price-basis mapping, actual offline-use permission,
independently reviewed dated calendar/exception coverage, Friday clarification,
finality/capture completeness/correction history and a genuinely independent
review. Reusing the existing import and provenance CLI grants none of these.
No reviewer packets, DecisionLogs or historical comparisons are produced here.
Exness remains BLOCKED; WAIT; execution_allowed=false; broker_access=false;
orders_requested=0; profitability_tested=false; historical validation PENDING;
comparisons NOT_RUN. Synthetic results are not broker or profitability validation.
