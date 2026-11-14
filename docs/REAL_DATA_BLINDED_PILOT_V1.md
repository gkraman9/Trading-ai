# Real-Data Blinded Chart Review Pilot v1

This is an offline reasoning-review workflow, not execution, prediction accuracy
or profitability measurement. All existing strategy predicates, adaptive rankings,
confluence thresholds and 5/15-minute first-breach rules remain unchanged. Exness
is BLOCKED; signal is WAIT; execution_allowed is false, including when a human's
research opinion says TRADE. No broker credentials, login, terminal or orders are used.

## Historical qualification is a human decision

`iat.pilot_qualification.qualify_historical` never creates an approval. Real
registration requires an explicitly supplied, independent human qualification
record **and** the existing manifest v2, source/evidence, checksum, calendar,
finality, chronology, duplicate/gap, OHLC and M1/M5 consistency/coverage checks.
A historical label, VERIFIED manifest fields, or the old private pilot alone
cannot start this pilot. Missing evidence yields DATA_NOT_QUALIFIED, no plan,
no charts, no IAT replay and no substitution of synthetic data. Manifest paths
are local; the tool does not fetch provider documents or authenticate accounts.

Use the existing [source review](SOURCE_QUALIFICATION_REVIEW.md),
[manifest/journal evaluation](JOURNAL_DATASET_EVALUATION.md) and session v2
contracts. A real source needs a dated calendar with non-synthetic provenance
covering the **entire** declared interval, including warm-up and exceptions.
Derived M5 remains INTERNAL_AGGREGATION_ONLY; it is not independent same-feed
native-bar corroboration. Existing historical minimum coverage is preserved.

The private qualification record has this strict structure:

- qualification_version: integer 1; dataset_id: SHA-256 of loaded dataset metadata;
  interval: exactly the manifest UTC range (warm-up included).
- provider_entity, feed_id, instrument (XAUUSD), price_basis. Feed and basis must
  match manifest v2 lineage, not an assumed broker convention.
- reviewer_code: a private pseudonym; independent_review_attested: true;
  reviewed_at_utc: UTC, no earlier than source retrieval.
- decision: APPROVED, PENDING or REJECTED. Only a human-supplied APPROVED passes.
- evidence: exactly usage, provenance, instrument, timestamp, price_basis, calendar
  and finality. Each has status VERIFIED/PENDING; a local `file`, SHA-256,
  reference, interval `scope` equal to the full dataset range, and explanation.
- sha256: canonical content hash excluding sha256, using the existing `digest`
  helper. Relative evidence files must remain inside the review record directory.

Every referenced evidence file is read-only and checksum-verified; missing,
changed, unsafe-path, wrong-scope or pending evidence rejects the gate. The
record must bind the exact dataset metadata (manifest, frame/calendar/raw hashes,
source and windows). No command changes PENDING to APPROVED for an operator.

The successful gate status is HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED, **not**
software certification of the provider. The software cannot authenticate an
unsigned human attestation or infer legal permission, document authenticity,
finality, session exceptions or independence from arbitrary document bytes.
A competent independent person must actually review the evidence. Hashes preserve
what was reviewed; they do not prove the review truthful. All such evidence and
identity mappings remain private. There is no real approved record in this PR.

## Register the sample before reading IAT

`register` performs technical qualification and locks `private/plan.json` before
calling any analytical replay. It creates a fresh directory and refuses overwrite.
The plan binds dataset/qualification/configuration hashes, full source interval,
reviewer roster, sampling, regime goals, blinding and versioned metrics.
`packets` is a separate step: it rechecks the exact source and human qualification
record before IAT replay. Changed datasets or configurations require a new plan.

The sampling spec contains pilot_id, revision, parent_plan_sha256, sampling,
regime_coverage_goals and reviewer_codes. Sampling is **FIXED_UTC_GRID** with
start_utc/end_utc, positive integer step_minutes, and an explicit
predeclared_without_iat_or_outcome_access attestation. Every grid point is retained;
it must be an evaluated, eligible M1 close. No selection by IAT predictions,
regime labels, human results or future prices is implemented. No silent replacement
of blocked timestamps is allowed. At least two distinct reviewers must annotate
every packet. All five regime goals are recorded before replay; unmet goals are
reported after reveal and do not trigger resampling or strategy adjustment.

