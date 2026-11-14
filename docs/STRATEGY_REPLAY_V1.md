# Strategy Replay Log v1

This milestone replays the two existing experimental strategies chronologically
without changing their rules, registry, confluence settings, API or DecisionLog
v1 contract. Strategy Replay Log v1 is a separate research artifact, not a
trading system, profitability test or historical-validation certificate.

## Causal entry point

`iat.intelligence.strategy_replay.replay_strategies` evaluates every supplied M1
bar's closing timestamp, selecting causal M1/M5 prefixes through the existing
`context_at` and quality gates. It does not fabricate a snapshot for a missing
M1 bar. Subsequent supplied snapshots expose the gap through existing gates.
Input M1 timestamps must be strictly increasing UTC; duplicate or backward
clocks are rejected. Visible histories are bounded by the existing 5,000-bar input
limit; an unavailable future tail does not consume the visibility budget. Full supplied warm-up history is retained; no rolling-window truncation
or window-relative evidence IDs determine setup identities.

An optional aware `as_of` stops replay at a visibility boundary. Unfinished M5
and future bars are excluded by existing causal selection. Appending future
bars cannot change earlier entries. A truncated-prefix run must keep the same
initial warm-up and analytical configuration; comparing only matching entry
prefixes is distinct from comparing final setup inventories at different dates.
The cutoff is not an analytical threshold and does not enter policy hashes.

No calendar means the inherited SESSION_NOT_CHECKED warning remains in every
applicable snapshot. Optional calendars/finality observations are enforced by
existing gates and fingerprinted in the log. Neither a research provenance label
nor a complete synthetic run qualifies a real historical source.

## Stable setup identity and re-arming

A setup ID is the SHA-256 of strategy ID, rule version, exact symbol, direction,
anchor kind and sorted unique canonical evidence references. Input list order,
M1 confirmation changes, contextual evidence revisions and snapshot timestamps
do not create a new setup. Logs are scoped to their configuration hashes;
identical IDs across different runs do not establish dataset equivalence.

| Strategy | Anchor | Expiry and re-arming |
| --- | --- | --- |
| M5 trend / M1 confirmation | Canonical confirmed-pivot references underlying the current same-direction M5 STRUCTURE observation | A distinct M5 pivot set supersedes the prior active setup. Loss of matching M5 trend expires it. Temporary missing M1 pattern/zone/confirmation does not expire it. A distinct anchor may qualify independently. |
| Sweep / M1 structure change | The canonical CONFIRMED_SWEEP event selected by the unchanged rule evaluator | Expires on the first valid snapshot strictly after sweep availability + five minutes. A newer selected sweep supersedes the old setup. A new CHoCH confirming the same sweep does not re-arm or increment its count. |

The existing strategy rules, including current candle/zone requirements and
opposing CHoCH/level-loss predicates, are documented in
[OFFLINE_RESEARCH_STRATEGIES.md](OFFLINE_RESEARCH_STRATEGIES.md).
They decide snapshot QUALIFIES/ABSTAINS/INVALIDATED outcomes unchanged.
Lifecycle policy version 1 interprets those outcomes separately:

- The first QUALIFIES for an anchor creates one qualified ACTIVE setup.
  Consecutive qualification records REPEATED_QUALIFICATION; the count stays one.
- INVALIDATED for the same ACTIVE qualified anchor closes it as INVALIDATED.
  This alone increments invalidated-qualified-setup counts.
- INVALIDATED without earlier qualification creates an
  UNQUALIFIED_INVALIDATED anchor record, with `qualified_at=null`. It never
  increments qualified or invalidated-qualified counts. The snapshot still
  counts as INVALIDATED in its own snapshot statistics.
- INVALIDATED and EXPIRED anchors are terminal. The same anchor cannot re-arm,
  even if a later snapshot again satisfies the rules or a prior M5 pivot set
  reappears. Such a snapshot remains QUALIFIES but emits ANCHOR_RETIRED_NO_REARM.
  Only a distinct canonical anchor can become a new qualified setup.
- ABSTAINS alone does not invalidate a setup. Known expiry/supersession rules
  can still close an active setup on a valid abstaining snapshot.
- Blocked quality yields a separate BLOCKED_DATA snapshot outcome, retaining
  the underlying rule result and diagnostics. It performs **no** qualification,
  invalidation, supersession or expiry transitions. A later valid snapshot may
  establish expiry at that timestamp; no transition time is invented inside the
  blocked interval. ACTIVE counts during blocking mean last-known unterminated
  setups, not currently eligible setups or positions.

Only the anchor selected by the current snapshot can be snapshot-invalidated.
If an older active anchor is superseded in that snapshot, it expires; an
invalidation of the new anchor is an unqualified invalidation. This avoids
attributing a new anchor's evidence to a previously qualified setup.
Unresolved/future anchors and configuration/provenance changes are rejected.
Rejected records do not partially advance the ledger. Ending a replay does not
expire open setups; otherwise prefix equivalence would be destroyed by the run
boundary. No orders, positions, stop prices or trade executions are modeled.

