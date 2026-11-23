# Exness session evidence investigation — 23 November 2026

Research only. `WAIT`, `execution_allowed=false`, `DATA_NOT_QUALIFIED`, Exness `BLOCKED`, historical validation `PENDING`, and historical comparisons `NOT_RUN`. No calendar approval, broker certification, services, terminal connection or trading readiness is implied. PR #41 remains unmerged.

## Inputs actually available

The requested Windows M1 CSV, M5 CSV and `b2_historical_boundaries_20261123.json` are **not available in this cloud workspace**. No real OHLC was inspected, reconstructed, regenerated or uploaded. Their exact checksums, headers, chronology, actual first/last timestamps, finality, and 813 numeric matches have **not** been independently reproduced. Real price comparison metrics remain unmeasured.

The operator reports 4,074 M1 observations, 816 M5 observations, 813 five-M1 matches, three 21:55 M5 partials, missing M1 21:58/21:59 on November 11–13, and resumption in the 23:00 interval on November 11/12. Those remain **OPERATOR_REPORTED**, not test evidence. The older `config/examples/historical-evidence/operator-reported-v1.json` also contains claimed hashes, but references a differently named historical diagnostic. Do not assume that diagnostic is the November 23 file or silently replace its hash.

`docs/research_audits/historical-evidence-manifest-synthetic-v1/audit.json` contains the same headline counts and explicitly says its flat OHLC is invented. Its numeric reproduction is a software fixture, **not a reproduction of the private export**. No matching synthetic archive was generated in this investigation to stand in for the unavailable data.

Inspected repository evidence:

- `config/profiles/exness-xauusd-v2.candidate.json` and `config/profiles/exness-xauusd-v2.review.json`: exact-byte candidate hash matches the review. Quote/trade/holiday/maintenance declarations and candle-finality verification are all false; the conflict hold remains. No profile/review bytes changed.
- `config/reference/exness-2026-11-11-13.relayed.json`: user-relayed claims, explicitly unauthenticated. Its original metadata/transcription are accessible in Git commit `09cf0f13c649b522447e1f5a1796bf52e2ff2519`, although that old directory is absent from the current tree. Exact metadata-file, canonical metadata-payload and transcription hashes match the reference. This establishes repository integrity, **not sender authenticity**. Original email headers and attachment inventory are `NOT_SUPPLIED`; provider sent-time is absent; independent authentication is pending.
- Existing session/boundary/qualification implementation and tests. No production change was needed to expose nominal partial-close geometry or distinguish quote availability from trading permission.

The metadata-only [consolidated JSON](source_reviews/exness-session-investigation-2026-11-23.json) binds repository file hashes, separates reported counts from actual checks, and records a real-data comparison status of `NOT_RUN`.

## Primary references checked on 23 November 2026

All descriptions below are our summaries, not copies of the articles. Public documentation is not proof of this export's entity/feed or exact dated applicability.

