# Unified Market Intelligence V3 presentation adapter

This milestone adds a pure Python research interface over existing reports. It does not add chart-reading algorithms, strategies, score weights, directional selection, data qualification, trading permissions or an HTTP route. A unified view is an explanation of supplied observations, never an order or a market prediction.

Base: PR #42 head `f73030dd6f8a4925741b9d273e65a6ace82d737c`. The separate feature branch targets `research/iat-v3-exness-boundary-evidence`; its PR diff contains only this adapter milestone, while PRs #41/#42 remain draft and unmerged. Their timing corrections, original journals, evidence verifier and source research are unchanged.

## Interface and data flow

```python
from iat.intelligence.market_view import (
    build_market_view_v3, validate_market_view_v3,
)

# existing_context is an existing typed ContextReport from the causal gated path.
view = build_market_view_v3(existing_context)
validate_market_view_v3(view, context_report=existing_context)
```

Full signature:

```text
build_market_view_v3(context_report, adaptive_report=None, scenario_report=None,
                     session_snapshot=None, qualification_snapshot=None,
                     *, intelligence_report=None) -> JSON-serializable dict
validate_market_view_v3(view, *, context_report=None, **same_inputs) -> True or rejection
```

No acquisition, wall clock, terminal initialization, account, market-data filesystem, service or provider call occurs. Module initialization loads only the checked-in public schema; `jsonschema>=4.23,<5` is now a runtime dependency shared with offline contract tests. Input reports are copied; nested output mutation cannot change an upstream report. The existing V1 intelligence/context APIs and all old consumers remain unchanged. The Python interface is the integration boundary recommended by the roadmap; HTTP integration is deferred to avoid introducing another live acquisition path or a falsely eligible response while Exness remains blocked.

1. The existing scenario assessment validates the typed context, canonical evidence, chronology, reference resolution, classifications, confluence caps, hypotheses and upstream selection. Critical quality failures quarantine analytical detail. Unsupported, malformed or unavailable input produces a redacted BLOCKED envelope.
2. Identical evidence copies collapse by canonical ID before adaptive presentation; conflicting same-ID observations fail the existing validator. There is no accumulated vote or score across snapshots.
3. Reuse the existing adaptive engine and unchanged policies for directional regime, volatility and conflicts. Optional supplied scenario/adaptive reports must validate and exactly match this context at the same cutoff and configuration. Wrong symbol, stale report, policy/hash mismatch or cross-cutoff children block rather than produce a mixed view. Existing adaptive offline provenance restrictions remain enforced; this adapter is not a new live-provenance approval path.
4. Copy the existing confluence scores, selected hypothesis, ranked hypotheses, ties, assumptions and invalidation conditions. The display rank never becomes a selector. Descriptive directional bias maps the inherited selected hypothesis only; abstention is NEUTRAL and unavailable input is UNKNOWN. Upstream signal remains WAIT. Even with a BLOCKED session, retained valid upstream facts/selection are historical research content, not currently usable confirmation.
5. A supplied V2 session public-state snapshot must have the exact known shape, matching evaluation cutoff, valid UTC coverage declarations and execution disabled. It is presented as a declaration, never independent calendar approval. Its fingerprint is recorded in the adaptive configuration, but that does not prove the calendar used to produce ContextReport v1. Since v1 has no session digest, otherwise usable declarations conservatively produce UNKNOWN plus SESSION_CONTEXT_BINDING_UNESTABLISHED. The public state does not carry symbol identity: the caller must obtain it from the same instrument calendar used upstream; this adapter does not claim to authenticate that association or independently reconstruct historical coverage. Missing snapshots remain UNKNOWN; BLOCKED, CLOSED, QUOTE_ONLY or CLOSE_ONLY snapshots restrict the whole view. Future coverage endpoints are declarations, not future observed candles.
6. An optional `qualification_snapshot` is only the exact current-stage `SAFETY` invariant mapping exported by this module. It is not a general approval document. An approval claim is rejected. Root qualification remains DATA_NOT_QUALIFIED regardless of snapshot or analytical status.
7. Seal canonical sorted-key JSON with SHA-256. No wall-clock generation time or output path enters the checksum. A hash checks integrity, not authenticity or independent validation.

