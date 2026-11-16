# Historical Data Qualification Assistant v1

A private, offline Windows CSV import workflow for XAUUSD M1/M5. It reuses the
existing quality/session engine, manifest v2, historical qualification gate and
blinded-review pilot. Strategies, thresholds and heuristic scores are unchanged.
Exness stays BLOCKED, signal WAIT and execution_allowed=false. No MT5 binding,
credentials, network downloads or live/demo order calls are used.

## Two different questions

`mechanical.status=PASS` means the declared CSV format, OHLC, ordering, cutoffs,
session geometry, native-frame declarations, consistency and warm-up checks pass.
It does **not** establish permission, provenance, native-feed authenticity,
finality or independent approval. Every prepared package is DATA_NOT_QUALIFIED.
All evidence-review statuses remain PENDING, source independent_review remains
PENDING and candidate finality_attested remains false. The assistant cannot approve
its own output, even when every document is present and its hash matches.

Only an external independent review can satisfy the existing qualification gate.
The assessor also rejects the preparer's reviewer code (case-insensitively).
Different pseudonyms are not proof of different people: actual independence,
legal permission and truthful source documentation still require human oversight.
Hashes detect changes against recorded bytes; they are not signatures or proof
that a document's claims are true. Historical validation remains PENDING and
historical comparisons NOT_RUN; this assistant does not run market replay or reviews.

## Input v1 and supported formats

The strict [example import spec](research_audits/qualification-assistant-synthetic-v1/import-spec.example.json)
is explicitly SYNTHETIC_ONLY test metadata, not real source evidence. Use its
structure with an authorized real export and verified declarations. Never relabel
the synthetic fixture as historical data. Unknown fields/versions are rejected.

Supply two UTF-8/UTF-8-BOM, comma-delimited CSV files, at most 4 MiB and 5,000 rows
per frame, with unique headers and consistent column counts. Decimal numbers use
a dot. No delimiter, decimal, column-name or broker-time guessing occurs. CSVs
with separate local date/time fields need a correctly documented UTC re-export;
v1 does not combine or convert them automatically.

Each frame explicitly maps:

| Mapping | Requirement |
| --- | --- |
| timestamp | One ISO-8601 UTC interval-opening column, with Z or zero UTC offset |
| open/high/low/close | Finite positive values with consistent OHLC bounds |
| volume | Column name or null; declare NONE/TICK/REAL/UNKNOWN semantics |
| complete | Column name or null; exact true/false tokens for PER_ROW_BOOLEAN |
| symbol/price_basis/feed_id | Column name or explicit null; when mapped, every row must match declarations |

All unused columns must be explicitly named in ignored_columns. Metadata absent
from row columns is an operator declaration, not machine-verified truth. Do not
ignore contradictory source metadata; supply uniform exports and have the source
identity/basis independently reviewed. Canonical runtime CSVs retain only the five
existing timestamp/OHLC columns. Volume is preserved separately with its own hash;
it is not fed into existing strategies. UNKNOWN volume semantics are reported
as unresolved evidence, not converted into tick/real volume or used analytically.

The spec requires preparer_code, authorized_local_use=true, provider legal entity,
feed, instrument XAUUSD, BID/ASK/MID basis, source reference, retrieval time,
curation ID, UTC range, evaluation and per-frame warm-up. Existing source/reference
and manifest limits apply, including safe references and no credentials/query
parameters in source URLs. Per-frame basis/feed must match the global declaration.
Unknown basis/feed/origin cannot be inferred from prices. M1 and M5 must both be
NATIVE_SAME_FEED; derived/unknown M5 is flagged and its lineage never rewritten as
native. The native declaration itself still needs independent provider evidence.

## Finality, corrections and calendars

Finality metadata separates CSV flag interpretation from the provider contract:

- PER_ROW_BOOLEAN requires a mapped completion column and explicit distinct tokens.
  Every supplied bar must be complete. False/unknown tokens reject; rows are not dropped.
- DOCUMENTED_CLOSED_EXPORT requires no mapped completion column and a referenced,
  checksummed finality document. This remains a **declared**, unverified export
  contract, not an independent finality attestation.
- UNKNOWN is blocked. A mapped completion column cannot be ignored by switching
  to documentary finality. Never intentionally hide contrary completion flags.

The existing v2 calendar gate currently supports **MT5_POSITION_1_ELAPSED** only.
The explicit provider_contract must match. A PROVIDER_COMPLETE_FLAG or other
provider contract is reported FINALITY_CONTRACT_UNSUPPORTED until an independently
validated adapter exists. Do not relabel it as MT5 finality. This version does not
qualify an OANDA or other provider's complete flag by analogy. A row's elapsed
close or true flag alone does not prove finalized historical data.

