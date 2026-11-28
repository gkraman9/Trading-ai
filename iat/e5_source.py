"""Private file-bound historical input snapshots. No MT5, downloads or approval writer."""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import csv
import io
from iat.replay_dataset import load_dataset, read_bytes, strict_json, utc
from iat.pilot_qualification import qualify_historical
from iat.paper_readiness import (
    historical_paper_preflight,
    bound_file,
    exact,
    audit_quote_events,
)
from iat.qualification_assistant import _spec, _parse_frame
from iat.strategy_qualification.dataset import quote_bar_audit
from iat.strategy_qualification.quotes import Quote
from iat.intelligence.context import context_at
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.market_view import build_market_view_v3
from iat.intelligence.strategy_replay import digest
from iat.intelligence.paper_contracts import (
    BrokerSpecification,
    SyntheticCosts,
    require,
    canonical,
    financial_context,
)
from iat.paper_source_scope import _register_source
from iat.e5_protocol import baseline, protocol

PLAN_INPUTS = (
    "manifest",
    "review",
    "paper_bundle",
    "outcome_manifest",
    "outcome_review",
    "import_spec",
    "bar_availability",
)
ASSERTIONS = (
    "raw_normalized_lineage",
    "quote_session_semantics",
    "receipt_price_fill_model",
    "outcome_finality",
    "instrument_cost_applicability",
)
BAR_COLUMNS = [
    "timeframe",
    "opened_at_utc",
    "closed_at_utc",
    "available_at_utc",
    "revision",
    "finality",
]


class AdmissionError(ValueError):
    def __init__(self, code, diagnostics=None):
        super().__init__(code)
        self.diagnostics = diagnostics


class Source:
    """Owned by the loader. Detached contexts are authenticated against frozen hashes."""

    def __init__(
        self,
        dataset,
        bundle,
        contents,
        quotes,
        availability,
        binding,
        *,
        historical=True
    ):
        self._dataset = deepcopy(dataset)
        self._bundle, self._contents = deepcopy(bundle), dict(contents)
        self._quotes, self._availability = deepcopy(quotes), deepcopy(availability)
        self._contexts = {}
        self._historical = historical
        self._provenance = "HISTORICAL_RESEARCH" if historical else "SYNTHETIC_RESEARCH"
        self._dataset_id, self._binding = digest(dataset.metadata), binding
        self._price_basis = dataset.metadata["lineage"]["price_basis"]
        self._policies = deepcopy(baseline())
        s = strict_json(contents["specification"])
        c = strict_json(contents["costs"])
        self._specification = BrokerSpecification(
            **s["values"],
            symbol="XAUUSD",
            feed=bundle["feed_id"],
            source="E5:" + sha256(contents["specification"]).hexdigest()[:32],
            effective_at_utc=s["effective_from_utc"],
            expires_at_utc=s["effective_until_utc"],
            session_eligible=True,
            verification="INDEPENDENT_HISTORICAL_DOCUMENTS_BOUND"
        )
        self._costs = SyntheticCosts(
            **c["values"], provenance="INDEPENDENT_HISTORICAL_DOCUMENTS_BOUND"
        )
        self._quote_index = {int(q["sequence"]): q for q in self._quotes}
        self._windows = deepcopy(bundle["windows"])
        self._sealed = True

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("E5 source snapshot is immutable")
        object.__setattr__(self, name, value)

    historical = property(lambda self: self._historical)
    provenance = property(lambda self: self._provenance)
    dataset_id = property(lambda self: self._dataset_id)
    binding = property(lambda self: self._binding)
    price_basis = property(lambda self: self._price_basis)
    policies = property(lambda self: deepcopy(self._policies))
    windows = property(lambda self: deepcopy(self._windows))
    specification = property(lambda self: self._specification)
    costs = property(lambda self: self._costs)

    def __deepcopy__(self, memo):
        # Context/session forks share an immutable source snapshot, not a copied capability.
        return self

    def authenticates_specification(self, value):
        return canonical(value) == canonical(self.specification)

    def authenticates_costs(self, value):
        return canonical(value) == canonical(self.costs)

    def permissions(self, occurred, available):
        cal = self._dataset.calendar
        a, b = cal.public_state(utc(occurred)), cal.public_state(utc(available))
        require(
            a["verification"] != "BLOCKED" and b["verification"] != "BLOCKED",
            "E5_SESSION_UNVERIFIED",
        )
        x, y = a["permissions"], b["permissions"]
        require(x["market_data_expected"] is True, "E5_QUOTE_SESSION_CONFLICT")
        require(
            x["broker_permissions_verified"] and y["broker_permissions_verified"],
            "E5_TRADE_PHASE_UNKNOWN",
        )
        return (
            y["market_data_expected"] is True,
            x["broker_open_positions"] is True and y["broker_open_positions"] is True,
        )

    def authenticates_quote(self, q):
        row = self._quote_index.get(q.sequence)
        if row is None:
            return False
        quotation, opening = self.permissions(
            row["occurred_at_utc"], row["available_at_utc"]
        )
        return (
            q.version == 1
            and q.provenance == self.provenance
            and q.symbol == "XAUUSD"
            and q.feed == self._bundle["feed_id"]
            and q.occurred_at_utc == row["occurred_at_utc"]
            and q.available_at_utc == row["available_at_utc"]
            and q.bid == row["bid"]
            and q.ask == row["ask"]
            and q.quotation_eligible is quotation
            and q.new_position_eligible is (quotation and opening)
        )

    def authenticates_context(self, context):
        return context.provenance == self.provenance and self._contexts.get(
            context.analysis_at
        ) == digest(context.to_dict())

    def context(self, at):
        now = utc(at)
        rows = {}
        for tf in ("M1", "M5"):
            rows[tf] = [
                deepcopy(r)
                for r in self._dataset.rows[tf]
                if utc(self._availability[(tf, r["timestamp"])]["available_at_utc"])
                <= now
            ]
        c = context_at(
            "XAUUSD",
            rows["M1"],
            rows["M5"],
            now,
            config=ContextConfig(),
            intelligence_config=IntelligenceConfig(),
            calendar=self._dataset.calendar,
            observed_finality=True,
            provenance=self.provenance,
        )
        self._contexts[c.analysis_at] = digest(c.to_dict())
        inputs = dict(session_snapshot=self._dataset.calendar.public_state(now))
        return c, build_market_view_v3(c, **inputs), inputs

    def quote_rows(self):
        return deepcopy(self._quotes)

    def close_times(self):
        return [
            self._availability[("M1", r["timestamp"])]["closed_at_utc"]
            for r in self._dataset.rows["M1"]
        ]

    def metadata(self):
        return deepcopy(self._dataset.metadata)


