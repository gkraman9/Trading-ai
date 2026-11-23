# PR #42 follow-up: one-command private evidence reproduction

The November 11–13 private CSVs and November 23 original report remain unavailable in cloud. Their counts, file SHA-256 values and original/recomputed comparison are **unmeasured / NOT_RUN here**. No original observations have been reconstructed. The original PR #42 source review, published references and conflict matrix remain the baseline; no completed web research was repeated.

PR #41 remains draft/unmerged. This follow-up updates PR #42 on the same branch, preserving its base relationship to PR #41. No calendar/profile/review or existing ordinary quality/execution gate is changed.

## One operator command

After the checkout at `E:\IAT2\IAT2-Latest` contains this PR's updated files, run exactly:

```powershell
powershell.exe -NoProfile -File 'E:\IAT2\IAT2-Latest\diagnostics\Verify-IATBoundaryEvidence.ps1'
```

This single entry script includes default paths for both original CSVs and `b2_historical_boundaries_20261123.json` in `E:\IAT2\Data`. It locates its checked-in Python helper and existing boundary diagnostic relative to the script, uses the existing Python 3.11 installation via `py -3.11`, and creates a new GUID output directory under `E:\IAT2\Data`. No separate setup, installs, network, terminal connection, account, MT5 package or service is needed. A specific existing interpreter can be supplied with `-PythonExe`; do not install dependencies or alter source data just to force PASS.

The operation is self-contained within this checkout and Python environment; do not copy only the PowerShell file without its checked-in helper. The script does not fetch or switch Git branches, execute downloaded scripts, or bypass Windows execution policy. Update/review the checkout through the existing Git workflow first. No merge is required.

Optional explicit parameters are `-M1Csv`, `-M5Csv`, `-OriginalReport`, `-CalendarPath`, `-OutputDirectory`, and `-PythonExe`. Use only local paths and a NEW output directory outside every Git checkout. The defaults match the operator's actual file locations. Do not provide example/synthetic exports as substitutes. The runner has no synthetic fallback or generation mode.

## What the command does

1. Checks Python 3.11 and all four inputs. Every readable input gets an exact original-byte SHA-256/byte count; missing/unsafe inputs get explicit unavailable records. UNC, URL, symlink and network-drive inputs are rejected. Private inputs and outputs are rejected inside Git checkouts; the reviewed candidate calendar may be inside the project.
2. Requires the previously declared CSV header order: `timestamp_utc,open,high,low,close,tick_volume,spread,real_volume`. Streams read-only UTF-8/BOM-aware parsing; checks UTC-zero-offset aware timestamps, interval alignment, duplicates, chronological ordering, positive finite OHLC and high/low consistency. All rows must lie in the explicit November 11–14-exclusive window; no silent selection/normalization. Bounds: 64 MiB per CSV, 5,000 rows per frame and bounded line lengths. Other formats need a separately reviewed mapping; never edit originals to fit this tool.
3. Records raw timestamp gaps as nominal gaps, not automatically unexpected market data. Session-related missing slots and classifications continue to come from the existing calendar-aware research diagnostic. Empty/malformed/insufficient or out-of-window inputs remain BLOCKED.
4. Validates the original report's existing payload checksum, research version/status, unqualified safety fields and ordinary-input suppression. Rechecksummed execution/approval fields cannot pass. An explicitly synthetic original report is rejected as operator evidence. Missing old source bindings are not invented or silently repaired.
5. Requires the actual v2 candidate's verification/finality flags to remain false. Runs the existing `diagnostics/historical_session_boundaries.py` as an offline child process, with no MT5 imports or execution APIs. Exit 3 is required **and** the output JSON/checksum/safety/bindings are checked; exit code alone is never success evidence. Timeout/unavailable output cannot produce a match.
6. Compares original and recomputed counts, per-frame classifications/phases, missing-slot counts, sampled M5 geometry/M1 slot assessments, window, calendar identity, and exact report-file/payload hashes. It records original-declared versus current M1/M5/calendar fingerprints. Even a change outside the projected fields is detected by the full payload hash. Raw byte differences and semantic differences are separate: it never normalizes evidence files to make SHA-256 match.
7. Compares the recomputed metrics with the **reported expectations**, kept as assertions: M1 4,074; M5 816; five-M1 matches 813; partial closes 3; missing M1 slots 6. The last count is the existing diagnostic's M1-slot absence count across observed M5 intervals, not every absent minute in session breaks. Expected figures never replace measurements.
8. Records six requested boundary windows: three 21:55–22:00 closes and three 23:00–23:05 windows (including Friday to make its scope visible). Opening labels remain interval openings; actual first tick is null/unknown. Five-M1 agreement never proves trading permission or full/partial finality. Sparse/restricted/missing intervals are not reconstructed.
9. Rehashes **all original inputs** after the operation. Any changed/unavailable input makes the result BLOCKED and its comparison not established. It records source-code fingerprints, preserves every assurance conflict as UNRESOLVED, and atomically publishes a new checksummed `evidence-summary.json`. Existing files/directories are never overwritten. An interrupted write leaves no completed success summary.