Warm-up must be explicitly declared for both frames. At registration its actual
closed-candle counts must satisfy the largest unchanged context/intelligence
lookback (ATR, range, momentum and pivot confirmation windows). This ensures
indicator history; it does not guarantee that a directional regime can be known.
UNKNOWN/UNCERTAIN assessments remain visible. Each packet contains all available
closed history used by IAT, under the existing 5,000-row-per-frame input bound.

For changes after results, create a **new revision** with the previous plan hash
as parent (revision 1 uses null). Existing plans, packets and receipts cannot be
overwritten by these commands. Keep both revisions and explain the change.
Unsigned local hashes and time-only selection cannot prove that an operator never
looked elsewhere before registering; use independent preregistration/oversight
if that assurance is required. No population-representative sampling is claimed.

## Blinding, annotation v2 and reveal

Reviewer packets reuse PR #19's static charts and JSON. They contain symbol,
frame labels, UTC interval openings, cutoff, OHLC, anonymous packet IDs and
reproducible hashes. Only candles closed by the cutoff are included. No future
bars, candidate pivots, future-confirmed swings, zones, indicators or IAT labels
are in reviewer files. The private event record uses the existing causal Phase 7
and context functions at exactly that cutoff, including confirmed BOS/CHoCH and
OHLC liquidity sweeps. Prefix tests cover both packets and private event records.

Share only the assigned charts/JSON and that reviewer's individual empty template.
Templates and roster stay private until individually distributed. Keep all other
reviews, IAT answers, source timestamps beyond the cutoff and price outcomes away
from reviewers. Folder names are not access permissions: use separate operator
and reviewer access. Human blinding and independence require oversight; no local
program can prevent outside charts or collusion.

Annotation v2 preserves v1's candle references, support/conflict observations,
scenarios/ties, uncertainty flags and what would change the view, and adds:

- Regime TREND_UP, TREND_DOWN, RANGE, TRANSITION or UNCERTAIN.
- Directional bias BULLISH, BEARISH, NEUTRAL or UNCERTAIN.
- Key levels including SUPPORT/RESISTANCE/SUPPLY/DEMAND/OTHER and rationale.
- Structure events HH_HL, LH_LL, BOS_UP/DOWN, CHOCH_UP/DOWN, and
  LIQUIDITY_SWEEP_UP/DOWN, each anchored to visible candles and timeframe.
- Confidence LOW/MEDIUM/HIGH/UNCERTAIN, separate from uncertainty reason flags.
- Best research decision TRADE/WAIT/UNCERTAIN and reasoning. This never changes
  IAT's WAIT execution contract.

Actual reviewers set blinded_attestation and independence_attestation to true;
synthetic fixtures are labeled SYNTHETIC_FIXTURE and never become real reviews.
Templates are not submissions. Strict schemas reject unknown versions, malformed
fields, future/wrong-frame references, missing views or attestations. At most one
immutable receipt per assigned reviewer/packet is accepted. The v1 adapter maps
UNCERTAIN to UNKNOWN and SUPPLY/DEMAND to OTHER **only** for existing coarse
benchmark comparison; the complete v2 original remains private and unchanged.

Reveal requires every assigned receipt plus explicit `--authorize-reveal`.
Authorization is recorded against the plan and receipt-set hashes. Missing,
duplicate, altered or foreign receipts fail. No operator authorization can skip
the complete-roster gate. The original IAT assessments remain frozen; later
5/15-minute reviews stay in the private benchmark report, separate from agreement.

## Anonymous comparisons, not truth labels

The public export is a strict allowlist of coded observations and counts: no
reviewer codes/names, identity mappings, prose, provider paths, raw data or full
journals. Aliases R001, R002, etc. identify reviewers **within** a pilot. The
operator privately maps them to the roster. Real annotations and reasons remain
private for manual side-by-side reasoning review; do not publish them by default.

Report IAT-to-reviewer and reviewer-to-reviewer comparisons separately:

- Exact regime/bias labels count EXACT; an uncertain versus concrete label counts
  PARTIAL_UNCERTAIN; conflicting concrete labels count DISAGREEMENT. UNKNOWN and
  UNCERTAIN normalize to the same unknown interpretation. Denominators include
  uncertain cases, whose counts are also reported explicitly.
