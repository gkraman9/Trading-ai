# Historical provenance and independent qualification gap analysis v1

Read-only evidence assessment. The five labels VERIFIED, PARTIALLY_VERIFIED,
UNVERIFIED, CONTRADICTED and NOT_APPLICABLE describe individual evidence
properties, not production qualification or permission to trade. This tool never
approves data, runs orders, changes calendars or changes strategy/scenario logic.

## Architecture and actual branch relationship

PR #25 (`d628805785fc9399165d94436d1972569863e01c`) is an ancestor of PR #28
(`37636f84556a8acef6aa4fcf3590e9065fe8747e`). PR #29
(`028c02e280ba1c8dfd7174a757e7cd35b00e3e73`) and PR #30
(`09cf0f13c649b522447e1f5a1796bf52e2ff2519`) are independent children of PR #28.
This feature starts from PR #29 and targets its development branch. PR #30 was
inspected at its exact commit; it was not merged or assumed to exist in PR #29.

`config/reference/exness-2026-11-11-13.relayed.json` is a redacted, pinned fact
snapshot extracted from PR #30's documentary `evidence.json`. It preserves the
original commit/path, metadata byte and payload hashes, transcript hash, dated
claims and unresolved questions. It contains no raw support correspondence,
account identity, server, reviewer identity or credentials. The runtime checks
its fixed canonical hash; a rehashed replacement fact snapshot is rejected.
This proves snapshot integrity, not independent authenticity of the broker reply.

The integration reuses the existing dataset loader, quality/calendar preflight,
M1/M5 alignment checker, import/normalization assistant, source-review registry,
human qualification gate, replay evidence validator and PR #29 diagnostics.
Their contracts, thresholds, state and code remain unchanged. This is a gap
report around those interfaces, not an alternative qualification system.

## Inputs and source binding

```python
from iat.provenance_assessment import (
    assess_historical_provenance, validate_provenance_assessment,
)
report = assess_historical_provenance(manifest_path,
    broker_binding_path=binding_path,             # optional declaration
    import_spec_path=original_import_spec,        # optional existing assistant schema
    independent_review_path=existing_review,     # optional existing qualification schema
    source_registry_path=existing_registry,      # optional PR #25 schema
    replay_report_path=existing_replay)          # optional PR #28 report
validate_provenance_assessment(report, manifest_path,
    broker_binding_path=binding_path,
    import_spec_path=original_import_spec,
    independent_review_path=existing_review,
    source_registry_path=existing_registry,
    replay_report_path=existing_replay)
```

Omit unavailable optional inputs rather than invent references. Only local files
are accepted; UNC/network paths and input symlinks are refused. The inherited
loader accepts bounded normalized XAUUSD M1/M5 CSVs with exact manifest checksums
(up to 5,000 rows/frame and 4 MiB/file). Use the existing import/pilot preparation
workflow to select and normalize a larger authorized archive first. The optional
replay input retains its existing 32 MiB bound and private embedded-data handling.

Inventory distinguishes supplied CSV hashes, normalized OHLC hashes, declared raw
lineage hashes and original import hashes. A declared `raw_sha256` is never
substituted for an inspected original file. Original import hashes become
available only when the existing import assistant reproduces both normalized
frames, feed/basis declarations and the source-set lineage hash. Source mapping
and corrections declarations remain separate from authenticated provider facts.

A source registry must bind the actual M1/M5 file hashes and UTC interval; an
original-file binding is accepted only after normalization is reproduced. A
supplied calendar must also match its referenced hash. PR #24 historical-evidence
manifest and diagnostic references not inspected by this invocation remain
explicitly unverified. Matching a subset of references never authenticates the
whole registry. Review assertions/disagreements remain assertions, not approvals.
The human review uses the existing gate and hashed, scoped documents; its reviewer
identity and correspondence are not echoed into this report.

A replay report must validate under PR #28 and match the loaded dataset metadata
exactly before PR #29 evidence-chain coverage is retained. A valid replay of a
different dataset is a reference conflict. No failed historical input falls back
to synthetic analysis. No source URL is downloaded by this tool.

## Three distinct layers

**Mechanical:** original supplied-byte hashes; monotonicity, duplicates, UTC grid,
positive finite OHLC/ranges; declared retrieval versus candle closing times;
missing grid intervals; conditional calendar geometry; comparable M1/M5 OHLC and
source-to-normalized traceability. Existing candle/preflight validators remain
visible. An invalid chronology is not sorted or deduplicated to make an alignment
comparison pass. Alignment is not run on structurally invalid bars.

