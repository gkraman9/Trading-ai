# Synthetic quote/fill model v1

E4.1 is implemented only for explicitly invented research observations. It does
not ingest MT5, private CSVs, real ticks, credentials or account information.
E3's cost declarations are not upgraded into financial evidence.

`SyntheticQuote` requires version, symbol, feed, sequence, occurrence and UTC
availability, exact decimal Bid/Ask, quotation eligibility and new-position
eligibility. The default provenance is SYNTHETIC_RESEARCH; other provenance fails.
`SyntheticQuoteTape` binds every detached canonical quote to a declared synthetic
dataset SHA-256 and its in-process append-only producer. A hash alone cannot
approve a supplied quote. Hashes establish reproducibility, not broker finality.
The producer is not a Python sandbox or portable signed attestation.

Occurrences cannot move backward; receipt availability must strictly increase for
new sequences. Sequence numbers must increment by one. An exact latest duplicate
is idempotent; conflicting/revised same-sequence observations are rejected.
Corrections require a separate reviewed replay/cohort, never in-place replacement.
Repeated prices are permitted with new occurrence times. A new receipt of an old
tick retains its original age. Same-availability competing quotes are rejected
rather than silently ordered. Crossed/nonpositive/nonfinite prices, booleans,
unknown session flags, naive/future occurrence/availability and wrong feeds fail.

`FillPolicy` has no implicit latency/freshness assumptions. It requires version,
latency_ms, max_age_ms, max_gap_ms and max_analysis_age_ms. Typed synthetic costs
also explicitly require adverse slippage. A fixture can declare zero latency or
zero slippage; this is not an actual broker assertion. Limits are durations in ms,
not modified production market-data tolerances. All time comparisons use UTC.

For entry, choose the first causally eligible quote after the authenticated E3
assessment. Occurrence must be at/after decision plus latency; availability must
be strictly after the decision and at/before the evaluation cutoff. It must be
fresh at that cutoff. The caller cannot choose a later more favorable quote.
A stale first quote fails rather than falling back to a newer favorable one.
Opening requires both quotation and new-position permission. Exits require
quotation permission; a declared close-only phase allows exits but not entries.
Neither declaration verifies an Exness calendar.

| Research direction | Entry | Exit |
| --- | --- | --- |
| BULLISH | Ask plus declared adverse slippage | Bid minus adverse slippage |
| BEARISH | Bid minus adverse slippage | Ask plus adverse slippage |

The versioned toy assumption fills at **quote availability/receipt time**, using
that observation's side-specific price with declared adverse slippage. Occurrence,
availability, decision and fill timestamps are all retained. This is not a claim
that a quote proves executable liquidity or a broker could fill at that price.
Candle OHLC is never substituted for a quote. The spread is already incorporated
in the Bid/Ask sides; no second spread deduction is made.

`validate_fill_report` recomputes the entire fill using the producing tape and
explicit policies. Rehashing a changed side or price cannot authenticate it.
Future source append cannot change an earlier cutoff's fill. Invented tape cap:
10,000 quotes by default, configurable up to 100,000. Sequence/resource/clock
failures leave the existing tape unchanged. Missing capture evidence or gaps are
not evidence of zero price movement. Actual-feed adapters remain NOT_IMPLEMENTED.