def bar_availability(raw, dataset):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
    require(reader.fieldnames == BAR_COLUMNS, "E5_BAR_AVAILABILITY_COLUMNS_REQUIRED")
    out = {}
    expected = {(tf, r["timestamp"]) for tf in ("M1", "M5") for r in dataset.rows[tf]}
    previous = {}
    for row in reader:
        exact(row, BAR_COLUMNS)
        tf = row["timeframe"]
        require(tf in ("M1", "M5"), "E5_BAR_FRAME_UNSUPPORTED")
        opening, closing, available = map(
            utc, (row["opened_at_utc"], row["closed_at_utc"], row["available_at_utc"])
        )
        key = (tf, opening.isoformat())
        require(
            key in expected and key not in out, "E5_BAR_DUPLICATE_OR_SOURCE_MISMATCH"
        )
        require(tf not in previous or opening > previous[tf], "E5_BAR_ORDER_INVALID")
        previous[tf] = opening
        require(
            closing == opening + timedelta(minutes=1 if tf == "M1" else 5)
            and available >= closing,
            "E5_BAR_CLOSE_OR_AVAILABILITY_INVALID",
        )
        require(
            row["finality"] == "FINAL" and row["revision"] == "0",
            "E5_BAR_CORRECTION_OR_FINALITY_UNSUPPORTED",
        )
        geometry = dataset.calendar.classify_bar(
            opening, tf, observed_finalized=True, research=True, as_of=available
        )
        require(
            geometry["classification"] == "FULL_SESSION_BAR",
            "E5_PARTIAL_OR_UNKNOWN_BAR_UNSUPPORTED",
        )
        out[key] = dict(
            row,
            opened_at_utc=opening.isoformat(),
            closed_at_utc=closing.isoformat(),
            available_at_utc=available.isoformat(),
        )
    require(set(out) == expected, "E5_BAR_AVAILABILITY_INCOMPLETE")
    return out


