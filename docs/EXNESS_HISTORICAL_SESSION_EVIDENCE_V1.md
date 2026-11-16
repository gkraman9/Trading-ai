# Exness historical session evidence review v1

Public text reviewed **2026-11-16 UTC**. Registry collection cutoff: `2026-11-16T08:16:14Z`. This is a limited primary-document review, not account/terminal validation or independent human approval. No private CSV, diagnostic or PR #24 local manifest bytes were supplied to Codex. No full source HTML, authenticated portal data or copyrighted article copy is committed; short factual summaries and inspectable URLs are recorded. No external original-byte artifact hash is invented.

## Primary references actually reviewed

| Source | Finding and qualification limit |
| --- | --- |
| [Exness winter notice](https://get.exness.help/hc/en-us/articles/31342732737180-Trading-Hours-Update-End-of-US-Daylight-Saving-Time-01-Nov-2026) | Ordinary XAUUSD's post-change trading reference closes weekdays at 21:58 UTC. Reopening distinguishes restricted and full phases. This does not independently establish the operator's demo quote schedule or dated exceptions. |
| [Exness platform timezone](https://get.exness.help/hc/en-us/articles/360014390760-What-is-the-default-timezone-set-for-MetaTrader) | Describes server-synchronized GMT+0 platform time. Historical export construction/account applicability still needs evidence. |
| [Exness instrument hours](https://get.exness.help/hc/en-us/articles/4405235684498-Instrument-trading-hours) | A filtered schedule widget and general maintenance/holiday information are described. No complete account-specific filtered November 11–13 schedule artifact was captured. Trial maintenance is mentioned, but exact applicable interruptions and duration remain unknown. |
| [Exness holiday hours](https://get.exness.help/hc/en-us/articles/17923046759836-Holiday-trading-hours) | Retrieved text did not establish complete XAUUSD exception coverage for the requested dates. A holiday list is not evidence of either closure or unchanged hours. |
| [MetaQuotes symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants) | Chart-mode documentation distinguishes Bid and Last bar construction. It does not certify the actual historical symbol setting or this export. |
| [MetaQuotes rate-range documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py) | Describes UTC bar openings and limited available terminal history. It does not establish this capture's completeness, partial-bar finality or broker correction policy. No documentation example code was run. |

URLs are genuine public references, not synthetic sources. Their content was reviewed through the research web tool, not by the offline runtime. Retrieval timestamps record this review's access, not an authenticated HTTP-capture timestamp. Publication/effective timestamps remain null where only a title day or page update was available. No end date is extrapolated from a seasonal notice. The registry contains six public leads and one separately identified internal candidate reference; independent reviewer declarations remain empty.

## Candidate and unresolved session correspondence

The candidate's weekday quote close remains **21:58 UTC**, consistent with the published trading-close reference. Consistency does not prove quote/trade equivalence or exact account applicability.

The candidate's weekday quote reopening at **23:00** is distinct from the notice's restricted-phase reference at **23:00:30** and full-trading reference at **23:02**. A minute display might describe a different phase/availability boundary, but this has not been established. Preserve the candidate and notice separately. Explicit conflict links mark this correspondence unresolved; the report must not present the different phase definitions as proven contradictory measurements of the same quote event. It does not alter any boundary or clear CALENDAR_SCHEDULE_CONFLICT.

For November 11–13, authoritative account/feed applicability, complete dated holiday/maintenance exceptions and native export finality remain missing. The November 11 holiday entry on a general list cannot establish XAUUSD's actual hours. General Trial-server maintenance is not evidence of an exact interruption or its end; do not manufacture a dated closure from it. A current widget, seasonal table, present chart mode or matching OHLC cannot fill those gaps.

## Historical price basis and finality

The reported chart mode 0 and CSV `spread` column are leads, not independent historical BID certification. Require attributable evidence tying the exact export, symbol/account settings, native M1/M5 construction, tick aggregation and UTC opening convention to the November dates. Also obtain completed-bar/capture evidence, partial-candle semantics, corrections/revisions and demo/live feed distinctions. The three conditional 180-second partial closes stay ineligible for ordinary inputs with unknown finality.

## Exact next evidence requests

Ask the operator/provider to supply, privately and with permitted use:

- Applicable legal entity/feed and exact account/instrument specification, mapped to an anonymous account-scope alias.
- Dated quote and trade-phase schedules for the target interval and relevant warm-up, with timezone/DST and explicit exceptions; clarify displayed quote reopen versus restricted/full trading phases.
- XAUUSD-specific November 11–13 holiday, maintenance and exceptional-announcement coverage, including confirmation of unchanged hours only if actually supported.
- Historical price-basis/native-export provenance, completion/correction contract and partial-bar treatment.
- Offline-use rights and any restrictions on storing/sharing raw or derived evidence.
- An actual independent reviewer record resolving applicability and preserving disagreements.

These are questions for manual evidence gathering; no messages are sent by this implementation. No credentials are needed or recorded. Even completed reviewer declarations cannot grant qualification in this PR.

Exness BLOCKED; DATA_NOT_QUALIFIED; historical validation PENDING; comparisons NOT_RUN; signal WAIT; execution_allowed=false. See [runtime workflow and commands](INDEPENDENT_SOURCE_QUALIFICATION_V1.md).