All openings/closes must fit the declared export interval, which cannot end after
retrieval/export time. Freshness is checked at the historical interval end, not
against today's live market. No prices are filled, sorted, interpolated,
deduplicated, repaired or adjusted.

Each frame declares corrections status NO_KNOWN_CORRECTIONS_DECLARED,
PROVIDER_CORRECTED or UNKNOWN. A provider correction needs a reference and a
previous export checksum different from the current source. Unknown corrections
block mechanical readiness. These fields record declarations, not a verified
change history; an independent reviewer must obtain correction/finality evidence
and prior bytes as appropriate. A corrected export creates a new package/dataset
identity. This tool never overwrites the earlier version.

Supply the existing dated session v2 configuration and its exact file hash.
Require full calendar/exception/holiday/maintenance coverage for all warm-up and
evaluation. Missing or malformed calendars block readiness. IANA calendar zones
and DST use the existing engine; actual candles must already be UTC. Naive local
times, nonzero UTC offsets and local DST folds are rejected rather than resolved.
Legitimate configured closures are distinguished from unexpected missing bars;
session alignment and partial boundaries retain existing strict rules.

Warm-up uses the **same shared lookback calculation as the pilot**, with unchanged
configuration hashes. M1/M5 consistency and evaluation coverage reuse existing
checks and minimums. No tolerance is tuned to make an export pass. Passing these
checks does not independently prove native M5 origin or the source calendar.

## Evidence package and integrity

Seven evidence entries (usage, provenance, instrument, timestamp, price_basis,
calendar, finality) have explicit local file/hash/reference fields, or explicit
nulls when unavailable. Missing documents and bad hashes stay unresolved; they
never become VERIFIED. Authorization is an operator declaration to permit local
inspection, not verification of upstream rights. All evidence paths are relative
to the spec directory and cannot escape it through traversal or symlinks.

`package` creates a fresh private directory containing:

- Original source byte copies under source/, with source hashes and feed/basis/
  correction declarations in report.json. Original input files are never written.
- Canonical m1.csv/m5.csv and optional volume sidecars; file and normalized-data
  hashes are recorded. The lineage raw_sha256 is the canonical digest of the two
  source CSV hashes, not a fabricated provider archive/tick hash.
- Exact calendar bytes, referenced evidence bytes, and original import-spec.json.
- candidate-manifest.json and an incomplete independent-review.template.json.
  No reviewer/date/approval is filled automatically.
- report.json with mechanical diagnostics, actions, pending issues, actual gate
  result, configuration hashes, safety and immutable dataset ID when parseable.
- package.lock.json, written last, binding the exact contents and report hash.

Treat a package as complete only when its lock exists. Atomic no-overwrite writes
prevent misleading partially published success files. Interrupted preparation can
leave a partial directory without a lock; create a new destination after inspecting
it. A package can be complete while its data is mechanically BLOCKED: the report
is an evidence inventory, not approval. Sources are rehashed after import to detect
concurrent source edits; freeze exports/documents while preparing the package.

Everything stays local and private. Do not upload raw market data, real packages,
provider documents or account credentials to GitHub/ChatGPT. Only intentionally
synthetic metadata/reports are committed for regression. The tool prints fixed
reason/action vocabulary, not OHLC, arbitrary exception strings or document prose.
Header inspection reports are private because column names may themselves be sensitive.

## Windows 10 / Python 3.11 commands

Use the existing Python 3.11 environment on this branch. From the user's verified
project root (adjust only if the checkout has actually moved):

```powershell
Set-Location 'E:\IAT2\Trading-ai-feat-iat2-windows-demo\Trading-ai-feat-iat2-windows-demo'
py -3.11 --version
Get-FileHash 'E:\IAT2\private-data\exports\XAUUSD_M1.csv' -Algorithm SHA256
Get-FileHash 'E:\IAT2\private-data\exports\XAUUSD_M5.csv' -Algorithm SHA256
py -3.11 diagnostics/qualification_assistant.py inspect `
  --file 'E:\IAT2\private-data\exports\XAUUSD_M1.csv' `
  --report-path 'E:\IAT2\private-evidence\m1-inspection-001.json'
```

Repeat inspection for M5. Use the reported exact headers to prepare import.json
beside the source CSVs, calendar and evidence documents. Each selected file must
be an authorized export; do not point inspection at account/credential files.
Then validate without changing inputs:

```powershell
py -3.11 diagnostics/qualification_assistant.py validate `
  --spec 'E:\IAT2\private-data\exports\import.json' `
  --report-path 'E:\IAT2\private-evidence\import-validation-001.json'
Get-Content 'E:\IAT2\private-evidence\import-validation-001.json'
py -3.11 diagnostics/qualification_assistant.py package `
  --spec 'E:\IAT2\private-data\exports\import.json' `
  --output-directory 'E:\IAT2\private-evidence\qualification-package-001'
```

