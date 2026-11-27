"""R1 offline interval contracts. No detector, broker, account or live integration."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
import json
import re
from iat.analysis import validate_candles


class FoundationError(ValueError):
    """Only fixed reason codes, never provider/configuration contents."""


def need(condition, code):
    if not condition:
        raise FoundationError(code)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def keys(value, expected):
    need(
        type(value) is dict
        and len(value) == len(expected.split())
        and all(type(k) is str for k in value)
        and set(value) == set(expected.split()),
        "SCHEMA_INVALID",
    )


def label(value):
    need(
        type(value) is str
        and re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", value) is not None,
        "IDENTIFIER_INVALID",
    )
    return value


def checksum(value):
    need(
        type(value) is str and re.fullmatch("[a-f0-9]{64}", value) is not None,
        "SHA256_REQUIRED",
    )
    return value


def utc(value):
    need(type(value) is str and len(value) <= 40, "UTC_TIMESTAMP_REQUIRED")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        raise FoundationError("UTC_TIMESTAMP_INVALID") from None
    need(result.utcoffset() == timedelta(0), "EXPLICIT_UTC_REQUIRED")
    return result.astimezone(timezone.utc)


def strict_json(raw):
    need(type(raw) is bytes and 0 < len(raw) <= 65536, "DOCUMENT_BYTES_LIMIT")

    def unique(pairs):
        result = {}
        for k, v in pairs:
            need(k not in result, "DUPLICATE_JSON_KEY")
            result[k] = v
        return result

    def constant(_):
        raise FoundationError("NONFINITE_JSON")

    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=constant
        )
    except FoundationError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise FoundationError("DOCUMENT_INVALID") from None


class FrameName(str, Enum):
    M1 = "M1"
    M3 = "M3"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"
    MN1 = "MN1"
    TICK = "TICK"


FIXED_SECONDS = MappingProxyType(
    {
        FrameName.M1: 60,
        FrameName.M3: 180,
        FrameName.M5: 300,
        FrameName.M15: 900,
        FrameName.M30: 1800,
        FrameName.H1: 3600,
        FrameName.H4: 14400,
    }
)


def fixed_frame(value):
    need(type(value) is str or type(value) is FrameName, "FRAME_NAME_INVALID")
    try:
        frame = FrameName(value)
    except ValueError:
        raise FoundationError("FRAME_UNKNOWN") from None
    need(
        frame not in (FrameName.D1, FrameName.W1, FrameName.MN1),
        "CALENDAR_SEMANTICS_REQUIRED",
    )
    need(frame is not FrameName.TICK, "TICK_IS_NOT_OHLC")
    return frame


@dataclass(frozen=True)
class FrameDefinition:
    name: FrameName
    version: int = 1

    def __post_init__(self):
        need(type(self.name) is FrameName, "TYPED_FRAME_REQUIRED")
        fixed_frame(self.name)
        need(type(self.version) is int and self.version == 1, "VERSION_UNSUPPORTED")

    @property
    def seconds(self):
        return FIXED_SECONDS[self.name]


@dataclass(frozen=True)
class EvidenceDocument:
    """Exact immutable source bytes, not independent approval or broker certification."""

    payload: bytes

    def __post_init__(self):
        d = strict_json(self.payload)
        keys(d, "version kind available_at_utc claims")
        need(type(d["version"]) is int and d["version"] == 1, "VERSION_UNSUPPORTED")
        need(
            d["kind"] in ("SOURCE", "INTERVAL", "CALENDAR", "FINALITY"),
            "EVIDENCE_KIND_UNSUPPORTED",
        )
        utc(d["available_at_utc"])
        c = d["claims"]
        if d["kind"] == "SOURCE":
            keys(c, "provider feed symbol price_basis provenance source_revision")
            for k in ("provider", "feed", "symbol", "source_revision"):
                label(c[k])
            need(c["symbol"] == "XAUUSD", "SYMBOL_UNSUPPORTED")
            need(c["price_basis"] in ("BID", "ASK", "MID"), "PRICE_BASIS_REQUIRED")
            need(
                c["provenance"] in ("SYNTHETIC_FIXTURE", "DECLARED_OFFLINE"),
                "PROVENANCE_UNSUPPORTED",
            )
        elif d["kind"] == "INTERVAL":
            keys(
                c,
                "source_sha256 frame provider_frame mapping duration_seconds anchor_utc grid_timezone valid_from_utc valid_until_utc bar_policy",
            )
            checksum(c["source_sha256"])
            frame = fixed_frame(c["frame"])
            need(c["provider_frame"] == frame.value, "PROVIDER_MAPPING_UNSUPPORTED")
            need(c["mapping"] == "FIXED_UTC_GRID_V1", "PROVIDER_MAPPING_UNSUPPORTED")
            need(
                type(c["duration_seconds"]) is int
                and c["duration_seconds"] == FIXED_SECONDS[frame],
                "DURATION_CONFLICT",
            )
            need(c["grid_timezone"] == "UTC", "LOCAL_TIME_GRID_UNSUPPORTED")
            need(utc(c["anchor_utc"]).microsecond == 0, "ANCHOR_AMBIGUOUS")
            need(
                utc(c["valid_from_utc"]) < utc(c["valid_until_utc"]), "COVERAGE_INVALID"
            )
            need(
                c["bar_policy"] == "FULL_QUOTATION_INTERVALS_ONLY",
                "PARTIAL_BAR_POLICY_UNSUPPORTED",
            )
        elif d["kind"] == "FINALITY":
            keys(c, "source_sha256 interval_sha256 policy correction_policy")
            checksum(c["source_sha256"])
            checksum(c["interval_sha256"])
            need(
                c["policy"] == "EXPLICIT_FINAL_CLOSE_AND_AVAILABILITY",
                "FINALITY_POLICY_REQUIRED",
            )
            need(
                c["correction_policy"] == "REVISION_BOUND_NO_RETROSPECTIVE_REWRITE",
                "CORRECTION_POLICY_REQUIRED",
            )
        else:
            keys(c, "source_sha256 coverage_start_utc coverage_end_utc phases")
            checksum(c["source_sha256"])
            start = utc(c["coverage_start_utc"])
            end = utc(c["coverage_end_utc"])
            need(start < end, "COVERAGE_INVALID")
            phases = c["phases"]
            need(type(phases) is list and 1 <= len(phases) <= 512, "PHASE_LIMIT")
            cursor = start
            for p in phases:
                keys(p, "start_utc end_utc quotations new_positions")
                a, b = utc(p["start_utc"]), utc(p["end_utc"])
                need(a == cursor and a < b <= end, "SESSION_COVERAGE_AMBIGUOUS")
                need(
                    p["quotations"] in ("OPEN", "CLOSED", "UNKNOWN")
                    and p["new_positions"] in ("ALLOWED", "DISALLOWED", "UNKNOWN"),
                    "SESSION_PHASE_INVALID",
                )
                need(
                    p["quotations"] == "OPEN" or p["new_positions"] != "ALLOWED",
                    "SESSION_PHASE_CONFLICT",
                )
                if p["quotations"] == "UNKNOWN":
                    need(p["new_positions"] == "UNKNOWN", "SESSION_PHASE_CONFLICT")
                cursor = b
            need(cursor == end, "SESSION_COVERAGE_AMBIGUOUS")

    @property
    def sha256(self):
        return sha256(self.payload).hexdigest()

    def data(self):
        return strict_json(
            self.payload
        )  # Fresh copy; never expose mutable proof state.


@dataclass(frozen=True)
class EvidenceStore:
    documents: tuple[EvidenceDocument, ...]

    def __post_init__(self):
        need(
            type(self.documents) is tuple and len(self.documents) <= 64,
            "EVIDENCE_LIMIT",
        )
        need(
            all(type(d) is EvidenceDocument for d in self.documents),
            "TYPED_EVIDENCE_REQUIRED",
        )
        need(
            len({d.sha256 for d in self.documents}) == len(self.documents),
            "DUPLICATE_EVIDENCE",
        )

    def get(self, sha, kind):
        checksum(sha)
        for doc in self.documents:
            if doc.sha256 == sha:
                d = doc.data()
                need(d["kind"] == kind, "EVIDENCE_KIND_MISMATCH")
                return d
        raise FoundationError("EVIDENCE_BYTES_UNAVAILABLE")


@dataclass(frozen=True)
class FrameBinding:
    frame: FrameName
    source_sha256: str
    interval_sha256: str
    calendar_sha256: str
    finality_sha256: str
    required_closed_bars: int
    max_slots: int
    version: int = 1

    def __post_init__(self):
        FrameDefinition(self.frame, self.version)
        for v in (
            self.source_sha256,
            self.interval_sha256,
            self.calendar_sha256,
            self.finality_sha256,
        ):
            checksum(v)
        need(
            type(self.required_closed_bars) is int
            and 3 <= self.required_closed_bars <= 5000,
            "HISTORY_POLICY_INVALID",
        )
        need(
            type(self.max_slots) is int
            and self.required_closed_bars <= self.max_slots <= 10000,
            "RESOURCE_POLICY_INVALID",
        )

    @property
    def sha256(self):
        return digest(asdict(self))

    def resolve(self, opened_at_utc, evidence):
        need(type(evidence) is EvidenceStore, "TYPED_EVIDENCE_REQUIRED")
        _, interval, _, _ = bound_documents(self, evidence)
        return _resolve_fixed(self, interval["claims"], opened_at_utc)

    def interval(self, opened_at_utc, evidence):
        opened, closed = self.resolve(opened_at_utc, evidence)
        return FixedInterval(self.frame, opened, closed, self.sha256)


@dataclass(frozen=True)
class FixedInterval:
    """Resolved nominal bounds only; not finality or analysis authorization."""

    frame: FrameName
    opened_at_utc: datetime
    closed_at_utc: datetime
    binding_sha256: str
    version: int = 1

    def __post_init__(self):
        FrameDefinition(self.frame, self.version)
        checksum(self.binding_sha256)
        need(
            all(
                type(v) is datetime and v.utcoffset() == timedelta(0)
                for v in (self.opened_at_utc, self.closed_at_utc)
            ),
            "EXPLICIT_UTC_REQUIRED",
        )
        need(
            self.closed_at_utc - self.opened_at_utc
            == timedelta(seconds=FIXED_SECONDS[self.frame]),
            "CLOSE_CONFLICT",
        )


def _resolve_fixed(binding, c, opened_at_utc):
    opened = utc(opened_at_utc)
    need(
        utc(c["valid_from_utc"]) <= opened < utc(c["valid_until_utc"]),
        "INTERVAL_COVERAGE_UNKNOWN",
    )
    delta = opened - utc(c["anchor_utc"])
    micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    need(micros % (FIXED_SECONDS[binding.frame] * 1000000) == 0, "TIMEFRAME_MISALIGNED")
    closed = opened + timedelta(seconds=FIXED_SECONDS[binding.frame])
    need(closed <= utc(c["valid_until_utc"]), "INTERVAL_COVERAGE_UNKNOWN")
    return opened, closed


def bound_documents(binding, evidence):
    docs = [
        evidence.get(getattr(binding, k + "_sha256"), kind)
        for k, kind in (
            ("source", "SOURCE"),
            ("interval", "INTERVAL"),
            ("calendar", "CALENDAR"),
            ("finality", "FINALITY"),
        )
    ]
    source, interval, calendar, finality = docs
    for d in (interval, calendar, finality):
        need(
            d["claims"]["source_sha256"] == binding.source_sha256,
            "SOURCE_BINDING_CONFLICT",
        )
    need(interval["claims"]["frame"] == binding.frame.value, "FRAME_BINDING_CONFLICT")
    need(
        finality["claims"]["interval_sha256"] == binding.interval_sha256,
        "FINALITY_BINDING_CONFLICT",
    )
    return tuple(docs)


@dataclass(frozen=True)
class TimeframeProfile:
    """No implicit enabled frames. This profile is never consumed by legacy APIs."""

    bindings: tuple[FrameBinding, ...] = ()
    edges: tuple[tuple[FrameName, FrameName], ...] = ()
    version: int = 1

    def __post_init__(self):
        need(type(self.version) is int and self.version == 1, "VERSION_UNSUPPORTED")
        need(
            type(self.bindings) is tuple
            and len(self.bindings) <= 7
            and all(type(b) is FrameBinding for b in self.bindings),
            "BINDINGS_INVALID",
        )
        names = [b.frame for b in self.bindings]
        need(len(set(names)) == len(names), "DUPLICATE_FRAME")
        need(type(self.edges) is tuple and len(self.edges) <= 42, "EDGES_INVALID")
        for edge in self.edges:
            need(
                type(edge) is tuple
                and len(edge) == 2
                and all(type(f) is FrameName and f in names for f in edge),
                "EDGE_FRAME_INVALID",
            )
            need(edge[0] != edge[1], "ROLE_GRAPH_CYCLE")
        need(len(set(self.edges)) == len(self.edges), "DUPLICATE_EDGE")

        def visit(node, path):
            need(node not in path, "ROLE_GRAPH_CYCLE")
            for parent, child in self.edges:
                if parent == node:
                    visit(child, path + (node,))

        for name in names:
            visit(name, ())

    @property
    def sha256(self):
        return digest(asdict(self))

    def binding(self, frame):
        frame = fixed_frame(frame)
        for b in self.bindings:
            if b.frame == frame:
                return b
        raise FoundationError("FRAME_NOT_ENABLED")

    @classmethod
    def from_json(cls, raw, *, evidence):
        need(type(evidence) is EvidenceStore, "TYPED_EVIDENCE_REQUIRED")
        d = strict_json(raw)
        keys(d, "version bindings edges")
        need(
            type(d["bindings"]) is list and len(d["bindings"]) <= 7, "BINDINGS_INVALID"
        )
        bindings = []
        for raw_binding in d["bindings"]:
            keys(
                raw_binding,
                "version frame source_sha256 interval_sha256 calendar_sha256 finality_sha256 required_closed_bars max_slots",
            )
            binding = FrameBinding(
                **dict(raw_binding, frame=fixed_frame(raw_binding["frame"]))
            )
            bound_documents(binding, evidence)
            bindings.append(binding)
        need(type(d["edges"]) is list and len(d["edges"]) <= 42, "EDGES_INVALID")
        edges = []
        for edge in d["edges"]:
            need(type(edge) is list and len(edge) == 2, "EDGES_INVALID")
            edges.append(tuple(fixed_frame(v) for v in edge))
        profile = cls(tuple(bindings), tuple(edges), d["version"])
        _profile_documents(profile, evidence)
        return profile


def _profile_documents(profile, evidence):
    """A single profile cannot silently combine incompatible feed/price bases."""
    docs = {b.frame: bound_documents(b, evidence) for b in profile.bindings}
    identities = {
        tuple(
            packet[0]["claims"][key]
            for key in ("provider", "feed", "symbol", "price_basis", "provenance")
        )
        for packet in docs.values()
    }
    need(len(identities) <= 1, "PROFILE_SOURCE_CONFLICT")
    return docs


SAFETY = MappingProxyType(
    dict(
        mode="READ_ONLY_SHADOW",
        signal="WAIT",
        execution_allowed=False,
        exness="BLOCKED",
        qualification="DATA_NOT_QUALIFIED",
        historical_validation="PENDING",
        historical_comparisons="NOT_RUN",
    )
)


def report(**fields):
    value = dict(
        foundation_version=1,
        model_version="IAT_FIXED_INTERVAL_FOUNDATION_V1",
        **fields,
        **SAFETY
    )
    return dict(value, sha256=digest(value))


def _phase_for(start, end, phases):
    relevant = [p for p in phases if p[0] < end and p[1] > start]
    states = {p[2] for p in relevant}
    need(relevant and "UNKNOWN" not in states, "SESSION_COVERAGE_UNKNOWN")
    if states == {"OPEN"}:
        return "OPEN"
    if states == {"CLOSED"}:
        return "CLOSED"
    raise FoundationError("PARTIAL_SESSION_INTERVAL_UNSUPPORTED")


def assess_closed_prefix(
    *, profile, evidence, frame, rows, window_start_utc, as_of_utc
):
    """Mechanical synthetic eligibility only, never historical qualification.

    Inspect the ordered consumed prefix; future/forming payloads are not inspected.
    Missing expected full-quotation slots (including leading/trailing) fail closed.
    """
    try:
        need(
            type(profile) is TimeframeProfile and type(evidence) is EvidenceStore,
            "TYPED_CONFIGURATION_REQUIRED",
        )
        binding = profile.binding(frame)
        packets = _profile_documents(profile, evidence)
        source, interval, calendar, finality = packets[binding.frame]
        now = utc(as_of_utc)
        start, first_close = _resolve_fixed(
            binding, interval["claims"], window_start_utc
        )
        need(
            start < now < utc(interval["claims"]["valid_until_utc"]),
            "INTERVAL_COVERAGE_UNKNOWN",
        )
        for d in (item for packet in packets.values() for item in packet):
            need(utc(d["available_at_utc"]) <= now, "CONFIGURATION_NOT_AVAILABLE_AS_OF")
        cal = calendar["claims"]
        need(
            utc(cal["coverage_start_utc"])
            <= start
            < now
            < utc(cal["coverage_end_utc"]),
            "SESSION_COVERAGE_UNKNOWN",
        )
        need(
            source["claims"]["provenance"] == "SYNTHETIC_FIXTURE",
            "INDEPENDENT_QUALIFICATION_REQUIRED",
        )
        need(type(rows) in (list, tuple) and len(rows) <= 5000, "HISTORY_LIMIT")
        selected = []
        previous = None
        metadata = []
        for row in rows:
            need(
                type(row) is dict
                and all(type(k) is str for k in row)
                and "opened_at_utc" in row,
                "BAR_SCHEMA_INVALID",
            )
            opened = utc(row["opened_at_utc"])
            if opened > now:
                break
            opened, closed = _resolve_fixed(
                binding, interval["claims"], row["opened_at_utc"]
            )
            if closed > now:
                break
            need(opened >= start, "BAR_OUTSIDE_WINDOW")
            need(previous is None or opened > previous, "BAR_CHRONOLOGY_INVALID")
            keys(
                row,
                "frame provider_frame provider feed symbol price_basis source_sha256 opened_at_utc closed_at_utc available_at_utc finality revision open high low close",
            )
            need(
                all(
                    type(row[k]) is str
                    for k in (
                        "frame",
                        "provider_frame",
                        "provider",
                        "feed",
                        "symbol",
                        "price_basis",
                        "source_sha256",
                        "closed_at_utc",
                        "available_at_utc",
                        "finality",
                    )
                ),
                "BAR_SCHEMA_INVALID",
            )
            need(
                all(
                    type(row[k]) in (int, float, str)
                    and (type(row[k]) is not str or len(row[k]) <= 64)
                    for k in ("open", "high", "low", "close")
                ),
                "OHLC_INVALID",
            )
            need(utc(row["closed_at_utc"]) == closed, "CLOSE_CONFLICT")
            available = utc(row["available_at_utc"])
            need(available >= closed, "AVAILABILITY_PRECEDES_CLOSE")
            need(available <= now, "SOURCE_NOT_AVAILABLE_AS_OF")
            need(row["finality"] == "FINAL", "FINALITY_UNESTABLISHED")
            need(
                type(row["revision"]) is int and row["revision"] >= 0,
                "BAR_REVISION_INVALID",
            )
            need(
                row["frame"] == binding.frame.value
                and row["provider_frame"] == interval["claims"]["provider_frame"],
                "FRAME_BINDING_CONFLICT",
            )
            need(
                row["source_sha256"] == binding.source_sha256, "SOURCE_BINDING_CONFLICT"
            )
            need(
                all(
                    row[k] == source["claims"][k]
                    for k in ("provider", "feed", "symbol", "price_basis")
                ),
                "SOURCE_METADATA_CONFLICT",
            )
            selected.append(
                dict(
                    timestamp=opened.isoformat(),
                    **{k: row[k] for k in ("open", "high", "low", "close")}
                )
            )
            meta = dict(
                opened_at_utc=opened.isoformat(),
                closed_at_utc=closed.isoformat(),
                available_at_utc=available.isoformat(),
                revision=row["revision"],
            )
            interval_id = "MTF:R1:INTERVAL:" + digest(
                [
                    binding.source_sha256,
                    binding.interval_sha256,
                    opened.isoformat(),
                    closed.isoformat(),
                ]
            )
            metadata.append(dict(meta, interval_id=interval_id))
            previous = opened
        need(len(selected) >= binding.required_closed_bars, "HISTORY_INCOMPLETE")
        try:
            candles = validate_candles(selected)
        except (ValueError, TypeError, OverflowError):
            raise FoundationError("OHLC_INVALID") from None
        selected = [
            dict(
                timestamp=c.timestamp.isoformat(),
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
            )
            for c in candles
        ]
        for meta, row in zip(metadata, selected):
            meta["observation_id"] = "MTF:R1:OBSERVATION:" + digest(
                [meta, row, binding.finality_sha256]
            )
        phases = tuple(
            (
                utc(p["start_utc"]),
                utc(p["end_utc"]),
                p["quotations"],
                p["new_positions"],
            )
            for p in cal["phases"]
        )
        period = timedelta(seconds=FIXED_SECONDS[binding.frame])
        slots = int((now - start) // period)
        need(slots <= binding.max_slots, "INTERVAL_RESOURCE_LIMIT")
        expected = []
        closed_slots = 0
        for i in range(slots):
            a = start + i * period
            b = a + period
            state = _phase_for(a, b, phases)
            if state == "OPEN":
                expected.append(a.isoformat())
            else:
                closed_slots += 1
        actual = [r["timestamp"] for r in selected]
        need(actual == expected, "MISSING_OR_OUTSIDE_SESSION_BARS")
        phase = next((p for p in phases if p[0] <= now < p[1]), None)
        need(phase is not None and phase[2] != "UNKNOWN", "SESSION_COVERAGE_UNKNOWN")
        need(phase[2] == "OPEN", "SESSION_CLOSED")
        return report(
            status="ELIGIBLE_SYNTHETIC_ONLY",
            closed_prefix_valid=True,
            as_of_utc=now.isoformat(),
            frame=binding.frame.value,
            configuration_sha256=profile.sha256,
            binding_sha256=binding.sha256,
            evidence_sha256=[
                binding.source_sha256,
                binding.interval_sha256,
                binding.calendar_sha256,
                binding.finality_sha256,
            ],
            evidence_validation="EXACT_BYTES_AND_DECLARATIONS_NOT_INDEPENDENT_APPROVAL",
            source_scope="SYNTHETIC_FIXTURE_ONLY",
            bars=selected,
            intervals=metadata,
            selected_prefix_sha256=digest([selected, metadata]),
            closed_bar_count=len(selected),
            scheduled_closed_slots=closed_slots,
            new_position_permission=phase[3],
            reason_codes=[],
            limitations=[
                "NO_ANALYTICAL_OR_STRATEGY_AUTHORIZATION",
                "NO_HISTORICAL_BRIDGE",
                "FULL_QUOTATION_INTERVALS_ONLY",
            ],
        )
    except FoundationError as exc:
        return report(
            status="BLOCKED",
            closed_prefix_valid=False,
            reason_codes=[str(exc)],
            bars=[],
            intervals=[],
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        return report(
            status="BLOCKED",
            closed_prefix_valid=False,
            reason_codes=["QUALITY_UNESTABLISHED"],
            bars=[],
            intervals=[],
        )


def validate_foundation_report(value, **inputs):
    try:
        need(type(value) is dict, "FOUNDATION_REPORT_MISMATCH")
        encoded = canonical(value)
        need(len(encoded) <= 8 * 1024 * 1024, "FOUNDATION_REPORT_LIMIT")
        need(
            encoded == canonical(assess_closed_prefix(**inputs)),
            "FOUNDATION_REPORT_MISMATCH",
        )
    except FoundationError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise FoundationError("FOUNDATION_REPORT_MISMATCH") from None
    return True


def event_reference(*, original_event_id, original_source_sha256, configuration_sha256):
    """Reference identity only. Does not authenticate or relabel a legacy event."""
    need(
        type(original_event_id) is str
        and re.fullmatch(r"[A-Za-z0-9_:.-]{1,256}", original_event_id) is not None,
        "EVENT_ID_INVALID",
    )
    checksum(original_source_sha256)
    checksum(configuration_sha256)
    return report(
        reference_version=1,
        original_event_id=original_event_id,
        original_source_sha256=original_source_sha256,
        configuration_sha256=configuration_sha256,
        sidecar_id="MTF:R1:EVENT_REF:"
        + digest([original_event_id, original_source_sha256, configuration_sha256]),
        reference_only=True,
        source_authentication="NOT_ESTABLISHED_BY_REFERENCE",
    )
