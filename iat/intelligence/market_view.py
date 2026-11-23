"""Unified V3 presentation. No acquisition, new rule, selection or execution path."""

from copy import deepcopy
from dataclasses import replace
import json
import re

from iat.replay_dataset import utc
from iat.intelligence.adaptive import assess_adaptive, validate_adaptive_report
from iat.intelligence.context_models import ContextReport
from iat.intelligence.context_evidence import identity, pivot_id, choch_event_id
from iat.intelligence.engine import analyze_intelligence
from iat.intelligence.models import IntelligenceConfig, IntelligenceReport
from iat.intelligence.scenario_assessment import (
    assess_scenarios,
    validate_scenario_assessment,
    NO_DIRECTION,
    NAMES,
    SCORE_KIND,
)
from iat.intelligence.strategy_replay import digest

MODEL = "IAT_MARKET_INTELLIGENCE_V3"
SAFETY = dict(
    mode="READ_ONLY_SHADOW",
    signal="WAIT",
    execution_allowed=False,
    qualification="DATA_NOT_QUALIFIED",
    exness="BLOCKED",
    historical_validation="PENDING",
    historical_comparisons="NOT_RUN",
)
POLICY = dict(
    version=1,
    selection="CONTEXT_UNMODIFIED",
    scores=SCORE_KIND,
    missing="EXPLICIT_UNAVAILABLE",
    session="DECLARATIONS_NOT_APPROVAL",
)
ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    IndexError,
    OverflowError,
    RecursionError,
)


def plain(value):
    return json.loads(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    )


class MarketViewInputError(ValueError):
    """An allowlisted adapter diagnostic, never an upstream exception string."""


def need(condition, code):
    if not condition:
        raise MarketViewInputError(code)


def unavailable(code):
    return dict(status="UNAVAILABLE", reason_codes=[code], items=[])


def collection(items):
    return dict(
        status="AVAILABLE" if items else "UNAVAILABLE",
        reason_codes=[] if items else ["NO_UPSTREAM_OBSERVATIONS"],
        items=plain(items),
    )


def _base():
    return dict(
        report_version=1,
        model_version=MODEL,
        status="BLOCKED",
        market_state=dict(
            symbol=None,
            observation_at_utc=None,
            provenance=None,
            available_timeframes=[],
            closed_through={},
            regime="UNKNOWN",
            directional_bias="UNKNOWN",
            trend_structure={},
            momentum={},
            volatility={},
        ),
        price_structure=dict(
            swings=unavailable("V1_INTELLIGENCE_NOT_SUPPLIED"),
            structural_events=unavailable("V1_INTELLIGENCE_NOT_SUPPLIED"),
            patterns=unavailable("CONTEXT_UNAVAILABLE"),
            support_resistance=unavailable("CONTEXT_UNAVAILABLE"),
            supply_demand=unavailable("CONTEXT_UNAVAILABLE"),
            structure_changes=unavailable("CONTEXT_UNAVAILABLE"),
        ),
        liquidity=dict(
            pools=unavailable("CONTEXT_UNAVAILABLE"),
            events=unavailable("CONTEXT_UNAVAILABLE"),
            hypotheses=[],
        ),
        confluence=dict(
            m1_structure="UNKNOWN",
            m5_structure="UNKNOWN",
            agreement=None,
            scores=None,
            conflicts=[],
            evidence_index=[],
            sources={},
        ),
        restrictions=dict(
            data_quality=None,
            session=None,
            calendar_qualification="UNKNOWN",
            missing_timeframes=["M1", "M5"],
            warmup=[],
            reason_codes=[],
            qualification_snapshot=None,
        ),
        advisory=dict(
            upstream_signal=None,
            selected_hypothesis=None,
            directional_bias="UNKNOWN",
            confidence=None,
            confidence_status="NOT_PROVIDED_BY_UPSTREAM",
            score_kind=SCORE_KIND,
            ranked_hypotheses=[],
            leading_hypotheses=[],
            supporting_evidence=[],
            contradictory_evidence=[],
            assumptions=[],
            invalidation_conditions=[],
            explanation=[],
            abstention_reasons=[],
            wait_reasons=["READ_ONLY_RESEARCH", "DATA_NOT_QUALIFIED", "EXNESS_BLOCKED"],
        ),
        bindings=dict(
            context=None,
            adaptive=None,
            scenario=None,
            intelligence=None,
            session=None,
            qualification=None,
            configuration_hashes={},
            policy=digest(POLICY),
        ),
        limitations=[
            "HEURISTIC_SCORES_NOT_PROBABILITIES_OR_SIGNALS",
            "OHLC_PROXIES_NOT_ORDER_FLOW_OR_BROKER_FINALITY",
            "INPUT_HASHES_DO_NOT_AUTHENTICATE_OR_QUALIFY_DATA",
        ],
        **SAFETY
    )


