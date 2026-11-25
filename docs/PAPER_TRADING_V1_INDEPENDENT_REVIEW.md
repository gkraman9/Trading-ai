# E4.6 automated independent-contract review

Parent: PR #49, `e18f6c7c61b3caebef45085a74b2aa93ba7caded`.
This is an automated adversarial technical review by the implementation assistant,
not independent human approval, broker certification or historical qualification.

The actual synthetic tape/fill, capital, specification/cost, account and journal
implementations were inspected. Twelve independently authored tests reuse actual
E1/E2/E3 producers with explicitly invented observations. Initial verified result:
12 tests, 10 pass, 2 fail (15.608s, Python3.11.9).
A preliminary midnight fixture shifted M5 openings off-grid; that fixture error
was corrected to a five-minute-aligned shift before reproducing the actual defect.
No production eligibility check was weakened to obtain the reproduction.

## HIGH E46-01 — specification effective after the modeled decision

`assess_capital` checks the specification at caller processing time, while the
modeled fill uses an earlier quote receipt and the original E3 decision cutoff.
A declaration effective0.5 or1.5 seconds after that cutoff was accepted with an
entry quote at+1 second and processing at+2 seconds. Financial specifications not
yet effective at decision could therefore authorize an earlier modeled fill.
Required correction: require effectiveness at/before that decision, as well as
validity at processing. Announced future-effective specifications need a separately
reviewed publication/availability contract; this model cannot silently assume it.
Correction: explicit SPEC_NOT_EFFECTIVE_AT_DECISION guard added in its own
commit. The isolated HIGH regression passes after the correction. No new
functionality was implemented while this finding remained open.

## MEDIUM E46-02 — realized losses bucketed by processing date

A source-authenticated exit fill at November12 23:59:59.900 UTC processed200ms
later was charged to November13. Costs/holding used the actual fill timestamp but
`daily_losses` used caller `as_of`. Required correction: bucket realized loss by
`exit_fill.filled_at_utc`, retaining processing cutoff separately in the journal.
Correction: realized loss now uses the actual modeled exit-fill UTC date;
processing/observation cutoff remains separately recorded. Corrected in a
separate accounting commit.

## LOW / design limits

Producer authentication is in-process, not a security sandbox or portable signed
attestation. Declared synthetic hashes, specs, cost rates and session flags are
not real provider evidence. Observed-only excursions are not complete capture.
V1 deliberately leaves margin/liquidation and ambiguous/missing exits unresolved.
A new protective model must consume every known quote in a cutoff prefix and must
not reinterpret old v1 journals or E2's closed-candle observation predicates.

Other tests verify down-rounding/minimum lots without stop changes, no spread or
fee duplication, unchanged historical drawdown after recovery, negative balances
and exhaustion without replenishment, source/hash forgery rejection, missing cost/
basis rejection, clock/source rollback, frozen reports and live provenance denial.
All safety invariants remain unchanged. No CRITICAL finding was established.

## Correction verification before E4.6 functionality

Both defects were reproduced against the untouched parent, then corrected in
separate source commits. The same12 adversarial tests now all pass (15.831s on
Python3.11.9). No unresolved CRITICAL or HIGH finding remains from this automated
review. Existing v1 goldens/consumer contracts remain regression requirements;
only the two invalid causal/accounting edge cases change. External review remains
pending. Protective-stop/liquidation functionality begins only after this result.
