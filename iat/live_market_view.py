"""Truthful live presentation over existing observations; never acquires market data."""

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
import re
from iat.intelligence.context_models import ContextReport
from iat.intelligence.market_view import (
    build_market_view_v3,
    validate_market_view_v3,
    SAFETY,
)
from iat.intelligence.strategy_replay import digest
from iat.intelligence.models import iso
from iat.replay_dataset import utc


def calendar_signature(calendar):
    def tree(value):
        if isinstance(value, datetime):
            return iso(value)
        if is_dataclass(value):
            return tree(asdict(value))
        if isinstance(value, dict):
            return {k: tree(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [tree(v) for v in value]
        if value is None or type(value) in (str, bool, int, float):
            return value
        raise ValueError("CALENDAR_CONTRACT_UNAVAILABLE")

    return digest(tree(calendar))


def session_state(calendar, now):
    if calendar is None:
        return dict(
            version=None,
            phase="UNKNOWN",
            verification="UNAVAILABLE",
            reason_codes=["SESSION_CALENDAR_UNAVAILABLE"],
        )
    state = (
        calendar.public_state(now)
        if getattr(calendar, "version", 1) == 2
        else dict(
            version=1,
            phase="UNKNOWN",
            verification="LEGACY_CONFIGURED_NOT_BROKER_CERTIFIED",
            reason_codes=[],
        )
    )
    state = deepcopy(state)
    try:
        calendar.validate_request("XAUUSD", now, timedelta(minutes=1))
    except Exception as exc:
        code = getattr(exc, "code", "SESSION_STATE_UNAVAILABLE")
        code = (
            code
            if isinstance(code, str) and re.fullmatch("[A-Z0-9_]+", code)
            else "SESSION_STATE_UNAVAILABLE"
        )
        state["reason_codes"] = sorted(set(state.get("reason_codes", []) + [code]))
    return state


def gate_fingerprint(calendar, now):
    state = session_state(calendar, now)
    # Receipt time alone is not a changed calendar/permission declaration.
    state.pop("evaluated_at_utc", None)
    return digest([calendar_signature(calendar), state])


def unavailable(code="OBSERVER_STARTING"):
    return dict(
        integration_version=1,
        model_version="IAT_LIVE_MARKET_VIEW_V3",
        source_snapshot_id=None,
        status="UNAVAILABLE",
        quote=None,
        cutoffs={},
        descriptive=None,
        session=None,
        formal_context=dict(
            status="UNAVAILABLE", source_sha256=None, reason_codes=[code]
        ),
        adapter=dict(
            available=True, status="UNAVAILABLE", reason_codes=[code], report=None
        ),
        strategy=dict(
            strategy_id="SR_REJECTION_M1_CONFIRMATION",
            rule_version="1.0.0",
            validation_status="SYNTHETIC_ONLY",
            live_status="NOT_RUN",
            reason_codes=["LIVE_STRATEGY_NOT_AUTHORIZED"],
        ),
        runtime={},
        reason_codes=[code],
        **SAFETY
    )


def formal_artifact(snapshot, context, calendar):
    """Consume original typed context; never relabel it as offline provenance."""
    result = dict(
        formal_context=dict(status="UNAVAILABLE", source_sha256=None, reason_codes=[]),
        adapter=dict(
            available=True, status="UNAVAILABLE", reason_codes=[], report=None
        ),
    )
    try:
        if (
            not isinstance(context, ContextReport)
            or context.symbol != "XAUUSD"
            or context.provenance != "VALIDATED_LIVE"
            or context.analysis_at != snapshot["analysis_at_utc"]
            or context.configuration_sha256
            != snapshot["observations"]["configuration_hashes"]["context"]
            or context.intelligence_configuration_sha256
            != snapshot["observations"]["configuration_hashes"]["intelligence"]
        ):
            raise ValueError("LIVE_CONTEXT_BINDING_INVALID")
        if context.data_quality["valid"]:
            if digest(context.interpretations["source_registry"]) != digest(
                snapshot["observations"]["source_registry"]
            ) or any(
                context.observed_facts[tf]["data_as_of"] != snapshot["cutoffs"][tf]
                for tf in ("M1", "M5")
            ):
                raise ValueError("LIVE_CONTEXT_BINDING_INVALID")
        reasons = sorted(
            {
                d["code"]
                for d in context.data_quality["diagnostics"]
                if d["code"] != "DATA_VALID"
            }
        )
        result["formal_context"] = dict(
            status="AVAILABLE" if context.data_quality["valid"] else "UNAVAILABLE",
            source_sha256=digest(context.to_dict()),
            reason_codes=reasons,
            provenance=context.provenance,
            analysis_at_utc=context.analysis_at,
        )
        args = (
            dict(session_snapshot=calendar.public_state(utc(context.analysis_at)))
            if getattr(calendar, "version", 1) == 2
            else {}
        )
        report = build_market_view_v3(context, **args)
        validate_market_view_v3(report, context_report=context, **args)
        codes = list(report["restrictions"]["reason_codes"])
        # The reviewed adaptive contract deliberately permits offline provenance only.
        if context.data_quality["valid"] and report["status"] == "BLOCKED":
            codes.append("V3_LIVE_PROVENANCE_UNSUPPORTED")
        result["adapter"] = dict(
            available=True,
            status=report["status"],
            reason_codes=sorted(set(codes)),
            report=report,
        )
    except Exception:
        result["formal_context"] = dict(
            status="UNAVAILABLE",
            source_sha256=None,
            reason_codes=["LIVE_CONTEXT_BINDING_INVALID"],
        )
        result["adapter"] = dict(
            available=True,
            status="UNAVAILABLE",
            report=None,
            reason_codes=["LIVE_CONTEXT_BINDING_INVALID"],
        )
    return result


def descriptive_summary(snapshot):
    obs = snapshot.get("observations", {})
    frames = obs.get("frames", {})
    context = obs.get("context", {})
    return dict(
        scope="DESCRIPTIVE_UNQUALIFIED_NOT_V3_FORMAL_ASSESSMENT",
        alignment=obs.get("alignment"),
        confluence=obs.get("confluence"),
        evidence_ids=sorted(e["id"] for e in obs.get("evidence", [])),
        frames={
            tf: dict(
                structure=f["structure"],
                swings=f["confirmed_pivots"][-6:],
                events=f["events"][-6:],
                event_reference_scope="V1_WINDOW_IDS_SCOPED_TO_THIS_SOURCE",
                patterns=context.get(tf, {}).get("patterns", []),
                support_resistance=context.get(tf, {}).get("support_resistance", []),
                supply_demand=context.get(tf, {}).get("supply_demand", []),
                liquidity_pools=context.get(tf, {}).get("liquidity_pools", []),
                liquidity_events=context.get(tf, {}).get("liquidity_events", []),
                momentum=context.get(tf, {}).get("momentum"),
                volatility=context.get(tf, {}).get("volatility"),
            )
            for tf, f in frames.items()
        },
    )


def envelope(snapshot, artifact, runtime, session, now):
    result = unavailable("LIVE_OBSERVATIONS_UNAVAILABLE")
    result.update(
        source_snapshot_id=snapshot.get("snapshot_id"),
        runtime=deepcopy(runtime),
        session=deepcopy(session),
    )
    if snapshot.get("snapshot_id") != digest(
        {k: v for k, v in snapshot.items() if k != "snapshot_id"}
    ):
        result["reason_codes"] = ["LIVE_SNAPSHOT_BINDING_INVALID"]
        return result
    if snapshot.get("feed_status") != "CONNECTED" or not snapshot.get("observations"):
        result["reason_codes"] = list(snapshot.get("reason_codes", []))
        return result
    quote = deepcopy(snapshot.get("quote"))
    if quote is None:
        return result
    age = (now - utc(quote["observed_at_utc"])).total_seconds()
    limit = runtime.get("quote_max_age_seconds", 2)
    if type(limit) not in (int, float) or not 0 < limit <= 30:
        return unavailable("QUOTE_POLICY_UNAVAILABLE")
    if age < 0 or age > limit:
        result["reason_codes"] = ["QUOTE_FUTURE" if age < 0 else "TICK_STALE"]
        return result
    quote["age_seconds"] = age
    point = quote.get("broker_point", runtime.get("broker_point"))
    quote["broker_point"] = point
    quote["spread_points"] = (
        (quote["ask"] - quote["bid"]) / point
        if quote.get("ask") is not None and type(point) in (int, float) and point > 0
        else None
    )
    result.update(
        status="DESCRIPTIVE_ONLY",
        quote=quote,
        cutoffs=deepcopy(snapshot["cutoffs"]),
        descriptive=descriptive_summary(snapshot),
        reason_codes=[],
    )
    if artifact is not None:
        result.update(deepcopy(artifact))
        result["reason_codes"] = sorted(
            set(
                result["formal_context"]["reason_codes"]
                + result["adapter"]["reason_codes"]
                + session.get("reason_codes", [])
            )
        )
        if result["adapter"]["status"] not in ("BLOCKED", "UNAVAILABLE"):
            result["status"] = "FORMAL_RESEARCH_PRESENTATION"
    return result


def seal_presentation(value):
    value = {k: v for k, v in value.items() if k != "sha256"}
    return dict(value, sha256=digest(value))