def _session(snapshot, at):
    if snapshot is None:
        return None
    s = plain(snapshot)
    expected = {
        "version",
        "configuration_sha256",
        "provenance_count",
        "evaluated_at_utc",
        "evidence_latest_at_utc",
        "coverage_start_utc",
        "coverage_end_utc",
        "expires_at_utc",
        "verification",
        "reason_codes",
        "provenance_kinds",
        "permissions",
    }
    need(
        isinstance(s, dict)
        and set(s) == expected
        and type(s["version"]) is int
        and s["version"] == 2,
        "SESSION_SNAPSHOT_INVALID",
    )
    need(
        re.fullmatch("[a-f0-9]{64}", s["configuration_sha256"]) is not None,
        "SESSION_HASH_INVALID",
    )
    need(utc(s["evaluated_at_utc"]) == at, "SESSION_CUTOFF_MISMATCH")
    need(
        s["verification"] in ("BLOCKED", "VERIFIED_DECLARATIONS"),
        "SESSION_VERIFICATION_INVALID",
    )
    p = s["permissions"]
    need(
        set(p)
        == {
            "phase",
            "market_data_expected",
            "broker_open_positions",
            "broker_close_positions",
            "broker_permissions_verified",
            "iat_execution_allowed",
        },
        "SESSION_PERMISSIONS_INVALID",
    )
    need(
        p["phase"] in ("UNKNOWN", "CLOSED", "QUOTE_ONLY", "CLOSE_ONLY", "FULL_TRADING"),
        "SESSION_PHASE_INVALID",
    )
    need(
        p["iat_execution_allowed"] is False
        and type(p["broker_permissions_verified"]) is bool,
        "UNSAFE_SESSION_SNAPSHOT",
    )
    need(
        all(
            v is None or type(v) is bool
            for k, v in p.items()
            if k
            in (
                "market_data_expected",
                "broker_open_positions",
                "broker_close_positions",
            )
        ),
        "SESSION_PERMISSIONS_INVALID",
    )
    need(
        isinstance(s["reason_codes"], list)
        and all(
            isinstance(c, str) and re.fullmatch("[A-Z0-9_]+", c)
            for c in s["reason_codes"]
        ),
        "SESSION_REASONS_INVALID",
    )
    # Metadata dates are coverage declarations, not observed future candles.
    start, end, evidence, expiry = [
        utc(s[k])
        for k in (
            "coverage_start_utc",
            "coverage_end_utc",
            "evidence_latest_at_utc",
            "expires_at_utc",
        )
    ]
    need(start < end and evidence < expiry, "SESSION_COVERAGE_INVALID")
    if s["verification"] == "VERIFIED_DECLARATIONS":
        need(
            not s["reason_codes"] and start <= at < end and evidence <= at < expiry,
            "SESSION_ASSURANCE_INCONSISTENT",
        )
    return s


