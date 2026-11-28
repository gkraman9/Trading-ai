# E5 operator acquisition procedure v1

Windows10, PowerShell5.1, existing Python3.11. Read-only, offline source inspection;
no MT5 import, package installation, network request or service startup is needed.
Use a reviewed checkout containing PR55 and this research. Keep original archives,
private journals, hashes/reports and correspondence outside Git. Do not paste
credentials, account numbers, server identifiers or original correspondence publicly.

## First operator command: recover existing boundary evidence

After confirming local inspection permission, run this **one command** from the
reviewed repository root, only if the three existing inputs are still at the documented
locations (`E:\IAT2\Data`):

```powershell
powershell.exe -NoProfile -File .\diagnostics\Verify-IATBoundaryEvidence.ps1
```

It reads the existing M1/M5 November11–13 CSVs and original boundary report, creates
a fresh GUID directory, hashes inputs before/after and reruns offline diagnostics.
It does not connect to MT5, approve data or change any original. See
[exact behavior, optional path overrides and recovery](BOUNDARY_EVIDENCE_REPRODUCTION_FOLLOWUP.md).
Exit3 is completed research, **not** E5 qualification; exit2 is BLOCKED. Inspect the
new private `evidence-summary.json` first. Do not substitute a synthetic file when
an input is missing. Share only an authorized redacted summary privately with the
reviewer; retain full source bytes locally. This task has not executed that command
on the operator's machine and has not reproduced the reported4,074/816 observations.

## Then inventory existing archives, one step at a time

Use this separate command only to list filenames/sizes, without opening account or
journal contents. Substitute a known authorized local archive directory when prompted;
do not search the entire computer or start new collection:

```powershell
$archive = Read-Host 'Existing authorized LOCAL archive directory (not a network share)'
Get-ChildItem -LiteralPath $archive -File | Select-Object Name, Length, LastWriteTimeUtc
```

Modification time is a filesystem observation, not receipt, provider finality or
acquisition time. For one selected existing file, the next command is:

```powershell
$file = Read-Host 'Exact authorized LOCAL file to hash'
Get-FileHash -LiteralPath $file -Algorithm SHA256
```

Hash original bytes; do not resave CSV/JSON in an editor, change line endings,
deduplicate or patch recorded hashes. A missing file stays unavailable. Do not hash
a live SQLite database as though frozen; use an existing closed archive. If the
collector is active, do not stop/start it or copy its files under this procedure;
arrange a separate authorized consistent snapshot and preserve all required SQLite
sidecars with collector/code/version metadata. No ad hoc SQL repair or journal edits.

## Required private deliverables before independent qualification

Predeclare exact UTC warm-up (each frame), evaluation and later outcome boundaries
before examining strategy outcomes. Keep original large archives; select only a
reviewed time window into new outputs with the existing pilot importer. Do not thin
ticks, discard corrections, fill gaps or change boundaries to fit validation.
E5 bounds:4MiB/artifact,5,000 bars/frame,256 M1 callbacks,100,000 quotes,10,000 account
events and10MB journal. An unsuitable window stays blocked pending separate review.

| Required file / record | Exact content / acceptance |
|---|---|
| Original native M1 and M5 CSVs | Explicit source column mapping, UTC interval openings, OHLC, optional volume; preserve original bytes/SHA256. Existing Exness8-column contract: `timestamp_utc,open,high,low,close,tick_volume,spread,real_volume`. Native M5 from same feed, never substitute aggregation |
| Normalized M1/M5 + manifests | Existing v2 dataset/import contracts; canonical `timestamp,open,high,low,close`; separate original and normalized checksums and dataset hashes. Evaluation manifest and independently qualified extended outcome manifest have identical prefixes |
| Native quote events | Exact ordered header `sequence,occurred_at_utc,available_at_utc,bid,ask,revision,finality`; contiguous original sequence, actual UTC occurrence and independently justified strategy availability, exact decimal prices, FINAL/revision0. No OHLC prices, fabricated receipts or reconstructed sequence |
| Candle availability | Exact header `timeframe,opened_at_utc,closed_at_utc,available_at_utc,revision,finality`; one record per native normalized bar, actual source publication/availability, FINAL/revision0; verified full session geometry |
| Source/rights documents | Applicable provider legal entity, symbol/feed and BID/ASK/MID mapping, permission for private offline analysis and independent review, acquisition method/time and original archive hashes; an Exness label is insufficient |
| Dated calendar documents | Quote and new-position/close-position permissions, breaks, Friday/weekend, DST/UTC anchors, holidays, regular/special maintenance, complete warm-up through outcome dates. Resolve the report's conflict matrix independently |
| Finality/capture/corrections | Provider convention plus original collection logs, missing/repeated/rejected observations, clock/availability evidence, completeness bounds and revision policy. Later retrieval is not original availability |
| Dated specification and cost documents | Exact financial checklist below; no guessed contract or fee defaults |
| Independent reviews | Existing source qualification reviews for evaluation AND extended outcome, E4.7 bundle, E5 adapter review; named privately, genuine independent review and exact-byte/hash/date scopes; no auto-approval |