- IAT bias is its single original scenario leader, otherwise UNCERTAIN; this is a
  declared comparison convention, not a new prediction or ranking rule.
- Structure compares timeframe/event-category sets. Nonempty equal sets are EXACT,
  overlap is PARTIAL, disjoint sets DISAGREEMENT. Empty unions are UNMEASURED,
  never perfect agreement. Report intersections, unions and pair denominators.
  Events span all confirmed events in the visible history. Sweeps are OHLC proxies;
  UP/DOWN denotes penetration of highs/lows, not a forecast. Matching categories
  does not prove identical levels, times or causal reasoning.
- Supporting/conflicting evidence and uncertainty retain benchmark v1 metrics and
  explicit denominators. Reviewer-pair evidence overlaps are separate. Confidence
  levels are counted; no calibrated IAT confidence score is invented.
- Abstentions, WAIT opinions, uncertain decisions, tied scenarios and unmet regime
  goals remain visible. Reasons/prose are not given a fabricated semantic score.
  Representative disagreements are deterministic examples, not adjudicated errors.

SYNTHETIC_ONLY has only synthetic_workflow_metrics; independent agreement is
UNMEASURED and real_review_metrics is null. Real reports require explicit human
attestations and are labeled OPERATOR_ATTESTED_REAL_REVIEW, never certified truth.
Historical validation remains PENDING and comparisons NOT_RUN in this pilot.

## Windows operator procedure

Use the existing Python 3.11 environment in the checked-out feature branch; the
following uses `py -3.11`. From the user's existing project location:

```powershell
Set-Location 'E:\IAT2\Trading-ai-feat-iat2-windows-demo\Trading-ai-feat-iat2-windows-demo'
py -3.11 diagnostics/review_pilot.py qualify `
  --manifest 'E:\IAT2\private-data\manifest.json' `
  --qualification 'E:\IAT2\private-data\source-review\qualification.json' `
  --report-path 'E:\IAT2\private-evidence\qualification-001.json'
```

Directories must already exist except the fresh pilot batch directory below.
A missing/unqualified source returns exit 3 and DATA_NOT_QUALIFIED. **Stop here**
unless the independent human approval and technical checks have both passed.
The existing private pilot does not qualify. No credentials belong in any file.

Prepare a private sampling spec using the documented fields. A deliberately
synthetic example is [synthetic-spec.json](research_audits/real-review-pilot-synthetic-v1/synthetic-spec.json).
For a real pilot use its approved interval, planned timestamps, private reviewer
codes and predeclared goals, not the example's synthetic dates. Do not choose
these after looking at IAT labels or future returns. Then:

```powershell
py -3.11 diagnostics/review_pilot.py register `
  --manifest 'E:\IAT2\private-data\manifest.json' `
  --qualification 'E:\IAT2\private-data\source-review\qualification.json' `
  --spec 'E:\IAT2\private-evidence\pilot-spec.json' `
  --pilot-directory 'E:\IAT2\private-evidence\pilot-001'
py -3.11 diagnostics/review_pilot.py packets `
  --manifest 'E:\IAT2\private-data\manifest.json' `
  --qualification 'E:\IAT2\private-data\source-review\qualification.json' `
  --pilot-directory 'E:\IAT2\private-evidence\pilot-001'
```

The plan is locked before packet generation/replay. Distribute only the assigned
`reviewer-packets` files and the matching individual v2 template from `private`.
Require independent, blinded review without another reviewer's answers. Return
the completed annotation privately. For each reviewer/packet:

```powershell
py -3.11 diagnostics/review_pilot.py submit `
  --pilot-directory 'E:\IAT2\private-evidence\pilot-001' `
  --annotation 'E:\IAT2\private-evidence\returned-review.json'
```

After every reviewer has submitted every selected packet:

```powershell
py -3.11 diagnostics/review_pilot.py reveal `
  --pilot-directory 'E:\IAT2\private-evidence\pilot-001' `
  --authorize-reveal
```