def _details(intelligence, context):
    """Bind optional original V1 frames to exactly the context's closed source bars.

    Reuse the original V1 calculation only as a consistency check, with its frozen
    configuration. Never infer missing HH/BOS or mint scores in the presenter.
    """
    need(isinstance(intelligence, IntelligenceReport), "TYPED_V1_INTELLIGENCE_REQUIRED")
    need(
        intelligence.report_version == 1
        and intelligence.model_version == "IAT_MARKET_INTELLIGENCE_V1"
        and intelligence.symbol == context.symbol
        and intelligence.analysis_at == context.analysis_at
        and intelligence.provenance == context.provenance
        and intelligence.data_quality == context.data_quality
        and intelligence.configuration_sha256
        == context.intelligence_configuration_sha256
        and intelligence.mode == "READ_ONLY_SHADOW"
        and intelligence.signal == "WAIT"
        and intelligence.execution_allowed is False,
        "INTELLIGENCE_BINDING_MISMATCH",
    )
    cfg = IntelligenceConfig.from_dict(intelligence.configuration)
    need(
        cfg.digest == intelligence.configuration_sha256,
        "INTELLIGENCE_CONFIGURATION_MISMATCH",
    )
    sources = context.interpretations["source_registry"]
    rows = {
        tf: sorted(
            (
                dict(timestamp=s["observed_at"], **s["ohlc"])
                for s in sources.values()
                if s["kind"] == "CANDLE" and s["timeframe"] == tf
            ),
            key=lambda r: utc(r["timestamp"]),
        )
        for tf in ("M1", "M5")
    }
    expected = analyze_intelligence(
        context.symbol,
        rows["M1"] or None,
        rows["M5"] or None,
        utc(context.analysis_at),
        config=cfg,
        provenance=context.provenance,
    )
    need(
        intelligence.frames == expected.frames
        and intelligence.alignment == expected.alignment,
        "INTELLIGENCE_FRAMES_MISMATCH",
    )
    swings, events = [], []
    for tf, frame in sorted(intelligence.frames.items()):
        refs = {
            r.id: identity(
                context.symbol,
                tf,
                "CANDLE",
                r.opened_at,
                *[rows[tf][r.index][k] for k in ("open", "high", "low", "close")]
            )
            for r in frame.evidence
        }
        refs.update(
            {p.id: pivot_id(context.symbol, tf, p) for p in frame.confirmed_pivots}
        )
        for p in frame.confirmed_pivots:
            swings.append(
                dict(
                    id=refs[p.id],
                    timeframe=tf,
                    kind=p.kind,
                    relation=p.relation,
                    price=p.price,
                    observed_at=p.occurred_at,
                    available_at=p.confirmed_at,
                    references=sorted(set(refs[r] for r in p.evidence)),
                )
            )
        for e in frame.events:
            event_id = (
                choch_event_id(
                    context.symbol, tf, e, refs[e.pivot_id], refs[e.break_candle]
                )
                if e.event_type.endswith("_CHOCH")
                else None
            )
            # Other V1 events have no durable canonical occurrence ID contract yet.
            # Retain their source ID only as a scoped V1 reference, never as an event key.
            events.append(
                dict(
                    source_report_sha256=digest(intelligence.to_dict()),
                    source_id=e.id,
                    event_id=event_id,
                    timeframe=tf,
                    event_type=e.event_type,
                    level=e.level,
                    available_at=e.confirmed_at,
                    policy=e.policy,
                    references=sorted(set(refs[r] for r in e.evidence)),
                )
            )
    return collection(sorted(swings, key=lambda r: r["id"])), collection(events)