If the export has no receipts, ask the original collector/provider for the original
capture/transport records and clock convention or an authoritative availability
contract with applicability to this exact export/window. A present-day MT5 tick
range download gives event time, not historical per-tick receipts. A complete flag
or expired interval is not permanent finality. If the evidence cannot be supplied,
record **NATIVE_RECEIPT_HISTORY_OR_REVIEWED_AVAILABILITY_CONTRACT_UNAVAILABLE** and stop
benchmark preparation; all historical metrics stay unmeasured.

## Historical financial evidence mapped to existing contracts

Provide dated documents effective/known by the earliest warm-up and valid through
outcome end, bound to the same entity/feed and instrument. Preserve original files
and hashes; record issue/retrieval/effective dates independently. Current terminal
screenshots are leads, not proof of past conditions. Do not use account credentials.

| Broker information | Existing E5 fields / evidence required |
|---|---|
| Contract / ticks | `contract_size,tick_size,tick_value,point_size`, account/profit/margin currencies; tick-value consistency and USD linear calculation applicability |
| Minimum order | `min_lot,max_lot,volume_step,min_stop_distance,freeze_level`; actual minimum-lot margin/risk rejection is allowed |
| Leverage / margin | `margin_method,leverage`, margin-call and stop-out equity ratios; dated account-class applicability without publishing account identity; dynamic/nonlinear/FX margin needs a separate adapter |
| Spread | Native time-specific Bid/Ask series and capture completeness; never replace with a fixed typical spread or charge spread twice |
| Commission / fees | `commission_convention,commission_per_lot_side,other_per_lot_side`; explicit charging currency/side/lot/time basis and genuine dated evidence of any zero |
| Financing / rollover | `financing_convention,financing_per_lot_day`, rollover clock/day multipliers, holiday handling and direction/account-class scope; current constant model cannot implement arbitrary real swap schedules |
| Fill assumptions | `slippage_price_per_fill,conversion_rate`; independently review frozen receipt-side model's applicability. No guaranteed fill or invented realized slippage; USD conversion1 only under actual supported currencies |
| Liquidation | Dated stop-out/margin-call rules, frozen entry-margin model applicability, competing-stop/event-order treatment; unsupported changes remain blocked |

Specifications/costs use E4.7 envelopes: version1, kind
`INSTRUMENT_SPECIFICATION`/`TRADING_COSTS`, symbol, feed_id, available_at_utc,
effective_from_utc, effective_until_utc and values. Reuse the exact existing schema
([E4.7](E47_PAPER_ENGINE_REVIEW_AND_READINESS.md)); don't create a weaker spreadsheet
contract. A single frozen spec/cost interval is supported. Multiple effective values,
revisions, nonconstant rollover or unavailable documentation require separate review,
not selecting convenient values or inventing zero charges.

## Independent handoff and final replay command

An operator prepares evidence; an independent reviewer examines actual source files,
terms, dates and unresolved conflicts. Nonempty fields and hashes alone cannot
prove authenticity, completeness or independence. The reviewer must not be the
preparer. Obtain actual source qualifications first; no approval generator is supplied.

Reuse [PR55's exact seven-role plan and independent adapter review](E5_HISTORICAL_PAPER_ADAPTER_V1.md).
The plan binds manifest, review, paper_bundle, outcome_manifest, outcome_review,
import_spec and bar_availability. The bundle binds raw M1/M5, native quotes,
specification/costs and the unchanged policy. Independent adapter assertions cover
raw-normalized lineage, quote/session semantics, receipt-price fill model, outcome
finality and instrument/cost applicability. Bind the frozen protocol SHA256
`e31b4c038dccdee4426cbdef879ef0ea23f2a8afd57b8d4309042194da4c01c8`.
Do not type APPROVED until a genuine independent review supports it.

Only after that handoff, run the existing offline E5 command (one step):

```powershell
$plan = Read-Host 'Existing independently reviewed local E5 plan JSON'
$review = Read-Host 'Existing independent adapter-review JSON'
$out = Read-Host 'Existing private LOCAL output directory outside Git'
$report = Join-Path $out ('e5-' + [Guid]::NewGuid().ToString('N') + '.json')
py -3.11 .\diagnostics\e5_historical_paper.py --plan $plan --independent-review $review --report-path $report
```

Do not run E5 with a template approval or use synthetic admission mocks. Exit0 only
means that the actual adapter/replay completed under its reviewed hypothetical model;
inspect all unresolved outcomes and comparisons. Exit3 is BLOCKED; exit1 is failure.
Read the generated reason codes and preserve evidence instead of editing inputs to
force success. E5 independently runs full/full/prefix comparisons. Keep full real-data
journals private. No command starts a service or approves Exness/calendar/execution.
