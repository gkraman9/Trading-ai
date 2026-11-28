# E5 historical evidence recovery v1

Review date: 2026-11-28. Exact parent: PR55
`6cb9e040c66e4366f3c605e8b1d738bc9524d314`.
**Benchmark BLOCKED; performance UNMEASURED; qualification DATA_NOT_QUALIFIED.**
Historical validation PENDING; historical comparisons NOT_RUN. This is an evidence
recovery review, not a historical replay, independent approval or broker certification.

## Scope and evidence strength

Reviewed the repository's source catalogs, pilot manifests/reviews, provenance and
boundary investigations, Exness intake, B.2 capture/processor contracts, E4.7 financial
contracts and E5 admission/replay. Checked open PRs on the review date: no newer
Exness correction or genuine source approval was present. R1/R2 remain separate.
No Windows files, accounts, terminal, journal service or credentials were accessed.
Existing cloud public-pilot bytes were inspected read-only; no new data downloaded.
Public URL references below retain their original review dates; this task does not
claim a fresh web retrieval or applicability authentication.

The [machine-readable inventory](source_reviews/e5-evidence-recovery-v1.json) pins
14 committed metadata references with exact file hashes. Its own canonical payload
hash excludes `sha256`. These establish byte integrity, not provider identity.
No required candidate has status AVAILABLE_INDEPENDENTLY_VERIFIED as a whole.
A property with a VERIFIED label in an old publisher review is not E5 qualification.

| Evidence lead | Availability / suitability | Established here | Still missing |
|---|---|---|---|
| 2021 public pilot | AVAILABLE_UNQUALIFIED; derived M5 UNSUPPORTED_CURRENT_ADAPTER | Existing cloud Parquet and CSV hashes match committed metadata; M1 240 rows, M5 48; UTC openings 08:00–11:59 and 08:00–11:55 on May25 | Upstream identity/rights, native M1/M5, actual receipt sequence, dated sessions/finality/corrections, outcome data, financial contracts and independent approval |
| November11–13 Exness exports | UNAVAILABLE here; operator-reported only | Repository records hashes, 4,074/816 counts, 813 comparisons, three partial M5 bars | Actual bytes/local reproduction, native feed/Bid mapping, all E5 evidence; partial bars unsupported |
| XAUUSD_M5_IAT_normalized.csv | UNAVAILABLE | Only a reported 40,610 rows / April1–October26 range | Actual authorized file/hash, matching native M1, basis/feed/finality and all other E5 evidence; no inferred native pair |
| Real B.2/B.3 / dashboard logs | UNAVAILABLE; possible acquisition leads | Recorder contract preserves packet receipt and source hashes; cloud example journals are synthetic | Actual immutable dated archives, exact versions, original collector clocks, coverage, correction/finality review and a reviewed conversion path |
| Exness support note and calendars | AVAILABLE_INCOMPLETE | Pinned redacted relay, BLOCKED candidate/review, conflict matrix | Authentic correspondence, attachment inventory, dated same-feed quote/trade coverage and independent review |
| Historical specs/costs and independent reviews | UNAVAILABLE as qualifying evidence | Typed E4.7/E5 contracts, pending/template/synthetic examples exist | Actual effective documents and genuine independent approvals |
| OANDA/FXCM/Dukascopy | Documentation leads, authorized exports UNAVAILABLE | Prior source review records provider-specific limitations | Entity-applicable rights, permitted export, native frames/quotes/receipts, dated calendar/finality and reviewed adapter |

### Public pilot: exact recovery findings

Existing cloud `private-xauusd-pilot` and `source-review` artifacts were found; their
private paths are not portable acquisition instructions. No market rows are published.

| Artifact | Bytes / rows | Actual SHA256, matches recorded value |
|---|---|---|
| Original Parquet | 10,304,019 / 1,156,740 | `6dd18367ceed4385424a69c7d4380455cb526a866af8d352a59d25520e123bec` |
| Normalized M1 | 14,892 / 240 | `3fcb4eed61ce5a6cb773de8c686ca11a108134031068289ee18ca7e2e7070023` |
| Derived M5 | 3,006 / 48 | `362c82c850bb22946b2820265b32d561859b7431c1acf2e8c675424754904dc6` |
| Private manifest | 2,957 | `dda3785de354bf93c66e7f1d47d2ff9bf31a4f4ddcaae4c7b68ec84f6b788992` |

Parquet columns are `timestamp,bid_price,ask_price,bid_volume,ask_volume`.
There is no separate receipt/availability or original sequence/correction field.
The publisher describes reconstructed broker-derived ticks; the named upstream feed
and original collection records are not established. No authoritative availability
contract or original capture log was found in the reviewed materials. This is not
proof such records cannot exist: request them from the publisher. Do not reinterpret
`timestamp` as receipt. The archive also exceeds E5's 4MiB artifact bound; do not
thin or relabel it to fit. M5 remains internal aggregation only, even though native
Bid/Ask columns exist in the raw file. Existing warm-up08:00–11:00/evaluation11:00–12:00
has no separately qualified outcome tail. Do not reuse Exness2026 evidence for2021.

