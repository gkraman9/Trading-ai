# Stage B: offline strategy research and blocked qualification

Base: PR #37, `389fa1b415df68b3d162a2f9ba1a1e270aef1794`.
This adds research specifications and a simulator. **Stage-B acceptance is BLOCKED**:
no independently eligible execution-price dataset or qualified candidate exists.
Stages C and D are BLOCKED_NOT_STARTED. There is no broker adapter, activation,
network request, credential access or order call in this package. Stage A and the
read-only observer, commentary providers, APIs, calendars and execution gates
are unchanged. Public reports retain WAIT, execution_allowed=false, Exness
BLOCKED, historical validation PENDING and historical comparisons NOT_RUN.

## Versioned policies and unchanged observations

`config/research/stage-b-protocol-v1.json` freezes the policies and analysis
thresholds before any qualified OOS run. Its code hash is reproducible; this is
not an independently timestamped preregistration or provider certification.
Both underlying registry entries remain EXPERIMENTAL_SYNTHETIC_ONLY.

| Research policy | BUY prerequisites | SELL prerequisites |
| --- | --- | --- |
| M5_TREND_M1_CONFIRMATION | Existing bullish M5/M1 structures, current bullish M1 pattern and nearby directional zone; no fresh opposing CHoCH | Existing bearish equivalents |
| SWEEP_M1_STRUCTURE_CHANGE | Existing confirmed LOWS sweep, subsequent fresh bullish CLOSE-policy M1 CHoCH, current bullish pattern/zone | Existing HIGHS sweep and bearish equivalents |

The original five-minute sweep window, structural eligibility, opposing CHoCH
invalidation and canonical setup lifecycle are reused without changing their
predicates or confluence thresholds. M5 structure must be established for the
reversal; agreement is not required. Decisions consume the original causal
context at each M1 close. Unfinished M5 candles and unconfirmed/future pivots are
unavailable. Warm-up initializes the original ledger; evaluation starts flat,
without retrospectively opening warm-up positions.

Additional **unvalidated IAT research choices**, specification
`stage-b-research-1.0.0`, apply separately:

- Existing M1 relative volatility must be in [0.67, 1.5]. Unknown blocks.
- Entry uses the first close/open-permitted quote strictly after the decision,
  within two seconds. BUY pays ask; SELL receives bid. Declared adverse slippage
  is applied. A quote at the decision timestamp cannot fill that decision.
- BUY stop: latest available confirmed M1 LOW, or lower swept level for reversal,
  less one tick. SELL uses HIGH/higher swept level plus one tick. Round outward
  to the declared tick grid; reject invalid geometry and minimum-distance failure.
- Target is 2R from the actual simulated entry, rounded away from entry. R uses
  the initial entry-to-stop price distance; realized R is gross P&L divided by
  that distance times contract size and 0.01 volume. Costs are reported separately.
- Stop crossing uses the observed worse executable price plus adverse slippage;
  target crossing gets the target limit, never an optimistic gap bonus. SELL
  exits pay ask; BUY exits receive bid. Broker queue/latency are not proven.
- Original qualified-anchor invalidation or expiry requests an exit at the next
  permitted quote strictly after the evidence. Retirement IDs only affect their
  own setup, not another concurrently observed anchor. Maximum hold is 15 minutes;
  close-session uncertainty is unresolved rather than an invented fill.
- Setup identity binds feed, policy hash and original canonical setup ID. Once
  opened, the same anchor cannot rearm. A distinct original anchor is required.
- Fixed 0.01 lot, one position, five openings per UTC day. Admission reserves
  planned loss, both legs' costs, slippage and known rollover costs against 1%
  daily equity. A breached loss limit latches for that UTC day. Gaps may exceed
  planned risk; this is not a guarantee that realized loss stays under 1%.

HH/HL/LH/LL, BOS/CHoCH, confirmed pivots, zones, liquidity and existing relative
volatility/momentum observations supply the research evidence. Existing ATR-like
observations are not independently validated execution indicators. VWAP, ADX and
SuperTrend are not added: there is no source-qualified evidence justifying more
indicators, and changing observation or confluence rules would confound this run.

