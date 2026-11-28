# E5 analysis-age model review v1

Independent code-path examination against PR55 exact head6cb9e040. This document
is research, not an independent source-qualification signature. The frozen USD50
benchmark and every execution/data gate are unchanged.

## Established implementation behavior

`FillPolicy.max_analysis_age_ms` is30000 in the frozen protocol. E5 updates original
E1/E2/E3 research on each eligible closed M1 publication; risk `evaluation_at_utc`
retains the logical closed-candle anchor. New native quote receipt never refreshes
that analytical timestamp. Actual late publication is tracked separately for
causality and fills, not used to create a newer logical close.

`ProtectedPaperAccount.observe` authenticates the quote and source, checks sequence
and quote gaps, then compares receipt cutoff minus risk evaluation time with30000ms.
Strictly greater produces `STRUCTURAL_ANALYSIS_STALE` and sets the position, stop
and liquidation status UNRESOLVED. This check precedes native-stop/liquidation
observation processing. A later quote or fresh M1 update cannot automatically recover
the position: E5 terminates that episode while unresolved exposure occupies the
single position slot. This is a model limitation, not proof that a broker protective
stop would cease to function. The original unprotected observation path also rejects
stale analysis (`ANALYSIS_STALE`); no policies are changed here.

Quote age is separate: max2000ms from **occurrence**, not receipt. Coverage maxgap
is120000ms. A just-received, fresh, contiguous quote can still fail structural age.
The age check is event-driven; passage of30 seconds alone creates no synthetic event.
If no eligible quote occurs in the over-age part before the next M1 update, no
stale transition follows solely from wall time. Other data/predicate failures can
still block before or after that interval.

## Quantification: labeled invented fixtures only

Executable study: `tests/e5_analysis_age_study.py`; tests:
`tests/test_e5_evidence_recovery.py`; [frozen study output](research_audits/e5-analysis-age.synthetic.json).
The fixture reuses unchanged E5 replay, original causal OHLC, USD50 policies and
paper producer. Invented prices are flat at the sampled quote points to avoid a
competing price-triggered exit. No historical source gate is mocked into approval;
this test-only source is explicitly registered as synthetic by inherited fixtures.
No account returns/P&L or market performance is claimed.

After logical M1 close15:36:00 in the synthetic fixture:

| Invented quote receipt offset | Observation |
|---|---|
| +1.000s | One position opens; another candidate is rejected by unchanged concurrency policy |
| +30.000s | Prefix replay contains one MONITORING position; zero structural-stale transitions |
| +30.001s | Exactly one STRUCTURAL_ANALYSIS_STALE transition; position becomes UNRESOLVED |
| +60.000s and +61.000s | Next M1 publication occurs; prior unresolved episode remains unresolved, no forced close/recovery |

Each invented receipt equals its occurrence; quote age0ms. Gaps are below120000ms.
Thus these failures are not stale quotes, missing sequences or clock skew. Full
and prefix paths use actual E5 scheduler; the study's canonical hash and repeated
output are checked. Existing full/full/prefix E5 tests remain inherited.

For ideal zero-delay eligible M1 updates60 seconds apart, continuous clock geometry
has a stale interval `(30s,60s)`: duration30 of60 seconds. This is half the idealized
interval by **duration**, not a confidence score, historical unresolved rate or
probability of loss. Boundary30.000 is accepted,30.001 is not. Quote arrivals, actual
positions and competing events determine how often the condition is encountered.
Delayed publication can lengthen it: with a fixed200ms delay, the logical anchor
remains at0 and the next update arrives60.2s, leaving `(30s,60.2s)` before that
publication. No measured historical frequency can be stated without qualified data.

## Decision for this benchmark

Retain the30000ms policy and its protocol hash. Report unresolved exposure honestly;
source qualification alone cannot eliminate this limitation. An admitted historical
run could therefore be only partially measured/unresolved. Do not raise the threshold,
refresh risk every quote from the same closed candle, fabricate intra-minute analysis,
remove stale observations or optimize the evaluation window after seeing results.

## Future model proposal — NOT IMPLEMENTED, NOT ACTIVATED

Proposed identifier `E5_ANALYSIS_VALIDITY_SEPARATION_DRAFT_V2` is documentary only;
there is no runtime registry entry, configuration switch, new default or approved
policy. Independently review separate validity contracts for (a) native quote-based
protective stop/liquidation monitoring and (b) structural entry/exit/risk decisions.
Specify max age, scheduled closed-candle publication/deadline, late/missing/quality
and session handling for each, with no implicit reuse of stale structure. Explicitly
review event ordering when structure is stale but a native price stop is observable.
Any extension needs a new protocol/model version, unchanged comparison baseline,
causal prefix/adversarial tests, independently reviewed source applicability and a
separate PR; it must not rewrite this benchmark or its journals.

Safety remains READ_ONLY_SHADOW, WAIT, execution_allowed=false, Exness BLOCKED,
DATA_NOT_QUALIFIED, historical validation PENDING and comparisons NOT_RUN.