def _liquidity_contract(r):
    """Check optional context detail against its existing canonical source registry."""
    sources = r["interpretations"]["source_registry"]
    for tf, frame in r["interpretations"]["frames"].items():
        at = utc(r["observed_facts"][tf]["data_as_of"])
        for p in frame["liquidity_pools"]:
            source = sources[p["id"]]
            need(
                p["timeframe"] == tf
                and p["kind"]
                in ("EQUAL_HIGHS", "EQUAL_LOWS", "SWING_HIGHS", "SWING_LOWS")
                and p["level"] > 0
                and set(p["evidence"]) <= set(sources)
                and utc(p["confirmed_at"]) <= at
                and p["id"]
                == identity(r["symbol"], tf, p["kind"], p["evidence"], p["level"])
                and source["kind"] == "LIQUIDITY_POOL"
                and source["level"] == p["level"]
                and source["references"] == p["evidence"]
                and source["available_at"] == p["confirmed_at"],
                "LIQUIDITY_POOL_INCONSISTENT",
            )
        pools = {p["id"]: p for p in frame["liquidity_pools"]}
        need(len(pools) == len(frame["liquidity_pools"]), "DUPLICATE_LIQUIDITY_POOL")
        ids = set()
        for e in frame["liquidity_events"]:
            source = sources[e["id"]]
            need(
                e["id"] not in ids
                and e["pool_id"] in pools
                and e["timeframe"] == tf
                and e["event_type"]
                in (
                    "LEVEL_PENETRATION",
                    "CONFIRMED_SWEEP",
                    "SUSTAINED_BREAKOUT",
                    "AMBIGUOUS_EVENT",
                )
                and utc(pools[e["pool_id"]]["confirmed_at"])
                <= utc(e["occurred_at"])
                <= utc(e["available_at"])
                <= at
                and e["level"] == pools[e["pool_id"]]["level"]
                and e["candle"] in sources
                and e["id"]
                == identity(
                    r["symbol"],
                    tf,
                    e["event_type"],
                    e["pool_id"],
                    e["occurred_at"],
                    e["available_at"],
                )
                and source["references"] == e["evidence"]
                and source["observed_at"] == e["occurred_at"]
                and source["available_at"] == e["available_at"]
                and set(e["evidence"]) <= set(sources),
                "LIQUIDITY_EVENT_INCONSISTENT",
            )
            ids.add(e["id"])