No calendar means the unexpected broker-missing-candle denominator is unknown:
UTC-grid gaps are measured but are not automatically called unexpected session
gaps. Supplied verified-declaration calendars can reproduce ordinary expected
intervals, including closures; that is still not independent calendar
authentication. Research geometry counts partial/restricted bars without making
them eligible. Uncovered M5 observations make whole-input cross-frame coverage
PARTIALLY_VERIFIED; the comparable subset can still match. Legitimate M5 warm-up
before M1 coverage is reported separately by the unchanged evaluation checker
and does not modify its production eligibility rules.

M5 derived from M1 is always INTERNAL_AGGREGATION_ONLY, even with zero mismatches.
A declared native feed is not independently authenticated by arithmetic. The
existing evaluation coverage denominator/threshold and cross-frame claim are
retained; no new thresholds or native-feed claims are introduced.

**Provenance:** provider/source name, acquisition URL, timestamp and price-basis
declarations, feed identity, rights/finality/corrections evidence and broker scope.
A known declaration is generally PARTIALLY_VERIFIED, not authenticated. A document
hash demonstrates that the provided bytes match a reference, not that the issuer,
acquisition or statements are genuine. An apparently complete mock review therefore
cannot make SOURCE_AUTHENTICITY VERIFIED.

**Independent qualification:** the existing qualification gate result is copied
separately, without replacing or modifying it. Even
HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED is an attestation/precheck result, not this
tool granting independent authenticity. This report's own qualification is always
DATA_NOT_QUALIFIED, historical validation PENDING and comparisons NOT_RUN.

The sixteen stable gaps each include a deterministic identifier, exact dataset
and interval scope, required/available evidence, one of the five labels, a
blocking reason where applicable, next verification action and resolving source
reference IDs. SPREAD_INFORMATION remains UNKNOWN and nonblocking for this OHLC
scope; no zero spread, Ask reconstruction or unsupported spread prerequisite is
invented. Independent authenticity numerator and denominator remain null.
Counts of gap labels have a known catalog denominator; they are not probabilities,
confidence scores, market-performance measures or percentages of data qualified.

## Exness applicability and unresolved boundaries

No broker is inferred from a file/source name. An optional v1 operator declaration
must contain exactly these fields, bound to the assessment's current dataset and
manifest hashes:

```json
{
  "binding_version": 1,
  "dataset_id": "<actual assessment dataset_id>",
  "manifest_sha256": "<actual manifest reference file_sha256>",
  "broker": "EXNESS"
}
```

`broker` may be EXNESS, NON_EXNESS or UNKNOWN. This is a declaration, not a new
approval. A mismatch is CONTRADICTED; omission/UNKNOWN leaves applicability
UNVERIFIED. NON_EXNESS or dates outside November 11–13, 2026 are NOT_APPLICABLE.
The 2021 publisher pilot must not inherit a 2026 Exness calendar.

For explicitly bound Exness candidates within those dates, the comparison uses
only the reported boundaries: quotes/trading close at 21:58 UTC; quotes resume
23:00 in close-only mode until 23:02. A 21:55 M5 bar has only 180 quoted seconds;
a 23:00 M5 interval includes close-only minutes and never obtains opening
permission from this tool. Opening new positions after 23:02 remains unknown.
Friday November 13 reopening remains unresolved; Friday 23:00+ rows are reported
as ambiguous, not assumed either missing or invalid. Rows during the unambiguous
closed-quote break conflict with the relayed statement, conditionally on the
operator's broker binding; this is not proof that the source provider is wrong.

The exact pinned note also retains Bid chart OHLC, no reported special
maintenance/holiday interruptions in those dates and the demo/real trading
conditions statement. These are operator-relayed broker claims, not an
authenticated original email, export permission or historical candle proof. A Bid
chart statement does not overwrite an UNKNOWN or ASK export declaration. No
ordinary permission or operational calendar is installed from this comparison.
All comparison observations retain iat_execution_allowed=false.

## Actual available source records

`docs/source_reviews/provenance-gap-analysis-v1/available-sources.json` inventories
committed metadata inspected for this task and their exact file hashes:

