# Independent source qualification review v1

This is an offline evidence-review workflow. It is not a new dataset qualifier. The result is always DATA_NOT_QUALIFIED, Exness BLOCKED, historical validation PENDING, comparisons NOT_RUN, signal WAIT and execution false. Existing strategy/replay/blinded-chart gates remain closed. A source-review JSON can be produced while `review_packets_allowed=false`: that flag concerns the existing gated market-review workflow, not this evidence worksheet.

## Audit and architecture

Base: PR #24, `870c7da64c1277bbabdc25e7e5ebf3fb67c429fd`; confirmed clean before branching. Existing PR #24 hashes, JSON validation, local-path guard and deny-only qualification gate are reused. Existing `chart_benchmark` supplies strict keys, canonical hashes and atomic non-overwriting publication; `replay_dataset` supplies bounded JSON/file reads and confined local artifact resolution; the existing session timezone conversion rejects ambiguous/nonexistent local instants. No second qualification state machine, session classifier or candle validator is added.

`iat/independent_source_evidence.py` validates registry v1, assesses evidence axes separately and builds a deterministic claim matrix. `diagnostics/independent_source_review.py` publishes the review artifact. The existing replay loader explicitly rejects both the registry and source-review packet, as it already rejects PR #24 evidence manifests. Existing qualification, finality, diagnostics, strategies, thresholds and candidate calendar contents are unchanged.

The operator reports completing PR #24's local integrity and mechanical reproduction checkpoints. The supplied manifest payload hash is `3c794f78db44c2de4a3844e32cfeb30fdfe962fd8890c7a389eb9fe588207895`. This is a canonical payload digest, not the original file hash. The local CSVs, private diagnostic and original verification manifest were not supplied to this cloud task. The registry therefore records that chain as **operator-reported**, not independently rerun here.

## Strict registry and review formats

[Registry example](../config/examples/independent-source-review/exness-review-v1.json) is `INDEPENDENT_SOURCE_EVIDENCE_V1`, version 1. It contains explicit collection cutoff, collector pseudonym, target historical interval, broker/account-scope alias/account category/instrument, PR #24 reference digests, normalized claims, source records and reviewer declarations. No publication/effective date is inferred from a URL/title or from a page's update timestamp. Null means unknown.

Each source has a unique ID, PR #24 gap category, claim ID/value, publisher/title/reference, publication/retrieval/effective timestamps, applicability declarations, summary, optional preserved artifact fingerprint, collection method/status, notes, conflict references and limitations. Quote and trade timezones, DST rule, explicit wall-clock anchors, session investigation fields and price-construction investigation fields are separate. A missing field cannot become a verified fact. Known clock predicates ending `_utc` require explicit valid second-level clock values; price-basis predicates require BID/ASK/MID/LAST or UNKNOWN.

Categories map directly to the nine PR #24 gaps: historical price basis; provider/feed provenance; historical usage rights; account/instrument specification; dated sessions/timezone/DST; holidays/special closures; maintenance; finality/corrections; independent approval. There is no profitability category or trading permission.

Source references accept sanitized HTTPS URLs without credentials/query/fragment, anonymous `document:filename` references, and synthetic references only in labeled synthetic fixtures. No reference is fetched. Optional artifacts use anonymous basenames and SHA-256, confined to an explicitly supplied local artifact directory; files are read as bounded bytes, never executed or interpreted as active HTML/PDF content. No account number or server identifier is required in shared data. The account-scope alias must map to privately reviewed applicability evidence; a matching alias is not proof of that mapping.

Reviewer records require a distinct pseudonymous reviewer, timestamp, evidence IDs, claim, exact review scope, conclusion, separate authority/temporal/instrument/account/claim-support criteria, unresolved conflicts, explanation and provenance document reference/hash. Conclusions are SUPPORTS, REJECTS, UNRESOLVED or ACKNOWLEDGED, not dataset APPROVED. Unknown fields/simple approval booleans are rejected. Self-review is rejected. Reviewer identity/signature and provenance-document authenticity are not authenticated by this program. No genuine reviewer declaration is fabricated in the example (`reviews=[]`).

## Independent evidence axes

| Axis | What the runtime establishes / does not establish |
| --- | --- |
| Source existence | A reference is provided, missing or declared unavailable. No HTTP existence check or download occurs. |
| Integrity | Preserved bytes match/differ from the declared SHA-256, or are uninspected/unavailable. A match is not issuer authentication. |
| Authority | A publisher is declared identifiable or remains unestablished. A domain/publisher string does not certify an issuer. |
| Temporal applicability | Explicit interval covers the target, overlaps insufficiently, is outside history, or remains unknown. Future publication/retrieval and inconsistent dates stay unresolved. |
| Instrument/account/broker | Exact declared scope matches, conflicts or is unknown. Matching declarations are not independently verified account specifications. |
| Timezone | Explicit IANA zones/anchors are checked. DST folds/gaps are rejected; no rounding, automatic fold choice or schedule conversion is invented. |
| Claim support/review | Reasoned reviewer declarations are retained, including uncertainty/disagreement. Acknowledgement is not support or qualification. |

The six matrix classes are SUPPORTED_WITH_APPLICABILITY, SOURCE_PRESENT_APPLICABILITY_UNKNOWN, INSUFFICIENT_EVIDENCE, CONFLICTING_EVIDENCE, SOURCE_UNAVAILABLE and NOT_REVIEWED. SUPPORTED_WITH_APPLICABILITY requires applicable declarations, an inspected matching artifact and supported independent-review declarations across criteria. It is explicitly a **review classification**, not authenticated external truth or dataset approval. One review cannot erase another reviewer's uncertainty or rejection.

