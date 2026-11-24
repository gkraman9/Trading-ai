"""Isolated causal S/R rejection research. Never registered with strategy selection."""

from collections import Counter
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from iat.intelligence.context_models import ContextReport, ContextConfig
from iat.intelligence.market_view import (
    build_market_view_v3,
    validate_market_view_v3,
    SAFETY,
    plain,
)
from iat.intelligence.strategy_replay import digest
from iat.replay_dataset import utc

STRATEGY = "SR_REJECTION_M1_CONFIRMATION"
RULE = "1.0.0"
POLICY = dict(
    version=1,
    qualification="IMMEDIATELY_FOLLOWING_CLOSED_M1",
    expiry_eligible_closes=5,
    blocked="NO_LIFECYCLE_PROGRESS",
    expiry_clock="DISTINCT_OBSERVED_ELIGIBLE_M1_CLOSES_AFTER_C",
    rearm="DISTINCT_ZONE_AND_FIRST_TOUCH_CANDLE",
    simultaneous_paper_events="UNRESOLVED_EVENT_ORDER",
)
SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "config/sr-rejection-research-v1.schema.json"
    ).read_text()
)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    IndexError,
    OverflowError,
    RecursionError,
)


class SRInputError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise SRInputError(code)


def setup_id(symbol, direction, zone, touch):
    return "SRSETUP:" + digest([STRATEGY, RULE, symbol, direction, zone, touch])


def seal(value):
    value = plain(value)
    return dict(value, sha256=digest(value))


def empty_result():
    return dict(
        research_version=1,
        kind="SR_REJECTION_RESEARCH",
        strategy_id=STRATEGY,
        rule_version=RULE,
        validation_status="SYNTHETIC_ONLY",
        status="BLOCKED",
        symbol=None,
        evaluation_at_utc=None,
        provenance=None,
        bindings=dict(
            view=None,
            context=None,
            configuration_hashes={},
            policy=digest(POLICY),
            dataset=None,
        ),
        current_bar=None,
        current_opposition=dict(BULLISH=[], BEARISH=[]),
        evidence={},
        evaluations=[],
        reason_codes=[],
        restrictions={},
        **SAFETY
    )


def _opposition(context, direction):
    return sorted(
        e.id
        for e in context.evidence
        if e.category == "TRANSITION"
        and e.timeframe == "M1"
        and e.direction in ("BULLISH", "BEARISH")
        and e.direction != direction
        and e.available_at == context.observed_facts["M1"]["data_as_of"]
        and e.details.get("fresh") is True
        and e.details.get("event_type") == e.direction + "_CHOCH"
    )


def _zones(context):
    return sorted(
        (
            plain(z.__dict__)
            for tf, f in context.interpretations["frames"].items()
            for z in f["support_resistance"]
        ),
        key=lambda z: z["id"],
    )


def _frozen(z):
    return {
        k: z[k]
        for k in ("id", "kind", "timeframe", "lower", "upper", "confirmed_at", "status")
    }


def _touch(c, z):
    return c["ohlc"]["high"] >= z["lower"] and c["ohlc"]["low"] <= z["upper"]


