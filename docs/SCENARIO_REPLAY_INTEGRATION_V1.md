# Historical Replay Integration & Evidence Validation v1

Offline software research only. No trading endpoint, broker connection, signal
selection, calendar change, source approval, strategy change or profitability
calculation is introduced. Historical validation remains PENDING; historical
comparisons remain NOT_RUN in both modes, including technically completed runs.

## Contracts and boundaries

`iat.scenario_replay.run_scenario_replay` accepts an existing local replay manifest
**v2**, optional existing human qualification review, typed ContextConfig and
IntelligenceConfig, an optional UTC cutoff and an optional ordered list of M1
close observation times. Defaults are unchanged upstream configurations. V1
manifests cannot provide the explicit lineage and evaluation metadata needed here
and are blocked, rather than upgraded or guessed. No provider-specific importer
or finality adapter is added.

The existing `load_dataset`, `dataset_preflight` and `qualify_historical` contracts
remain unchanged. Evidence manifests/source-review registries are not replay
manifests and cannot bypass those gates. The existing loader still limits each
file to 4 MiB and each timeframe to 5,000 rows. Full audit JSON is bounded to
32 MiB. This is a bounded reference implementation, not a large-archive engine.

Two explicit modes are supported:

* SYNTHETIC_RESEARCH requires a SYNTHETIC_FIXTURE manifest and known feed, price
  basis, UTC interval-opening convention and M5 origin. Synthetic observed finality
  must be declared. No synthetic declaration qualifies historical data.
* EXTERNAL_UNQUALIFIED_RESEARCH requires INDEPENDENT_HISTORICAL input. The tool
  preserves source declarations/references, original file bytes/hashes, timestamps,
  price basis, lineage, calendar and supplied review documents. It does not grant
  source permission or independently authenticate those declarations. Analysis
  requires the existing **human qualification gate** to report
  HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED, including hashed usage-rights evidence,
  dated sessions, finality and independent approval. Without that evidence the
  result is BLOCKED, with qualification reasons and no analytical records. This
  stricter boundary intentionally preserves existing repository policy; this
  milestone does not add a permissive unqualified-real-data analysis path. Even
  after an existing gate passes, this module's own qualification remains
  DATA_NOT_QUALIFIED and its historical validation remains PENDING.

Internally the existing engine uses SYNTHETIC_RESEARCH or HISTORICAL_RESEARCH as
required by its current contract. Both the external research label and the exact
engine provenance are recorded. Arbitrary caller provenance overrides, unknown
price basis/M5 origin and relabeling synthetic input as external are rejected.
Native M5 is never inferred or substituted. Derived M5 is explicitly labeled
INTERNAL_AGGREGATION_ONLY by the unchanged alignment check; it cannot establish
independent native cross-frame validation. No spread or bid/ask reconstruction is
performed. Missing source fields are never fabricated.

## Pipeline and availability

After full-archive admission through the existing gates:

1. Process M1 closes in strictly increasing UTC order. The default schedule is
   every supplied M1 close. An optional explicit schedule permits observation-gap
   tests; it never fills missing candles. Duplicate/reversed schedules block the
   run before producing analytical records. Unsupported/unavailable observations
   also block. The cutoff must be a UTC minute boundary within the declared range.
2. Select only ordered M1 bars with `open + 60s <= observation`, and M5 bars with
   `open + 300s <= observation`, using the existing `prefix` helper. Future and
   unfinished bars are not passed to either analytical layer. Completed bars
   still pass the unchanged quality/session/finality gates. Partial session bars
   are not rounded into eligible bars. Invalid archive gaps, timestamps and OHLC
   are blocked by preflight; a gap in the observation schedule is an abstained
   transition under PR #27's adjacent-M1 policy.
3. Generate Market Intelligence v1 and Market Context v1 on exactly these closed
   prefixes. Context already computes intelligence internally; one explicit
   additional intelligence call obtains its report reference without changing
   upstream interfaces. This deliberate recomputation preserves their outputs.
4. Feed ContextReport to `assess_scenarios`, then adjacent assessments to
   `assess_scenario_transition`. PR #27's synthetic replay helper remains
   synthetic-only; the integration uses its pure pairwise interface. Validate
   both reports with their existing validators. Rankings, selections, score
   semantics, narrow M5 invalidation proof and abstention policies are unchanged.
