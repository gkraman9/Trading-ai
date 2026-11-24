# Market Intelligence V3 — automated contract audit

This is an **automated code-review assessment**, not independent external approval, broker certification or human sign-off. The original implementation and this review were performed within the same assistant session; new fixtures and adversarial reproductions provide additional technical evidence, not organizational independence.

Reviewed baseline: draft PR #43 `da8c1f69b3e95213572420432410e54e1b465ffe`; dependencies PRs #41/#42 remain draft/unmerged. The original 1,621-test CI matrix was green. This audit inspected actual adapter code, published schema, tests, documentation, example, context/scenario/adaptive/V1 orchestration, canonical identities and strategy definitions. No source web research was repeated and no MT5, live account, provider transport, service, original journal or private CSV was accessed.

## Verdict and scope

**Reviewed baseline: REQUIRES CORRECTION. Corrected contract: READY FOR HUMAN REVIEW only after the delivered head's focused/full/CI checks pass.** This verdict never authorizes trading, approves the calendar or independently qualifies a dataset. Final exact test/CI results are recorded in PR #43 against its corrected head; incomplete checks must not be represented as passed.

The correction does not change chart-reading algorithms, confluence weights/caps/thresholds, hypothesis selection, strategy predicates, execution gates or risk controls. No new strategy is implemented. Report version 1 field names and the original neutral/missing output structure remain compatible. Validation is stricter: previously malformed objects are rejected and unsupported root ASSESSED/ABSTAINED claims become UNKNOWN. This is an intentional correction to v1 source-binding/status semantics, not a new analytical rule.

## Prioritized findings

Line references below identify the **reviewed baseline**, not current shifted lines. Reproduction is checked into `tests/test_market_view_audit.py` using independent invented staircase-wave OHLC; it imports none of the original test fixture helpers.

| ID / severity | Baseline location | Reproduction and evidence | Consequence / correction | Blocks next research milestone? |
|---|---|---|---|---|
| MV-01 HIGH | `market_view.py:684`, schema collection `items` definitions | Add `approval:true` to a collection and recompute SHA: Python accepted what JSON schema rejected. Replace a swing with an incomplete `{kind,price}` object: both accepted it. | Nested contract was not enforced. Runtime now validates the same published schema as offline checks; collection items, source variants, evidence, hypotheses, measurements, quality and session metadata have explicit types/fields. Unknown nested fields fail. | Yes before fix; corrected. |
| MV-02 HIGH | `market_view.py:474`, `market_view.py:588` | Produce context with calendar A, pass an otherwise usable session snapshot with a different digest. Root ASSESSED was accepted; adaptive was recomputed using that same supplied digest. | Hashing a declaration is not binding it to the context's actual calendar. ContextReport v1 contains no calendar digest, so no positive binding can be proved. Root remains UNKNOWN with SESSION_CONTEXT_BINDING_UNESTABLISHED unless already BLOCKED. Existing upstream interpretations are preserved. | Yes before fix; conservatively corrected. A future truly bound session contract remains separate work. |
| MV-03 MEDIUM | `market_view.py:775` through validator return | Rechecksum a hypothesis with rank 999 or score 9000; alter session child hash; mark a nonempty collection UNAVAILABLE; change a neutral warm-up report to ASSESSED. Original validator accepted them. | Internal consistency was too shallow even without source authentication. Validate dense ranking/ties, inherited score contributions/selection, collection semantics, hash projections and status restrictions; bound-input validation still compares the complete result. | Yes before fix; corrected. |
| MV-04 MEDIUM | `market_view.py:162`–250 | Set session provenance count negative or provenance kinds to an integer. Builder still emitted ASSESSED. Original phase tests also supplied contradictory permission flags. | Malformed session declarations could appear trustworthy. Apply strict shared session shape plus phase/permission coherence. Original tests now supply coherent UNKNOWN/close-only/quote-only fixtures; contradictory metadata blocks. | Yes before fix; corrected. |
| MV-05 LOW | `market_view.py:349` | V1 serialization and SHA-256 ran inside every structural-event iteration. Larger synthetic workloads amplified repeated work. | Avoidable CPU/allocation cost. Compute the constant report digest once per call. No hidden market cache, weakened validation or rule change. | No; corrected. |
| MV-06 INFORMATIONAL | `market_view.py:333`–350 | Inspect BOS/other non-CHoCH items in independent fixtures. Their event_id is null; source_id is accompanied by the report SHA. | This already correctly distinguishes report-scoped references from durable CHoCH occurrence IDs. Validator now checks source-report scope, no duplicate scoped key and no fabricated canonical ID for non-CHoCH. Never use source_id alone for rolling deduplication. | No; durable BOS identity is separate future work. |
| MV-07 INFORMATIONAL | `market_view.py:453`, context/scenario validators | Valid source binding and canonical hashes do not authenticate the feed, finality, calendar evidence, rights or independent reviewer. | Keep DATA_NOT_QUALIFIED / PENDING / NOT_RUN and Exness BLOCKED; no independent approval is supplied here. | Blocks real-data claims, not synthetic research. |