def _evaluate(view, context, *, view_inputs=None, dataset=None):
    out = empty_result()
    validated_view = False
    try:
        need(isinstance(context, ContextReport), "TYPED_CONTEXT_REQUIRED")
        at = utc(context.analysis_at)
        out.update(
            symbol=context.symbol,
            evaluation_at_utc=context.analysis_at,
            provenance=context.provenance,
        )
        validate_market_view_v3(view, context_report=context, **(view_inputs or {}))
        validated_view = True
        need(view["status"] != "BLOCKED", "MARKET_VIEW_BLOCKED")
        if context.provenance != "SYNTHETIC_RESEARCH":
            need(dataset is not None, "HISTORICAL_MANIFEST_REQUIRED")
        need(
            context.data_quality["valid"]
            and set(context.observed_facts) == {"M1", "M5"},
            "ELIGIBLE_M1_M5_REQUIRED",
        )
        need(
            utc(context.observed_facts["M1"]["data_as_of"]) == at,
            "CURRENT_M1_CLOSE_REQUIRED",
        )
        config = ContextConfig.from_dict(context.configuration)
        sources = context.interpretations["source_registry"]
        bars = sorted(
            (
                (k, s)
                for k, s in sources.items()
                if s["kind"] == "CANDLE" and s["timeframe"] == "M1"
            ),
            key=lambda item: utc(item[1]["observed_at"]),
        )
        need(len(bars) >= 3, "PTC_HISTORY_REQUIRED")
        # References carry existing canonical IDs; no price series is generated here.
        evidence = {
            k: dict(
                kind=s["kind"],
                timeframe=s["timeframe"],
                observed_at=s["observed_at"],
                available_at=s["available_at"],
            )
            for k, s in sources.items()
        }
        evidence.update(
            {
                e.id: dict(
                    kind="CONTEXT_" + e.category,
                    timeframe=e.timeframe,
                    observed_at=e.observed_at,
                    available_at=e.available_at,
                )
                for e in context.evidence
            }
        )
        last_id, last = bars[-1]
        out.update(
            current_opposition={
                d: _opposition(context, d) for d in ("BULLISH", "BEARISH")
            },
            status="EVALUATED",
            current_bar=dict(
                id=last_id,
                opened_at=last["observed_at"],
                closed_at=last["available_at"],
                close=last["ohlc"]["close"],
            ),
            evidence=evidence,
            restrictions=plain(view["restrictions"]),
        )
        out["bindings"].update(
            view=view["sha256"],
            context=view["bindings"]["context"],
            configuration_hashes=dict(
                context=context.configuration_sha256,
                intelligence=context.intelligence_configuration_sha256,
                break_tolerance=config.break_tolerance,
            ),
            dataset=dataset,
        )
        zones = _zones(context)
        for z in zones:
            direction = "BULLISH" if z["kind"] == "SUPPORT" else "BEARISH"
            opposite = _opposition(context, direction)
            for confirmation in (False, True):
                p, t = (bars[-3], bars[-2]) if confirmation else (bars[-2], bars[-1])
                c = bars[-1] if confirmation else None
                if not _touch(t[1], z):
                    continue
                conditions = dict(
                    zone_active=z["status"] in ("FRESH", "TESTED"),
                    zone_known=utc(z["confirmed_at"]) <= utc(t[1]["observed_at"]),
                    m5_compatible=context.context["m5_structure"]
                    in (direction, "RANGING"),
                    previous_not_touching=not _touch(p[1], z),
                    touch_close_inside=z["lower"]
                    <= t[1]["ohlc"]["close"]
                    <= z["upper"],
                    contiguous=utc(p[1]["available_at"]) == utc(t[1]["observed_at"])
                    and (
                        c is None
                        or utc(t[1]["available_at"]) == utc(c[1]["observed_at"])
                    ),
                    confirmation_body=c is not None
                    and (
                        (c[1]["ohlc"]["close"] > c[1]["ohlc"]["open"])
                        if direction == "BULLISH"
                        else (c[1]["ohlc"]["close"] < c[1]["ohlc"]["open"])
                    ),
                    confirmation_break=c is not None
                    and (
                        (c[1]["ohlc"]["close"] > z["upper"] + config.break_tolerance)
                        if direction == "BULLISH"
                        else (
                            c[1]["ohlc"]["close"] < z["lower"] - config.break_tolerance
                        )
                    ),
                    no_opposing_choch=not opposite,
                )
                codes = dict(
                    zone_active="UNSUPPORTED_ZONE_STATE",
                    zone_known="ZONE_NOT_KNOWN_AT_TOUCH",
                    m5_compatible="M5_STRUCTURE_INCOMPATIBLE",
                    previous_not_touching="P_ALREADY_TOUCHES_ZONE",
                    touch_close_inside="TOUCH_CLOSE_OUTSIDE_ZONE",
                    contiguous="PTC_NOT_CONTIGUOUS",
                    confirmation_body="M1_CONFIRMATION_NOT_DIRECTIONAL",
                    confirmation_break="CONFIRMATION_BOUNDARY_NOT_CLEARED",
                    no_opposing_choch="FRESH_OPPOSING_M1_CHOCH",
                )
                required = [
                    k
                    for k in conditions
                    if confirmation
                    or k
                    not in (
                        "confirmation_body",
                        "confirmation_break",
                        "no_opposing_choch",
                    )
                ]
                reasons = sorted(codes[k] for k in required if not conditions[k])
                base = all(
                    conditions[k]
                    for k in (
                        "zone_active",
                        "zone_known",
                        "m5_compatible",
                        "previous_not_touching",
                        "touch_close_inside",
                        "contiguous",
                    )
                )
                state = (
                    "INVALIDATED"
                    if confirmation and base and opposite
                    else (
                        "ABSTAINED"
                        if reasons
                        else "QUALIFIED" if confirmation else "CANDIDATE"
                    )
                )
                # A candidate is not a trade and cannot qualify without a closed C.
                opposing_zones = [
                    _frozen(other)
                    for other in zones
                    if other["kind"] != z["kind"]
                    and other["status"] in ("FRESH", "TESTED")
                    and utc(other["confirmed_at"]) <= at
                    and c is not None
                    and (
                        (other["lower"] > c[1]["ohlc"]["close"])
                        if direction == "BULLISH"
                        else (other["upper"] < c[1]["ohlc"]["close"])
                    )
                ]
                out["evaluations"].append(
                    dict(
                        setup_id=setup_id(context.symbol, direction, z["id"], t[0]),
                        direction=direction,
                        state=state,
                        zone=_frozen(z),
                        candles=dict(P=p[0], T=t[0], C=c[0] if c else None),
                        conditions=conditions,
                        reason_codes=reasons
                        or [
                            (
                                "ALL_RESEARCH_RULES_MET"
                                if confirmation
                                else "CONFIRMATION_PENDING"
                            )
                        ],
                        supporting_evidence=sorted(
                            set([z["id"], p[0], t[0]] + ([c[0]] if c else []))
                        ),
                        contradictory_evidence=opposite,
                        invalidation_conditions=[
                            "LATER_ELIGIBLE_CLOSE_LOSES_FROZEN_ZONE",
                            "FRESH_OPPOSING_M1_CHOCH",
                        ],
                        exit_hypothesis=dict(
                            kind="PAPER_OBSERVATION_ONLY",
                            opposing_zones=opposing_zones,
                            expiry_eligible_closes=5,
                            unresolved_if="SIMULTANEOUS_EVENTS_OR_OHLC_ORDER_UNKNOWN",
                        ),
                    )
                )
        out["evaluations"].sort(key=lambda e: e["setup_id"])
        out["reason_codes"] = ["NO_TOUCH_EPISODE"] if not out["evaluations"] else []
    except ERRORS as exc:
        # Caller input/metadata strings are never returned as error messages.
        out = empty_result()
        if isinstance(context, ContextReport):
            try:
                utc(context.analysis_at)
                if (
                    isinstance(context.symbol, str)
                    and 0 < len(context.symbol) <= 128
                    and not any(c.isspace() or ord(c) < 32 for c in context.symbol)
                ):
                    out.update(
                        symbol=context.symbol,
                        evaluation_at_utc=context.analysis_at,
                        provenance=(
                            context.provenance
                            if context.provenance
                            in ("SYNTHETIC_RESEARCH", "HISTORICAL_RESEARCH")
                            else None
                        ),
                    )
            except ERRORS:
                pass
        if validated_view:
            out["restrictions"] = plain(view["restrictions"])
        out["bindings"]["dataset"] = dataset
        out["reason_codes"] = [
            (
                str(exc)
                if isinstance(exc, SRInputError)
                else "SOURCE_BOUND_ELIGIBLE_INPUT_REQUIRED"
            )
        ]
    return seal(out)


