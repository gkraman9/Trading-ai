# Offline blinded chart-reading benchmark v1

This small benchmark compares reviewer chart interpretations with **frozen IAT
assessments**, not with a ground-truth market label. It does not evaluate trading,
returns, profitability or independent broker correctness. Strategy predicates,
adaptive ranking, confluence thresholds, and journal 5/15-minute first-breach
criteria are unchanged. Exness is BLOCKED; signal is WAIT; execution is disabled.

## Separate reviewer packets and the private answer key

`prepare_benchmark` first calls the existing manifest-gated journal dataset replay.
The original source, checksum, finality/closed-bar, calendar, quality, chronology
and M1/M5 consistency/coverage gates remain mandatory. A caller cannot supply a
historical label as a substitute for evidence. Blocked inputs produce no packets.
The manifest is loaded again and its metadata compared to detect changes after
preflight. Selected timestamps must be evaluated M1 closes inside the declared
evaluation window with eligible data; unavailable or blocked snapshots reject
preparation. UNKNOWN interpretations may still be reviewed when data is eligible.

Prepare one to 32 timestamps and one to 16 pseudonymous reviewers, selected
before reviewing IAT results. The roster is frozen in the private key. Packets
contain the same available closed history used by IAT, bounded by the existing
5,000-row-per-frame dataset limit. Each M1/M5 candle opening and OHLC is visible,
with a content-derived candle ID. A candle is included only when opening plus
its timeframe is at or before the selected UTC timestamp. Thus at 08:23 UTC the
08:20–08:25 M5 bar is absent. Both static SVG charts and exact JSON are supplied;
hover a candle for its UTC opening, OHLC and ID. There are no external assets,
network calls, JavaScript, computed IAT indicators or embedded hidden answers.

Packet identity depends only on its visible candles and fixed public protocol,
not on whole-dataset hashes, later candles, future journal outcomes, roster or
IAT labels. Appending eligible future bars leaves an earlier packet and chart
byte-for-byte unchanged. Source and configuration hashes stay in the private key.

The preparation directory contains:

- `reviewer-packets/`: public packet JSON, static HTML charts, and empty annotation
  templates for the roster. Share only this directory with reviewers.
- `private/bundle.json`: the complete journal, original assessments, bindings,
  manifest metadata and policy/configuration hashes. Never give this to reviewers.
- `private/receipts/`: immutable recorded annotations, kept away from other reviewers.
- `COMPLETE.json`: created last. Treat preparation as successful only when present.

Use separate reviewer/operator access permissions. Directory naming is not an OS
access-control boundary. The tool enforces submission-before-reveal for the frozen
roster, but cannot stop an operator inspecting the answer key, a reviewer using
external charts, or people sharing answers. Hashes detect edits against recorded
content; they are not signatures or externally timestamped proof of independence.
No blinding or independence certification is claimed.

## Annotation v1

Every annotation has an explicit version, packet ID and hash, pseudonymous
reviewer ID, and kind (`SYNTHETIC_FIXTURE` or `INDEPENDENT_ANALYST`). The reviewer
must actively set `blinded_attestation=true` after recording their own view;
actual independent annotations additionally require `independence_attestation`.
Empty templates do not qualify as submitted annotations. Synthetic packets cannot
be relabeled as actual independent-analyst evidence.

Required fields are:

- Regime: TREND_UP, TREND_DOWN, RANGE, TRANSITION or UNKNOWN.
- Key levels: support/resistance/other, positive finite price, timeframe, visible
  candle references and rationale. These are retained for manual review; v1 does
  not invent a numeric level-match tolerance.
- Supporting and conflicting observations: category, timeframe, direction,
  visible candle IDs and free-text explanation. Categories are STRUCTURE,
  TRANSITION, CANDLE, SUPPORT_RESISTANCE, SUPPLY_DEMAND, LIQUIDITY, MOMENTUM and
  VOLATILITY. Directions are BULLISH/BEARISH/NEUTRAL.
- All three plausible scenarios: LEADING, PLAUSIBLE, UNLIKELY or UNKNOWN,
  assumptions and invalidation conditions. Multiple LEADING scenarios are allowed.
- Uncertainty: LOW/MODERATE/HIGH/UNKNOWN, explicit reason flags, and explanation.
- What new evidence would change the view. Unknowns can be stated explicitly.

The strict validator rejects unknown fields/versions, future or wrong-frame
candle references, non-finite prices, invalid enums, wrong packet hashes and
missing attestations. Record once per reviewer/packet. Existing receipts are
never overwritten; a revised study needs a new batch rather than replacing the
original. All reviewers' annotations are retained independently, without voting
away disagreement or selecting a convenient consensus.

## Agreement definitions and denominators

Reveal requires exactly one valid receipt for every packet/roster member. Missing,
duplicate, altered, foreign or extra receipts reject the reveal before publishing
an answer report. Original IAT assessments and their hashes are copied unchanged.

Regime agreement is exact label agreement per reviewer/packet, with an explicit
annotation denominator, UNKNOWN count, known-regime denominator and confusion
counts. Scenario-leader set agreement preserves ties. Pairwise reviewer regime
disagreements have their own pair denominator. A reviewer is not ground truth.

Evidence agreement uses **coarse** sets of category/timeframe/direction, separately
for supporting and conflicting roles. IAT's support/opposition comes from the
union across its original leading scenarios, retaining both roles in a tie.
RANGING is mapped to NEUTRAL. Each comparison retains shared, reviewer-only and
IAT-only tokens, IAT leader basis, intersection/union counts and empty-union counts.
Summary denominators count annotation pairs and nonempty unions, plus pooled
shared/union tokens. Empty unions are not scored as perfect agreement. This
measures coded overlap, not identical pivots/events/levels, explanation quality,
or truth of the interpretation. Human candle references and prose remain visible
for review of representative disagreements.