## Schema and field mapping

Contract: `config/market-intelligence-v3.schema.json`; `report_version=1`, `model_version=IAT_MARKET_INTELLIGENCE_V3`. “V3” identifies the presentation model, not a replacement V1 contract. Timestamps are UTC. Runtime and offline validation now enforce the same complete schema, including nested collection items, source variants and null semantics. The Python validator additionally checks causal references, chronology, dense ranks, score contributions, selection, child hashes, session restrictions and hashes. Supplying the original inputs to the validator checks the entire mapping against those inputs. An unbound checksum alone cannot establish that a rechecksummed analytical value came from the upstream source.

| Section | Existing source / behavior |
|---|---|
| `market_state` | Context symbol, cutoff, provenance, frame availability/closed-through and structure; existing adaptive directional regime and separate volatility; existing per-frame momentum |
| `price_structure.patterns` | Canonical current CANDLE evidence, preserving names/interpretations/references; no new pattern detection |
| `price_structure.swings` | Optional original V1 confirmed pivots with original HH/HL/LH/LL/EH/EL/UNCLASSIFIED relations and canonical context pivot IDs |
| `price_structure.structural_events` | Optional V1 BOS, CHoCH, failed/ambiguous/wick events; original close/wick policy, availability, level and canonical underlying references |
| `price_structure.support_resistance`, `supply_demand` | Existing zone geometry, lifecycle and original IDs; potential zones are not entry/stop/target instructions |
| `price_structure.structure_changes` | Existing canonical TRANSITION evidence and stable CHoCH occurrence IDs |
| `liquidity` | Existing pools/equal highs/lows and events checked against their source bindings; existing hypotheses citing liquidity evidence, not new hypotheses or actual order-book claims |
| `confluence` | Original M1/M5 structure/alignment, exact score object, canonical evidence/source registry and adaptive conflicts, including fresh opposing M1 CHoCH |
| `restrictions` | Original quality diagnostics; missing frames, warm-up reasons, supplied session declaration, calendar qualification and existing rejection reasons |
| `advisory` | Original WAIT signal, selected hypothesis, ranked hypotheses/ties, evidence, assumptions, invalidations, explanations and abstention; explicit research/qualification WAIT reasons |
| `bindings` | Canonical validated-context hash; child scenario/adaptive hashes; optional original V1, session and qualification hashes; original configuration hashes and fixed presentation policy digest |

Optional V1 detail must be an `IntelligenceReport` with the same symbol/cutoff/provenance/quality and intelligence configuration. For integrity, the adapter reconstructs the context's already retained closed source rows and reuses the original V1 engine with that exact configuration, comparing frames/alignment before copying detailed pivots/events. This bounded extra recomputation is a consistency check, not a new analytical policy or qualification gate. Its cost is a limitation for high-rate integrations; optimization must preserve the contract.

CHoCH occurrence IDs and evidence revisions retain their existing canonical identity. V1 BOS/other structural events do not yet have a durable canonical occurrence-ID contract: `event_id` remains null and `source_id` is explicitly scoped by `source_report_sha256`. Never deduplicate or count durable events by that window-relative source ID alone. Underlying references are translated to existing canonical candle/pivot identities. No new durable event identity is invented by the presenter. Unconfirmed candidate pivots are withheld rather than promoted to confirmed structure.

## Missing and restricted data

