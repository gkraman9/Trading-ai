# E4.7 paper engine review and historical replay readiness v1

This is an automated adversarial technical review by the implementation assistant,
not independent human sign-off, broker certification or performance evaluation.
Review date: 27 November 2026. No historical or live paper engine is activated.
The first effectiveness benchmark remains unchanged M1/M5 with USD50 virtual
starting capital. R2/ML/AI expansion is not a prerequisite or part of this work.

## Dependency audit and parent

Open draft PR stack inspected before implementation:

| PR | Verified head | Scope |
|---|---|---|
|49|e18f6c7c61b3caebef45085a74b2aa93ba7caded|Synthetic paper/capital v1|
|50|5c9b965fe9fa3c6b50122f566620605d18e6aaae|E4.6 protection/liquidation v2|
|51|bf5bd478e8298c7e45cffa713a148ab88ce0d2a5|MT5 lifecycle hardening|
|52|6bdee14174f9087ab020afb432c650f0e349f506|Architecture/protocol/roadmap|
|53|1f7054d5981c2f8147262ae51a089e466066701a|R1 offline timeframe foundation|

No existing E4.7 implementation was found in the open PRs, branch names or source.
Parent is exact PR52 head, including PR50/51 and the research architecture, while
remaining independent of R1/R2 implementation. Target is PR52's
`docs/iat-v3-multi-timeframe-architecture`. Existing PRs remain draft/unmerged.
The architecture, research protocol and implementation roadmap are retained.

## Reproduced defects and corrections

### E47-01: serialized journal boolean/integer type confusion (medium)

Both v1 and v2 journal validators compared Python dictionaries directly. Changing
`execution_allowed: false` to numeric `0`, leaving the checksum untouched, passed
because Python treats False == 0. This did not authorize an order, but accepted a
malformed safety contract as authentic. Two subtests reproduced the failure.
Correction: source equality also requires identical canonical JSON digests. This
is source recomputation, not checksum-only approval. Top-level and nested account
flags are tested; genuine JSON round trips remain valid. No serialized producer
fields, original journal versions, scores or financial outcomes change.

### E47-02: closed-quotation exception preceded history authentication (high)

A new tape with matching source labels/current closed-quotation row but missing
entry history produced UNRESOLVED and committed a journal mutation before the
private original-prefix proof was checked. One adversarial test reproduced this.
Correction: verify committed source history before handling quotation closure or
any unresolved-state mutation. Forged replacement now rejects transactionally;
a genuine quotation-closed row still becomes explicitly unresolved. The complete
original prefix remains required; matching names/checksums alone are insufficient.

Before corrections: 2 test methods, 3 failing subtests, 1.482s on Python3.11.9.
After corrections: the same 2 methods pass, 2.890s. No assertion was weakened.
New review checks additionally cover corrected old quotes, complete journal/private
history/cost rollback on resource failure, retry without double fill, and ambient
Decimal precision. Those checks did not establish additional defects.

## Lifecycle review coverage

Inspected paper_contracts, capital_intelligence, paper_account,
protection_contracts and protected_paper end to end, their risk/source contracts,
existing dataset qualification, quote qualification, preflight and regression tests.

