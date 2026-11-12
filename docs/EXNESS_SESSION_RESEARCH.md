# Exness XAUUSD research and unresolved reconciliation

Access date: **2026-11-12 UTC**. This is a source review, not a test of the user's
terminal. The screenshot itself was not attached to this task: the supplied
weekly times are treated as a **user-supplied transcription**. No account or
server identifier is recorded here or in the redacted terminal report.

## Sources and applicability

| Official source | Finding and limit |
| --- | --- |
| [MetaTrader timezone](https://get.exness.help/hc/en-us/articles/360014390760-What-is-the-default-timezone-set-for-MetaTrader) | Exness specifies GMT+0 for MetaTrader. `UTC` is used without shifting the supplied clock times. This source does not independently identify/test the local connection. |
| [US DST end notice, 1 November 2026](https://get.exness.help/hc/en-us/articles/31342732737180-Trading-Hours-Update-End-of-US-Daylight-Saving-Time-01-Nov-2026) | Dated winter reference for ordinary XAUUSD; the XAUUSD 247 row is a different instrument and is not applied. The notice distinguishes close-only phases from ordinary opening. |
| [Instrument trading hours](https://get.exness.help/hc/en-us/articles/4405235684498-Instrument-trading-hours) | US seasonal changes affect hours even though server timezone remains UTC. Possible trial-environment maintenance needs separate applicability/duration evidence. The public page embeds a dated schedule widget; no complete instrument/date export was captured in this review. |
| [Holiday trading hours](https://get.exness.help/hc/en-us/articles/17923046759836-Holiday-trading-hours) | A general holiday list, including 11 November, does not establish XAUUSD closures or unchanged hours for the coverage. Instrument-specific notices are needed. No holiday is invented from that list. |
| [Only Close explanation](https://get.exness.help/hc/en-us/articles/11449086534044--Only-Close-error) | Close-only is a restricted session/instrument state, not ordinary opening. No orders are needed or permitted in this workflow. |

Only primary Exness pages were used for these conclusions. Regional summer-only
summaries, third-party broker tables and another instrument's hours are not used
to override the dated XAUUSD notice. General notices are not server-specific
attestations. The checksum-bound `.review.json` records URLs, access date,
applicability, reference phase values and unresolved codes without copying whole
articles. The legacy v1 `verification.verified_at` field records this review's
access timestamp; its explicit `IAT_UNVERIFIED:` source marker prevents that field
being mistaken for broker certification.

## Observed display versus published phases

The user-supplied displayed schedule is preserved exactly:

| Day | Displayed sessions, interpreted against published GMT+0 basis |
| --- | --- |
| Sunday | 23:01–24:00 |
| Monday–Thursday | 00:00–21:58; 23:00–24:00 |
| Friday | 00:00–21:58 |
| Saturday | Closed |

The dated winter notice places Sunday close-only at **23:01:30–23:05:00**, with
full opening at **23:05**. Monday–Thursday close at **21:58**, resume close-only at
**23:00:30**, and fully reopen at **23:02**. Friday closes at **21:58**.

A minute display may include restricted phases or truncate seconds, but that is
an **unverified explanation**, not a reconciliation established against this
terminal. The sources must be kept separate. A timezone conversion cannot explain
these second/minute-level differences. The candidate does not replace displayed
openings with full-open times or claim the broker/terminal is wrong.

The v1 format has minute boundaries and boolean open windows. It cannot express
30-second boundaries, close-only, quote-only or distinctions between trade and
quote availability. Encoding the published phases faithfully therefore requires
a separately reviewed phase-capable format/policy; rounding them is unsafe.

## DST and finite coverage

UTC itself does not move for DST. Exness's dated US-season notice changes the
**session schedule in UTC**, not the server timezone. The pre-change gold
reference closes at 20:58 and fully reopens at 22:02; the post-change reference is
21:58/23:02. The Sunday full-opening reference changes from 22:05 to 23:05. These
facts are recorded as research references, not an automatically extrapolated
summer calendar. In particular, do not set America/New_York as the server zone.

The candidate covers **2026-11-06 00:00 UTC through exclusive 2026-11-16 00:00 UTC**.
It includes the preceding Friday so a current-week request has more than 100
potential fully contained M5 grid slots. This is theoretical calendar coverage,
not a claim that any actual candles were fetched. It expires explicitly; the
installer cannot silently extend dates or generate next season's hours.

## Holidays and maintenance remain unknown

Empty `holidays`, `exceptions` and `closures` arrays contain no fabricated entries.
For this candidate they **do not mean verified absence**: the compiled calendar
carries `HOLIDAY_COVERAGE_UNKNOWN` and `MAINTENANCE_COVERAGE_UNKNOWN` runtime holds.
A weekly specification/export cannot resolve dated holiday notices. A possible
maintenance start is not enough to invent its end, recurrence or quote effect.
Unexplained gaps must continue to fail rather than being retrospectively excused.

Required next evidence: dated official XAUUSD schedules covering the whole
history/request interval, the applicable maintenance/exception notices, explicit
restricted-phase semantics, and independently reviewed local UTC M1/M5 boundary
observations. Keep raw account/server details private. The local demo state
reported by the user is useful setup context, not cloud-verified evidence.