Only normalized values for the same claim are compared. Different values that could apply to the target are preserved; definite wrong-date/account/instrument alternatives remain in the inventory but are excluded from active contradictions. Explicit conflict links retain unresolved semantic differences, including quote versus trading phases. No majority vote resolves conflicts. Natural-language equivalence is not inferred. Missing qualification evidence remains visible even when a specific claim has a supported review declaration.

Optional `--manifest` inspects the actual PR #24 manifest bytes, validates its payload digest, compares any supplied file digest, checks the recorded state, dataset digests, diagnostic payload and target interval. It does **not** rerun the raw CSV computation. Without the file, the result says NOT_SUPPLIED; with mismatching bytes/claims, INVALID_OR_CONFLICTING_MANIFEST. No matching manifest can qualify a source.

## Safe manual collection

1. Preserve the current registry and PR #24 report privately; do not edit expected hashes to force a match.
2. Prioritize dated official Exness notices and exact instrument/account applicability evidence, then official platform/export documentation, holiday/maintenance notices and attributable broker-support correspondence. Seek independent corroboration where available. This tool sends no messages or requests.
3. Inspect terms and permission before preserving/sharing a document. Keep raw CSVs and account-identifying correspondence private. Do not use authenticated portal scraping, credentials or tokenized links.
4. Record the actual title, publisher, canonical safe reference, actual access time, and only dates the source supplies. Preserve a lawful local copy when permitted; compute its original-byte SHA-256 with `Get-FileHash`. An inaccessible source stays unavailable, not verified.
5. Record exactly which claim the source supports, its limitations and explicit account/instrument/date scope. A current page or weekly table does not establish dated exceptions. Store filtered schedule snapshots only where permitted, with their actual date/timezone filters and applicability documented; a generic URL alone is insufficient.
6. Preserve alternatives as separate evidence IDs and link conflicts. Do not replace the candidate calendar or reinterpret missing minutes as confirmed closures.
7. Ask an actual independent reviewer to inspect the originals and complete the structured declarations. Do not prepopulate a signature, review timestamp, criterion result or approval on their behalf.
8. Generate the offline report and retain conflicts/unknowns. A future separately reviewed and explicitly authorized qualification process is required before any historical replay or gated market-review workflow can proceed.

See [Exness source findings](EXNESS_HISTORICAL_SESSION_EVIDENCE_V1.md) and the [review worksheet](HISTORICAL_EVIDENCE_REVIEW_V1.md).

## Windows 10 / Python 3.11

After checking out `feat/iat2-independent-source-qualification-v1`, reuse the existing Python 3.11 environment. `tzdata` is already declared in requirements.txt; the runtime performs no dependency installation or network access.

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
New-Item -ItemType Directory -Force -Path 'E:\IAT2\Reports' | Out-Null
py -3.11 diagnostics/independent_source_review.py `
  --registry 'config/examples/independent-source-review/exness-review-v1.json' `
  --manifest 'E:\IAT2\Reports\historical-evidence-verified-20261116-131944298.json' `
  --artifact-root 'config/profiles' `
  --report-path 'E:\IAT2\Reports\historical-source-review-001.json'
```

This verifies the candidate profile's locally preserved bytes and inspects the supplied local manifest if present; it does not fetch public references or read the CSVs. To generate a reference-only packet when the private manifest is unavailable, omit `--manifest`. For subsequently collected lawful documents, use a private artifact folder and a reviewed registry copy with anonymous file references, instead of copying private documents into the repository.

```powershell
$r = Get-Content -LiteralPath 'E:\IAT2\Reports\historical-source-review-001.json' -Raw | ConvertFrom-Json
$r.local_manifest_inspection
$r.claim_matrix | Select-Object @{n='Claim';e={$_.claim.id}},classification
$r.source_assessments | ConvertTo-Json -Depth 12
$r.coverage | ConvertTo-Json -Depth 8
$r.reason_codes
$r.qualification
```

Exit **3** means a valid review artifact that remains blocked, including unresolved claims. Exit **2** means invalid inputs, missing/mismatching manifest/artifact bytes or publication failure. Inspect per-source integrity/applicability and reason codes; do not bypass the failure. Existing destinations are never overwritten. Choose a fresh suffix on retry. UNC/URL file paths, traversal identities and unsafe outputs are rejected before access. No personal paths or raw prices are copied into the report.

Limits: registry <=256 KiB, <=64 claims/sources/reviews, <=16 conflict references per source, <=8 wall-time anchors, <=500 characters per text field, source/manifest reads <=4 MiB, report publication <=4 MiB. Unsupported versions, duplicate identifiers/JSON keys, malformed dates and oversized inputs fail closed. Atomic publishing and original-source preservation reuse existing utilities. Outputs are deterministic for the same inputs/cutoff/artifact bytes; claim/evidence/review IDs normalize record order. Canonical payload digests and exact original-file digests remain distinct. Runtime clocks, output paths and filesystem modification times are not injected into payloads.

Tests use clearly labeled synthetic source statements and reviewer declarations. No real Exness document is fabricated as a test fixture. Full local and Linux/Windows CI results are recorded in the PR after execution. No source-review packet is accepted as qualification, strategy/replay authorization, trading signal or execution permission.