def _review(raw, plan_raw, root, bundle):
    r = strict_json(raw)
    exact(
        r,
        (
            "version",
            "kind",
            "preparer_code",
            "reviewer_code",
            "independently_reviewed",
            "decision",
            "reviewed_at_utc",
            "plan_sha256",
            "protocol_sha256",
            "assertions",
        ),
    )
    require(
        type(r["version"]) is int
        and r["version"] == 1
        and r["kind"] == "E5_INDEPENDENT_ADAPTER_REVIEW",
        "E5_REVIEW_VERSION_INVALID",
    )
    require(
        r["independently_reviewed"] is True
        and r["decision"] == "APPROVED"
        and r["preparer_code"] == bundle["preparer_code"]
        and type(r["reviewer_code"]) is str
        and r["reviewer_code"].strip()
        and r["reviewer_code"] != r["preparer_code"],
        "E5_INDEPENDENT_ADAPTER_REVIEW_REQUIRED",
    )
    require(
        utc(r["reviewed_at_utc"]) >= utc(bundle["reviewed_at_utc"]),
        "E5_REVIEW_CLOCK_INVALID",
    )
    require(
        r["plan_sha256"] == sha256(plan_raw).hexdigest()
        and r["protocol_sha256"] == protocol()["sha256"],
        "E5_REVIEW_BINDING_INVALID",
    )
    exact(r["assertions"], ASSERTIONS)
    first = min(utc(v["start"]) for v in bundle["windows"]["warmup"].values())
    last = utc(bundle["windows"]["outcome"]["end"])
    for ref in r["assertions"].values():
        exact(ref, ("status", "file", "sha256", "scope"))
        require(
            ref["status"] == "VERIFIED"
            and utc(ref["scope"]["start"]) <= first
            and utc(ref["scope"]["end"]) >= last,
            "E5_REVIEW_ASSERTION_INCOMPLETE",
        )
        bound_file(root, {k: ref[k] for k in ("file", "sha256")})
    return r


def quote_gap_audit(quotes, calendar, max_gap_ms):
    """Known no-quote windows explain evidence gaps, not frozen account overnight exits."""
    scheduled = unexpected = 0
    for x, y in zip(quotes, quotes[1:]):
        a, b = utc(x["available_at_utc"]), utc(y["available_at_utc"])
        if (b - a).total_seconds() * 1000 <= max_gap_ms:
            continue
        portions = [
            (max(a, s), min(b, e)) for s, e in calendar.windows if max(a, s) < min(b, e)
        ]
        if any((e - s).total_seconds() * 1000 > max_gap_ms for s, e in portions):
            unexpected += 1
        else:
            scheduled += 1
    return dict(
        scheduled_closure_gaps=scheduled,
        unexpected_open_session_gaps=unexpected,
        caveat="KNOWN_CLOSURES_DO_NOT_RELAX_FROZEN_PAPER_GAP_OR_ANALYSIS_AGE_POLICIES",
    )


def warmup_audit(dataset, availability, evaluation_start):
    c, i = ContextConfig(), IntelligenceConfig()
    required = max(
        c.atr_period + 1,
        c.roc_period + 2,
        2 * c.range_period,
        i.range_window + 1,
        i.left_strength + i.right_strength + 1,
        i.trend_window + 1,
    )
    counts = {
        tf: sum(
            utc(availability[(tf, r["timestamp"])]["closed_at_utc"])
            <= utc(evaluation_start)
            and utc(availability[(tf, r["timestamp"])]["available_at_utc"])
            <= utc(evaluation_start)
            for r in dataset.rows[tf]
        )
        for tf in ("M1", "M5")
    }
    require(
        all(n >= required for n in counts.values()),
        "E5_WARMUP_UNAVAILABLE_OR_INSUFFICIENT",
    )
    return dict(
        required_closed_bars_per_frame=required,
        available_closed_bars=counts,
        structural_evidence="CONFIRMED_PIVOTS_AND_ZONES_STILL_REQUIRED_BY_UNCHANGED_DETECTORS",
    )


