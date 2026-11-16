# Independent historical evidence review worksheet v1

Dataset: XAUUSD M1/M5, November 11–13, 2026 UTC. **No independent approval recorded.** Keep account-identifying documentation and actual data private. Use anonymous document names in any shared manifest. Do not enter credentials or account numbers here.

## Observed — operator assertions

The operator reports using PR #23 commit `5083984745527402b8f75b1ab568e558d3cad92e` on Windows/Python 3.11 with tzdata 2026.6. Source declarations and fingerprints are frozen in [operator observations](../config/examples/historical-evidence/operator-reported-v1.json). Reported findings: 4,074 M1 rows, 816 M5 rows, 813 matching five-M1 comparisons, three partial comparisons, six unresolved absent M1 slots. The three conditional partial closes are November 11/12/13 at 21:55 UTC, each nominally 180 quote seconds under the candidate calendar. Schedule verification is false.

These are operator-reported local diagnostics. The original CSVs and private diagnostic report were **not available to Codex**. Matching file fingerprints have not been independently checked for the real files in the cloud.

## Mechanically reproduced — fill from actual local output

- Local verification manifest file SHA-256: **not supplied**.
- Actual verifier checkout revision (`git rev-parse HEAD`): **not supplied**.
- Evidence collection timestamp: **not supplied**.
- LOCAL_INTEGRITY_VERIFIED checkpoint: **pending local run**.
- LOCAL_MECHANICAL_REPRODUCED checkpoint: **pending local run**.
- Reproduced counts, partials, coverage and blocker codes: **pending local run**.
- Input/output integrity review: **pending**.

Do not replace these entries with synthetic CI results. Exact bytes matching declarations establishes integrity relative to those declarations; it does not authenticate the feed or external facts. Local diagnostic reproduction is separate from historical strategy comparisons, which remain NOT_RUN.

## Candidate assumption

The checked-in Exness candidate suggests a 21:58 UTC quote close, explaining a possible 21:55–22:00 partial close. Quote/trade, holiday/maintenance and finality verification remain false, with schedule conflicts unresolved. The missing 21:58/21:59 observations remain MISSING_UNESTABLISHED_UNVERIFIED_CALENDAR. No official dated broker close is established by this geometry.

## Externally corroborated

**None newly established by this PR.** Existing calendar source references are leads for independent review; their presence does not establish exact account/feed applicability, dated exceptions, capture completeness or finality. Do not fabricate citations, access dates or approvals.

## Still unresolved — qualification checklist

| Item | Required independent evidence | Current state |
| --- | --- | --- |
| Account/server identification | Privately inspect exact applicable demo/provider entity and feed; publish only an anonymized applicability conclusion. Never credentials. | MISSING |
| Exact XAUUSD specification | Dated instrument identity, native M1/M5 export provenance and relevant specification, not just a current screenshot. | MISSING |
| Historical quote/feed provenance | Provider/terminal/export provenance and capture process for the entire warm-up/evaluation interval. | MISSING |
| Price basis | Dated BID/ASK/MID/LAST evidence applicable to exported history. Current chart mode 0 is not independent historical proof. | MISSING |
| Timezone/DST | Authoritative timestamp convention and dated UTC/session conversion applicability. | MISSING |
| Dated quote/trade sessions | Applicable November 11–13 schedule and preceding warm-up, plus resolution of candidate conflicts. | MISSING |
| Holiday/special closures | Date-specific exception coverage; weekly metadata alone is insufficient. | MISSING |
| Maintenance interruptions | Applicable dated maintenance coverage and unexpected-gap handling. | MISSING |
| Completion and corrections | Full/partial candle finality, capture completeness and revision/correction contract with referenced document hashes. | MISSING |
| Usage/redistribution rights | Authorized offline analysis and any restrictions on sharing source data or derived reports. | MISSING |
| Independent review decision | Genuine independent reviewer evidence, scope, conflicts/limitations and decision. No self-approval. | MISSING |

For each item record a sanitized document reference, original-byte SHA-256, independently inspected content/applicability, reviewer date, unresolved conflicts and limitations in a private review record. A nonempty reference is not verified evidence. The v1 manifest records references only as OPERATOR_REFERENCE_NOT_VERIFIED and cannot approve them.

Independent reviewer identity/signature: **not supplied**. Decision: **PENDING, NOT APPROVED**. Decision date: **not supplied**. Remaining disagreements: **unresolved**. The existing independent qualification workflow must assess genuine evidence separately; this worksheet cannot bypass it or automatically generate blinded packets.

Preserve these blocker codes: BROKER_PHASE_RESTRICTED, CALENDAR_COVERAGE_UNVERIFIED, CALENDAR_SCHEDULE_CONFLICT, CANDLE_FINALITY_UNCERTAIN, HOLIDAY_COVERAGE_UNKNOWN, MAINTENANCE_COVERAGE_UNKNOWN, PARTIAL_SESSION_CANDLE, SESSION_PHASE_UNKNOWN.

Exness BLOCKED; signal WAIT; execution_allowed=false; historical validation PENDING; historical comparisons NOT_RUN. No profitability or predictive-edge claim follows from this review.

## PR #25 operator update and independent-source worksheet

The operator now reports completing LOCAL_INTEGRITY_VERIFIED → LOCAL_MECHANICAL_REPRODUCED → INDEPENDENT_QUALIFICATION_REQUIRED in the private PR #24 report. Reported payload digest: `3c794f78db44c2de4a3844e32cfeb30fdfe962fd8890c7a389eb9fe588207895`; reported diagnostic payload digest: `d78cb26862e5fdc880313f97b8fa6a81b60b5cab6fee0b80f02b01e3067a4069`. These are payload hashes, not original-file hashes. The original bytes were not provided to Codex, so this update does not claim a cloud reproduction. Do not infer a UTC collection timestamp from the Windows report filename.

Use the [independent source registry and workflow](INDEPENDENT_SOURCE_QUALIFICATION_V1.md) and [dated public-source review](EXNESS_HISTORICAL_SESSION_EVIDENCE_V1.md). Public references supply limited research leads, not exact account/date approval. The original unresolved checklist above remains open.

For each genuine independent review, complete these fields privately; no entry below is a signature or completed review:

| Field | Current entry |
| --- | --- |
| Reviewer pseudonym, distinct from collector | NOT SUPPLIED |
| Actual review UTC timestamp | NOT SUPPLIED |
| Evidence IDs and exact claim ID | NOT SUPPLIED |
| Broker, anonymous account scope/category, instrument and UTC interval | NOT SUPPLIED |
| Authority / temporal / instrument / account / claim-support findings | UNRESOLVED |
| Scope of support or rejection | NOT SUPPLIED |
| Contradictory references and unresolved conflicts | UNRESOLVED |
| Reasoned conclusion (SUPPORTS / REJECTS / UNRESOLVED / ACKNOWLEDGED) | UNRESOLVED |
| Review provenance document and original-byte SHA-256 | NOT SUPPLIED |
| Independent identity/signature authentication | NOT ESTABLISHED |
| Dataset qualification | DATA_NOT_QUALIFIED |

The source-review schema records claim-level declarations, not a dataset APPROVED boolean. Acknowledgement is not support; support is not qualification. Self-review, missing scope, unsupported timestamps, unreviewed criteria and contradictory reviewer conclusions cannot become supported applicability. The existing replay/strategy/blinded-review/execution gates remain blocked even if the worksheet is later completed.