| Topic | Established behavior / tests | Remaining limitation |
|---|---|---|
|Entry and sizing|Authenticated original E1/E2/E3; first causal quote; downward volume rounding; minimum-lot/risk/free-margin rejection|Synthetic mapping/specification only; no leverage or risk increase to reach minimum lot|
|Bid/Ask|Long entry Ask/exit Bid; short entry Bid/exit Ask; spread already embedded|No executable broker liquidity evidence|
|Stops and gaps|Frozen structure-to-quote reference, establishment before logical open; side-specific trigger; first eligible delayed fill; gap loss may exceed budget|Synthetic receipt-price/latency model, not guaranteed broker fills|
|Competing exits|Distinct structural/stop/liquidation order remains unresolved; only identical stop/liquidation fill functions coalesce|OHLC cannot establish intrabar event order|
|Costs|Per-side fees once; adverse slippage once per fill; explicit financing convention|Linear USD and per-24h financing only; no inferred swap/triple-rollover/currency adapter|
|Margin|Frozen declared entry margin, warnings restrict entries; reviewed synthetic stop-out policy|Not verified Exness margin/liquidation rules; dynamic margin changes unsupported|
|Capital|USD50 examples: unaffordable minimum lot, insufficient margin, repeated losses, recovery, spread, adverse gap, exhaustion/negative balances|Test arithmetic does not establish realistic broker affordability or profitability|
|Loss limits|Daily loss by actual fill UTC day; historical drawdown retained; consecutive losses constrain subsequent opportunities|External deposits/withdrawals are explicit and must be excluded/frozen for benchmark|
|Missing/delayed data|Occurrence/receipt/freshness separate; missing known quote or stale analysis unresolved; duplicates idempotent|No complete real capture or historical receipt-time adapter|
|Integrity|Producer prefix authentication; source-bound frozen reports; transactional rollback incl private history; deterministic replay/prefix/future-append tests|In-process authentication is not a signed external evidence system or hostile-code sandbox|

Existing regression groups: test_paper_trading, test_paper_independent_review,
test_paper_report_contracts, test_paper_protection_review, test_protection_intelligence
and test_protection_scenarios. No strategy predicates, thresholds, risk parameters,
fill algorithms, calendars or ordinary accounting goldens are altered.

## Historical preflight contract

`iat.paper_readiness.historical_paper_preflight(manifest, review, bundle)` is a
read-only readiness inspection, not a dataset importer or replay permission.
It first calls existing `qualify_historical` (including actual loader, checksums,
calendar, finality, M1/M5 coverage and independent file-bound review). A caller's
historical label is insufficient. If it fails, the bundle is not admitted/read.
All evidence remains private/local. Exact source bytes are hashed; no CRLF or other
evidence normalization is used to repair a checksum mismatch.

A v1 paper bundle has exactly:

- `version: 1`, `symbol: XAUUSD`, `feed_id`, `dataset_id` (existing metadata digest).
- `preparer_code`, different `reviewer_code`, literal boolean
  `independently_reviewed: true`, UTC `reviewed_at_utc` not before retrieval.
  These are attestations, not automatic verification of a person's independence.
- `windows`: `warmup` M1/M5 and `evaluation` exactly match the v2 manifest;
  `outcome` has UTC start/end, starts at evaluation end, and ends later.
- `artifacts`: raw_m1, raw_m5, quote_events, specification, costs, policies.
  Each is a relative local `{file, sha256}` reference, resolved with existing safe
  path and bounded-reader rules (4MiB per artifact); originals are never modified.
- `evidence`: usage, source_feed, raw_normalized_lineage,
  timestamp_availability, bid_ask_sequence_completeness,
  calendar_holidays_maintenance, bar_finality_corrections,
  dated_instrument_specifications, dated_costs, independent_qualification.
  Each has exactly status VERIFIED, file, sha256, scope {start,end}, reference,
  explanation. Actual nonempty document bytes must match, with scope covering
  earliest warm-up through outcome end. Missing evidence never auto-approves.

Quote CSV columns are exact and ordered:

```text
sequence,occurred_at_utc,available_at_utc,bid,ask,revision,finality
```

Sequences are contiguous integers; occurrences never decrease, receipts strictly
increase, occurrence <= receipt. Bid/Ask are positive exact decimal strings with
Bid <= Ask. Explicit FINAL and revision0 only: corrected histories need a reviewed
as-of revision adapter, not silent replacement. The full file is mechanically
inspected; rows after a cutoff never authorize analysis. No quote is manufactured
from M1/M5 OHLC. Coverage brackets warm-up through outcome end. Sequence continuity
and matching OHLC cannot establish capture completeness. Gaps beyond the unchanged
fill-policy max_gap_ms explicitly add PAPER_QUOTE_GAPS_UNRESOLVED; no session closure
is inferred and no tolerance is increased.