* The Silva/Hugging Face 2021 pilot reports 240 M1/48 M5 rows, a raw archive hash,
  Bid-tick aggregation and publisher CC-BY-4.0 attribution. Its original source
  feed, dated 2021 calendar and capture/finality evidence remain unestablished.
  The record is metadata-only; raw archive bytes were not re-read in this task.
* The operator-reported November Exness exports declare 4,074 M1/816 M5 rows and
  file hashes. Their actual files were not supplied to this task. Feed identity
  and export price basis remain unknown; the later chart Bid statement does not
  silently update those archive declarations.

These are reported inventories, not newly reproduced real-data findings. No raw
market data or support correspondence is embedded in public audit output. No
network acquisition or real-data replay occurred. Existing OANDA documentation
leads do not substitute for an authorized export, dated sessions or finality.

## Private Windows export workflow

From the repository root using the existing Python 3.11 environment:

```powershell
py -3.11 diagnostics/provenance_assessment.py `
  --manifest 'C:\PrivateIAT\candidate\candidate-manifest.json' `
  --import-spec 'C:\PrivateIAT\original\import-spec.json' `
  --json-output 'C:\PrivateIAT\reports\provenance-001.json' `
  --text-output 'C:\PrivateIAT\reports\provenance-001.txt'
```

Add `--broker-binding`, `--independent-review`, `--source-registry` and/or
`--replay-report` only when actual matching private artifacts exist. To generate
an unknown-source checklist, omit the manifest; no row counts or source hashes
are manufactured. Use the reported dataset/manifest IDs to create a broker binding
only after independently determining which broker supplied the export; a provider
name is not enough. Regenerating/changing a manifest requires a new binding.

All outputs remain private/local, including acquisition references. The CLI
prints fixed status/label counts only and never uploads or echoes account details,
raw CSVs, reviewer identities or support correspondence. It uses existing atomic,
non-overwriting file publication; both filenames must be new/distinct and cannot
alias an input. JSON/text publication is per-file, not a pair transaction. A text
publication failure can leave a complete valid JSON; the command returns failure,
not approval. Use new filenames for recovery and do not delete original exports.
Exit 3 means a research-only gap report was created; exit 1 is invalid input/export
failure, and argparse may use 2 for malformed command syntax. No exit means data
qualified. No credentials, terminal or optional MT5 installation is needed.

`config/historical-provenance-assessment-v1.schema.json` is the strict structural
JSON schema. `validate_provenance_assessment(report, original_private_inputs...)`
also re-executes the assessment and compares every field/hash. Merely recomputing
a checksum after altering source references, labels, scope, denominators or safety
flags cannot pass semantic validation. Original input hashes are rechecked after
inspection to detect changes; source files are never normalized in place.

## Synthetic audit and verification

`docs/research_audits/provenance-gap-analysis-synthetic-v1/audit.json` contains nine
explicitly synthetic cases with reproducible dataset/report/input hashes. They
cover clean inputs, a missing interval, duplicate timestamps, invalid OHLC, M1/M5
mismatch, an Exness break, close-only bars, Friday ambiguity and a non-Exness feed.
The clean case verifies supplied bytes, candle mathematics, comparable aggregation
and provided-reference integrity. It does not establish origin authenticity,
usage rights, finality or independent qualification. Metadata-only source reviews
remain distinct from these reproduced synthetic mechanical checks.

```powershell
$env:PYTHONPATH = 'tests'
py -3.11 -m unittest test_provenance_assessment -v
py -3.11 -m unittest test_independent_source_evidence test_scenario_replay test_replay_diagnostics -v
py -3.11 -m unittest discover -s tests -v
```

Focused cases also exercise altered bytes/missing hashes, out-of-order/misaligned
rows, NaN OHLC, incorrect references, unknown Bid/Ask/spread, independent document
hash tampering, original-to-normalized reproduction, existing-gate pass without
new qualification, replay mismatch, stable JSON and cross-platform private export.
CI runs inherited and new tests on Linux/Windows, Python 3.11.9/3.12.

All trading/session/qualification gates remain unchanged: READ_ONLY_SHADOW,
Exness BLOCKED, WAIT, execution_allowed=false, historical validation PENDING and
comparisons NOT_RUN. Remaining real-data blockers are authenticated acquisition
and feed/basis, permitted use, exact dated sessions (including Friday and 23:02),
closed-bar capture/finality/corrections, and independent qualification. No real
performance, win rate, source certification or broker-equivalence claim is made.