The first nine adversarial tests all failed against the exact reviewed head (`Ran 9 tests ... FAILED (failures=9)`), establishing concrete pre-fix defects rather than hypothetical risks. They all pass after correction. Nine additional independent tests exercise the causal/state/source-binding matrix. The original 29 tests remain, with two fixture/status expectations corrected to match truthful calendar binding rather than unsupported positive status.

## Verified contract and source-binding matrix

| Concern | Enforcement / evidence | Limit |
|---|---|---|
| Context/scenario/adaptive symbol, cutoff and configuration | Existing strict scenario validation and exact optional-child equality; independent opposite-symbol/direction fixtures and configuration tampering tests | A typed report/hash alone is not provider authentication. |
| Optional V1 detail | Original engine recomputes frames from exactly retained closed source rows and frozen V1 configuration; mismatches block | Bounded reconstruction costs CPU; no new analysis algorithm was written. |
| Closed M1/M5 and causality | Existing prefix/quality gates; independent unfinished M5, stale data, future-tail and prefix/repeat tests | An entirely fictional but internally consistent synthetic report remains synthetic. |
| Source/evidence identities | Existing canonical IDs; duplicate evidence collapses, conflicting same-ID data blocks; source references resolved | BOS/window-relative IDs are not global durable occurrences. |
| Scores, ranking, selection | Original confluence output copied; contribution arithmetic, IDs, dense ranks, ties and selected flags checked; exact bound validation available | A wholly reauthored coherent object cannot be authenticated from an unkeyed checksum. |
| Mutation | Deep copies and repeated original V1/context comparisons | Frozen dataclasses alone do not freeze nested dicts; copies matter. |
| Session/calendar | Shape, cutoff, declarations, phase permissions and SHA projection checked; unmatched provenance is UNKNOWN | ContextReport v1 cannot prove its calendar digest or symbol against public-state metadata. No positive binding is asserted. |
| Qualification | Fixed current-stage mapping; no self-approval, no broker-data qualification | Missing independent evidence remains missing. |
| Shape vs semantics | Official JSON schema enforced at runtime; semantic validator adds hashes, references and cross-field constraints | Schema-only validation cannot evaluate SHA-256 or prove source-bound equality. Call the Python validator too. |
| Static schema/runtime | `jsonschema>=4.23,<5` promoted from dev-only to runtime requirements; checked-in schema loaded once, no remote references | Schema must accompany the source package. Static contract objects are not market-data caches. |

## State matrix

| Input | Corrected root status | Analytical content |
|---|---|---|
| Valid synthetic context, no session | UNKNOWN | Original facts, scores and selection retained; missing session explicit |
| Missing M1 or M5 | UNKNOWN if surviving frame eligible; otherwise BLOCKED | No invented confirmation; missing frame explicit |
| Unfinished/future closed-prefix violation, stale data, malformed/conflicting reports | BLOCKED | Quarantined detail, no ranked authorization |
| Warm-up | UNKNOWN if mechanics valid | Existing abstention, missing history/structure reasons retained |
| Conflicting structures / fresh opposing M1 CHoCH | UNKNOWN absent a proven session binding, or BLOCKED for quality/session failure | Existing contradictions/abstention stay visible despite alignment label |
| UNKNOWN session with coherent unknown permissions | UNKNOWN | Unknown never becomes an approval |
| BLOCKED calendar / CLOSED / QUOTE_ONLY / CLOSE_ONLY | BLOCKED | Supplied valid observations may remain visible as restricted research content |
| Otherwise usable session declaration, including synthetic | UNKNOWN | SESSION_CONTEXT_BINDING_UNESTABLISHED; no circular “proof” from recomputing the adaptive hash with that declaration |
| Missing qualification | UNKNOWN/BLOCKED according to the above | Always DATA_NOT_QUALIFIED; not independently approved |