Specifications and costs use exact envelopes: version1, kind
INSTRUMENT_SPECIFICATION/TRADING_COSTS, symbol, feed_id, available_at_utc,
effective_from_utc, effective_until_utc, values. Knowledge/effectiveness must cover
warm-up through outcome end. Specification values are the financial fields of
BrokerSpecification excluding identity/source/effectiveness/verification/version/
session_eligible; costs use the five numerical cost fields. Unsupported currencies,
margin/fee conventions, inconsistent tick values/lot lattices or slippage reject.
No real document is converted into a synthetic verification declaration.

Policies contain exactly version1, starting_capital string50, baseline
UNCHANGED_M1_M5, fill/capital/exit/stop/liquidation objects matching the existing
versioned dataclasses. This freezes assumptions/hashes; it does not certify actual
broker policies or change existing defaults. Future adapters must bind these hashes
to the preregistered baseline and preserve them throughout evaluation.

Even fully matching documents produce only DOCUMENT_AND_MECHANICAL_CHECKS_PASSED
and **BLOCKED / DATA_NOT_QUALIFIED**, never historical readiness approval. E5 must
still review raw-to-normalized lineage, quote/session/receipt semantics, outcome
candle coverage and the adapter that binds these documents to the engine. Existing
manifest v2 ends its candle range at evaluation end: later outcome candles need
separately qualified extended inputs, not fabricated continuation. Matching hashes
and operator attestations do not authenticate a provider. Synthetic schema tests
mock the upstream gate only to exercise this boundary; they are not real approval.

## Performance reporting contract

`performance_readiness(account)` provides a separate source-bound v1 report;
`validate_performance_readiness` recomputes from the actual v1/v2 producer. Existing
journal/metrics contracts are preserved. It records starting/ending balance,
equity, closed gross/net P&L, total/resolved/winning/losing/flat trades, win rate,
profit factor, net expectancy, holding duration, costs, maximum drawdown, capital
lifecycle, admitted/rejected opportunities, unresolved/open positions, equity curve
and individual journal. Rates use closed trades only; zero denominators are null.
Profit factor is null without losing trades, not an invented infinity. Closed-trade
costs and account costs differ if entry fees on open positions exist. Opportunity
counts cover account-admitted setups, not all raw chart observations or signals.

Entry/exit efficiency remains null with an explicit missing causal reference and
complete-quote-coverage reason. No favorable hindsight benchmark is invented.
Unresolved equity remains null, pending exits remain in a separate denominator,
and open monitoring positions are visible. All values here are synthetic
accounting descriptions; `historical_metrics` is null. Synthetic profit/loss is
never presented as measured strategy effectiveness.

## Blocker matrix and next E5 instructions

| Priority | Blocker | Required evidence/action |
|---|---|---|
|Critical|No qualified historical quote export available here|Provider-authorized native Bid/Ask occurrence/receipt/sequence export; license, exact feed, complete capture and correction/finality evidence|
|Critical|Exness calendar still BLOCKED|Resolve dated quote vs trade phases and overnight gaps independently; preserve 21:58/23:00/23:02 distinctions and review partial21:55 M5 finality|
|Critical|No reviewed actual specifications/costs|Dated contract/volume/tick/currency/margin/liquidation rules, commission/financing/rollover/slippage evidence; no account credentials|
|Critical|E5 adapter not implemented/approved|Map historical occurrence/availability/finality/corrections and session permissions without relabeling as synthetic; bind raw/normalized lineage and outcome coverage|
|Critical|Independent qualification/reproduction absent|Independent person reviews file hashes, source evidence and calendar; retain disagreements; run full/full/common-cutoff prefix after admission|
|Next|USD50 benchmark unmeasured|Freeze unchanged M1/M5 rules, capital/risk/cost/config hashes, warm-up/evaluation/outcome windows; record every accepted/rejected opportunity and unresolved outcome|
|Later|E6 live paper|Separate qualification/bridge review after historical results; no implicit activation from E4.7|

