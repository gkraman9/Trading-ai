# Entry Intelligence v1 — E1

E1 projects the existing SR_REJECTION_M1_CONFIRMATION rule 1.0.0 into a deterministic
research plan. It adds no indicators, predicates, rankings, default strategy
selection, probability, fill, stop/target allocation, sizing or order capability.
Only typed SYNTHETIC_RESEARCH contexts enter E1's current interface. The parent SR
rule is unchanged and remains SYNTHETIC_ONLY. Live and historical label overrides
block **before** calling the SR evaluator. Historical integration requires a future
reviewed manifest bridge; no genuine qualified export was available in this task.

See [the complete architecture](ENTRY_EXIT_INTELLIGENCE_ARCHITECTURE.md) for all
eight entry families, E2 exit requirements, risk and future paper research.

## Interface and source binding

```python
from iat.intelligence.entry_intelligence import (
    EntryResearchSession, validate_entry_report,
)
# context/view must already come from the existing causal research pipeline.
session = EntryResearchSession()
report = session.record(view, context, view_inputs=original_view_inputs)
validate_entry_report(report, source=session)
```

`assess_entry(view, context, **options)` is the one-snapshot convenience function;
retain EntryResearchSession when expiry, carry-forward or invalidation matters.
The pure interface has no wall clock, broker, network, credential or order input.
`as_of` defaults to the context close; an explicit different time fails closed:
future source → ENTRY_FUTURE_SOURCE, older source → ENTRY_SOURCE_NOT_CURRENT.
No new freshness tolerance is introduced. Underlying M1/M5 chronology, eligibility,
closed bars, quality, session restrictions and source proof remain checked by the
unchanged context/V3/SR interfaces. Synthetic no-calendar fixtures do not establish
broker sessions; a supplied blocked calendar remains blocked.

Before transactionally replacing session state, E1 verifies V3 against its typed
source, records through the existing public SR ledger and validates that SR
result against the same view/context. Rejected source, backward/same-cutoff
revision, scope or resource input cannot partially advance lifecycle. Genuine
blocked SR observations may be logged but advance no eligible-close expiry and
withhold all old plans. Source failures are generic codes, never exception data.

The session is single-threaded, explicitly bounded: 256 accepted distinct SR
snapshots, 10,000 accumulated source IDs, 2,048 setups. These are E1 resource
limits, not changes to the SR predicates or confluence thresholds. A duplicate
last observation is revalidated, returns the same report and counts once, even at
the snapshot cap. No unbounded cache is introduced; only one last report, the
bounded original ledger and one hash per produced snapshot are retained. Start a
new session deliberately when a resource limit is reached; it does not inherit
old lifecycle state or silently treat old setups as newly validated opportunities.

`sr_log()` exports the unchanged SR log v1; regression tests compare it byte-for-
JSON with the original ledger's log. Existing DecisionLog v1, Strategy Replay Log
v1, manifest qualification and warm-up/evaluation accounting are untouched.

## Report contract

`report_version=1`, `model_version=IAT_ENTRY_INTELLIGENCE_V1`. Canonical JSON uses
sorted keys, no NaN and an SHA-256 of all fields except sha256. It contains:

- Status EVALUATED or BLOCKED, symbol/cutoff/provenance and SYNTHETIC_ONLY validation.
- Existing strategy identity and unchanged rule version.
- Bindings to original V3, typed context, SR result/log, original configurations,
  SR policy and the E1 policy. Hashes bind content; they do not certify a feed.
- Suitability: exact upstream market state (regime, structures, momentum,
  volatility), M1/M5 context, liquidity and restrictions. No new suitability rule.
- Sorted plans retaining canonical SR setup identity, direction, frozen location,
  P/T/C and predicate results, evidence, missing confirmation, structural
  invalidation reference/tolerance, causal qualification, age and lifecycle events.
- Used evidence metadata with event occurrence and availability; frozen references
  may originate in an earlier eligible source snapshot. An ID changing its metadata
  fails closed. No V1 window-relative ID becomes a new setup identity.
- Explicit unavailable price observation: the upstream SR contract provides no
  Bid/Ask basis/spread. E1 never guesses them or accepts arbitrary quote labels.
- Exit/risk/paper interfaces NOT_IMPLEMENTED, fill=null, performance_metrics=null.
- Reasons, explanations, limitations and immutable read-only safety fields.

Multiple plans/directions/states may coexist; there is no aggregate winner or
execution selection. `research_states=['NO_SETUP']` means no upstream touch
anchors exist in this session. The other states map as follows:

| Entry state | Upstream meaning |
|---|---|
| WATCHING | Reserved only; E1 has no invented proximity predicate and never emits it |
| AWAITING_CONFIRMATION | Existing CANDIDATE, no qualifying immediate closed C |
| RESEARCH_QUALIFIED | Existing QUALIFIED; **not** BUY/SELL or permission |
| ABSTAINED | Existing terminal failed/missing immediate confirmation |
| INVALIDATED | Existing anchored invalidation; qualified time remains null if never qualified |
| EXPIRED | Existing five distinct observed eligible M1 closes after C |
| BLOCKED | No eligible current report; no cached plan or evidence exposed |

The upstream first-touch canonical ID, frozen zone and immediate P/T/C timing are
unchanged. Terminal anchors never re-arm under the same ID. A distinct first-touch
anchor can produce a new setup under the upstream rules. Time since first seen is
reported separately from eligible-close age; wall time does not drive expiry.
Current fresh opposing CHoCH references are included even without a new touch.
A later observation may revise the current lifecycle but never mutate a returned
prior report. Previously produced report hashes remain verifiable by their
original bounded session after future observations.