ASSESSED/ABSTAINED remain names in the v1 shape vocabulary for compatibility, but cannot be validated as root positive statuses for ContextReport v1 after this correction. The original assessed/abstained research hypothesis is still preserved exactly in advisory fields. Reintroducing a positive root status would require an explicitly reviewed upstream session-binding contract; it must never mean trading permission. Do not rewrite historical journals or overwrite old reports to hide the original behavior.

## Performance methodology and results

Reproduction command from the checkout:

```powershell
py -3.11 tests/benchmark_market_view_audit.py --iterations 3 --repeat-calls 100
```

For baseline comparison, extract only the trusted reviewed source with Git, then pass its local path via `--baseline-module`. The benchmark never downloads code, writes market data or starts a service. Recorded measurements are in `docs/research_audits/market-view-contract-review-performance.synthetic.json`.

Inputs are built before timing from independent synthetic fixture recipes (60 or 180 bars per frame; missing case four M1 bars). Each workload has one excluded warm-up, three timed iterations, `perf_counter_ns`, Python `tracemalloc` peak bytes, explicit GC and no retained output. Repeated calls record retained Python allocations after GC. Dataset/context/configuration/source/schema hashes and package versions identify the run. Peak traced memory is not RSS; these are small samples on a shared Linux machine, with local tests running concurrently, not hard real-time or production capacity claims. Baseline versus corrected paths have different validation costs, so no isolated optimization speedup is asserted.

Actual timing/memory table and repeated-call observations are generated from the recorded benchmark in the final section below. There is no test that loosens quality/future/freshness gates for performance. No custom hidden cache or persistent market state was added.

## Next narrow milestone — proposed implementation prompt only

Implement **Support/Resistance Rejection Research v1**, a single original IAT experimental composition. Reuse existing canonical support/resistance zones and closed M1/M5 observations. Do not implement it as part of this review, modify the two existing rules/registry hashes/confluence thresholds, or route it into default strategy selection.

- Separate extension module and versioned research result, not changes to DecisionLog v1, Strategy Replay Log v1 or the current four adaptive candidate rows. Evaluate bullish and bearish independently. ID `SR_REJECTION_M1_CONFIRMATION`, rule version `1.0.0`, validation status SYNTHETIC_ONLY.
- Inputs: exact source-bound V3 view plus its typed context and frozen extension policy; historical entry point must reuse manifest/preflight and native same-feed/basis coverage/finality. A provenance label or V3 UNKNOWN alone cannot grant historical eligibility. Synthetic evaluation may inspect valid observations while recording all session uncertainty; it never grants execution.
- Bullish setup: existing M5 structure BULLISH or RANGING; a canonical SUPPORT zone FRESH/TESTED, known by the opening of touch bar T; prior M1 bar P does not touch that zone; T intersects the fixed zone and closes inside its boundaries; distinct immediately following closed M1 bar C has bullish body and closes strictly above zone.upper + existing ContextConfig.break_tolerance. Mirror RESISTANCE, bearish body and close below zone.lower - tolerance for bearish. Candidate pivot/zone creation after T cannot qualify. Exclude ROLE_REVERSAL_CANDIDATE and supply/demand from this first family.
- Require contiguous eligible P/T/C and eligible M5 history at C's cutoff. Reject any fresh opposing M1 CHoCH from the existing evidence even when the alignment label agrees. Ambiguous or conflicting multiple zones yield separate candidates/ties, never an arbitrary chosen trade.
- Stable setup identity scopes strategy/rule/symbol/direction to canonical zone ID and first touch candle T ID. Repeated observation of that anchor counts once. Re-arm only after a distinct touch episode (new T with immediately preceding non-touch P); no window-relative IDs.
- Qualification exists only at C's close. Missing predicates ABSTAIN; blocked quality is a separate outcome. After qualification, an eligible later M1 close beyond the opposite zone edge plus existing break tolerance, or a fresh opposing CHoCH, invalidates the setup. Invalidation without earlier qualification must not count as an invalidated qualified setup. Expire five M1 closes after C if neither event has occurred; preserve blocked intervals and only establish expiry at the next valid snapshot.
- Paper exit hypothesis: an eligible later close through an opposing zone already frozen at C, invalidation or expiry; report simultaneous/ambiguous order as unresolved. No fabricated executable price, order, target allocation, sizing or realized P&L. Keep existing separate 5/15-minute journal first-breach reviews unchanged; they are not trading exits or win rates.
- Tests: independent synthetic positive/negative cases both directions, late/unfinished M5, unknown session, overlapping zones/ties, missing confirmation, opposing CHoCH, one-count lifecycle, new touch re-arm, invalidation-before-qualification, expiry, future append, full/full/prefix and unchanged existing rules/logs. Keep all execution/qualification gates fixed and historical validation pending until eligible evidence exists.