def evaluate_sr_rejection(view, context, *, view_inputs=None):
    """Typed, source-bound synthetic research. Historical callers use the manifest path."""
    return _evaluate(view, context, view_inputs=view_inputs)


def validate_sr_result(result, *, view=None, context=None, view_inputs=None):
    try:
        VALIDATOR.validate(result)
    except ValidationError:
        raise ValueError("SR_RESULT_SCHEMA_INVALID") from None
    need(
        result["sha256"] == digest({k: v for k, v in result.items() if k != "sha256"}),
        "SR_RESULT_CHECKSUM_INVALID",
    )
    need(result["bindings"]["policy"] == digest(POLICY), "SR_POLICY_MISMATCH")
    if result["evaluation_at_utc"] is not None:
        at = utc(result["evaluation_at_utc"])
        for e in result["evidence"].values():
            need(
                utc(e["observed_at"]) <= utc(e["available_at"]) <= at,
                "SR_FUTURE_EVIDENCE",
            )
    if result["status"] == "BLOCKED":
        need(
            not result["evaluations"]
            and not result["evidence"]
            and result["current_bar"] is None
            and not any(result["current_opposition"].values()),
            "SR_BLOCKED_HAS_EVIDENCE",
        )
    else:
        need(
            result["bindings"]["view"] is not None
            and result["bindings"]["context"] is not None,
            "SR_BINDING_REQUIRED",
        )
        bar = result["current_bar"]
        need(
            bar["id"] in result["evidence"] and utc(bar["closed_at"]) == at,
            "SR_CURRENT_CLOSE_INVALID",
        )
        for direction, refs in result["current_opposition"].items():
            need(
                refs == sorted(set(refs)) and set(refs) <= set(result["evidence"]),
                "SR_OPPOSITION_INVALID",
            )
            need(
                all(
                    result["evidence"][k]["kind"] == "CONTEXT_TRANSITION"
                    and result["evidence"][k]["timeframe"] == "M1"
                    and utc(result["evidence"][k]["available_at"]) == at
                    for k in refs
                ),
                "SR_OPPOSITION_INVALID",
            )
        ids = []
        for row in result["evaluations"]:
            ids.append(row["setup_id"])
            z = row["zone"]
            c = row["candles"]
            conditions = row["conditions"]
            need(
                row["setup_id"]
                == setup_id(result["symbol"], row["direction"], z["id"], c["T"]),
                "SR_SETUP_ID_INVALID",
            )
            need(
                set(row["supporting_evidence"] + row["contradictory_evidence"])
                <= set(result["evidence"]),
                "SR_UNRESOLVED_EVIDENCE",
            )
            need(
                utc(z["confirmed_at"]) <= at and z["id"] in result["evidence"],
                "SR_ZONE_INVALID",
            )
            need(
                c["P"] in result["evidence"]
                and c["T"] in result["evidence"]
                and (c["C"] is None or c["C"] in result["evidence"]),
                "SR_CANDLE_REFERENCE_INVALID",
            )
            need(
                row["contradictory_evidence"]
                == result["current_opposition"][row["direction"]],
                "SR_OPPOSITION_INVALID",
            )
            need(
                conditions["no_opposing_choch"] == (not row["contradictory_evidence"]),
                "SR_OPPOSITION_INVALID",
            )
            need(
                c["C"] == bar["id"] if c["C"] is not None else c["T"] == bar["id"],
                "SR_CURRENT_CLOSE_INVALID",
            )
            facts = result["evidence"]
            need(
                all(
                    facts[k]["kind"] == "CANDLE" and facts[k]["timeframe"] == "M1"
                    for k in c.values()
                    if k is not None
                ),
                "SR_CANDLE_REFERENCE_INVALID",
            )
            contiguous = utc(facts[c["P"]]["available_at"]) == utc(
                facts[c["T"]]["observed_at"]
            ) and (
                c["C"] is None
                or utc(facts[c["T"]]["available_at"])
                == utc(facts[c["C"]]["observed_at"])
            )
            need(
                conditions["contiguous"] == contiguous
                and conditions["zone_known"]
                == (utc(z["confirmed_at"]) <= utc(facts[c["T"]]["observed_at"])),
                "SR_CONDITION_CHRONOLOGY_INVALID",
            )
            base = all(
                conditions[k]
                for k in (
                    "zone_active",
                    "zone_known",
                    "m5_compatible",
                    "previous_not_touching",
                    "touch_close_inside",
                    "contiguous",
                )
            )
            expected = (
                "INVALIDATED"
                if c["C"] is not None and base and not conditions["no_opposing_choch"]
                else (
                    "QUALIFIED"
                    if c["C"] is not None and all(conditions.values())
                    else "CANDIDATE" if c["C"] is None and base else "ABSTAINED"
                )
            )
            need(row["state"] == expected, "SR_OUTCOME_INCONSISTENT")
            if row["state"] == "INVALIDATED":
                need(
                    c["C"] is not None and not conditions["no_opposing_choch"],
                    "SR_UNQUALIFIED_INVALIDATION_INVALID",
                )
            if row["state"] == "QUALIFIED":
                need(
                    c["C"] is not None and all(conditions.values()),
                    "SR_QUALIFICATION_INVALID",
                )
            if row["state"] == "CANDIDATE":
                need(
                    c["C"] is None
                    and all(
                        conditions[k]
                        for k in (
                            "zone_active",
                            "zone_known",
                            "m5_compatible",
                            "previous_not_touching",
                            "touch_close_inside",
                            "contiguous",
                        )
                    ),
                    "SR_CANDIDATE_INVALID",
                )
        need(ids == sorted(set(ids)), "SR_DUPLICATE_SETUP")
    if context is not None:
        need(
            result == evaluate_sr_rejection(view, context, view_inputs=view_inputs),
            "SR_SOURCE_BINDING_MISMATCH",
        )
    return True


