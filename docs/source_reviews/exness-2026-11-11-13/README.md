# Exness reply: November 11–13, 2026 (UTC)

Recorded November 17, 2026, using the operator's pasted reply. The text is a
transcription with Markdown styling removed, not an authenticated original email.
`evidence.json` hashes the exact stored UTF-8 transcription. Provider send time,
email headers, ticket identity and attachment inventory were not supplied. No
account number, server identifier, password or credential is stored here.

This is an evidence note, not a runtime calendar, replay manifest or independent
qualification registry. Existing registry contracts require file-bound historical
manifest/evidence references that are not available here; none are invented.
The operational Exness calendar, approvals and execution gates are unchanged.
This branch is based on PR #28, separate from PR #29's diagnostics changes.

## What the broker is reported to have said

The response applies to XAUUSD for November 11–13, 2026:

* Both quotations and trading closed at 21:58 UTC; the daily break ended at 23:00.
* Quotations resumed at 23:00, with close-only mode until 23:02 UTC.
* MT5 and Exness-terminal chart OHLC use Bid prices.
* No special maintenance/holiday schedule applied during the stated dates.
* Demo and real trading conditions are reported to be the same.

These are broker-attributed claims relayed by the operator; independent
verification remains pending. No DST conversion is needed for these explicitly
UTC boundaries. The response does not establish a year-round timezone/DST rule,
Sunday opening, Friday final close, or a full-week dated schedule. The close-only
endpoint implies a transition at 23:02, but does not expressly state when opening
new positions resumes. Preserve that ambiguity rather than silently granting
FULL_TRADING permission. The Bid statement concerns chart construction; it does
not independently prove that a particular CSV archive uses the same feed/basis.
The demo/real statement does not prove identical historical candles or capture.

No actual historical export or attachment was included in the material supplied
for this task. That does not prove Exness supplied no attachments elsewhere.
Original message/attachment inventory, explicit post-23:02 opening permission,
export feed/basis and UTC interval-opening convention, finality/completeness,
correction policy, usage authorization and independent review remain outstanding.
A normal weekly schedule cannot establish missing dated holiday evidence beyond
these three days. The response is not permission to use an arbitrary export.

## Existing engine behavior, conditional on declared test phases

Regression fixtures use SYNTHETIC_TEST provenance and the existing v2 calendar.
They encode the reported quote/break/close-only boundaries as explicit dated
exceptions for all three dates. FULL_TRADING before the break and after 23:02 is
an **illustrative test assumption**, not a verified operational broker schedule.
No synthetic OHLC is presented as real data and no candle is manufactured.

| UTC boundary | Quotation geometry / conditional engine result |
| --- | --- |
| 21:57 M1 | Last full minute ends at 21:58. |
| 21:55 M5 | Only 180 quoted seconds before 21:58: PARTIAL_SESSION_CLOSE, excluded from ordinary inputs; its scheduled end stays 22:00. |
| 21:58–23:00 | No quotes; CLOSED; neither open nor close permission. |
| 23:00–23:02 | Quotes available; CLOSE_ONLY; opening forbidden. Full quoted M1 bars remain strategy-ineligible. |
| 23:00 M5 | Full 300 seconds of quotes, but mixed CLOSE_ONLY/FULL_TRADING phases in the conditional fixture; not strategy-eligible. |
| 23:02 | Valid M1 opening; its candle is not closed until 23:03. It is not an M5 grid opening. |
| 23:05 M5 | First wholly FULL_TRADING M5 interval under the conditional fixture; not closed until 23:10. |

A second fixture leaves the post-23:02 phase UNKNOWN with the trade schedule
unverified. Quotes can be available while broker opening permission remains null;
ordinary analysis stays blocked. The strict compiler rejects an UNKNOWN phase
when a caller falsely marks its trade schedule verified. This preserves the
separation between quotation availability and permission to open positions.

Even the fully declared synthetic fixture only becomes research-eligible with
separately declared finality and elapsed full-bar time. In **every** phase,
`iat_execution_allowed=false`. Informational `broker_open_positions=true` in a
conditional test is never authorization for IAT execution. Quote resumption,
chart Bid basis and a helpdesk statement cannot establish archive finality.

## Reproduce

```powershell
py -3.11 -m unittest discover -s tests -p test_exness_dated_boundaries.py -v
py -3.11 -m unittest discover -s tests -p test_session_v2.py -v
py -3.11 -m unittest discover -s tests -v
```

The tests cover all three dates, exact half-open endpoints, partial and mixed-phase
M1/M5 bars, expected ordinary openings, unknown trade permission, finality/time
requirements, transcript checksum and unchanged safety markers. Linux/Windows CI
runs the full suite on Python 3.11.9 and 3.12. No broker terminal was contacted.

Historical validation remains PENDING, historical comparisons NOT_RUN, source
DATA_NOT_QUALIFIED and Exness BLOCKED. Signal WAIT and execution_allowed=false
remain unchanged. This change records and tests evidence; it certifies no source,
feed, broker compatibility, historical capture or trading performance.