Inspect `anonymous-report.json` for coded comparisons and denominators. Keep
`private/revealed.json`, original receipts, qualification documents, identity
mapping and full real-data journals private. Shared evidence contains no prose,
so reasoning disagreements need an authorized human to inspect the private
side-by-side annotations. Do not assume anonymized codes prevent reidentification
from independently known context; disclose reports only with reviewer consent.

Every command refuses overwrites. Publication uses existing atomic no-overwrite
writes. An interrupted packet run can leave partial files; only
PACKETS_COMPLETE.json marks a completed batch. Submission requires that marker.
The export is published only after successful, explicitly authorized review.
An export publication failure can leave an authorized private review but no public
report; that is not a completed export. Exit 0 means step complete, 3 means blocked.
No command downloads dependencies/scripts or data. Artifact reads are bounded to
64 MiB; use a small declared evaluation window with sufficient warm-up, not a bulk
archive. Large studies require separate performance and privacy review.

For synthetic verification use `register-synthetic` explicitly. It accepts only
SYNTHETIC_FIXTURE manifests and never enters the real qualification path.
The complete deterministic synthetic fixture is constructed in temporary folders
by the regression suite, including the CLI workflow:

```powershell
py -3.11 -m unittest discover -s tests -p test_review_pilot.py -v
py -3.11 -m unittest discover -s tests -v
```

## Actual synthetic audit and external blockers

The [audit](research_audits/real-review-pilot-synthetic-v1/audit.json),
[anonymous synthetic report](research_audits/real-review-pilot-synthetic-v1/anonymous-report.json),
[08:23 packet](research_audits/real-review-pilot-synthetic-v1/packet.json) and
[chart](research_audits/real-review-pilot-synthetic-v1/packet.html) are explicitly
SYNTHETIC_ONLY. Two software-fixture reviewers annotate two grid closes, 08:21
and 08:23 UTC on 2026-11-12. This yields four synthetic annotations and two
reviewer pairs; no actual independent humans reviewed these charts.

| Comparison | Denominator | Exact | Partial/uncertain | Disagreement |
| --- | ---: | ---: | ---: | ---: |
| IAT vs reviewer regime | 4 | 2 | 1 | 1 |
| IAT vs reviewer bias | 4 | 1 | 2 | 1 |
| Reviewer vs reviewer regime | 2 | 0 | 1 | 1 |
| Reviewer vs reviewer bias | 2 | 0 | 2 | 0 |
| IAT vs reviewer structure sets | 4 | 0 | 2 | 2 |

One synthetic review is uncertain about regime; two say WAIT and two express a
research TRADE opinion, while machine signal remains WAIT throughout. Structure
intersection/union counts are 2/18 for IAT/reviewer comparisons; these are coarse
category overlaps, not event accuracy. All annotation originals are unchanged.
Full/full bundle and export hashes agree. Truncated-prefix packets and confirmed
event records agree at both selected cutoffs. At 08:23, M1 ends at the 08:22
opening, M5 at 08:15: the unfinished 08:20 M5 is absent. The opposing fresh M1
CHoCH is only available in the private answer key after submission.

The available private archive remains **DATA_NOT_QUALIFIED**:
CANDLE_FINALITY_UNCERTAIN, EVIDENCE_CALENDAR_PENDING,
EVIDENCE_FINALITY_PENDING, HUMAN_QUALIFICATION_REVIEW_REQUIRED,
INDEPENDENT_REVIEW_PENDING and SESSION_CALENDAR_REQUIRED. Its real pilot did not
register or replay. Real human-review metrics are unmeasured, historical validation
PENDING and comparisons NOT_RUN.

To proceed, a provider/operator must supply an authorized export with an identified
legal provider entity and feed; exact XAUUSD instrument and price basis; permission
for this offline use plus upstream provenance; UTC opening timestamp conventions;
native M1/M5 or explicitly documented aggregation; capture completeness/closed-bar
finality for the selected dates; and a dated verified session/exception/holiday/
maintenance calendar spanning all warm-up and evaluation. Independently review the
source documents and bind them to a human approval record and exact file hashes.
Also supply at least two genuinely independent, consenting reviewers, a private
identity mapping, predeclared sample/roster and actual blinded annotations. Do not
reuse another broker's calendar to fill an unknown source schedule. Nothing in
this PR certifies Exness, OANDA or any real terminal.