5. Record each original context in ReplayLedger and unchanged DecisionLog v1.
   Carry its causal evidence/event revisions through warm-up into evaluation.
   Warm-up includes closes <= evaluation start; evaluation includes later closes
   through the observation cutoff. Warm-up counts remain separate.

Archive admission checks the complete supplied archive, including metadata,
checksums and cross-frame coverage. That admission is not an online decision at
each timestamp. Once admitted, analytical calls see only the closed prefixes.
Prefix/future-append equivalence is claimed for eligible extensions with the same
source scope, configuration, evaluation boundary and unchanged earlier candles;
a newly corrupted archive is blocked at admission, not silently repaired or used
to revise previously published events.

## Evidence chain, manifest and strict validation

Each versioned record carries dataset identity and both provenance labels, UTC
observation and phase, per-frame first/last openings, last closing, closed count
and prefix hash; references to intelligence, context, normalized assessment input,
assessment, transition and DecisionLog entry; canonical evidence IDs; selected
upstream hypothesis; snapshot/transition state and reason codes; traceable
invalidation proof; deterministic record/event IDs and checksum.

The raw ContextReport hash and the scenario assessment's normalized-context hash
are both retained: PR #26 normalizes canonical ordering, so they need not be the
same digest. No identity is silently replaced. Intelligence window-local IDs
remain scoped inside its hashed report; durable context/evidence IDs remain the
existing canonical IDs. A warm-up data-quality BLOCKED snapshot is different from
an eligible insufficient-evidence ABSTAINED snapshot. Evidence validation
PASSED_INTEGRITY_NOT_AUTHENTICITY means the chain reproduced successfully, even
when its recorded quality outcome is blocked; it is not source qualification.

`replay_manifest` is a deterministic, versioned object inside the private report.
It records source metadata, original manifest and source-file hashes, normalized
hashes, evaluation/warm-up declarations, lineage, calendar hash, configuration
hashes, source scope and replay policy/hash. A standalone **synthetic example** is
committed at `docs/research_audits/scenario-replay-integration-synthetic-v1/replay-manifest.json`.

Dataset identity denotes a stable **research source series**, hashing symbol,
mode, source name/reference/curation ID, feed/basis/time convention/M5 origin,
calendar hash and finality declaration. It is not an archive-content fingerprint.
The full archive/manifest hashes are frozen separately in the replay manifest and
root `run_id`/checksum. Causal prefix hashes, configuration and all stage results
bind each record's identity. This separation allows future file extensions to
change the full-run hash without changing earlier record/event IDs. Different
prices or causal evidence cannot be hidden behind an unchanged series ID.

`validate_scenario_replay(report)` does more than check hashes. It reconstructs
**temporary copies** of embedded original files, reuses the strict loader and
source/preflight gates, replays the closed prefixes, and requires exact schema,
all stage references, records, IDs, checksums, summaries and DecisionLog equality.
It does not overwrite/read user source paths. Unknown schema versions, tampered
source bytes, changed transitions/references or false promotion fail validation
even when nested record IDs and checksums are recomputed. Hashes prove content
consistency, not independent authenticity or independent analyst agreement.

Temporary paths, wall time, randomness and system locale never enter analytical
outputs. Object key order is canonicalized with the existing digest utility;
source bytes, list order and timestamps are not silently repaired. Invalid inputs
return a blocked run (or validation raises on an invalid serialized report).

## Private CLI and Windows commands

Full reports embed source CSVs and any supplied review documents as lossless
base64 witnesses. **Base64 is not redaction or encryption. Keep real reports and
inputs private/offline; do not commit or upload them.** Only synthetic audit
summaries and the labeled synthetic manifest are committed here. The CLI performs
no downloads and prints only status/counts. It never modifies original files.
Use the existing Python 3.11 environment and already installed project dependencies.

From the repository directory in Windows PowerShell (replace paths with your own):

```powershell
$Manifest = 'C:\PrivateIAT\candidate\manifest.json'
$Review = 'C:\PrivateIAT\candidate\independent-review.json'
$Output = 'C:\PrivateIAT\reports\scenario-replay-001.json'
# The output directory must already exist; the output filename must be new.
py -3.11 diagnostics/scenario_replay.py --mode EXTERNAL_UNQUALIFIED_RESEARCH `
  --manifest $Manifest --review $Review --report-path $Output
