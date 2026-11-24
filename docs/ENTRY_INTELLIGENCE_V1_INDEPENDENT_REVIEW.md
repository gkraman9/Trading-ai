# E1 independent-contract technical review

Reviewed base: PR #46, 6740a403d8d4203e798bc287ed39ef79f0503565.
This is automated contract-derived adversarial review by the implementation
assistant using separately invented OHLC and new tests. It is not external human
approval, a separate-author security audit, broker certification or historical
validation. No terminal, AI provider, orders or private datasets were used.

## Findings and disposition

| Severity | Finding | Disposition |
|---|---|---|
| CRITICAL | None verified | No execution path or source-eligibility bypass found in reviewed interfaces |
| HIGH | None verified | No unresolved finding preventing E2 research implementation |
| MEDIUM | None verified | Transactional, chronology and qualification guards resisted the new probes |
| LOW | Producing-session verification is in-process only; private Python internals are not a security sandbox | Existing documented limitation; no portable authenticity claim. Stateless assess_entry does not retain its producer: use EntryResearchSession when verification matters |
| LOW | Bounded full-prefix copies/revalidation cost increases with session size | Existing explicit resource limits; benchmark before broader use; not production/live-latency approval |

No verified E1 defect required a predicate, validation or lifecycle correction.
An initially failing review assertion incorrectly expected only EXPIRED: the actual
contract allows original expired anchors alongside unrelated abstained anchors.
The assertion was corrected to inspect the relevant lifecycle; upstream rules were
not changed to satisfy it. Automated review **passes for proceeding to E2**;
external human review remains outstanding.

## Inspected implementation and evidence

EntryResearchSession stages a copied SR ledger, validates V3 against typed context,
records through the unchanged SR public interface and compares its result to the
same source. Projection/resource failures do not commit the candidate. Live and
historical labels reject before SR evaluation. Canonical setup IDs include
strategy/version/symbol/direction/zone/touch. The source SR ledger rejects corrected
or late prefix data, same-cutoff conflicts and backward time; immutable canonical
zones and original tolerance are retained. Confirmation availability is the closed
C timestamp, never a fill. Five distinct observed eligible closes drive expiry;
blocked snapshots and repeated calls do not increment it. Concurrent opposite or
overlapping anchors remain distinct and do not select a trade.

Serialized EVALUATED E1 reports must have a valid canonical checksum, unchanged
safety and a hash actually produced by the original session. Rechecksummed edits
and another session fail. Previously returned reports remain verifiable after
later snapshots, but their authenticity is not a claim of *current* eligibility.
E2 must independently bind the original qualification cutoff and current source.
No serialized report alone grants approval. Live dashboard code displays only
availability and never invokes the synthetic research session. PowerShell default
root resolution occurs in the body; the existing actual Windows PowerShell 5.1
-File test must remain in CI. Operator reports that startup now works are operator
evidence, not independent cloud reproduction of the MT5 terminal.

New tests: tests/test_entry_independent_review.py with independent OHLC in
exit_fixtures.py. Eighteen adversarial tests passed on Python 3.11.9 (12.374 s),
before E2 implementation began. They exercise forged hashes/fields, provenance,
future append, source revision, cutoff chronology, duplicate identity, immutable
exports, source/setup caps, injected projection failure rollback, confirmation
expiry/re-arm timing, overlapping directions, blocked age and startup source.
Inherited E1/SR/V3 tests remain required in the full matrix.

## Reviewed E2 integration boundary

E2 must fork a verified E1 source at the original report's exact SR log prefix,
not copy a producer's possibly future state. A new additive fork_at interface
verifies the original report, replays only its trusted SR prefix and checks its
exact log hash before returning an isolated session. No arbitrary log import is
exposed and no historical/live label override is added. New tests must show future
source entries cannot affect frozen targets or initial E2 lifecycle. This extension
is integration work, not a change to existing SR predicates or E1 output hashes.

WAIT; execution_allowed=false; Exness BLOCKED; DATA_NOT_QUALIFIED;
historical_validation=PENDING; historical_comparisons=NOT_RUN. PRs remain drafts.