- No context, malformed input, quality error, stale bars or mismatched supplied child: BLOCKED, with no assessed detail.
- Genuine quality-blocked context retains the existing neutral/no-direction selection and WAIT signal, but no evidence/ranks are emitted.
- Missing M1/M5, insufficient structure or absent/unknown session: UNKNOWN, with available observations and original abstention preserved. UNKNOWN never implies confirmation.
- Valid data plus a BLOCKED/restricted supplied session: BLOCKED; retained upstream interpretations remain explicitly restricted research content.
- After the automated contract review, root ASSESSED/ABSTAINED are not emitted for ContextReport v1: it cannot establish a same-calendar digest binding. Eligible synthetic declared sessions stay UNKNOWN, while the original assessed/abstained hypothesis, scores and reasons remain unchanged in the advisory section. The status names remain reserved in the shape vocabulary, but the Python validator rejects promoting a v1 presentation to either status. Any future positive status requires an explicitly reviewed upstream binding contract, never permission to trade.
- Empty upstream pools/zones/patterns are `status=UNAVAILABLE`, `items=[]`, with `NO_UPSTREAM_OBSERVATIONS`. This is not proof no real liquidity/level exists.
- Without original V1 detail, swings and structural-event history are UNAVAILABLE with `V1_INTELLIGENCE_NOT_SUPPLIED`; they are not inferred from incomplete context fields.
- Confidence is null with `NOT_PROVIDED_BY_UPSTREAM`. Scores retain `HEURISTIC_EVIDENCE_NOT_PROBABILITY`; no numerical probability, entry, stop, target or new BUY/SELL field is created.

Historical callers must still use the existing manifest loader and historical preflight before publishing any historical claim. A ContextReport, provenance string, session declaration or matching JSON hash is never independent source qualification. No raw CSV or full real-data response should be committed to Git.

## Synthetic example and regression scope

`docs/research_audits/market-view-v3.synthetic.json` is an explicitly labeled excerpt from `tests/test_market_view_v3.py::reports()` with invented OHLC, not an Exness export. It records the complete view's golden canonical hash, original configuration hashes, score summary and safety. It is an excerpt, not a complete schema-valid response.

That example has both frames, TREND_UP, inherited BULLISH_CONTINUATION_POSSIBILITY and original heuristic scores. Overall status is UNKNOWN because the fixture has no session snapshot and inherited SESSION_NOT_CHECKED. Signal remains WAIT, confidence null, qualification DATA_NOT_QUALIFIED and execution false. Its confirmed swing/event counts are descriptive synthetic observations only.

The new focused suite covers both directions; missing frames, pools and zones; conflicts/fresh CHoCH; stale observations; warm-up; unchanged Exness profile bytes; UNKNOWN/close-only/quote-only sessions; exact child/V1/config bindings; duplicate/conflicting evidence; future inputs and unfinished M5; serialized tampering; safety; V1 non-mutation; repeatability; prefix equivalence; future-append invariance; and the frozen full-view hash. No fixture is passed off as real broker evidence. Exact focused/full results and final Linux/Windows CI are recorded against the delivered head in the draft PR.

## Integration and next milestone

Use an existing gated context at its original M1 close; optionally supply matching already computed scenario/adaptive and V1 intelligence outputs plus the same-cutoff V2 public-state snapshot. Call bound validation before storing a new private research artifact. Do not feed independent reports from different timestamps/configurations or apply a new selection rule. Missing evidence stays missing.

Next: independent review of this presentation contract and its missing-data semantics, then one separately versioned strategy-research extension at a time while preserving the existing two rules. Real evidence collection proceeds separately through the unchanged PR #42 verifier. Historical validation remains PENDING and comparisons NOT_RUN until genuinely qualified evidence supports the existing historical gates. No broker certification, actual-terminal success, profitable strategy or trading readiness is claimed.

## Automated review correction

See [the automated audit](MARKET_INTELLIGENCE_V3_AUTOMATED_REVIEW.md) for independently constructed fixtures, nine original failing regressions, minimal fixes, performance measurements, source-binding limits and the next single-family research contract. This is automated code review, not external independent approval. V1 report names/fields and upstream decisions are preserved; malformed objects previously accepted by shallow checks are now rejected. Old positive-status artifacts should be retained as historical evidence and regenerated into NEW research outputs for current validation, never overwritten or silently relabeled. No existing logs, private files or historical qualification gates are migrated or changed.