The family is preferred over breakout/retest first because canonical zone identity and lifecycle already exist; a breakout engine would additionally depend on durable BOS event identity that this presenter intentionally does not invent. Rule choices above are unvalidated IAT research hypotheses, not external market advice, learned optimal parameters or performance claims.

## Recorded synthetic measurements

Medians of three traced calls; peak KiB is the maximum across those calls. Context creation is excluded. All workload repetitions produced identical output hashes within each implementation.

| Python | Workload | Baseline median ms | Corrected median ms | Corrected peak KiB | Sources |
|---|---|---:|---:|---:|---:|
| 3.12.14 | normal | 152.572 | 488.408 | 1065.7 | 188 |
| 3.12.14 | larger_registry | 454.768 | 1292.054 | 2730.1 | 572 |
| 3.12.14 | normal_with_v1 | 514.704 | 588.929 | 1382.0 | 188 |
| 3.12.14 | larger_with_v1 | 3452.390 | 1716.064 | 3650.3 | 572 |
| 3.12.14 | missing_frame_warmup | 24.054 | 42.005 | 228.4 | 4 |

| 3.11.9 | normal | not measured | 491.351 | 1422.6 | 188 |
| 3.11.9 | larger_registry | not measured | 1300.262 | 3678.5 | 572 |
| 3.11.9 | normal_with_v1 | not measured | 605.669 | 1809.2 | 188 |
| 3.11.9 | larger_with_v1 | not measured | 1727.032 | 4823.3 | 572 |
| 3.11.9 | missing_frame_warmup | not measured | 75.283 | 286.4 | 4 |

Python 3.12.14: 100 sequential calls, retained traced bytes after GC first/last 7,080/34,396; min/max 7,080/34,396; peak 1,120,641 bytes. Bound validation (one untraced call) took 182.088 ms.

Python 3.11.9: 30 sequential calls, retained traced bytes after GC first/last 7,411/54,796; min/max 7,411/54,796; peak 1,506,681 bytes. Bound validation (one untraced call) took 164.775 ms.

The first 100-call run retained about 34 KiB at its end, including measurement bookkeeping and library allocations; retained samples rose most early and then grew more slowly. This small bounded experiment does not establish an unbounded leak or prove that none exists. No full output registry was retained across calls. Standards-compliant nested validation costs CPU; the event-report hashing correction reduces redundant V1 work, but larger/more varied production loads and live freshness integration remain unmeasured. The adapter stays an offline research interface.

## Verification record

The original 1,621-test baseline was successful on Linux/Windows Python 3.11/3.12. This correction adds 18 independent automated audit tests, for 1,639 total. Focused adapter/audit suites pass: 47 tests on Python 3.11.9 (10.916 s) and Python 3.12.14 (13.626 s), with zero failures. The nine pre-fix failures were reproduced before correction. Five committed provenance metadata SHA-256 checks pass, with zero restored checkout files. Complete local suites pass: 1,639 tests on Python 3.11.9 in 433.423 s and 1,639 tests on Python 3.12.14 in 356.685 s, zero failures or skips. Exact-head Linux/Windows CI results are recorded in PR #43 before delivery; a prior-head pass is not evidence for a changed head.

No critical execution-permission defect was found: even the original malformed/misleading presentations retained the top-level execution-disabled policy. The HIGH findings concern contract integrity and false source-binding/assessment implications. All findings marked corrected have targeted reproductions; unresolved authentication, session identity, private-data and capacity limitations remain explicit.