## Data gate and actual source review

`run_study()` accepts paths, never a desired qualification or approval boolean.
It first invokes the existing `qualify_historical()` loader, manifest v2,
checksums, source, usage, UTC, dated session/calendar, native/derived M5, finality,
M1/M5 coverage and independent human-review requirements. A provenance string
cannot bypass those checks. Human signatures/identity remain documented
attestations, not cryptographic provider authentication; independent reviewers
must actually inspect the documents and authority.

The existing private May 25, 2021 pilot has 240 M1 / 48 M5 bars. M5 is derived
from M1: **internal aggregation only**. Its publisher identifies XAUUSD/Bid and
CC-BY-4.0, but underlying provider/feed identity, dated sessions, capture
completeness/finality and independent approval remain unresolved. The gate
returned DATA_NOT_QUALIFIED, including CANDLE_FINALITY_UNCERTAIN,
EVIDENCE_CALENDAR_PENDING, EVIDENCE_FINALITY_PENDING,
HUMAN_QUALIFICATION_REVIEW_REQUIRED, INDEPENDENT_REVIEW_PENDING and
SESSION_CALENDAR_REQUIRED. The truncated pilot also fails evaluation coverage.
This is reuse of the documented source review, not a new authentication claim.

`docs/source_reviews/stage-b-source-readiness-v1.json` records the actual
metadata-only gate outputs, coverage and hashes. Raw files, prices, private
paths and full real-data journals are not published. No broker-authorized native
M1/M5 export, same-feed complete bid/ask quote tape, dated cost/symbol evidence,
preregistered window plan or independent reproduction was supplied. Other
operator exports have not been inspected or assumed to have native M1 pairs.
**Historical trade counts and performance are null/unmeasured, not zero; actual
historical full/full/prefix and performance comparisons are NOT_RUN.**

## Quote and cost evidence contracts

Execution research additionally needs ordered, complete, same-feed observed
bid/ask quotes. CSV columns are exactly `timestamp,bid,ask`, UTF-8 (optional BOM),
UTC-aware observation timestamps and positive decimal strings, bid <= ask.
Duplicate timestamps are rejected because this v1 has no verified within-timestamp
sequence contract. Source SHA-256 is streamed before and after inspection; no
normalization repair, imputation or silent truncation. At most 1,000,000 quotes
are retained in memory. Original candle-loader limits remain 4 MiB/file and
5,000 bars/frame. Longitudinal sharding to reach qualification sample requirements
is **not implemented/independently validated**; do not lower thresholds to force
qualification on a small window.

Quote manifest v1 exact keys:

```
version symbol feed_id timestamp_convention price_basis interval file sha256
preparer_code reviewer_code reviewed_at_utc costs_config_sha256 evidence
```

Use XAUUSD, OBSERVATION_UTC, BID_ASK. `interval` has start/end matching the candle
manifest's entire UTC range, including warm-up. Quote coverage must span it.
`preparer_code` and `reviewer_code` are distinct opaque nonempty codes, never
account IDs. `evidence` requires all of usage, source_feed, timestamp, price_basis,
dated_calendar, capture_completeness, finality_corrections and costs_symbol.
Each has exact keys `status,file,sha256,reference,interval`; VERIFIED is a human
review claim with a nonempty checksummed local document covering the full range.
Do not create VERIFIED declarations for missing evidence. Relative document/file
paths resolve beside the manifest under the existing safe-path rules.

The quote-derived M1 OHLC must match the declared candle price basis within 1e-8;
M5 consistency retains its native-versus-aggregated label. Matching OHLC does not
prove tick completeness, feed authenticity or intrabar event order by itself.

Costs JSON exact keys (all numeric monetary/price quantities are decimal strings):