### Can existing recorder archives recover receipts?

`iat/live_shadow/feed.py:observed_tick` records MT5 `time_msc` occurrence and validates
it against the post-read clock. The returned `observed_at_utc` field is the tick's
occurrence, **not** its receipt. `processor.py` records packet `received_at` separately.
Range capture retrieves historical ticks at a later query: each tick's event time
is not a native individual receipt time. Repeated polls/unchanged ticks do not create
new native occurrences or prove continuous capture. A database filename or intact
hash chain does not authenticate broker completeness.

Recover immutable archives and matching collector version/configuration first.
Retain actual packet acquisition timestamps as observation evidence, with query
bounds, rejection/clock/reset/coverage records. Do not assign one query receipt to
each tick as if independently received; do not fabricate a sequence/finality flag
from row order. E5 has no reviewed B.2-journal conversion adapter. Even an archive
with enough fields requires explicit clock/lineage/availability review before a
conversion can be considered. November23 captures cannot establish November11–13
receipt history or costs. B.3 analytical outputs cannot replace original B.2 inputs.

The existing `qualify_historical()` gate was run read-only against the recovered
private pilot manifest without inventing a review. Actual result: DATA_NOT_QUALIFIED,
with CANDLE_FINALITY_UNCERTAIN, EVIDENCE_CALENDAR_PENDING, EVIDENCE_FINALITY_PENDING,
HUMAN_QUALIFICATION_REVIEW_REQUIRED, INDEPENDENT_REVIEW_PENDING and SESSION_CALENDAR_REQUIRED.
No historical replay ran. These are observed gate results, not newly assigned approvals.

## Minimum dated Exness resolution matrix

Target lead interval: November11–13,2026 UTC, plus a **predeclared** warm-up and
outcome window. These are leads, not an approved evaluation interval.

| Issue | Existing evidence / conflict | Minimum independent evidence |
|---|---|---|
| Quote availability / closure | Relay says quotes and trading stop21:58, quotes return23:00; candidate agrees on quote openings but public winter notice says closed until23:00:30 | Authenticated dated same-feed schedule and native first/last tick evidence with subsecond occurrence/availability; minute openings cannot locate first tick seconds |
| New-position permission | Relay says23:00–23:02 close-only; candidate UNKNOWN23:00–23:00:30, then CLOSE_ONLY | Explicit dated open/close permissions for each phase, including at/after23:02; never infer from quote availability |
| Friday November13 | Candidate closes after21:58; generic daily wording may suggest23:00 reopening | Explicit Friday/weekend date coverage, feed-specific exceptions and authenticated provider clarification; do not invent reopening |
| Overnight coverage | Missing21:58/21:59 M1 reportedly repeats across dates | Dated verified quote calendar plus independent capture completeness; absence alone cannot prove closure |
| Partial21:55 M5 | Three reported bars may cover only21:55–21:58 | Provider interval/finality/correction contract and original constituent records. E5 rejects partial/unknown bars; never pad to22:00, drop silently or shift close |
| Full M1/M5 finality | 813 reported numeric matches do not establish eligibility | Native frame identity, UTC opening/closing convention, actual publication/availability and version/correction evidence |
| Holidays and maintenance | Relay says no special interruptions; general pages do not certify the exact feed/dates | Authenticated dated holiday and regular/special maintenance coverage including warm-up/outcome; no special exception does not prove no regular pause |

Sources remain the pinned [investigation](source_reviews/exness-session-investigation-2026-11-23.json)
(review2026-11-23), [relay](../config/reference/exness-2026-11-11-13.relayed.json),
and candidate/review. The investigation cites the Exness November1 winter notice,
instrument hours, holiday guidance, MetaTrader UTC documentation and MQL5 weekly
quote/trade functions. Weekly metadata is not dated exception proof. Original reply
headers/sent time/attachments and export-specific applicability are still missing.
No calendar JSON, review flag, permission or expiry is changed by this research.

E5 currently requires full verified M1/M5 geometry. A November11–13 package including
partial21:55 bars remains unsupported even if a provider later certifies them.
Do not remove those bars merely to force admission. An independently preregistered
intraday window with complete warm-up/outcome wholly inside reviewed coverage could
avoid that geometry legitimately; document the selection before viewing results.
It still needs every quote/source/cost/review requirement. Otherwise a separately
reviewed partial-bar adapter is required; not part of this task.

## First-benchmark decision

Prioritize the existing Exness archive and its original collector records. If the
receipts were never recorded and no authoritative availability contract can establish
them, this window cannot support E5 as implemented. Obtain another authorized
historical archive with the required records; do not repair history with a new live
capture. The [operator procedure](E5_OPERATOR_ACQUISITION_V1.md) lists exact schemas
and review handoffs. The [analysis-age review](E5_ANALYSIS_AGE_REVIEW_V1.md) explains a
separate model limitation that remains even with complete source evidence.

All six research deliverables are supplied across this report, its inventory and
the two companion documents. Historical metrics are unmeasured; DecisionLog and
paper full/full/prefix historical comparisons remain NOT_RUN. No live services,
orders, credentials, calendar approval, AI or paper activation, or merges occurred.