class SRRejectionLedger:
    """New append-only research log. Existing journals/selection are never touched."""

    def __init__(self):
        self.entries = []
        self.setups = {}
        self.scope = None
        self.known_candles = {}
        self.last = None

    def record(self, view, context, *, view_inputs=None):
        result = evaluate_sr_rejection(view, context, view_inputs=view_inputs)
        return self._record(result)

    def _record(self, result):
        validate_sr_result(result)
        at = utc(result["evaluation_at_utc"])
        if self.last is not None:
            need(at >= utc(self.last["evaluation_at_utc"]), "SR_CLOCK_BACKWARD")
            if at == utc(self.last["evaluation_at_utc"]):
                need(result == self.last, "SR_SAME_CUTOFF_CHANGED")
                return deepcopy(self.entries[-1])
        if self.scope is not None:
            need(
                result["symbol"] == self.scope[0]
                and result["provenance"] == self.scope[1],
                "SR_SCOPE_CHANGED",
            )
        scope = [
            result["symbol"],
            result["provenance"],
            result["bindings"]["configuration_hashes"],
            result["bindings"]["dataset"],
        ]
        if result["status"] == "EVALUATED":
            need(self.scope is None or scope == self.scope, "SR_SCOPE_CHANGED")
            current = {
                k: e for k, e in result["evidence"].items() if e["kind"] == "CANDLE"
            }
            need(set(self.known_candles) <= set(current), "SR_HISTORY_PREFIX_CHANGED")
            if self.known_candles:
                previous_available = max(
                    utc(e["available_at"]) for e in self.known_candles.values()
                )
                need(
                    all(
                        k in self.known_candles
                        or utc(e["available_at"]) > previous_available
                        for k, e in current.items()
                    ),
                    "SR_LATE_OR_CORRECTED_CANDLE",
                )
        # Work on copies; rejected chronology/scope never partially advances state.
        inventory = deepcopy(self.setups)
        events = []

        def transition(sid, old, new, codes):
            events.append(
                dict(
                    setup_id=sid,
                    from_state=old,
                    to_state=new,
                    at_utc=result["evaluation_at_utc"],
                    reason_codes=codes,
                )
            )

        if result["status"] == "EVALUATED":
            bar = result["current_bar"]
            tolerance = result["bindings"]["configuration_hashes"]["break_tolerance"]
            for sid, s in sorted(inventory.items()):
                if s["state"] == "QUALIFIED" and at > utc(s["qualified_at_utc"]):
                    s["eligible_closes_after_C"] += 1
                    bullish = s["direction"] == "BULLISH"
                    z = s["zone"]
                    lost = (
                        bar["close"] < z["lower"] - tolerance
                        if bullish
                        else bar["close"] > z["upper"] + tolerance
                    )
                    # Current context contradictions are recorded even if this anchor is not being touched now.
                    # The direction-specific evidence is stored independently of touch rows.
                    opposite = result["current_opposition"][s["direction"]]
                    invalid = lost or bool(opposite)
                    expired = s["eligible_closes_after_C"] >= 5
                    exits = [
                        v["id"]
                        for v in s["exit_hypothesis"]["opposing_zones"]
                        if (
                            bar["close"] > v["upper"] + tolerance
                            if bullish
                            else bar["close"] < v["lower"] - tolerance
                        )
                    ]
                    paper_events = (
                        (["INVALIDATION"] if invalid else [])
                        + (["EXPIRY"] if expired else [])
                        + (["FROZEN_OPPOSING_ZONE_CLOSE"] if exits else [])
                    )
                    if s["paper_review"]["status"] == "PENDING" and paper_events:
                        s["paper_review"] = dict(
                            status=(
                                "UNRESOLVED_EVENT_ORDER"
                                if len(paper_events) > 1
                                else "OBSERVED"
                            ),
                            at_utc=result["evaluation_at_utc"],
                            events=paper_events,
                            zone_ids=exits,
                        )
                    if invalid or expired:
                        old = s["state"]
                        s["state"] = "INVALIDATED" if invalid else "EXPIRED"
                        s["terminal_at_utc"] = result["evaluation_at_utc"]
                        transition(
                            sid,
                            old,
                            s["state"],
                            (
                                ["FRESH_OPPOSING_M1_CHOCH"]
                                if opposite
                                else (
                                    ["FROZEN_ZONE_LOST"]
                                    if lost
                                    else ["FIVE_ELIGIBLE_CLOSES"]
                                )
                            ),
                        )
            rows = {r["setup_id"]: r for r in result["evaluations"]}
            for sid, s in sorted(inventory.items()):
                if s["state"] == "CANDIDATE" and sid not in rows:
                    s["state"] = "ABSTAINED"
                    s["terminal_at_utc"] = result["evaluation_at_utc"]
                    transition(
                        sid,
                        "CANDIDATE",
                        "ABSTAINED",
                        ["IMMEDIATE_CONFIRMATION_UNAVAILABLE"],
                    )
            for sid, row in sorted(rows.items()):
                old = inventory.get(sid)
                if old and old["state"] in (
                    "QUALIFIED",
                    "INVALIDATED",
                    "EXPIRED",
                    "ABSTAINED",
                ):
                    continue
                if old:
                    need(
                        all(
                            old["zone"][k] == row["zone"][k]
                            for k in (
                                "id",
                                "kind",
                                "timeframe",
                                "lower",
                                "upper",
                                "confirmed_at",
                            )
                        )
                        and old["candles"]["P"] == row["candles"]["P"]
                        and old["candles"]["T"] == row["candles"]["T"],
                        "SR_FROZEN_ANCHOR_CHANGED",
                    )
                state = row["state"]
                s = dict(
                    deepcopy(row),
                    first_seen_at_utc=(
                        old["first_seen_at_utc"] if old else result["evaluation_at_utc"]
                    ),
                    qualified_at_utc=(
                        result["evaluation_at_utc"] if state == "QUALIFIED" else None
                    ),
                    terminal_at_utc=(
                        result["evaluation_at_utc"]
                        if state in ("INVALIDATED", "ABSTAINED")
                        else None
                    ),
                    eligible_closes_after_C=0,
                    paper_review=dict(
                        status="PENDING", at_utc=None, events=[], zone_ids=[]
                    ),
                )
                if old:
                    s["zone"] = old["zone"]
                inventory[sid] = s
                if old is None or old["state"] != state:
                    transition(
                        sid, old["state"] if old else None, state, row["reason_codes"]
                    )
        entry = dict(
            result=deepcopy(result),
            transitions=events,
            inventory_sha256=digest(inventory),
        )
        self.entries.append(entry)
        self.setups = inventory
        self.last = deepcopy(result)
        if result["status"] == "EVALUATED":
            self.scope = scope
            self.known_candles = current
        return deepcopy(entry)

    def to_dict(self):
        setups = [deepcopy(self.setups[k]) for k in sorted(self.setups)]
        summary = dict(
            snapshots=len(self.entries),
            blocked_snapshots=sum(
                e["result"]["status"] == "BLOCKED" for e in self.entries
            ),
            directions={},
        )
        for direction in ("BULLISH", "BEARISH"):
            group = [s for s in setups if s["direction"] == direction]
            summary["directions"][direction] = dict(
                unique_qualified=sum(s["qualified_at_utc"] is not None for s in group),
                invalidated_qualified=sum(
                    s["qualified_at_utc"] is not None and s["state"] == "INVALIDATED"
                    for s in group
                ),
                expired_qualified=sum(
                    s["qualified_at_utc"] is not None and s["state"] == "EXPIRED"
                    for s in group
                ),
                unqualified_invalidated=sum(
                    s["qualified_at_utc"] is None and s["state"] == "INVALIDATED"
                    for s in group
                ),
                states=dict(sorted(Counter(s["state"] for s in group).items())),
            )
        return seal(
            dict(
                log_version=1,
                kind="SR_REJECTION_REPLAY",
                policy=POLICY,
                entries=deepcopy(self.entries),
                setups=setups,
                summary=summary,
                **SAFETY
            )
        )


def validate_sr_log(log):
    need(
        log["log_version"] == 1
        and type(log["log_version"]) is int
        and log["kind"] == "SR_REJECTION_REPLAY",
        "SR_LOG_VERSION_INVALID",
    )
    need(
        set(log)
        == {"log_version", "kind", "policy", "entries", "setups", "summary", "sha256"}
        | set(SAFETY),
        "SR_LOG_SCHEMA_INVALID",
    )
    for k, v in SAFETY.items():
        need(type(log[k]) is type(v) and log[k] == v, "SR_LOG_SAFETY_INVALID")
    need(
        log["sha256"] == digest({k: v for k, v in log.items() if k != "sha256"})
        and log["policy"] == POLICY,
        "SR_LOG_CHECKSUM_INVALID",
    )
    replay = SRRejectionLedger()
    for entry in log["entries"]:
        expected = replay._record(entry["result"])
        need(entry == expected, "SR_LOG_TRANSITION_INVALID")
    need(log == replay.to_dict(), "SR_LOG_INVENTORY_INVALID")
    return True