```

A missing/unapproved review produces BLOCKED, not a synthetic fallback. To inspect
that blocked outcome without supplying a review, omit `--review`. Use a new output
filename for each run. Optional explicit configuration files use existing schemas:

```powershell
py -3.11 diagnostics/scenario_replay.py --mode EXTERNAL_UNQUALIFIED_RESEARCH `
  --manifest $Manifest --review $Review --cutoff-utc '2026-11-12T08:25:00Z' `
  --context-config 'C:\PrivateIAT\context.json' `
  --intelligence-config 'C:\PrivateIAT\intelligence.json' `
  --report-path 'C:\PrivateIAT\reports\scenario-prefix-001.json'
$Audit = Get-Content -LiteralPath $Output -Raw | ConvertFrom-Json
$Audit.status
$Audit.reason_codes
$Audit.summary
$Audit.replay_manifest.dataset.checksums
```

The timestamp is an **example**, not an assertion about available real data. It
must be inside the actual declared input range. `--observations schedule.json`
accepts an explicit ordered JSON array of UTC M1 close timestamps; do not choose
historical observations using later outcomes. Default replay evaluates every M1
close. Exit codes: 0 software replay COMPLETED, 3 BLOCKED, 1 invalid arguments or
publication failure (argparse also uses 2 for malformed CLI syntax). COMPLETED
never means historical validation. Existing output files are never replaced.
Publication uses the existing atomic non-overwriting `write_new`; interruption or
publication failure cannot leave a newly published partial success file.

Missing metadata: prepare a proper v2 manifest with the existing qualification
assistant. Missing source permission, calendar/finality evidence or approval:
obtain it through the existing independent qualification workflow. Gaps/mismatches:
obtain a corrected provider export, not interpolated prices. Invalid timestamps:
use documented UTC openings, not guessed broker offsets. Existing output:
choose a new filename. No credentials or terminal connection are needed.

## Synthetic audit and regression commands

```powershell
py -3.11 -m unittest discover -s tests -p test_scenario_replay.py -v
py -3.11 -m unittest discover -s tests -v
```

`tests/test_scenario_replay.py` creates explicitly synthetic OHLC through existing
fixture configs (short research lookbacks inherited from prior tests), not changed
production defaults. Eight 30-observation cases include continuation/reversal,
mirrored directions, aligned structural invalidation/replacement and comparable
support changes. All overlapping M5 bars are actually aggregated from M1. Earlier
M5-only warm-up is explicitly separate; no native-feed comparison is claimed.

The committed golden audit records **actual observed results**:
244 records: ABSTAINED 188, BLOCKED 24, NEW 12, PERSISTING 15, INVALIDATED 2,
REPLACED 1, STRENGTHENING 1, WEAKENING 1. The extra four records come from a missing
observation schedule; duplicate/reversed schedules are blocked at run admission
and produce zero records. Warm-up blocks and abstentions are included explicitly.
All eight states are exercised without overriding upstream reports or changing
thresholds. These are snapshot counts, not unique strategy setups or performance.

Worked aligned examples: at 08:29 UTC the original bullish scenario remains
selected; at 08:30 newly confirmed opposing M5 structure supplies four canonical
pivot references and INVALIDATED. Its mirrored dataset exercises bearish-to-bullish
invalidation. The ranging variant produces REPLACED with no invalidation proof.
The support variant produces STRENGTHENING at 08:27 and WEAKENING at 08:28, reusing
the same fixed anchors and capped support semantics. No probabilities or trade
levels are calculated.

Regressions cover complete/prefix repeated replay, truncated-file/future-append
invariance, unchanged source files/hashes and upstream reports, DecisionLog v1,
M5 boundaries, partial candle exclusion, source-mode mismatch, missing independent
review, synthetic calendars rejected as real proof, source document hashes,
malformed OHLC/times/gaps, and semantic tampering with recomputed IDs/checksums.
CI runs the inherited and new tests on Ubuntu/Windows, Python 3.11.9 and 3.12,
plus a missing-source/semantic safety smoke check.

No permitted, independently qualified external export was supplied or replayed.
Real-data source permission, actual feed/basis and dated session/finality evidence,
independent qualification and real blinded annotations remain outstanding.
Historical comparisons are NOT_RUN and historical metrics remain unmeasured.
Only the existing narrow M5 structural invalidation condition is supported;
zone/session-expiry proof remains unavailable under the upstream transition v1
contract. Execution gates, READ_ONLY_SHADOW, WAIT, execution_allowed=false,
Exness BLOCKED, broker_access=false and orders_requested=0 remain unchanged.