def build_market_view_v3(
    context_report,
    adaptive_report=None,
    scenario_report=None,
    session_snapshot=None,
    qualification_snapshot=None,
    *,
    intelligence_report=None
):
    """Research-only Python integration. No provider, clock, filesystem or HTTP access.

    Reports must describe the same observation. Missing optional detail stays
    unavailable; mismatched supplied detail blocks the entire presentation.
    """
    out = _base()
    try:
        need(isinstance(context_report, ContextReport), "TYPED_CONTEXT_REQUIRED")
        # The existing validator checks chronology, canonical identities, caps,
        # hypotheses and selection, and canonicalizes identical evidence copies.
        scenario = assess_scenarios(context_report)
        validate_scenario_assessment(scenario)
        out["restrictions"]["data_quality"] = plain(context_report.data_quality)
        out["restrictions"]["reason_codes"] = scenario["reason_codes"]
        if scenario["status"] == "BLOCKED":
            if (
                scenario["selected_hypothesis"] == NO_DIRECTION
                and "BLOCKED_DATA_QUALITY" in scenario["reason_codes"]
            ):
                out["advisory"].update(
                    upstream_signal="WAIT", selected_hypothesis=NO_DIRECTION
                )
            out["advisory"]["abstention_reasons"] = scenario["abstention_reasons"]
            out["advisory"]["wait_reasons"] += scenario["reason_codes"]
            return _seal(out)
        by_id = {e.id: e for e in context_report.evidence}
        context = replace(
            context_report, evidence=tuple(by_id[k] for k in sorted(by_id))
        )
        at = utc(context.analysis_at)
        session = _session(session_snapshot, at)
        if qualification_snapshot is not None:
            need(
                plain(qualification_snapshot) == SAFETY,
                "QUALIFICATION_SNAPSHOT_CANNOT_APPROVE",
            )
        if scenario_report is not None:
            validate_scenario_assessment(scenario_report)
            need(plain(scenario_report) == scenario, "SCENARIO_BINDING_MISMATCH")
        adaptive = assess_adaptive(
            context, session_sha256=session["configuration_sha256"] if session else None
        )
        validate_adaptive_report(adaptive)
        if adaptive_report is not None:
            validate_adaptive_report(adaptive_report)
            need(plain(adaptive_report) == plain(adaptive), "ADAPTIVE_BINDING_MISMATCH")
        need(adaptive["status"] != "BLOCKED", "ADAPTIVE_CONTEXT_BLOCKED")
        r = plain(context.to_dict())
        frames = r["interpretations"]["frames"]
        sources = r["interpretations"]["source_registry"]
        bias = "UNKNOWN"
        selected = scenario["selected_hypothesis"]
        if scenario["status"] == "ASSESSED":
            bias = (
                "BULLISH"
                if selected.startswith("BULLISH")
                else "BEARISH" if selected.startswith("BEARISH") else "NEUTRAL"
            )
        elif selected == NO_DIRECTION:
            bias = "NEUTRAL"
        out["status"] = scenario["status"]
        out["market_state"] = dict(
            symbol=r["symbol"],
            observation_at_utc=r["analysis_at"],
            provenance=r["provenance"],
            available_timeframes=sorted(frames),
            closed_through={
                tf: r["observed_facts"][tf]["data_as_of"] for tf in sorted(frames)
            },
            regime=adaptive["regime"]["directional"],
            directional_bias=bias,
            trend_structure={
                tf: f["structure"]["classification"] for tf, f in sorted(frames.items())
            },
            momentum={tf: f["momentum"] for tf, f in sorted(frames.items())},
            volatility=adaptive["volatility"],
        )
        price = out["price_structure"]
        price["patterns"] = collection(
            [
                dict(
                    id=e.id,
                    timeframe=e.timeframe,
                    available_at=e.available_at,
                    references=list(e.references),
                    **e.details
                )
                for e in context.evidence
                if e.category == "CANDLE"
            ]
        )
        for key in ("support_resistance", "supply_demand"):
            price[key] = collection(
                [item for tf, f in sorted(frames.items()) for item in f[key]]
            )
        price["structure_changes"] = collection(
            [
                plain(e)
                for e in scenario["evidence_index"]
                if e["category"] == "TRANSITION"
            ]
        )
        if intelligence_report is not None:
            price["swings"], price["structural_events"] = _details(
                intelligence_report, context
            )
        _liquidity_contract(r)
        for key, upstream in (
            ("pools", "liquidity_pools"),
            ("events", "liquidity_events"),
        ):
            out["liquidity"][key] = collection(
                [item for tf, f in sorted(frames.items()) for item in f[upstream]]
            )
        # Existing hypotheses that actually cite liquidity evidence, not new stories.
        liquidity_ids = {e.id for e in context.evidence if e.category == "LIQUIDITY"}
        out["liquidity"]["hypotheses"] = [
            h["hypothesis_type"]
            for h in scenario["ranked_hypotheses"]
            if liquidity_ids.intersection(
                h["supporting_evidence"] + h["contradictory_evidence"]
            )
        ]
        out["confluence"] = dict(
            m1_structure=r["context"]["m1_structure"],
            m5_structure=r["context"]["m5_structure"],
            agreement=r["context"]["phase7_alignment"],
            scores=r["confluence"],
            conflicts=adaptive["conflicts"],
            evidence_index=scenario["evidence_index"],
            sources=sources,
        )
        limitations = sorted(set(r["context"]["limitations"] + adaptive["uncertainty"]))
        restrictions = out["restrictions"]
        restrictions.update(
            session=session,
            calendar_qualification=session["verification"] if session else "UNKNOWN",
            missing_timeframes=sorted({"M1", "M5"} - set(frames)),
            warmup=sorted(
                c
                for c in limitations + scenario["reason_codes"]
                if any(
                    word in c
                    for word in ("WARMUP", "INSUFFICIENT", "HISTORY_UNAVAILABLE")
                )
            ),
            qualification_snapshot=plain(qualification_snapshot),
            reason_codes=sorted(set(scenario["reason_codes"] + limitations)),
        )
        if session is None:
            restrictions["reason_codes"].append("SESSION_SNAPSHOT_UNAVAILABLE")
            out["status"] = "UNKNOWN"
        else:
            restrictions["reason_codes"] += session["reason_codes"]
            phase = session["permissions"]["phase"]
            if session["verification"] == "BLOCKED" or phase in (
                "CLOSED",
                "QUOTE_ONLY",
                "CLOSE_ONLY",
            ):
                out["status"] = "BLOCKED"
                restrictions["reason_codes"].append("SESSION_RESTRICTED")
            elif phase == "UNKNOWN":
                out["status"] = "UNKNOWN"
        if (
            adaptive["status"] == "UNKNOWN"
            or restrictions["missing_timeframes"]
            or "SESSION_NOT_CHECKED" in scenario["reason_codes"]
        ):
            if out["status"] != "BLOCKED":
                out["status"] = "UNKNOWN"
        h = next(h for h in scenario["ranked_hypotheses"] if h["selected_by_context"])
        out["advisory"].update(
            upstream_signal=r["signal"],
            selected_hypothesis=selected,
            directional_bias=bias,
            ranked_hypotheses=scenario["ranked_hypotheses"],
            leading_hypotheses=scenario["leading_hypotheses"],
            supporting_evidence=h["supporting_evidence"],
            contradictory_evidence=h["contradictory_evidence"],
            assumptions=h["assumptions"],
            invalidation_conditions=h["invalidation_conditions"],
            explanation=r["explanation"],
            abstention_reasons=r["abstention_reasons"],
        )
        out["advisory"]["wait_reasons"] += (
            restrictions["reason_codes"] + r["abstention_reasons"]
        )
        out["bindings"].update(
            context=scenario["context_report_sha256"],
            adaptive=adaptive["sha256"],
            scenario=scenario["sha256"],
            intelligence=(
                digest(intelligence_report.to_dict()) if intelligence_report else None
            ),
            session=digest(session) if session else None,
            qualification=(
                digest(qualification_snapshot) if qualification_snapshot else None
            ),
            configuration_hashes=adaptive["configuration_hashes"],
        )
        out["limitations"] += [
            "SESSION_SNAPSHOT_IS_A_DECLARATION_NOT_CALENDAR_APPROVAL"
        ]
    except ERRORS as exc:
        out = _base()
        # Never echo arbitrary exception/provider strings or malformed inputs.
        code = (
            str(exc)
            if isinstance(exc, MarketViewInputError)
            else "MARKET_VIEW_INPUT_INVALID"
        )
        out["restrictions"]["reason_codes"] = [code]
        out["advisory"]["wait_reasons"].append(code)
    return _seal(out)