## Log contract and persistence

Each log records version/kind, symbol/provenance, registry and lifecycle policy
hashes, context/intelligence hashes, optional session/finality hashes,
chronological UTC entries, anchor references, rule evidence, source registry,
reason codes, quality diagnostics and lifecycle events. Final setup records
retain first qualification and terminal times. The summary separates timestamps,
four directional snapshots per timestamp, blocked timestamps, per-strategy and
direction snapshot outcomes/reasons, and unique qualified/active/invalidated/
expired setup counts. Unqualified invalidated anchors are counted separately.

Canonical JSON SHA-256 covers the log excluding its own `sha256` field.
`validate_strategy_replay_log` checks safety/version, hashes, chronology,
references and availability, snapshot accounting, setup identity, lifecycle
transitions and final state/summary consistency. A checksum detects changes;
it does not authenticate the source or establish capture completeness.

`write_strategy_replay_log(path, log)` validates before reserving a new path,
uses atomic replacement, and refuses to overwrite existing evidence. Failed
publication leaves an explicit INCOMPLETE placeholder that is not a valid log.
A full log contains source OHLC: keep it in a private directory outside GitHub
for any real dataset. The committed audit contains synthetic summary metadata
and hashes only. No new account, credential or provider access is performed.

```python
from iat.intelligence.strategy_replay import (
    replay_strategies, validate_strategy_replay_log, write_strategy_replay_log,
)

# Supply local data and an explicit permitted research provenance.
log = replay_strategies('XAUUSD', m1_rows, m5_rows,
                        provenance='SYNTHETIC_RESEARCH')  # synthetic inputs only
validate_strategy_replay_log(log)
write_strategy_replay_log(private_output_path, log)
```

For incremental observation-contract tests, `StrategyReplayLedger.record`
accepts typed existing ContextReports with fixed configuration and provenance.
It is not a bypass for raw-data validation or historical source qualification.
The chronological raw-OHLC entry point is `replay_strategies`.

## Actual synthetic replay results

The checked-in [synthetic audit](source_reviews/strategy-replay-synthetic-v1.json)
records exact input/configuration/log hashes and all four directional groups
for each of four independent procedural fixtures. All use explicitly synthetic
OHLC and the inherited small-window unit-test configurations. Production
analytical defaults remain unchanged. Counts below refer to each fixture's
intended strategy/direction, not to all four directional evaluations combined.

| Fixture / intended case | Timestamps | QUALIFIES | ABSTAINS | INVALIDATED | BLOCKED_DATA | Unique qualified | Invalidated qualified | Expired qualified |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Continuation bullish | 23 | 2 | 18 | 1 | 2 | 1 | 1 | 0 |
| Continuation bearish | 23 | 2 | 18 | 1 | 2 | 1 | 1 | 0 |
| Sweep reversal bearish | 30 | 2 | 26 | 0 | 2 | 1 | 0 | 1 |
| Sweep reversal bullish | 30 | 2 | 26 | 0 | 2 | 1 | 0 | 1 |

Together these are 106 timestamps / 424 directional snapshots, with eight
blocked timestamps (32 blocked directional snapshots). The fixture beginnings
have insufficient raw history, rather than hidden warm-up exclusions. The
other directional groups and their counts are included in the audit.
Two extra OHLC control cases remove the initial continuation confirmations:
each produces one INVALIDATED snapshot, zero qualified setups and zero
invalidated-qualified setups, in bullish and bearish directions respectively.

Each of the four main datasets was replayed twice: canonical full-log hashes
matched. Truncated-prefix and bounded-full-input logs matched exactly; their
22 continuation or 24 reversal entries also matched full-run overlapping
entries. Additional future M1/unfinished M5 append tests pass for both
strategies/directions. Observation-contract tests separately cover distinct
new anchors, re-arming refusal, transient blocked snapshots, configuration
changes and expiry boundaries. These software comparisons are explicitly
**synthetic**, not historical DecisionLog comparisons.

Historical validation remains **PENDING** and historical comparisons remain
**NOT_RUN** until an eligible export is replayed. Exness stays **BLOCKED**,
signal stays **WAIT**, execution_allowed stays **false**. DecisionLog v1,
strategy rule versions, registry hash and confluence defaults are unchanged.

## Verification and remaining limits

The complete suite passed on Python 3.11.9 (568 tests, 50.360 seconds) and
Python 3.12.14 (568 tests, 30.389 seconds): 545 inherited tests plus 23 new
replay/lifecycle tests. Final Linux/Windows CI results are recorded in the draft
PR. No MT5 terminal, broker credentials or independently sourced historical
export was used. The reference implementation recomputes full prefixes and
stores their source observations; large histories incur substantial time and
memory costs. Throughput optimization and historical validation are separate
milestones and must preserve causal/log equivalence.
