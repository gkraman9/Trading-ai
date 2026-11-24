# E2 automated independent-contract review

Base: PR #47, a4c37543db734d2f629196d27c78c5e80d4b020b.
This review was performed by the implementation assistant with new contract-derived
adversarial tests and separately invented OHLC. It is not external human approval,
a separate-author audit, broker certification or historical validation.

| Severity | Verified finding | Disposition |
|---|---|---|
| CRITICAL | None | No execution or source-eligibility bypass verified |
| HIGH | None | No unresolved blocker to E3 research implementation |
| MEDIUM | None | Source, chronology, lifecycle and rollback probes passed |
| LOW | Producing-session authentication is in-process, not portable attestation or a Python sandbox | Existing explicit limitation; preserve raw-source replay prerequisites |
| LOW | Full-prefix verification and staged copies cost more as the bounded session grows | Existing limits retained; no live-latency or maximum-memory guarantee |

No E2 predicate or validation defect required correction. In particular, a past
report's authenticity does not make it a current observation; E3 must require an
explicit matching evaluation cutoff. Mixed lifecycle states across independent
anchors are legitimate and do not select a trade. Automated review passes for
proceeding to E3; external human review remains outstanding.

## Inspected contracts and new evidence

ExitResearchSession authenticates the original qualification-cutoff E1 report,
selects an explicit canonical setup and uses EntryResearchSession.fork_at to replay
only that report's trusted SR prefix. The original SR log hash must match; later
producer state and newer targets are not imported. Original target candidates are
confirmed, opposite-kind FRESH/TESTED zones beyond the original confirmation close.
Ranking is distance to near boundary then canonical ID; all candidates remain
frozen. Neither a late E1 snapshot nor forged/rechecksummed JSON is an original.

The original strict close invalidation and tolerance, canonical fresh opposing
CHoCH, five observed eligible-close expiry, blocked-clock handling and terminal
state are reused. Wick contact is different from close confirmation, and neither
is a fill. Same-bar conflicts retain both observations; simultaneous close
availability is distinguished from unknown intrabar ordering. Event occurrence
interval, availability and first observed cutoff are separate. Missing intervals
create sticky uncertainty and never backfill target success. Source/configuration
changes and same-cutoff revisions reject transactionally; resource/projection
failure does not partially commit staged source or event state. Prior reports
remain immutable/authenticated. Live/historical labels reject before synthetic
entry evaluation; live dashboard presentation never invokes E1/E2.

New tests/test_exit_independent_review.py covers 21 independent probes: source
future prefixes, target ties/ranking, retrospective selection, forged original and
current reports, wrong producer/checksum, changed configurations, same-cutoff
conflict, both directions' exact strict tolerance, wick/close distinction,
unconfirmed wick, same-bar ambiguity, simultaneous close/expiry, duplicate events,
terminal no-late-success, skipped and blocked observations, first-observed versus
occurrence, immutable outputs, resource/injected-failure rollback and recovery,
cutoff mismatch, provenance isolation and null fills/P&L/permissions. They use
independently invented tests/risk_fixtures.py, not real exports. **21 tests passed**
on Python 3.11.9 (27.579 s) before E3 implementation began. The inherited 40 E2
regressions, E1/source tests and Windows PowerShell 5.1 -File regression remain.

## E3 integration requirements

E3 must authenticate original E1, original qualification-cutoff E2 and current E2
through their actual producers, compare identity/direction/configuration/policy
and frozen references, and use the original SR confirmation bar from its verified
prefix. Current authenticated context/V3 is optional only for extra descriptive
volatility; no caller-supplied ATR value is trusted. E3 must not confuse reference
geometry with a fill, unknown price basis with Bid, or declared synthetic cost
metadata with independently qualified costs. It should be stateless and leave the
E1/E2 lifecycle untouched. WAIT; execution_allowed=false; Exness BLOCKED;
DATA_NOT_QUALIFIED; historical_validation=PENDING; comparisons=NOT_RUN.