`validate_entry_report` checks JSON contract version, checksum, exact safety and
binding to the producing in-process session. EVALUATED reports without that source
session reject; checksum-only approval is impossible. BLOCKED reports can validate
standalone but must be canonical empty reports with explicit reasons and optional
content hashes. This is not an independent sign-off, signed portable journal or
an importer for arbitrary serialized results. Exported JSON alone cannot grant
eligibility. A future portable validator must replay qualified raw sources.

## Confirmation and fill separation

Location is the upstream **zone interval**, never an invented executable price.
C's opening/event time and its closed/available time are distinct. The earliest
research qualification is the original qualified-at timestamp. An absent C cannot
have that timestamp. Confirmation predicates are copied exactly from SR v1 and labeled as the upstream
anchored snapshot. RESEARCH_QUALIFIED describes the original lifecycle, not a
new entry authorization or a fresh rerun of confirmation at every later cutoff.
A missing immediate C cannot be backfilled with a later candle under the same
anchor; there is no new delayed-confirmation rule in E1.

Even RESEARCH_QUALIFIED has fill=null. A later, validated side-specific Bid/Ask
observation and a reviewed timing/cost model are required. C close is not a fill;
M1/M5 OHLC cannot manufacture ticks, spread, slippage or a 50-second exit. Unknown
quote basis and costs remain unknown rather than zero.

## Live dashboard and Windows startup correction

The existing dashboard now has an **availability-only** Entry and Exit Intelligence
section. It shows BLOCKED / SYNTHETIC_ONLY, unavailable entry location/confirmation/
structural invalidation, NOT_IMPLEMENTED exit/risk/fill and actual V3 restriction
codes. It never calls the E1 session or SR evaluator on live observations. Existing
chart, endpoints, quote freshness, formal live provenance and calendar gates remain
unchanged. No AI provider is activated.

The operator's Split-Path empty-Path error was consistent with evaluating
`PSScriptRoot` inside a default parameter expression during `-File` binding.
The isolated startup fix leaves ProjectRoot empty in param(), resolves the script
parent **inside the body**, and preserves explicit overrides. It never guesses the
root from the caller's current directory. `Test-IATLiveStartup.ps1` launches actual
Windows PowerShell 5.1 children with `powershell.exe -NoProfile -NonInteractive -File`
from an unrelated temporary directory, without ProjectRoot, then with an explicit
override; it verifies no validation-only files or source changes. This is separate
from strategy logic and runs without SDK attachment, services or network.

After checking out this draft PR's feature branch in the operator's worktree and
manually stopping any old dashboard on port 8768, use the same single startup:

```powershell
powershell.exe -NoProfile -File 'E:\IAT2\IAT3-Live-Test\diagnostics\Start-IATLiveMarketView.ps1'
```

For an offline startup-only check from any directory:

```powershell
powershell.exe -NoProfile -File 'E:\IAT2\IAT3-Live-Test\diagnostics\Start-IATLiveMarketView.ps1' -ValidateOnly
```

The helper requires the existing Python 3.11 environment/dependencies, creates a
new private GUID journal outside Git and defaults to port 8768/interval 10. Keep
DEMO connected with Algo Trading and external API trading disabled. It neither
kills old services nor starts B.2/B.3. No actual Windows terminal success is claimed
by synthetic cloud tests; operator runtime evidence must establish that separately.

## Synthetic examples, tests and measurements

`tests/entry_fixtures.py` independently invents OHLC around 2100 with explicit labels,
not real market prices. M5 and M1 are separate synthetic detector fixtures, not a
same-feed historical consistency claim. `docs/research_audits/entry-intelligence.synthetic.json`
records actual deterministic report hashes, counts and a worked zone/reference
plan. They are analytical regression examples, not evidence of profitability.

```text
python -m unittest discover -s tests -p test_entry_intelligence.py -v
python -m unittest discover -s tests -v
python tests/benchmark_entry_intelligence.py
```

The benchmark uses prebuilt synthetic typed inputs, measures source-bound V3
validation separately, first E1 evaluation, three revalidated duplicate snapshots
and traced allocation peak. It checks one SR snapshot, stable output hash and
unchanged setup count. It excludes upstream context construction, process RSS,
Windows/MT5/network latency and market validation. Revalidation is intentionally
retained rather than trusting a caller's checksum for speed.

Limitations: synthetic-only integration, bounded single-thread session, no portable
source attestation/historical bridge, no newly implemented other entry family,
exit, risk or fill model. Historical validation remains PENDING and comparisons
NOT_RUN. Exness BLOCKED; DATA_NOT_QUALIFIED; WAIT; execution_allowed=false.

Measured on Linux Python 3.11.9 with tracing enabled: source-binding validation
330.274 ms; first E1 evaluation 1,138.190 ms; three revalidated duplicates
1,140.125 / 1,143.395 / 1,148.300 ms; peak traced allocations 2,061,045 bytes.
One SR snapshot, two qualified synthetic setups and one produced hash remain
after repeated observations. The report hash was
`b2b67e8533c430cb6615620311fd75c802f7f352b4b87b21ff797314bc715ff5`.
Reproduce with the command above; timings/allocations vary. Strict source-bound
revalidation dominates this small workload; E1 makes no live-latency claim.

Focused validation of E1 plus inherited live-view/observer integration: 112 tests
passed on Python 3.11.9 (32.702 s) and 3.12.14 (28.948 s), including 33 E1 tests.
Full-suite and exact-head Linux/Windows CI results are recorded in this draft PR's
validation section. Windows startup success here means the offline `-File`
regression only, never a verified connection to the operator's MT5 terminal.