```
initial_equity currency contract_size tick_size minimum_stop_distance
volume_min volume_step max_spread slippage_ticks commission_per_side_per_lot
fee_per_side_per_lot rollovers evidence_sha256 known_at currency_quantum
money_rounding spread_stress_multiplier
```

`slippage_ticks` is an integer. `rollovers` is a sorted array of exact
`timestamp,announced_at,long_per_lot,short_per_lot` objects; signed amounts are
cashflow per lot, with negative swap debited. Known-at UTC must precede decisions;
future rollover charges must have been announced before entry. Empty rollover
arrays require reviewed evidence that no rollover applies over the interval,
not an assumption of zero swap. The baseline spread_stress_multiplier is exactly
"1". Currency is USD only; other currencies fail closed pending conversion data.
Declare currency_quantum (e.g. "0.01") and ROUND_HALF_EVEN or ROUND_HALF_UP from
reviewed terms; commission and fee components round per leg independently.
Use the actual dated evidence, not these examples, as parameter authority.
`evidence_sha256` binds the costs_symbol document; the quote reviewer separately
binds the exact costs JSON bytes through costs_config_sha256.

An overnight position needs an exact UTC-midnight observed quote for opening
equity; missing marks make the run inconclusive. Coincident rollover and quote
barrier events have unresolved event order, even if a deterministic audit order
is used. Blocked evidence, unknown exit permissions, stale final marks, unfinished
entry horizons and open positions at cutoff remain explicit unresolved cases.
There is no forced terminal liquidation. OHLC-only simultaneous stop/target touch
is unresolved, never arbitrarily declared a win.

## Evaluation protocol and registry

Validation plan v1 exact keys: `version,registered_protocol_sha256,in_sample,
out_of_sample,walk_forward`. Each interval is start/end UTC; each fold has train
and test intervals. IS must end before or at OOS start; every train ends before
its test begins; test folds cannot overlap. All intervals must lie inside the
manifest evaluation interval. Decisions use prior warm-up context, but each
performance subwindow starts flat with the same declared paper equity. These
are explicitly separate fixed-policy studies, not one continuous account track.
No parameters are trained or chosen from OOS or walk-forward tests.

Frozen research criteria: at least 300 closed trades across 60 exit UTC days;
OOS at least 100 across 30 days; >=3 walk-forward test folds, each >=30 trades;
positive net expectancy, PF >=1.2, maximum observed equity drawdown <=10%, positive
95% day-cluster-bootstrap expectancy lower bound. Every test fold must meet
performance/uncertainty checks, so its 30-day bootstrap requirement still applies.
Bootstrap uses 1,000 resampled UTC exit-day blocks with seed 1729, only when >=30
blocks exist. This is a research uncertainty heuristic, not proof of IID returns
or a probability of future profit. No-loss PF has no finite denominator and
cannot silently pass as infinity; insufficient samples remain inconclusive.

All 12 OOS sensitivity runs are reported, with no best-parameter selection:
commission/fee/slippage multipliers 1/1.5/2, spread-cost multipliers 1/1.5/2,
RR 1.5/2/2.5 and holding horizon 10/15/20 minutes. Each needs resolved outcomes
and positive expectancy. Spread stress widens modeled ask adversely on the tick
grid while preserving original quote bytes/IDs; it is labeled
SPREAD_COST_MODEL_NOT_OBSERVED_QUOTES, not a new historical market tape.

Metrics separate closed/open counts, win rate, PF denominator status, expectancy,
gross/net P&L, drawdown, average win/loss, gross realized R, consecutive losses,
UTC exit-day, regime, volatility and verified entry/exit permission phases.
Geographic sessions are not invented. Missing historical runs have null metrics.