Parent directories must exist. Outputs are never overwritten. Exit **3 is expected**
for DATA_NOT_QUALIFIED, even if mechanical checks pass and a package was completely
written. Inspection uses exit 0. Assessment uses 0 only for an independently
recorded approval that passes the unchanged gate; this is not historical validation.
Do not chain the commands assuming exit 3 means no report/package was created.
A blocked report includes precise reason codes, frame diagnostics and next actions.

## Independent review and existing pilot integration

The importer/preparer must not approve their own package. An independent person
reviews the original exports, permission/provenance, native feed/instrument/basis,
UTC conventions, dated calendar and closed/corrected history evidence.

If they can genuinely verify them, they create a **new** reviewed-manifest.json
beside the canonical files. Only source.independent_review, finality_attested and
existing evidence_review attestations may change. They cannot change prices,
lineage, dates, feed, paths, hashes or calendar to force acceptance. Failed data
requires a new source export/package. They complete a separate qualification
record under the existing [pilot qualification format](REAL_DATA_BLINDED_PILOT_V1.md).
They—not this assistant—supply reviewer identity, date, explicit approval and
VERIFIED evidence after actually reviewing it.

A reviewed manifest has a new dataset ID because attestations change its bytes.
The pending template's initial ID must be replaced with that exact reviewed ID.
Obtain it read-only with the existing qualification command (without approval it
still returns DATA_NOT_QUALIFIED and records dataset_id):

```powershell
py -3.11 diagnostics/review_pilot.py qualify `
  --manifest 'E:\IAT2\private-evidence\qualification-package-001\reviewed-manifest.json' `
  --report-path 'E:\IAT2\private-evidence\reviewed-id-001.json'
```

The reviewer must recompute their record's canonical sha256, excluding its own
sha256 field, using the existing `iat.intelligence.strategy_replay.digest` helper.
This hash is not a signature or a substitute for independence. Then assess:

```powershell
py -3.11 diagnostics/qualification_assistant.py assess `
  --package-directory 'E:\IAT2\private-evidence\qualification-package-001' `
  --reviewed-manifest 'E:\IAT2\private-evidence\qualification-package-001\reviewed-manifest.json' `
  --independent-review 'E:\IAT2\private-evidence\qualification-package-001\independent-review.json' `
  --report-path 'E:\IAT2\private-evidence\independent-assessment-001.json'
```

Assessment verifies the lock, unchanged data/calendar, unchanged import
configurations, sufficient warm-up, independent reviewer code and the existing
historical gate. It creates no approval. Only after genuine success follow the
[predeclared blinded pilot workflow](REAL_DATA_BLINDED_PILOT_V1.md) using that exact
reviewed manifest and approval record. At least two actual consenting blinded
reviewers and an authorized reveal are still needed. This assistant performs none.

## Actual sample and current blockers

The [sample report](research_audits/qualification-assistant-synthetic-v1/sample-report.json)
and [audit](research_audits/qualification-assistant-synthetic-v1/audit.json) are
**SYNTHETIC_ONLY**. Native-shaped M1 and M5 files are constructed separately with
constant synthetic OHLC; their simulated native declaration is not actual feed
provenance. No raw real export or real human approval is included.

Baseline: 150 M1 and 30 M5 rows, 90/18 closed warm-up rows, 12 comparable evaluation
M5 bars, mechanical PASS, qualification DATA_NOT_QUALIFIED. Packages and hashes
repeat identically; input bytes remain unchanged. Missing M1/M5 bars, duplicates,
conflicting OHLC, ambiguous timestamps, mismatched basis, derived M5, insufficient
warm-up, unknown finality and calendar hash mismatch are mechanically BLOCKED.
Absent usage evidence leaves mechanics PASS while qualification remains blocked.
Additional regressions cover DST, metadata-row conflicts, corrections, optional
volume, self-approval, lock corruption and the strict downstream gate.

No authorized real native M1/M5 export with complete independent evidence has been
supplied. Remaining needs: identified provider/entity/feed and legal offline-use/
upstream provenance; exact instrument/basis and UTC opening convention; proof of
native M5; a supported, documented finality/correction contract; dated source-specific
session/holiday/exception/maintenance coverage including warm-up; all document
checksums; and a genuinely independent approval. Then real blinded review can begin.
Historical validation is PENDING, historical comparisons NOT_RUN and real review
metrics unmeasured. No local Exness/MT5 terminal validation is claimed.

CI uses Ubuntu 24.04 and Windows with Python 3.11.9/3.12. Ubuntu is pinned because
Ubuntu 26.04 (now ubuntu-latest) has no setup-python build for Python 3.11.9;
this preserves the existing interpreter requirement rather than skipping it.
