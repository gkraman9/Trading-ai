# Historical Evidence Manifest v1

This offline pipeline records evidence, not approval:

**Operator observation → manifest → local integrity check → mechanical diagnostic reproduction → independent qualification review.**

It does not run strategies, historical comparisons or trading. Every state retains DATA_NOT_QUALIFIED, historical validation PENDING, comparisons NOT_RUN, Exness BLOCKED, READ_ONLY_SHADOW, signal WAIT, execution false, broker access false, zero orders and profitability_tested=false.

## Repository audit and architecture

Base: PR #23, `5083984745527402b8f75b1ab568e558d3cad92e`. The working tree was clean and this commit was available before branching. Existing `chart_benchmark.hashed/check_hash` implement canonical payload digests; `write_new` atomically publishes fresh files; `replay_dataset.read_bytes/strict_json/utc` bound JSON reads and reject duplicate keys, non-finite JSON and non-UTC timestamps. `pilot_preparation.file_fingerprint` streams exact-byte SHA-256. Existing `validate_candles` checks chronology, uniqueness and OHLC integrity. Existing qualification/preflight already separates independent evidence from mechanical consistency.

The new `iat/historical_evidence_manifest.py` reuses those utilities and strictly validates the versioned operator observations and output manifest. The PR #23 CSV reader and report-building body are moved without changing their calculations into `iat.historical_session_boundaries.read_window/inspect_csv_files`; both the original diagnostic CLI and the new verifier call that same implementation. The old CLI still exports `read_window` for compatibility. No second session classifier or alignment formula is introduced.

The existing replay loader now explicitly rejects `kind=HISTORICAL_EVIDENCE_MANIFEST`. Its existing replay schemas and preflight requirements remain unchanged. `qualification_gate()` always denies ordinary strategy inputs, review packet preparation and qualification, regardless of manifest fields or processing state. There is no override. Supplying all document references does not approve anything; actual independent evidence must go through the existing qualification workflow.

## Inputs and separation of facts

[Operator observations](../config/examples/historical-evidence/operator-reported-v1.json) contain the exact user-supplied M1, M5 and diagnostic file hashes, 4,074/816 row counts, 813 five-M1 matches, three partial comparisons, six unresolved absent slots and three conditional 180-second boundary bars. These are **operator-reported, not reproduced in the cloud**. The collection date, byte sizes, exact first/last row timestamps, historical basis and feed identity remain null/UNKNOWN where not supplied. The calendar hash describes the checked-in candidate bytes; it is not broker evidence. The declared observation window is November 11 through exclusive November 14 UTC, as supplied for the PR #23 run.

The strict v1 format accepts only XAUUSD M1/M5 and the reported header layout. It records explicit OHLC/volume mappings, ignored columns, native-timeframe declarations, feed and price-basis declarations. It rejects unknown fields, unsupported versions and unsafe filename identities. It does not infer account/server identifiers, source authorization, candle completion or calendar approval from the CSV. Conflicting declared feeds/bases or derived M5 produce invalid evidence rather than an approval. Derived M5 never substitutes for native M5.

- `operator_assertions` remain frozen declarations, including the reported PR #23 revision and tool version.
- `local_facts` is null in reported mode. In verification mode it records actual file hashes, sizes, headers, counts, opening coverage and normalized OHLC payload hashes. Successfully reproduced findings appear here only after all checks succeed.
- `reproduction` explicitly states REPRODUCED or NOT_REPRODUCED. REPRODUCED refers only to the PR #23 research diagnostic, never a strategy replay or independent verification of market prices, provenance, rights, sessions or finality.
- `externally_verified_evidence` stays empty. Each of nine evidence gaps is MISSING or OPERATOR_REFERENCE_NOT_VERIFIED. References are sanitized local PDF basenames plus declared SHA-256; files are not automatically inspected or accepted as approvals.

## State transitions

| State | Prerequisite / meaning |
| --- | --- |
| OPERATOR_REPORTED | Strict observations accepted; no source CSV read implied. |
| LOCAL_INTEGRITY_VERIFIED | Both CSVs, diagnostic and calendar match expected original-byte hashes and any declared sizes. This is a processing checkpoint, not a final permission. |
| LOCAL_MECHANICAL_REPRODUCED | Exact headers/counts, UTC chronology, duplicate rejection, finite valid OHLC, timeframe boundaries and coverage pass; the existing diagnostic is reproduced exactly; counts, all declared partials, false schedule verification and unchanged blockers match. |
| INDEPENDENT_QUALIFICATION_REQUIRED | Terminal successful processing state, still blocked. Neither previous checkpoint supplies independent evidence. |
| INVALID_OR_CONFLICTING_EVIDENCE | Any mismatch, unsupported input, missing file or contradiction; reproduction stays NOT_REPRODUCED and blockers remain. |

`state_history` records only permitted transitions. Invalid input that cannot form a valid manifest produces a separate `HISTORICAL_EVIDENCE_INPUT_FAILURE` artifact. It cannot masquerade as a valid successful manifest. All eight required PR #23 blocker codes remain present, including in malformed-input failure artifacts.

## Exact digest and determinism contract

| Digest | Calculation |
| --- | --- |
| Source/diagnostic/calendar **file** SHA-256 | Hash of every original byte, including encoding, whitespace and newline differences. |
| Embedded JSON `sha256` | Existing IAT payload digest: remove only root `sha256`, serialize JSON with sorted keys, compact separators, default ASCII escaping, allow_nan=false, UTF-8, then SHA-256. |
| Normalized OHLC payload hash | Same canonical function applied to `{"rows": normalized_rows}`. Original-byte hashes remain separate. |