The existing Exness V2 review still lists CALENDAR_SCHEDULE_CONFLICT,
CALENDAR_COVERAGE_UNVERIFIED, SESSION_PHASE_UNKNOWN, HOLIDAY_COVERAGE_UNKNOWN,
MAINTENANCE_COVERAGE_UNKNOWN and CANDLE_FINALITY_UNCERTAIN. Relayed broker statements
and reported boundary counts are evidence leads, not complete verified per-feed
capture. Review docs/EXNESS_SESSION_EVIDENCE_INVESTIGATION_2026_11.md. No calendar
correction/approval PR was found in the open stack; this work does not perform it.

Acquire permitted exports/documents from the provider/operator's existing authorized
archive, not a new terminal session. Preserve originals, compute local hashes,
record actual receipt availability (if unavailable, report that exact blocker),
run existing CSV qualification and independent review, then prepare the bundle.
Do not reconstruct receipt times from candle openings, infer ticks from OHLC, or
label a new capture as historical evidence for unavailable dates.

E5 should be a separate draft based on reviewed E4.7 corrections. First write
adversarial adapter tests and a frozen USD50 baseline protocol; do not run a
historical episode until all evidence gates pass. Preserve pending trades as
unresolved at the declared observation cutoff, not a fictitious forced close.
Compare two complete journals/hashes and overlapping prefix records; report the
actual population/coverage, costs, equity curve and denominators before any MTF/AI
comparison. Keep execution disabled regardless of research results.

## Safe Windows10 / Python3.11 / PowerShell5.1 commands

From the actual checked-out project root (no hardcoded personal paths):

```powershell
$root = (Get-Location).Path
$out = Join-Path $root ('private-e47-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $out | Out-Null
py -3.11 .\diagnostics\paper_replay_readiness.py --report-path (Join-Path $out 'readiness.json')
```

Expected exit3, BLOCKED, historical PENDING and comparisons NOT_RUN. This runs
without MT5, network, credentials or services. With independently reviewed existing
local inputs, substitute your own private paths (the tool does not create approval):

```powershell
py -3.11 .\diagnostics\paper_replay_readiness.py --manifest $manifest --review $review --paper-bundle $bundle --report-path (Join-Path $out 'candidate-readiness.json')
Get-Content -LiteralPath (Join-Path $out 'candidate-readiness.json') -Raw | ConvertFrom-Json | Select-Object status,input_checks_status,reason_codes
Get-FileHash -Algorithm SHA256 -LiteralPath $manifest,$review,$bundle
```

Reports are reserved FAIL/RUN_INCOMPLETE first and published atomically, never
overwriting existing reports. Keep reports/data private; don't upload raw files,
credentials or account identifiers. No local Windows commands or terminal run
are required to complete this cloud review.

## Verification

Commands: `python -m unittest discover -s tests -p 'test_e47*.py' -v` and
`python -m unittest discover -s tests -v`; unchanged paper/protection goldens and
full/full/prefix/future-append tests remain inherited regression requirements.
The CI workflow retains Linux/Windows Python3.11/3.12 and actual PowerShell5.1
startup/ValidateOnly checks. Exact final counts, head and CI links are recorded in
the draft PR after completion, not claimed from an unfinished run.

No qualified private source was supplied or accessed. Historical validation
PENDING, historical comparisons NOT_RUN, historical effectiveness unmeasured.
READ_ONLY_SHADOW, WAIT, execution_allowed=false, Exness BLOCKED,
DATA_NOT_QUALIFIED. No broker/demo orders, permission/calendar changes, AI activation,
new trading strategy, paper activation or PR merge.
