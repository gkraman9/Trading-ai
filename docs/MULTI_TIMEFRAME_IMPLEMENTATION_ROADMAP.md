# Multi-timeframe integration: separate research PR sequence

DESIGN ONLY. This roadmap does not enable additional frames or delay the existing
M1/M5 deterministic paper baseline. Parent audit: PR51 at
`bf5bd478e8298c7e45cffa713a148ab88ce0d2a5`.

[Architecture and audit](MULTI_TIMEFRAME_INTELLIGENCE_ARCHITECTURE.md) ·
[Experiment protocol](MULTI_TIMEFRAME_RESEARCH_PROTOCOL.md).

## Delivery lanes

Continue baseline paper review, accounting and evidence qualification in its own
lane. MTF development begins offline with synthetic fixtures, uses existing pure
analytical functions and produces an additive report. Calendar corrections and
MT5 lifecycle work remain separate assurance dependencies; do not change their
approval flags to unlock this work. No implementation PR is authorized to merge
automatically by this plan.

| Proposed PR milestone (not assigned GitHub numbers) | Bounded change | Exit evidence / comparison |
|---|---|---|
| R1: typed frame/interval foundation | Strict versioned registry, finite frame maps, fixed-frame interval resolver; preserve M1/M5 default wrappers; no live acquisition expansion | Unsupported names/duplicates/anchors/cycles reject; byte/hash-equivalent baseline; existing suite passes |
| R2: M15 observations and causal sidecar | Reuse frame detectors/context components, per-frame metadata/warm-up and canonical identity; keep legacy confluence untouched | M15 detector parity with direct reference; future/unfinished M15 cannot influence prior M1 decisions; A decisions identical; B context only |
| R3: H1 observations and hierarchy edges | Intraday H1 plus explicit parent/setup/timing relations and conflicts; immutable event/revision handling | Fresh opposing M1 CHoCH remains visible against aligned labels; no majority; no evidence inflation; C context only |
| R4: H4 observations and scheduling | Strategic H4 role, per-frame closed-update caches, bounded dependency invalidation; serialized owner interfaces only | Full-prefix versus cached output matches; HTF computations scale with new HTF closes, not tick count; D context only |
| R5: D1 interval/finality research | Versioned provider day anchors, IANA/DST, multiple session segments and dated exceptions; independently reviewed session adapter | 23/25-hour days where applicable, overnight breaks, partial/no-quote days, finality/expiry unknowns block; no unverified Exness approval |
| R6: W1 and extended context | Verified weekly anchor/coverage and sufficient warm-up; D1/W1 strategic relations | Weekend/holiday/week-boundary tests; E context only; no aggregation labeled native |
| R7: M3/M30 and MN1 adapters | M3/M30 reuse the reviewed fixed-frame path; MN1 separately verifies variable calendar-month bounds | Leap February, short/long months, DST/zone publication cases; no 30-day constant for MN1; no unannounced A–E arm changes |
| R8: reviewed data/replay bridge and offline experiments | New manifest/qualification extension and matched profiles; preregistered optional context filters, unchanged baseline strategy/risk/fill/accounting | Permitted independent source, same-feed/basis/native lineage, closed-bar/correction/calendar evidence and independent sign-off; full/full/prefix logs; actual A–E measurements only for admitted arms |
| R9: research dashboard integration | Read-only published multi-frame matrix, forming/closed distinction, provenance/conflicts/missing roles; no HTTP acquisition | Sanitized versioned API, bounded render/payload, no automatic AI/strategy/paper/trading activation; baseline UI/API compatibility |
| R10: tick execution-research adapter | Independently qualified sequenced Bid/Ask/receipt input into the existing read-only paper model | Completeness, side selection, skew/freshness/gap, latency, stop/liquidation ambiguity, unchanged costs/capital and no broker order dependency |

These are scoped increments, not one monolithic prerequisite chain for the paper
baseline. M15, H1, H4 and D1 take priority. Context-only B/C/D can be reviewed as each
frame is added; a qualified paired B-versus-A replay need not wait for W1/MN1 or the
rest of E. R8 can be delivered in frame-specific sub-PRs after the corresponding
interval/source contracts are ready; R10 is separately gated on tick evidence and
can progress independently of R7. No OHLC-only performance claim can substitute
for required tick-level execution evidence.

## Regression requirements before each implementation is accepted

1. Preserve existing M1/M5 golden reports, selected hypotheses, strategy predicates,
   setup identities, confluence/configuration hashes, 5/15-minute review semantics,
   DecisionLog v1, Strategy Replay Log v1 and paper journal contracts. Preserve
   existing safety assertions and all supported-platform checks.
2. Reuse identical detectors on identical eligible data; compare new orchestration
   against direct reference results. No second BOS/CHoCH, swing or zone algorithm.
3. Test every new frame at the instant before/at/after its verified close and source
   availability. Appending a forming/future higher candle or later right-strength
   confirmation cannot alter any earlier frame, packet, assessment or decision.
4. Test session breaks, overnight and DST changes, holidays, dated coverage expiry,
   missing finality/corrections, partial/empty periods, duplicate/out-of-order bars,
   source/basis mismatch and missing required frames. Unknown means blocked, not
   a guessed candle/calendar. Include current 21:58/23:00 quote-versus-open-trade
   boundary cases only with their existing evidence status; do not alter boundaries.
5. Test repeated closed-prefix cache hits, tick-only updates, source corrections,
   reconnection generation and configuration/calendar changes. Verify deterministic
   full/full and common-cutoff prefix equivalence, window shifts, stable events
   with separate contextual revisions and no duplicate correlated evidence count.
6. Exercise up/down/range/transition, high volatility with trend, intact parent
   trend plus retracement, opposing fresh CHoCH despite matching structure labels,
   incompatible higher frames, ties and all-unknown inputs. Neither majority voting
   nor a higher-frame label can erase contradictory lower-frame facts.
7. Use bounded per-frame histories and sufficient feature warm-up, including
   confirmed pivot counts. Test W1/D1 warm-up preceding M1 coverage without charging
   it to evaluation, and missing long history without quietly shortening it.
8. Verify HTTP uses cached publications only and SDK operations remain serialized.
   Forming previews cannot influence confirmed reports. Simulate unavailable
   native timeframe constants and retain all demo/permission/session gates.
9. Keep synthetic fixtures clearly labeled. Historical comparisons remain NOT_RUN
   without an eligible source and bridge; profits cannot be inferred from fixture
   balances. Baseline-only context additions must produce identical trade outcomes.
10. Run meaningful focused regressions and the inherited suite on Linux/Windows
    Python3.11/3.12 for implementation PRs, retaining actual PowerShell5.1 startup
    coverage. Documentation changes alone do not claim new runtime test coverage.

## Operational and evidence blockers

Current validators reject higher frames; the existing manifest formats are pair-
only. Session v2 cannot certify D1/W1/MN1 or arbitrary subday grids. No native
higher-frame export, dated interval/finality evidence or independent approval is
supplied by this planning request. Existing E1/E4 accept authenticated synthetic
sources, not a historical-label override. Tick completeness and real execution-cost
inputs remain independently gated. Actual Windows runtime validation is separate
from cloud synthetic tests. No historical experiment has been run for this plan.

Baseline PR51's 2,054-test result is a reference at the audited commit, not evidence
that MTF exists or has passed tests. This documentation milestone changes no Python,
PowerShell, configuration, runtime API, strategy or execution code. Validate the
new documentation links and diff; future implementation PRs must provide their own
actual test counts, CI results, benchmarks and source qualification evidence.