Registry states: EXPERIMENTAL, DATA_NOT_QUALIFIED, BACKTEST_INCONCLUSIVE,
BACKTEST_FAILED, BACKTEST_QUALIFIED. A qualified state additionally requires an
independent file-bound reproduction review v1 with exact keys
`version,preparer_code,reviewer_code,reviewed_at_utc,run,validation`. Run/validation
each has relative `file,sha256` binding JSON identical to recomputed results.
Different reviewer/preparer codes attest independence; code cannot authenticate
who signed. The CLI never creates approvals. Serialized studies with runs are
recomputed from their original files during validation, preventing a status or
metric edit plus rechecksum from establishing qualification. BACKTEST_QUALIFIED
would allow Stage-C **review only**, never broker activation. Original strategy
registry and Stage-A execution readiness are not promoted by this package.

## Windows 10 / Python 3.11

Keep terminals and trading permissions unchanged. No MT5 or AI package is needed
for this CLI. Use reviewed local files outside Git. Run from the existing clone:

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
git fetch origin feat/iat-v3-strategy-qualification
git switch --no-track -c local/iat-stage-b origin/feat/iat-v3-strategy-qualification
py -3.11 -m pip install -r requirements.txt
$private = Read-Host 'Private evidence directory outside the Git checkout'
$report = Join-Path $private ('stage-b-' + [Guid]::NewGuid().ToString('N') + '.json')
py -3.11 diagnostics/strategy_qualification.py --report-path $report
```

The last command intentionally exits 3 with BLOCKED and null metrics. After actual
independent evidence preparation, use the existing manifest/human-review schema:

```powershell
$report = Join-Path $private ('stage-b-' + [Guid]::NewGuid().ToString('N') + '.json')
py -3.11 diagnostics/strategy_qualification.py `
  --manifest (Join-Path $private 'manifest.json') `
  --review (Join-Path $private 'independent-qualification.json') `
  --quote-manifest (Join-Path $private 'quotes-manifest.json') `
  --costs (Join-Path $private 'reviewed-costs.json') `
  --validation-plan (Join-Path $private 'registered-validation-plan.json') `
  --report-path $report
Get-Content -LiteralPath $report -Raw | ConvertFrom-Json | Select-Object status, reason_codes, acceptance, later_stages
Get-FileHash -LiteralPath $report -Algorithm SHA256
```

After another reviewer actually reproduces matching runs, the optional
`--continuation-reproduction-review` / `--sweep-reproduction-review` paths bind
that evidence. Do not fabricate files merely to satisfy a schema. Full private
reports contain local file references and trade audits; do not publish them.
Exit 0 means research thresholds/reproduction passed, 3 means blocked or
inconclusive, 1 means failure. Use a new report path for every invocation.
Atomic publication reserves FAIL/RUN_INCOMPLETE before work; a crash cannot leave
a success report. Original input files are read-only and exact hashes are checked.
If the fetch creates a tag-like ref instead of a branch, inspect
`git rev-parse origin/feat/iat-v3-strategy-qualification` and use the verified PR
head SHA with `git switch --no-track -c local/iat-stage-b <head-SHA>`.

Tests (offline mocks and explicitly synthetic fixtures only):

```powershell
py -3.11 -m unittest discover -s tests -p test_strategy_qualification.py -v
py -3.11 -m unittest discover -s tests -v
py -3.12 -m unittest discover -s tests -v
```

The committed synthetic contract example exercises BUY/SELL fills for both
policy identities; it is not proof that underlying OHLC rules produce profitable
trades. Separate typed-observation and original OHLC fixtures exercise the causal
observation-to-decision path, warm-up, unfinished M5 exclusion and abstention.
The original rules/thresholds remain fixed even when every snapshot abstains.

## Remaining acceptance barriers

Obtain independently reviewed provider-authorized candle and bid/ask exports,
dated quote/open/close calendars, completeness/correction/finality evidence,
cost/symbol terms and a sufficient longitudinal evaluation plan; address bounded
loader/sharding limitations without weakening gates; reproduce the actual study
with an independent reviewer. Only then can Stage-B acceptance be assessed.
Stage C still needs a separately proven atomic demo-account-bound transport and
observer/executor isolation. Stage D remains unavailable until B/C acceptance.
No C/D PR or operational adapter is created from a blocked research result.