Uncertainty is compared separately through versioned flags:

| Flag | Frozen IAT interpretation |
| --- | --- |
| DATA_LIMITATION | Status is not READY or uncertainty includes INCOMPLETE/INSUFFICIENT |
| STRUCTURE_CONFLICT | TRANSITION regime or an explicit conflict |
| SCENARIO_TIE | Multiple original leading scenarios |
| HIGH_VOLATILITY | Original overall volatility is HIGH |
| NO_SUITABLE_STRATEGY | Existing NO_SUITABLE_STRATEGY_CANDIDATE reason |
| EXPERIMENTAL_METHOD | Always present: unvalidated research methodology |

Report exact flag-set agreement and per-flag presence agreement with denominators.
IAT has no calibrated confidence scale: reviewer confidence levels are preserved
but explicitly NOT_COMPARABLE_NO_IAT_CONFIDENCE_SCALE. They are not converted
into made-up IAT probabilities. Representative disagreements are the first ten
in deterministic packet/reviewer order, with the full comparisons retained.

The original journal's separate 5/15-minute price-outcome records are returned
under `price_outcome_reviews_separate`, alongside the explicit outcome observation
cutoff. They do not alter annotations or agreement metrics. They remain outcomes
under the existing first-breach criteria, including incomplete/unresolved reviews.

## Private commands

Use Python 3.11 or 3.12 from the checked-out feature branch. Example PowerShell
commands from the repository root (replace the illustrative dates with reviewed
manifest dates). No MT5 or credentials are involved.

```powershell
python diagnostics/chart_benchmark.py prepare `
  --manifest 'E:\IAT2\private-data\manifest.json' `
  --at '2026-11-12T08:23:00Z' `
  --reviewer analyst-a --reviewer analyst-b `
  --output-directory 'E:\IAT2\private-evidence\review-batch-001'
```

Share only `reviewer-packets`. Have each reviewer edit their own template without
seeing IAT, later candles, outcomes or another reviewer's annotation. Return the
completed files privately to the operator. Then record each file:

```powershell
python diagnostics/chart_benchmark.py record `
  --private-bundle 'E:\IAT2\private-evidence\review-batch-001\private\bundle.json' `
  --annotation 'E:\IAT2\private-evidence\returned-analyst-a.json' `
  --receipts-directory 'E:\IAT2\private-evidence\review-batch-001\private\receipts'
```

After both roster members have submitted every packet:

```powershell
python diagnostics/chart_benchmark.py reveal `
  --private-bundle 'E:\IAT2\private-evidence\review-batch-001\private\bundle.json' `
  --receipts-directory 'E:\IAT2\private-evidence\review-batch-001\private\receipts' `
  --report-path 'E:\IAT2\private-evidence\review-batch-001\private\comparison.json'
```

Exit 0 means the requested workflow step completed; 3 means blocked/invalid.
No-overwrite atomic publication prevents partial success JSON. Interrupted
preparation can leave partial directories, but no COMPLETE marker. Do not reuse
these directories as completed batches. Keep raw datasets, private keys, real
annotations and full journals outside Git. CLI output contains fixed status text,
never exception strings or annotation prose. The Python API can accept existing
typed configurations for controlled synthetic regression; CLI uses unchanged
production defaults, and all configuration hashes are frozen in the private key.

## Worked synthetic review packet and results

[Static dual-frame chart](research_audits/chart-review-synthetic-v1/packet.html),
[exact candle packet](research_audits/chart-review-synthetic-v1/packet.json),
and [audit](research_audits/chart-review-synthetic-v1/audit.json) are deliberately
synthetic. No independent human analysts supplied these annotations; the two
example annotations are software fixtures, not evidence of analyst agreement.

The selected close is **2026-11-12 08:23 UTC**. The packet has 23 M1 candles,
ending with the 08:22 opening, and 21 M5 candles, ending with the 08:15 opening.
The unfinished 08:20 M5 bar and every later candle are absent. Only after both
synthetic annotations are recorded does the worked reveal show the frozen IAT
TRANSITION regime and unique BEARISH leader, including fresh opposing M1 CHoCH.

Synthetic reviewer A labels TREND_UP; B labels TRANSITION. Both retain tied
BULLISH/BEARISH plausible leaders rather than the unique IAT leader. The workflow
reports **1/2** exact regime agreements and one disagreement out of one reviewer
pair. Coded supporting-evidence intersection/union is **0/8** across the two
annotations; conflicting-evidence overlap is **2/2**. This illustrates that matching
a regime does not establish agreement about the supporting observation. Exact
uncertainty flag-set agreement is **0/2**, while STRUCTURE_CONFLICT presence agrees
in **2/2**. High reviewer confidence/uncertainty labels are not mapped to invented
IAT confidence. Both later 5/15-minute first-breach reviews happen to be SUPPORTED
in this fixture; those are reported separately and never used to grade reviewers.

Full/full preparation and comparison repeatability passed. The 08:23 packet and
HTML from a dataset ending at 08:25 are identical to those from the full archive
ending at 08:45. Invariance applies when both archives pass preflight: a later
archive defect still rejects that archive rather than bypassing its gates.

Independent analyst agreement remains **UNMEASURED**, with metrics `null`.
Historical validation stays **PENDING**, historical comparisons **NOT_RUN**.
No eligible permitted export or actual blinded annotations were supplied for this
milestone. Next evidence needed: an eligible export passing existing provenance,
calendar/finality and coverage gates, preselected timestamps/roster, and actual
independently recorded blinded annotations. Small operator-selected samples and
coarse coded overlap cannot establish general chart-reading accuracy.