| Reference | What was established | Limit |
|---|---|---|
| [Exness November DST notice](https://get.exness.help/hc/en-us/articles/31342732737180-Trading-Hours-Update-End-of-US-Daylight-Saving-Time-01-Nov-2026) (updated November 3) | Ordinary winter XAUUSD: weekday close 21:58; close-only begins 23:00:30 and ends 23:02; Friday stays closed after 21:58. Sunday has different boundaries. | Not authenticated per-feed dated exception evidence; do not substitute XAUUSD 247. |
| [Instrument trading hours](https://get.exness.help/hc/en-us/articles/4405235684498-Instrument-trading-hours) (updated November 22) | UTC+0 servers; current dynamic date-selection widget; general maintenance guidance includes brief Cent/Trial daily pauses around 23:20. | Updated after the target dates; no exact November 11–13 duration or historical completeness established. |
| [Holiday trading hours](https://get.exness.help/hc/en-us/articles/17923046759836-Holiday-trading-hours) | November 11 is listed as a holiday; the visible exception table does not establish this export's dated gold schedule. | A holiday name does not prove either a gold closure or absence of exceptions. |
| [Exness MetaTrader timezone](https://get.exness.help/hc/en-us/articles/360014390760-What-is-the-default-timezone-set-for-MetaTrader) | General GMT+0 convention. | Does not authenticate CSV timestamp conversion or interval-opening convention. |
| [MetaQuotes bar range API](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py) | UTC **bar opening** timestamps and chart-history availability constraints. | An interval label is not first-tick time or proof of capture completeness. |
| [MetaQuotes position API](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py) | Position zero is the current bar. | Excluding it does not independently prove permanence, corrections policy, or partial-bar finality. |
| [Quote sessions](https://www.mql5.com/en/docs/marketinformation/symbolinfosessionquote), [trade sessions](https://www.mql5.com/en/docs/marketinformation/symbolinfosessiontrade), [Python API inventory](https://www.mql5.com/en/docs/python_metatrader5) | MQL session functions describe symbol/day-of-week windows; these session functions are not listed in the standard Python API. | Weekly metadata is not a dated holiday/maintenance archive or intraday permission audit. No terminal/bridge was run. |

The official help page embeds a public schedule widget. Its page/scripts were inspected read-only; **no script was executed, client key reused, account accessed, or credential supplied**. A noncredentialed GET to its discovered schedule route for the target dates returned HTTP 403, so no dated schedule payload was obtained. This is a retrieval limitation, not proof that the official UI cannot display those dates. An operator/reviewer can save the dated UTC/XAUUSD output from the official UI for independent review. No access-control bypass was attempted and no raw vendor page/script was committed.

## Calendar conflict matrix (all UTC)

Configured quotation geometry is conditional. Verified permissions remain unknown and IAT execution remains false throughout.

| Date/interval | Candidate geometry and phase | Reported/other evidence | Finding |
|---|---|---|---|
| Nov 11–13, 21:55–22:00 M5 | Quotes through 21:58: 180 nominal quoted seconds; `PARTIAL_SESSION_CLOSE`; scheduled end remains 22:00. | Three partial native M5 bars reported. | Compatible geometry only. No partial finality or eligible full-bar claim. |
| Nov 11–13, 21:58 and 21:59 M1 | Outside nominal quote windows; phase CLOSED. | Six absent observations reported. | Candidate is unverified: diagnostic absence remains `MISSING_UNESTABLISHED_UNVERIFIED_CALENDAR`, not a verified legitimate closure or unexpected full-session gap. |
| Nov 11/12, 23:00:00–23:00:30 | Quotes configured; phase UNKNOWN. | Published winter notice: closed until :30. Relayed reply: quotation/close-only from :00. | Unresolved source conflict. A bar opening at 23:00 cannot distinguish these second-level starts. |
| Nov 11/12, 23:00:30–23:02 | Quotes configured; CLOSE_ONLY. | Public notice and relayed reply overlap on close-only here. | Corroboration of general phase description; no opening permission or exact-feed certification. |
| Nov 11/12, from 23:02 | Quotes configured; FULL_TRADING. | Public ordinary schedule agrees; relayed reply does not independently establish new-position permission after this boundary. | Calendar flags still false; observed quotations do not prove permission. |
| Nov 11/12, 23:00–23:05 M5 | FULL_SESSION_BAR describes **quote geometry**; phases UNKNOWN, CLOSE_ONLY and FULL_TRADING are mixed. | Could numerically match five M1 rows if available. | Matching/full geometry is not ordinary full-trading eligibility. |
| Fri Nov 13, from 21:58 (including 23:00) | CLOSED; no Friday reopening. | Public winter schedule agrees. Generic relayed daily-break language lacks an explicit Friday carve-out; operator reports reopening only Nov 11/12. | Friday/weekend scope needs dated clarification. Do not invent a Friday 23:00 reopen or infer closure from a truncated export. |
| Nov 11 holiday / possible regular maintenance | No exceptions entered; holiday/maintenance flags false. | Relayed reply says no **special** interruptions; public guidance also describes regular maintenance. | No special interruption does not independently prove absence of regular pauses. Minute bars can hide sub-minute interruptions. |
| Historical window vs current request | Coverage Nov 6 through exclusive Nov 16; expiry Nov 16 00:00Z; evidence captured Nov 12. | Review remains BLOCKED. | Historical nominal inspection is possible; current Nov 23 requests are expired. Earlier causal requests cannot use later-captured evidence as contemporaneous verification. |

**Key identifiability limit:** both quote-start hypotheses (:00 and :30) can yield an M1 candle whose interval opening is 23:00. Under :00 it has 60 nominal quoted seconds; under :30 it is a 30-second partial opening. OHLC/interval labels cannot establish the first quote's second or trading permission. Likewise, elapsed nominal 22:00 does not prove when the native 21:55 partial bar became final.

## Implementation audit

`diagnostics/historical_session_boundaries.py` delegates explicit CSV mapping/window inspection to `inspect_csv_files()`. It hashes original bytes before/after, parses UTC openings and OHLC, then calls `boundary_research()`. The sidecar:

- Reuses v2 research classification, with separate ordinary classification and verification fields; it never emits ordinary inputs.
- Compares exactly five aligned M1 openings against native full-geometry M5 only when both frame inputs are numerically valid and the nominal interval elapsed. It never replaces native M5 or aggregates three M1 bars into an eligible candle.
- Keeps partial comparisons suppressed, differences null, finality unestablished, and candidate missing-slot assessments unverified. Unknown/close-only phase diagnostics remain visible even when a full-geometry interval has a numeric match.
- Limits stored interval samples to 64 while preserving full aggregate counts. Three 21:55 partials are prioritized in those samples; sample length is not total M5 coverage.
- Uses calendar geometry **conditionally**, not as independent evidence of actual quotations. Research as-of and configured expiry are distinct from the date the tool runs.
- Does not validate provider entity, feed, BID mapping, legal permission, export completeness or original broker email authentication. Those belong to the existing independent qualification gate.

No ordinary validation, v2 classification, finality, alignment, qualification or execution rule was modified. Existing tests already cover partial close/open geometry, coverage, assurance holds, expiry, missing bars, close-only phases and unchanged profile bytes. Eight additional synthetic regressions lock down the actual candidate's three dates, five-row/partial separation, minute-label ambiguity, mixed phases, Friday scope, expiry/future evidence, structural phase conflicts and missing-input behavior. Synthetic probes are nine M1/three M5 boundary rows, not a replacement 4,074/816 dataset. Regression results and full CI evidence are recorded in the draft PR.

## Safe local reproduction, without services or terminal access

Run in a checkout containing this research branch. These commands inspect only the already exported CSVs and candidate JSON. They do not start B.2/B.3, connect MT5, adjust flags or alter existing reports. Keep all outputs private and outside Git.

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
$m1 = 'E:\IAT2\Data\XAUUSD_M1_Exness_20261111_20261113.csv'
$m5 = 'E:\IAT2\Data\XAUUSD_M5_Exness_20261111_20261113.csv'
$previous = 'E:\IAT2\Data\b2_historical_boundaries_20261123.json'
$calendar = (Resolve-Path '.\config\profiles\exness-xauusd-v2.candidate.json').Path
$inputs = @($m1, $m5, $previous, $calendar)
foreach ($path in $inputs) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required local input missing: $path" }
}
# Inspect the CSV headers locally; do not print full broker datasets.
Get-Content -LiteralPath $m1 -TotalCount 1
Get-Content -LiteralPath $m5 -TotalCount 1
$before = @{}
foreach ($path in $inputs) { $before[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
$out = Join-Path 'E:\IAT2\Data' ('session-review-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $out -ErrorAction Stop | Out-Null
# Use timestamp_utc ONLY if both inspected headers confirm that exact UTC-opening column.
py -3.11 .\diagnostics\historical_session_boundaries.py --m1 $m1 --m5 $m5 --calendar $calendar --timestamp-column timestamp_utc --start-utc '2026-11-11T00:00:00Z' --end-utc '2026-11-14T00:00:00Z' --report-path (Join-Path $out 'recomputed.json')
# Existing research CLI intentionally exits 3 even when diagnostics are produced: it never qualifies data.
if ($LASTEXITCODE -ne 3) { throw 'Unexpected diagnostic runner result' }
$r = Get-Content -LiteralPath (Join-Path $out 'recomputed.json') -Raw | ConvertFrom-Json
if ($r.status -ne 'RESEARCH_DIAGNOSTICS_ONLY' -or $r.qualification -ne 'DATA_NOT_QUALIFIED' -or $r.safety.execution_allowed -ne $false) { throw 'Blocked/invalid diagnostic; inspect reason codes' }
foreach ($path in $inputs) {
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $before[$path]) { throw "Input changed during research: $path" }
}
# Save exact hashes privately. No normalization or replacement of originals.
$before | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $out 'private-input-sha256.json') -Encoding UTF8
$r.comparison_counts
$r.m1_slot_absence_counts
$r.frames.M1.observed_count
$r.frames.M5.observed_count
$r.m5_intervals | Where-Object { $_.geometry.classification -eq 'PARTIAL_SESSION_CLOSE' } | Select-Object geometry, five_m1_comparison, partial_finality, ordinary_eligible
```

If headers differ, pass the existing explicit `--timestamp-column` and `--open-column/--high-column/--low-column/--close-column` options with verified names; do not infer timezone/basis or rename source bytes. UTC interval-opening semantics require evidence in addition to the column name. The CLI's end is exclusive. Its `historical_comparisons=NOT_RUN` refers to qualified historical replay; mechanical five-M1 diagnostic counts are a separate research observation.

Compare the old report's window, calendar hash, source fingerprints, parse errors and complete aggregate counts against the new output before treating them as the same run. An old file with the same headline counts can still bind different bytes, scope or policy. The existing `diagnostics/historical_evidence_manifest.py verify` workflow can bind a privately reviewed strict observations document to the exact M1/M5/diagnostic/calendar bytes; do not reuse the example's asserted hashes or diagnostic name unless each actually matches. Mechanical reproduction still does not qualify the source.

If no local access can be arranged, an authorized operator can supply a private package containing the two unchanged CSVs, original report, exact file hashes, header mapping, declared interval convention and permitted-use references through an approved private channel. Never commit that package. If redistribution is not permitted, run the commands locally and retain source files locally; independent reviewers must have authorized access before signing anything. A summary alone cannot authenticate the raw bars.

## Prioritized remaining evidence

1. **P0 — exact local inputs and permission:** inspect source hashes/bytes, headers, UTC range and native same-feed M1/M5 provenance; independently bind the legal provider entity, feed, UTC interval openings and BID basis to these exact files. The relayed general Bid-chart claim alone does not bind the export. Obtain offline usage/independent review permissions.
2. **P1 — authenticated dated sessions:** reconcile :00 versus :30 and Friday weekend scope with instrument/feed-specific primary evidence covering the full warm-up and evaluation dates. Obtain the complete broker reply with authenticated provenance, sent-date and attachment inventory, or reviewed dated public schedule output. Record actual quote availability separately from opening/closing permissions; no self-approval.
3. **P1 — exceptions and continuity:** independently establish November 11 holiday applicability and all regular/special maintenance for the exact feed/dates, including any 23:20 pause. Weekly symbol metadata and current article contents do not certify dated absence of interruptions. Tick-level or provider-capture evidence is needed for second-level completeness.
4. **P2 — bar finality/corrections:** obtain provider contracts covering full bars, the 21:55 partial-close bars, native M5 finalization time, corrections/version history and capture completeness. Matching OHLC, position 1, elapsed time and stable file hashes do not establish these facts. The current ordinary engine does not accept partial candles even with a full-bar attestation; changing that policy is a separate reviewed project.
5. **P2/P3 — independent qualification then bounded research:** independent reviewers resolve conflicts, verify source artifacts and sign the existing qualification workflow. Any future scoped window avoiding unsupported partials must declare excluded scope and preserve original archive hashes, sufficient warm-up and all gates. Do not delete interior rows, round boundaries, replace native M5, or raise verification flags to force PASS. Historical replay/blinded review remain NOT_RUN until the required qualification is genuinely satisfied.