In particular, the operator's diagnostic **file** hash `74bc31d4e59c16d5eb0f7033fda9116ca7e8e93c68c7e4cd096dfe30aa82863a` must not be compared to its embedded JSON payload digest. The verifier checks both contracts, then compares the entire parsed diagnostic to a fresh computation.

Equivalent input bytes and declarations produce identical manifest objects/digests. All serialized fields except root `sha256` are hashed. Absolute paths, destination filename, runtime clock, filesystem mtime and runtime Python/platform/tzdata metadata are omitted entirely rather than changing the deterministic payload. Tool version is a reliable implementation constant; the reported code revision is explicitly an operator assertion, not an attestation about the verifier's checkout. Record `git rev-parse HEAD` separately in the private review worksheet if needed. Semantic equality alone does not make different original bytes share a file hash.

Dependencies are frozen as observation assertions → manifest; M1/M5/calendar bytes → diagnostic; diagnostic byte and payload digests plus local inspection → reproduced facts → manifest. Reformatting an input report changes its file hash, even if its embedded payload digest stays valid. Do not replace expected hashes simply to obtain a match; review changed evidence and record a separate declared observation revision.

## Windows 10 / Python 3.11 commands

Check out this feature branch first. `tzdata` is already explicitly declared in `requirements.txt`; the operator reports having installed version 2026.6. Reuse the existing Python 3.11 environment. The tool itself installs nothing and has no network or broker access.

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
git rev-parse HEAD
py -3.11 -c "from zoneinfo import ZoneInfo; print(ZoneInfo('UTC'))"
New-Item -ItemType Directory -Force -Path 'E:\IAT2\Reports' | Out-Null

# Record supplied assertions only; this does NOT inspect source files.
py -3.11 diagnostics/historical_evidence_manifest.py reported `
  --observations 'config/examples/historical-evidence/operator-reported-v1.json' `
  --report-path 'E:\IAT2\Reports\historical-evidence-reported-001.json'

# Next local verification: read original bytes and reproduce the PR #23 diagnostic.
py -3.11 diagnostics/historical_evidence_manifest.py verify `
  --observations 'config/examples/historical-evidence/operator-reported-v1.json' `
  --m1 'E:\IAT2\Data\XAUUSD_M1_Exness_20261111_20261113.csv' `
  --m5 'E:\IAT2\Data\XAUUSD_M5_Exness_20261111_20261113.csv' `
  --diagnostic 'E:\IAT2\Reports\historical-session-boundaries-003.json' `
  --calendar 'config/profiles/exness-xauusd-v2.candidate.json' `
  --report-path 'E:\IAT2\Reports\historical-evidence-verified-001.json'
```

Exit **3** means a valid evidence-processing result that is still blocked/unqualified. Exit **2** means invalid/conflicting inputs or failure to publish. Neither is trading success. Existing destinations, source aliases, traversal paths, symlink outputs and unsupported output suffixes are rejected. Use a fresh suffix on a retry; never edit the source files or overwrite the original diagnostic. A missing report directory must be created explicitly. The CLI prints states/reason codes, not input paths or raw candles.

Inspect the result locally:

```powershell
$r = Get-Content -LiteralPath 'E:\IAT2\Reports\historical-evidence-verified-001.json' -Raw | ConvertFrom-Json
$r.evidence_state
$r.state_history
$r.reproduction
$r.local_facts.research_findings
$r.reason_codes
$r.evidence_gaps | ConvertTo-Json -Depth 8
$r.qualification_gate
Get-FileHash -LiteralPath 'E:\IAT2\Reports\historical-session-boundaries-003.json' -Algorithm SHA256
```

On a hash mismatch, confirm the path and compare with the frozen declarations. On header/count/coverage problems, verify the exact original export and UTC scope. On reproduction mismatch, retain both artifacts and inspect code/calendar/report differences privately. On timezone errors, repair the Python environment using the project's declared dependencies; never change session boundaries to force a match.

## Limits and privacy

This first verifier deliberately targets the supplied bounded pilot export: observations <=64 KiB, JSON report/calendar reads <=4 MiB, source files <=64 MiB, <=5,000 rows per timeframe, <=20,000 window minutes and <=32 partial boundary declarations. Every CSV row must lie in the declared observation window; this is not a silent subset selector. UNC/network paths are rejected before file access. Observation inputs must be regular local JSON files. Source file size is checked before/after streamed hashing. Existing CSV scan/line bounds also apply. Unsupported conditions fail closed. For larger archives, use the existing explicit-window preparation workflow and freeze new artifacts/declarations without modifying originals.

Only a fresh separate JSON is written atomically. No raw CSVs, raw price arrays, private diagnostics, personal paths, account IDs, passwords, server labels or tokens are committed or automatically uploaded. No input is executed as code. References are never fetched. Keep real-data output packages private and share only an intentionally sanitized review copy. Integrity digests are not signatures, broker certifications or approvals.

See the [independent review worksheet](HISTORICAL_EVIDENCE_REVIEW_V1.md), [reported manifest example](../config/examples/historical-evidence/operator-manifest-v1.json), and [synthetic audit](research_audits/historical-evidence-manifest-synthetic-v1/audit.json). Tests use invented flat OHLC, never the operator's prices. Full local and Linux/Windows matrix results are recorded in the PR after execution. Historical validation remains PENDING and comparisons NOT_RUN.