## Outputs and exit codes

The script prints the new private summary path. Keep the whole directory outside Git:

- `recomputed-boundaries.json`: existing research diagnostic, if it could run. A partial directory or this file alone is not a completed verification result.
- `evidence-summary.json`: completed deterministic evidence record, including raw input hashes before/after, CSV scans, whitelisted original/recomputed projections, differences, exact report hashes, reported expectations, requested boundaries, code fingerprints and unresolved conflicts. It contains no account information, credentials or raw OHLC rows. It is still private evidence, not a public broker certification.

| Summary status | Meaning |
|---|---|
| `LOCAL_MECHANICAL_MATCH` | Original/recomputed payload and projected findings agree, original source bindings match actual bytes, inputs stayed unchanged and all five reported totals match. This is **not** source authentication, independent qualification, completeness, finality or permission. |
| `DIFFERENCES_FOUND` | The operation completed, but report content, original input bindings or expected totals differ. Read the individual fields; do not regenerate old hashes or adjust candles/calendar to hide differences. A semantic match with different report formatting records both exact byte hashes without changing either file. |
| `BLOCKED` | Missing/unsafe/malformed input, integrity error, untrusted checksum/safety fields, changed inputs, diagnostic failure or another precondition failure. No reproduction claim. |

Exit **3** means completed research (`LOCAL_MECHANICAL_MATCH` or `DIFFERENCES_FOUND`), with qualification still blocked. Exit **2** means BLOCKED or no completed summary could safely be published. No exit code grants trading permission. Every report retains `WAIT`, `execution_allowed=false`, `DATA_NOT_QUALIFIED`, Exness `BLOCKED`, historical validation `PENDING`, and historical comparisons `NOT_RUN`.

Differences include a total count and up to 128 field-level entries; the underlying old report and recomputed report remain private for further inspection. Original diagnostic samples are bounded to 64 M5 intervals; this does not reduce aggregate coverage counts. CSV scan gap samples are bounded to 64 with a separate total. No bounded sample is claimed to be the complete tick tape.

## Conflict matrix: unchanged pending independent evidence

| Claim | What local mechanical reproduction can add | Still required; state stays UNRESOLVED |
|---|---|---|
| Reopening 23:00 vs 23:00:30 | Actual interval-opening presence and nominal geometry | Dated same-feed quote/tick/session evidence; a 23:00 minute label cannot resolve first-tick seconds. |
| CLOSE_ONLY vs FULL_TRADING | Mixed-phase bar classifications | Independent dated permission evidence; quotation availability and numeric matches are not permission. |
| Friday/weekend | Actual file openings around Friday close/reopening | Full source coverage plus explicit Friday/weekend applicability; no inferred Friday reopening or closure from a truncated export. |
| November 11 holidays | Source/report consistency, not an exception attestation | Instrument/feed-specific dated holiday evidence. |
| Regular vs special maintenance | Observed gaps at available granularity | Dated regular/special maintenance coverage and capture completeness; minute bars cannot exclude sub-minute pauses. |
| UTC / Bid provenance | Syntactically UTC openings and preserved source bytes | Export/collection convention and legal provider/feed/Bid mapping. Header labels alone do not establish provenance. |
| Full / partial finality | Partial geometry, elapsed schedule and numeric consistency | Provider full/partial finality contract. Three M1 rows never become an eligible full M5 by interpolation. |
| Corrections / completeness | Exact byte integrity and discrepancies at this run | Provider correction/version policy and independently established capture/history completeness. |

Usage authorization, authenticated broker correspondence/attachment inventory and independent reviewer approval remain required as in PR #42. No self-approval or verification-flag changes are offered by this runner.

## Continuing after the operator run

Provide the private `evidence-summary.json` through an authorized private channel; retain the original inputs and both diagnostic reports locally. Do not commit CSVs, private summaries, local journals or account information. The summary is intentionally free of source absolute paths and raw prices, but its hashes still identify private evidence.

The next analysis will verify the summary checksum, input before/after records, original bindings, code fingerprints and reported-count checks, then inspect its recorded differences/boundary windows. It can continue from these artifacts and PR #42's existing source matrix without restarting the web investigation. If source bytes need independent review, reviewers must have authorized access; a summary cannot authenticate the broker feed.

## Test and CI scope

New tests address genuine runner gaps: full local path with tiny **labeled synthetic** files, no input mutation, expected-vs-measured differences, safety under a mechanical match, checksum/safety tampering, missing bindings, changed inputs, CSV header/UTC/order/OHLC errors, payload changes, exact byte differences, missing-file coverage, deterministic repeatability, safe paths and failed publication. They do not rebuild a 4,074/816 synthetic archive to stand in for the operator's export.

PR #42's eight boundary regressions remain in the full suite. Their duplicated standalone CI step was removed; Windows Python 3.11 CI now additionally runs the actual PowerShell entry point with explicit synthetic temporary files and a missing-input case. This validates quoting, exit codes and safety on Windows without touching real data or starting services. Exact focused/full results and CI are recorded in PR #42.