@financial_context
def load_source(plan_path, adapter_review_path):
    """Only admission route. Never creates or signs independent approvals."""
    require(
        plan_path is not None and adapter_review_path is not None,
        "E5_PLAN_AND_INDEPENDENT_REVIEW_REQUIRED",
    )
    root = Path(plan_path).resolve().parent
    raw = read_bytes(plan_path)
    plan = strict_json(raw)
    exact(plan, ("version", "protocol_sha256", "inputs"))
    require(
        type(plan["version"]) is int
        and plan["version"] == 1
        and plan["protocol_sha256"] == protocol()["sha256"],
        "E5_PROTOCOL_MISMATCH",
    )
    exact(plan["inputs"], PLAN_INPUTS)
    # Read/check every actual artifact before any qualified capability exists.
    snapshots = {}
    for key, ref in plan["inputs"].items():
        try:
            snapshots[key] = bound_file(root, ref)
        except (ValueError, TypeError, KeyError, OSError):
            raise AdmissionError(
                "E5_INPUT_" + key.upper() + "_UNAVAILABLE_OR_HASH_MISMATCH",
                {"input_role": key},
            ) from None
    paths = {k: root / v["file"] for k, v in plan["inputs"].items()}
    try:
        review_raw = read_bytes(adapter_review_path)
    except (ValueError, OSError):
        raise AdmissionError("E5_INDEPENDENT_ADAPTER_REVIEW_UNAVAILABLE") from None
    ready = historical_paper_preflight(
        paths["manifest"], paths["review"], paths["paper_bundle"]
    )
    allowed = {
        "E5_REVIEWED_RECEIPT_AND_SESSION_ADAPTER_REQUIRED",
        "E5_OUTCOME_CANDLE_COVERAGE_ADAPTER_REQUIRED",
        "E5_RAW_NORMALIZED_LINEAGE_ADAPTER_REQUIRED",
        "PAPER_QUOTE_GAPS_UNRESOLVED",
    }
    if (
        ready["input_checks_status"] != "DOCUMENT_AND_MECHANICAL_CHECKS_PASSED"
        or not set(ready["reason_codes"]) <= allowed
    ):
        raise AdmissionError("E5_E47_SOURCE_OR_BUNDLE_NOT_QUALIFIED", ready)
    require(
        ready["bundle_sha256"] == sha256(snapshots["paper_bundle"]).hexdigest(),
        "E5_BUNDLE_CHANGED_DURING_QUALIFICATION",
    )
    q = qualify_historical(paths["outcome_manifest"], paths["outcome_review"])
    if q["status"] != "HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED":
        raise AdmissionError("E5_OUTCOME_DATA_NOT_QUALIFIED", q)
    require(
        ready["source_qualification"]["human_review_sha256"]
        == sha256(snapshots["review"]).hexdigest()
        and q["human_review_sha256"] == sha256(snapshots["outcome_review"]).hexdigest(),
        "E5_QUALIFICATION_REVIEW_BYTES_MISMATCH",
    )
    data, extended = load_dataset(paths["manifest"]), load_dataset(
        paths["outcome_manifest"]
    )
    bundle = strict_json(snapshots["paper_bundle"])
    m, n = data.metadata, extended.metadata
    require(
        digest(m) == ready["source_qualification"]["dataset_id"]
        and digest(n) == q["dataset_id"],
        "E5_SOURCE_CHANGED",
    )
    require(
        m["lineage"]["m5_origin"] == n["lineage"]["m5_origin"] == "NATIVE_SAME_FEED"
        and m["lineage"]["feed_id"] == n["lineage"]["feed_id"] == bundle["feed_id"]
        and m["lineage"]["price_basis"] == n["lineage"]["price_basis"]
        and m["session_config_sha256"] == n["session_config_sha256"]
        and m["warmup"] == n["warmup"]
        and m["evaluation"]["start"] == n["evaluation"]["start"]
        and utc(n["evaluation"]["end"]) == utc(bundle["windows"]["outcome"]["end"]),
        "E5_OUTCOME_LINEAGE_MISMATCH",
    )
    for tf, minutes in (("M1", 1), ("M5", 5)):
        prefix = [
            r
            for r in extended.rows[tf]
            if utc(r["timestamp"]) + timedelta(minutes=minutes)
            <= utc(m["evaluation"]["end"])
        ]
        require(prefix == data.rows[tf], "E5_OUTCOME_PREFIX_MISMATCH")
    _review(
        review_raw,
        raw,
        Path(adapter_review_path).resolve().parent,
        bundle,
    )
    contents = {
        k: bound_file(paths["paper_bundle"].parent, v)
        for k, v in bundle["artifacts"].items()
    }
    require(
        {k: sha256(v).hexdigest() for k, v in contents.items()} == ready["artifacts"],
        "E5_ARTIFACT_CHANGED_DURING_QUALIFICATION",
    )
    require(
        strict_json(contents["policies"]) == baseline(), "E5_FROZEN_POLICY_MISMATCH"
    )
    _, spec = _spec(paths["import_spec"])
    require(
        spec["dataset_kind"] == "INDEPENDENT_HISTORICAL", "E5_RAW_PROVENANCE_MISMATCH"
    )
    require(
        spec["source"]["feed_id"] == bundle["feed_id"]
        and spec["source"]["price_basis"] == m["lineage"]["price_basis"],
        "E5_RAW_LINEAGE_MISMATCH",
    )
    require(
        spec["preparer_code"] == bundle["preparer_code"],
        "E5_PREPARER_IDENTITY_MISMATCH",
    )
    for role in ("review", "outcome_review"):
        human = strict_json(snapshots[role])
        require(
            type(human.get("reviewer_code")) is str
            and human["reviewer_code"].strip()
            and human["reviewer_code"] != bundle["preparer_code"]
            and human.get("independent_review_attested") is True
            and human.get("decision") == "APPROVED"
            and human.get("provider_entity") == spec["source"]["provider_entity"],
            "E5_INDEPENDENT_PROVIDER_REVIEW_MISMATCH",
        )
    for tf in ("M1", "M5"):
        f = spec["frames"][tf]
        require(
            f["feed_id"] == bundle["feed_id"]
            and f["price_basis"] == m["lineage"]["price_basis"]
            and f["origin"] == "NATIVE_SAME_FEED"
            and f["corrections"]["status"] == "NO_KNOWN_CORRECTIONS_DECLARED"
            and f["finality"]["policy"]
            in ("PER_ROW_BOOLEAN", "DOCUMENTED_CLOSED_EXPORT")
            and type(f["finality"]["reference"]) is str
            and f["finality"]["reference"].strip(),
            "E5_RAW_METADATA_UNSUPPORTED",
        )
        rows, _, complete = _parse_frame(
            contents["raw_" + tf.lower()], f, spec["source"]
        )
        require(
            rows == extended.rows[tf] and all(complete),
            "E5_RAW_NORMALIZED_MISMATCH_OR_UNFINISHED",
        )
    availability = bar_availability(snapshots["bar_availability"], extended)
    warmup = warmup_audit(extended, availability, m["evaluation"]["start"])
    first = min(utc(v["start"]) for v in m["warmup"].values()).isoformat()
    audit = audit_quote_events(
        contents["quote_events"], start=first, end=bundle["windows"]["outcome"]["end"]
    )
    require(
        len(extended.rows["M1"]) <= protocol()["resources"]["max_m1_snapshots"]
        and audit["count"] <= protocol()["resources"]["max_quotes"],
        "E5_BOUNDED_WINDOW_REQUIRED",
    )
    quotes = list(audit["rows"])
    quote_audit = quote_bar_audit(
        extended, [Quote(r["occurred_at_utc"], r["bid"], r["ask"]) for r in quotes]
    )
    require(
        not quote_audit["missing_quote_groups"] and not quote_audit["ohlc_mismatches"],
        "E5_NATIVE_QUOTES_OHLC_MISMATCH",
    )
    binding = digest(
        [
            sha256(raw).hexdigest(),
            sha256(review_raw).hexdigest(),
            ready["sha256"],
            q,
            quote_audit,
            protocol()["sha256"],
        ]
    )
    source = Source(extended, bundle, contents, quotes, availability, binding)
    # Validate each declared quote phase, and reject unexplained missing open-session capture.
    for row in quotes:
        source.permissions(row["occurred_at_utc"], row["available_at_utc"])
    gap_audit = quote_gap_audit(
        quotes, source._dataset.calendar, baseline()["fill"]["max_gap_ms"]
    )
    require(
        not gap_audit["unexpected_open_session_gaps"],
        "E5_UNVERIFIED_OPEN_SESSION_QUOTE_GAP",
    )
    for key, path in paths.items():
        require(
            read_bytes(path) == snapshots[key], "E5_SOURCE_CHANGED_DURING_ADMISSION"
        )
    require(
        read_bytes(plan_path) == raw and read_bytes(adapter_review_path) == review_raw,
        "E5_REVIEW_OR_PLAN_CHANGED_DURING_ADMISSION",
    )
    for key, ref in bundle["artifacts"].items():
        require(
            bound_file(paths["paper_bundle"].parent, ref) == contents[key],
            "E5_ARTIFACT_CHANGED_DURING_ADMISSION",
        )
    return _register_source(source), dict(
        readiness=ready,
        outcome_qualification=q,
        quote_bar_audit=quote_audit,
        quote_gap_audit=gap_audit,
        warmup_audit=warmup,
        plan_sha256=sha256(raw).hexdigest(),
        binding=binding,
    )