def _seal(out):
    out["restrictions"]["reason_codes"] = sorted(
        set(out["restrictions"]["reason_codes"])
    )
    out["advisory"]["wait_reasons"] = sorted(set(out["advisory"]["wait_reasons"]))
    out = plain(out)
    return dict(out, sha256=digest(out))


def _observed_chronology(value, at, key=None):
    dates = {
        "observed_at",
        "available_at",
        "occurred_at",
        "confirmed_at",
        "detected_at",
        "origin_at",
        "broken_at",
        "invalidated_at",
        "generated_at",
        "historical_touches",
        "retests",
    }
    if isinstance(value, dict):
        for k, v in value.items():
            _observed_chronology(v, at, k)
    elif isinstance(value, list):
        for v in value:
            _observed_chronology(v, at, key)
    elif value is not None and key in dates:
        need(utc(value) <= at, "MARKET_VIEW_FUTURE_OBSERVATION")


def validate_market_view_v3(view, *, context_report=None, **inputs):
    """Serialized integrity checks; optional bound inputs establish exact mapping.

    SHA-256 is integrity, not authentication. Independent source qualification is
    deliberately outside this presentation validator.
    """
    need(
        isinstance(view, dict) and set(view) == set(_base()) | {"sha256"},
        "MARKET_VIEW_SCHEMA_INVALID",
    )
    need(
        view["report_version"] == 1
        and type(view["report_version"]) is int
        and view["model_version"] == MODEL,
        "MARKET_VIEW_VERSION_INVALID",
    )
    need(
        view["sha256"] == digest({k: v for k, v in view.items() if k != "sha256"}),
        "MARKET_VIEW_CHECKSUM_INVALID",
    )
    for key, value in SAFETY.items():
        need(
            type(view[key]) is type(value) and view[key] == value,
            "MARKET_VIEW_SAFETY_INVALID",
        )
    need(
        view["status"] in ("BLOCKED", "UNKNOWN", "ABSTAINED", "ASSESSED"),
        "MARKET_VIEW_STATUS_INVALID",
    )
    for section in (
        "market_state",
        "price_structure",
        "liquidity",
        "confluence",
        "restrictions",
        "advisory",
        "bindings",
    ):
        need(
            isinstance(view[section], dict)
            and set(view[section]) == set(_base()[section]),
            "MARKET_VIEW_SCHEMA_INVALID",
        )
    a = view["advisory"]
    need(
        a["upstream_signal"] in (None, "WAIT")
        and a["confidence"] is None
        and a["confidence_status"] == "NOT_PROVIDED_BY_UPSTREAM"
        and a["score_kind"] == SCORE_KIND,
        "MARKET_VIEW_ADVISORY_INVALID",
    )
    need(view["bindings"]["policy"] == digest(POLICY), "MARKET_VIEW_POLICY_INVALID")
    at = view["market_state"]["observation_at_utc"]
    if at is None:
        need(
            view["status"] == "BLOCKED"
            and not view["confluence"]["evidence_index"]
            and not a["ranked_hypotheses"]
            and a["selected_hypothesis"] in (None, NO_DIRECTION),
            "MARKET_VIEW_BLOCKED_INVALID",
        )
    else:
        at = utc(at)
        need(
            view["restrictions"]["data_quality"]["valid"] is True,
            "MARKET_VIEW_QUALITY_INVALID",
        )
        for section in ("price_structure", "liquidity", "confluence", "advisory"):
            _observed_chronology(view[section], at)
        need(
            view["market_state"]["available_timeframes"]
            == sorted(view["market_state"]["closed_through"]),
            "MARKET_VIEW_FRAME_INVALID",
        )
        need(
            view["confluence"]["scores"]["selected_hypothesis"]
            == a["selected_hypothesis"],
            "MARKET_VIEW_SELECTION_INVALID",
        )
        for stamp in view["market_state"]["closed_through"].values():
            need(utc(stamp) <= at, "MARKET_VIEW_FUTURE_FRAME")
        sources = view["confluence"]["sources"]
        ids = [e["id"] for e in view["confluence"]["evidence_index"]]
        need(ids == sorted(set(ids)), "MARKET_VIEW_EVIDENCE_INVALID")
        for s in sources.values():
            need(
                utc(s["observed_at"]) <= utc(s["available_at"]) <= at,
                "MARKET_VIEW_FUTURE_SOURCE",
            )
            need(
                set(s.get("references", [])) <= set(sources),
                "MARKET_VIEW_SOURCE_INVALID",
            )
        for e in view["confluence"]["evidence_index"]:
            need(
                utc(e["observed_at"]) <= utc(e["available_at"]) <= at
                and set(e["references"]) <= set(sources),
                "MARKET_VIEW_EVIDENCE_INVALID",
            )
        need(
            a["selected_hypothesis"] in NAMES
            and len(a["ranked_hypotheses"]) == len(NAMES)
            and {h["hypothesis_type"] for h in a["ranked_hypotheses"]} == NAMES
            and all(
                type(h["selected_by_context"]) is bool for h in a["ranked_hypotheses"]
            )
            and sum(h["selected_by_context"] for h in a["ranked_hypotheses"]) == 1,
            "MARKET_VIEW_SELECTION_INVALID",
        )
        need(
            all(
                h["selected_by_context"]
                == (h["hypothesis_type"] == a["selected_hypothesis"])
                and set(h["supporting_evidence"] + h["contradictory_evidence"])
                <= set(ids)
                for h in a["ranked_hypotheses"]
            ),
            "MARKET_VIEW_SELECTION_INVALID",
        )
        session = _session(view["restrictions"]["session"], at)
        if session is None:
            need(view["status"] == "UNKNOWN", "MARKET_VIEW_SESSION_INVALID")
        elif session["verification"] == "BLOCKED" or session["permissions"][
            "phase"
        ] in ("CLOSED", "QUOTE_ONLY", "CLOSE_ONLY"):
            need(view["status"] == "BLOCKED", "MARKET_VIEW_SESSION_INVALID")
        elif session["permissions"]["phase"] == "UNKNOWN":
            need(view["status"] == "UNKNOWN", "MARKET_VIEW_SESSION_INVALID")
        if view["status"] in ("ASSESSED", "ABSTAINED"):
            need(
                view["restrictions"]["session"] is not None
                and view["restrictions"]["calendar_qualification"]
                == "VERIFIED_DECLARATIONS",
                "MARKET_VIEW_SESSION_INVALID",
            )
    if context_report is not None:
        need(
            view == build_market_view_v3(context_report, **inputs),
            "MARKET_VIEW_SOURCE_BINDING_INVALID",
        )
    return True
