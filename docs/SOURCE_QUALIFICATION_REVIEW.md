# XAUUSD source qualification review — 2026-11-14

Historical validation remains **PENDING**. No source qualified in this review;
no new market-data acquisition, replacement sample, manifest or DecisionLog was
produced. Full-run hash and prefix comparisons are **NOT_RUN**. Snapshot,
hypothesis, abstention and stable-event counts are unmeasured (`null`), not zero.
The machine-readable record is
[source-qualification-2026-11-14.json](source_reviews/source-qualification-2026-11-14.json).

This review starts at PR #11 commit
`e14243e2d8db35be34efbc01163d929f5b3c1529`. It checks primary documentation
before acquiring another sample. It does not certify any provider or terminal.
Exness remains BLOCKED, signal=WAIT and execution_allowed=false.

## Pilot recheck

The [publisher API](https://huggingface.co/api/datasets/CarlosSilva1/xauusd-ticks)
still identifies revision `d14fc64dc3b0452732e60662d94b500a6bb3d534`.
Its [pinned card](https://huggingface.co/datasets/CarlosSilva1/xauusd-ticks/raw/d14fc64dc3b0452732e60662d94b500a6bb3d534/README.md)
has SHA-256
`7ac3b98b7bd639f8f33f6a6858b36d7eb05683e6494d6da76235751e3409a132`.
The publisher describes reconstructed broker ticks with UTC milliseconds and
bid/ask prices. The broker/feed is unnamed. The CC-BY-4.0 declaration does not
establish the unnamed upstream provider's redistribution rights. No dated
session calendar or complete-capture/finality contract was established.

The requested interval remains 2021-05-25: warm-up 08:00–11:00 UTC;
evaluation 11:00–12:00 UTC. Nothing in this review establishes trading hours,
holidays, exceptional closures or capture completeness for that source/interval.
A calendar from Exness or another broker cannot establish them.

The earlier [pilot review](SOURCE_EVALUATION_PILOT.md) and its manifest remain
unchanged. Their 12 comparable evaluation M5 bars, 0 uncovered and 100% mechanical
coverage are **prior PR #11 preflight observations**, not new replay results.
M5 was derived from M1: internal aggregation only. The archived bytes' checksum
is recorded there; this review downloaded only publisher metadata, not prices.
The earlier two full attempts and prefix attempt were BLOCKED without logs.
Their lack of logs cannot establish repeatability or prefix equivalence.

## Identifiable replacement candidates

| Candidate | Checks performed | Exact qualification blockers |
| --- | --- | --- |
| OANDA v20 | Native M1/M5 schema, UTC and price components, complete flag, authentication, Canadian hours/holidays and API license reviewed | No authorized XAU/USD export or matching entity/entitlement; offline-use permission not established for this task; dated calendar and sample finality not established; current adapter does not accept this finality convention |
| FXCM public candle archive | Official instrument/period catalog, UTC, indicative price basis and personal-use/EULA references checked | Catalog does not document XAUUSD candle availability; no native M5; dated gold sessions and capture/finality evidence not established |
| Dukascopy | Official website access restrictions reviewed before acquisition | Automated acquisition consent not available; export-specific usage, UTC/price basis, dated sessions and finality remain unreviewed |

### OANDA: promising documentation, no eligible sample

The [instrument definitions](https://developer.oanda.com/rest-live-v20/instrument-df/)
document native M1/M5, start-of-interval timestamps and separate bid, ask and
mid candles. A `complete` candle has an ending time that is not in the future.
That is not a promise of immutable history or complete tick capture.
The [primitive definitions](https://developer.oanda.com/rest-live-v20/primitives-df/)
document UTC/RFC3339 and epoch representations. An eventual export must retain
the selected component and observed complete flags; its XAU_USD identity and
feed must be checked rather than inferred from this generic schema.

[Authentication](https://developer.oanda.com/rest-live-v20/authentication/)
uses an account-linked bearer token. No account was accessed, no credential
was obtained, and no account API was called. No authorized offline export was
available. This task does not authorize working around those access conditions.

The [Canadian legal index](https://www.oanda.com/ca-en/legal/) provides a working
[API license](https://legal.oanda.com/ocan/api_license_agreement_ocan/en), effective
2024-06-24. Sections 3.0–3.1 describe a limited license, internal use and
restrictions on third-party dissemination. Section 9.1 disclaims completeness.
This is not a blanket public-data grant, nor proof of the applicable contract
for an unidentified account/entity or offline XAUUSD export. No permission or
license acceptance was assumed. The developer site's older terms link failed;
the legal index was followed instead.

The [Canadian hours page](https://www.oanda.com/ca-en/trading/hours-of-operation/)
currently lists XAU/USD in USD, New York time, Sunday–Friday 18:05–16:59.
The [holiday page](https://www.oanda.com/ca-en/trading/holiday-trading-hours/)
presents 2025/2026 information. Neither establishes May 2021 coverage or
applicability to the prospective API feed/entity. These are current regional
pages, not a retrospective calendar. DST and exceptional closures would need
explicit dated coverage; no conversion was used to fill the pilot's gaps.
A different evaluation interval would still need its own complete evidence.

The session calendar v2 finality model required by historical replay uses
`MT5_POSITION_1_ELAPSED`.
An OANDA export must not be relabeled with that convention. A separately
reviewed adapter/schema change would be required before using complete flags
as eligibility evidence. No adapter or evidence flags were changed here.

### FXCM: public catalog does not establish a gold candle sample

The [provider's CandleData documentation](https://github.com/fxcm/MarketData/blob/master/CandleData/README.md)
lists m1/H1/D1, weekly minute/hour publication, UTC and indicative Active Trader
pricing. Its candle instrument list contains FX pairs, not XAUUSD. Gold in other
market-data categories does not establish XAUUSD OHLC availability. No guessed
download URL was used. Personal use is subject to its
[EULA](https://www.fxcm.com/uk/forms/eula/); public access does not authorize
redistribution. Dated gold hours and a candle-finality/capture contract remain
unestablished for a concrete export. Deriving M5 would add internal consistency
evidence only and would not cure the instrument or finality gaps.

### Dukascopy: access gate prevents automated sample preparation

The [official terms](https://www.dukascopy.com/swiss/english/legal-pages/terms-of-use/)
restrict use/redistribution and automated acquisition without prior written
consent. None was available. No feed download was attempted. This is a review
of the access gate, not a claim that provider-specific timestamp, price basis,
sessions or finality documentation cannot exist. Those checks remain pending
for an explicitly permitted export.

## Evidence handling and reproducibility changes

All sources were accessed on 2026-11-14 UTC. The JSON registry distinguishes
observed HTTP response hashes from web-text/PDF reviews. Several direct HTTP
requests returned 403 even where the web tool exposed readable official text.
A 403 body checksum fingerprints that response, **not** the provider policy.
Dynamic HTML hashes are neither signed attestations nor stable document IDs.
Only references, hashes and short findings are published; no raw prices,
credentials, account identifiers or copied provider documents are committed.
Checks performed and evidence still pending are separate fields.

Analytical settings remain at the PR #11 defaults:

- Context: `d8bda7da1af47cc1f1f349682b71ca75f39bef89b7fb5d5873bc0bba5510d424`
- Intelligence: `0b1db8f78abc3801b23a2aec62ee6057a1b0b711a8244405bc5f77ff582653ff`

Replay comparison now requires identical dataset metadata (including checksums,
source and evidence declarations), configurations and log configuration hashes
before labeling two full runs repeatable. Equal logs from differently declared
inputs produce NOT_RUN with an explicit mismatch reason. Prefix comparison
requires the same source, archive lineage, warm-up starts, evaluation start and
analytical/session settings, plus a contained end range. Prefix CSV/manifest
hashes may differ because the files are truncated. Entries themselves still
must match, including evidence revisions. Missing logs remain NOT_RUN.
These comparisons verify declared input identity; they cannot authenticate a
publisher's claims or prove private bytes not supplied to the loader.

New regressions use explicitly synthetic offline fixtures. Their comparison
PASS results establish software behavior only. Inherited tests remain required
on Python 3.11/3.12 and Linux/Windows; Windows smoke checks must continue to
show the unverified Exness profile blocked without terminal access.

## Next evidence milestone

Obtain an independently reviewed, legally usable offline XAUUSD export with
named feed/entity, explicit UTC interval openings and price basis, native
same-feed M1/M5 if available, dated session/holiday/exception coverage spanning
warm-up and evaluation, and source-specific closed-bar/capture evidence.
Keep raw data private. Review those documents **before** preparing a sample or
setting evidence attestations. A publisher declaration alone is not independent
verification. No credentials need to enter source code or this workflow.

After those gates pass, create a private manifest v2 with exact file/calendar
checksums and separate warm-up/evaluation windows; preserve all current
thresholds. Run full/full/prefix with identical source and settings, compare
actual DecisionLogs, and report eligible/blocked snapshots, coverage,
abstention reasons, hypotheses and stable CHoCH counts. At least 12 comparable
evaluation M5 bars and full required coverage are needed for the existing
coverage gate. Derived M5 remains internal aggregation even at 100% coverage.
No profitability or real-terminal validation is claimed by this milestone.

## Local verification

The complete suite passed on Python 3.11.9 (521 tests, 36.060 seconds) and
Python 3.12.14 (521 tests, 20.969 seconds). This includes all 512 inherited
tests and nine new source-review/comparison regressions. No live provider
or MT5 terminal was used. Final Linux/Windows CI results are recorded in
the draft PR and its linked Actions run.
