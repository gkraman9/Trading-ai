from iat.paper_source_scope import current_source, context_allowed, report_allowed

"""Stateless E3 reference geometry; no fill, sizing, costs or trade approval."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, localcontext, Context, ROUND_HALF_EVEN, DecimalException
from math import isfinite
import json
import re
from iat.replay_dataset import utc
from iat.intelligence.entry_intelligence import (
    EntryResearchSession,
    validate_entry_report,
)
from iat.intelligence.exit_intelligence import ExitResearchSession, validate_exit_report
from iat.intelligence.context_models import ContextReport
from iat.intelligence.market_view import SAFETY, plain, validate_market_view_v3
from iat.intelligence.strategy_replay import digest

MODEL = "IAT_RISK_INTELLIGENCE_V1"
ARITHMETIC = Context(prec=34, rounding=ROUND_HALF_EVEN)
LIMITS = dict(max_candidates=2048, max_sources=10000, max_report_bytes=1000000)
NULL_FIELDS = (
    "entry_fill",
    "exit_fill",
    "executable_stop_loss",
    "executable_take_profit",
    "fill_based_risk_reward",
    "net_risk_reward",
    "position_size",
    "capital_at_risk",
    "margin_required",
    "hypothetical_pnl",
    "realized_pnl",
    "expected_return",
    "probability_of_success",
    "performance_metrics",
)
COST_NUMBERS = (
    "bid",
    "ask",
    "spread",
    "broker_point",
    "tick_size",
    "tick_value",
    "contract_size",
    "commission",
    "slippage",
    "currency_conversion",
    "swap",
)


class RiskInputError(ValueError):
    pass


class GeometryError(RiskInputError):
    pass


def need(ok, code):
    if not ok:
        raise RiskInputError(code)


def number(value):
    need(type(value) in (int, float, str, Decimal), "NUMERIC_INVALID")
    if type(value) is str:
        need(len(value) <= 64, "NUMERIC_RESOURCE_LIMIT")
    if type(value) is int:
        need(value.bit_length() <= 1078, "NUMERIC_RESOURCE_LIMIT")
    try:
        d = Decimal(str(value))
    except (ValueError, DecimalException):
        raise RiskInputError("NUMERIC_INVALID") from None
    need(d.is_finite(), "NUMERIC_NONFINITE")
    need(
        abs(d.adjusted()) <= 324 and len(d.as_tuple().digits) <= 64,
        "NUMERIC_RESOURCE_LIMIT",
    )
    return d


def text_number(value):
    if value is None:
        return None
    s = format(value, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def reference_geometry(
    direction, confirmation, lower, upper, tolerance, target_near=None
):
    """Isolated arithmetic ONLY; this function establishes no source eligibility."""
    try:
        need(direction in ("BULLISH", "BEARISH"), "DIRECTION_INVALID")
        need(
            all(x is not None for x in (confirmation, lower, upper, tolerance)),
            "RISK_REFERENCE_UNAVAILABLE",
        )
        with localcontext(ARITHMETIC):
            c, lo, hi, tol = (
                number(v) for v in (confirmation, lower, upper, tolerance)
            )
            need(c > 0 and 0 < lo <= hi and tol >= 0, "REFERENCE_GEOMETRY_INVALID")
            # Exactly the existing SR float threshold, not a rationalized/rounded replacement.
            threshold = (
                float(lower) - float(tolerance)
                if direction == "BULLISH"
                else float(upper) + float(tolerance)
            )
            need(isfinite(threshold) and threshold > 0, "REFERENCE_GEOMETRY_INVALID")
            boundary = number(threshold)
            risk = c - boundary if direction == "BULLISH" else boundary - c
            need(risk > 0, "REFERENCE_RISK_NONPOSITIVE")
            reward = (
                None
                if target_near is None
                else (
                    number(target_near) - c
                    if direction == "BULLISH"
                    else c - number(target_near)
                )
            )
            need(reward is None or reward > 0, "REFERENCE_REWARD_NONPOSITIVE")
            return dict(
                authentication="NOT_ESTABLISHED_BY_ARITHMETIC",
                basis="REFERENCE_RR_ONLY",
                direction=direction,
                units="INSTRUMENT_PRICE_UNITS",
                ratio_units="DIMENSIONLESS",
                invalidation_threshold=text_number(boundary),
                risk_distance=text_number(risk),
                reward_distance=text_number(reward),
                reward_to_risk=(
                    text_number(reward / risk) if reward is not None else None
                ),
                breach_semantics=(
                    "STRICT_ELIGIBLE_CLOSE_BELOW_THRESHOLD"
                    if direction == "BULLISH"
                    else "STRICT_ELIGIBLE_CLOSE_ABOVE_THRESHOLD"
                ),
            )
    except (
        RiskInputError,
        ValueError,
        TypeError,
        OverflowError,
        DecimalException,
    ) as exc:
        raise GeometryError(
            str(exc)
            if isinstance(exc, RiskInputError)
            else "REFERENCE_GEOMETRY_INVALID"
        ) from None


def seal(value):
    value = plain(value)
    return dict(value, sha256=digest(value))


@dataclass(frozen=True)
class RiskPolicy:
    version: int = 1
    atr_timeframe: str | None = None

    def __post_init__(self):
        need(type(self.version) is int and self.version == 1, "RISK_POLICY_INVALID")
        need(self.atr_timeframe in (None, "M1", "M5"), "ATR_TIMEFRAME_UNSUPPORTED")


def _base(code="RISK_SOURCE_UNAVAILABLE"):
    need(
        isinstance(code, str) and re.fullmatch("[A-Z0-9_]+", code),
        "RISK_REASON_INVALID",
    )
    return dict(
        report_version=1,
        model_version=MODEL,
        risk_policy_version=1,
        risk_policy=None,
        source_eligibility="BLOCKED",
        validation_status="SYNTHETIC_ONLY",
        symbol=None,
        original_setup=None,
        research_direction=None,
        qualification_at_utc=None,
        evaluation_at_utc=None,
        confirmation_reference=None,
        frozen_invalidation=None,
        frozen_target=None,
        target_candidates=[],
        reference_geometry=None,
        reference_price_basis=dict(status="UNAVAILABLE", value=None),
        volatility=dict(
            status="VOLATILITY_UNAVAILABLE", reason_codes=["ATR_SOURCE_UNAVAILABLE"]
        ),
        costs=dict(
            status="COST_MODEL_UNAVAILABLE",
            qualified_model_available=False,
            fields={},
            reason_codes=["COST_EVIDENCE_UNAVAILABLE"],
        ),
        hypothesis_lifecycle=None,
        ambiguity=None,
        source_restrictions=None,
        states=["BLOCKED"],
        research_eligibility="REFERENCE_RESEARCH_ONLY_NOT_TRADE_SUITABILITY",
        missing_evidence=[code],
        supporting_evidence=[],
        contradictory_evidence=[],
        bindings=dict(
            original_e1=None,
            original_e2=None,
            current_e2=None,
            context=None,
            view=None,
            configurations={},
            exit_policy=None,
            risk_policy=None,
            arithmetic_policy=digest(
                dict(
                    precision=34,
                    rounding="ROUND_HALF_EVEN",
                    threshold="ORIGINAL_SR_FLOAT_OPERATION",
                )
            ),
        ),
        explanation=[
            "Reference geometry is not fill-based, net or executable risk/reward."
        ],
        limitations=[
            "NO_FILL_OR_COST_MODEL",
            "UNKNOWN_PRICE_BASIS_IS_NOT_BID",
            "NO_RR_THRESHOLD_APPROVAL_OR_RANKING",
        ],
        reason_codes=[code],
        **{k: None for k in NULL_FIELDS},
        **SAFETY
    )


def blocked_risk(code="RISK_SOURCE_UNAVAILABLE"):
    return seal(_base(code))


def _authenticate(
    original, original_exit, current, entry_source, exit_source, cutoff, setup_id
):
    need(
        type(entry_source) is EntryResearchSession
        and type(exit_source) is ExitResearchSession,
        "SOURCE_PRODUCERS_REQUIRED",
    )
    validate_entry_report(original, source=entry_source)
    validate_exit_report(original_exit, source=exit_source)
    validate_exit_report(current, source=exit_source)
    need(
        original["status"] == "EVALUATED"
        and report_allowed(original, entry_source._historical_source)
        and entry_source._historical_source is exit_source._entry._historical_source,
        "SYNTHETIC_SOURCE_REQUIRED",
    )
    need(
        original_exit["source_eligibility"] == current["source_eligibility"] == "VALID",
        "CURRENT_SOURCE_BLOCKED",
    )
    identity = original_exit["original"]
    need(identity == current["original"], "SOURCE_MISMATCH")
    need(identity["entry_report_sha256"] == original["sha256"], "SOURCE_MISMATCH")
    need(setup_id is None or setup_id == identity["setup_id"], "SOURCE_MISMATCH")
    plans = [p for p in original["plans"] if p["setup_id"] == identity["setup_id"]]
    need(len(plans) == 1, "SOURCE_MISMATCH")
    plan = plans[0]
    need(
        plan["research_state"] == "RESEARCH_QUALIFIED"
        and plan["research_direction"] == identity["research_direction"],
        "SOURCE_MISMATCH",
    )
    qualified = utc(identity["qualification_at_utc"])
    need(
        qualified
        == utc(original["evaluation_at_utc"])
        == utc(original_exit["current_observation_cutoff_utc"]),
        "ORIGINAL_QUALIFICATION_REQUIRED",
    )
    need(
        qualified
        == utc(plan["confirmation"]["earliest_research_qualification_at_utc"]),
        "SOURCE_MISMATCH",
    )
    need(cutoff is not None, "EVALUATION_CUTOFF_REQUIRED")
    at = utc(cutoff.isoformat() if isinstance(cutoff, datetime) else cutoff)
    need(
        at == utc(current["current_observation_cutoff_utc"]) and at >= qualified,
        "CURRENT_CUTOFF_MISMATCH",
    )
    need(
        original["bindings"]["configuration_hashes"]
        == original_exit["bindings"]["configurations"]
        == current["bindings"]["configurations"],
        "CONFIGURATION_MISMATCH",
    )
    for field in (
        "frozen_invalidation",
        "frozen_target",
        "target_candidates",
        "exit_policy",
        "target_status",
    ):
        need(original_exit[field] == current[field], "SOURCE_MISMATCH")
    need(
        current["frozen_invalidation"] == plan["structural_invalidation"],
        "SOURCE_MISMATCH",
    )
    need(
        digest(current["exit_policy"])
        == current["bindings"]["exit_policy"]
        == original_exit["bindings"]["exit_policy"],
        "EXIT_POLICY_MISMATCH",
    )
    need(
        len(current["target_candidates"]) <= LIMITS["max_candidates"],
        "RISK_RESOURCE_LIMIT",
    )
    row = entry_source.fork_at(original).sr_log()["entries"][-1]["result"][
        "current_bar"
    ]
    need(
        row["id"] == plan["confirmation"]["candle_ids"]["C"]
        and utc(row["closed_at"]) == qualified,
        "CONFIRMATION_MISMATCH",
    )
    return plan, row, at


def _volatility(context, view, inputs, current, original, policy, geometry):
    unavailable = dict(
        status="VOLATILITY_UNAVAILABLE",
        reason_codes=["ATR_SOURCE_OR_TIMEFRAME_UNAVAILABLE"],
    )
    if context is None and view is None:
        return unavailable
    need(context is not None and view is not None, "VOLATILITY_SOURCE_MISMATCH")
    need(
        isinstance(context, ContextReport)
        and context_allowed(context, current_source()),
        "VOLATILITY_SOURCE_MISMATCH",
    )
    need(
        len(context.interpretations["source_registry"]) <= LIMITS["max_sources"],
        "RISK_RESOURCE_LIMIT",
    )
    validate_market_view_v3(view, context_report=context, **(inputs or {}))
    need(
        view["sha256"] == current["bindings"]["view"]
        and view["bindings"]["context"] == current["bindings"]["context"],
        "VOLATILITY_SOURCE_MISMATCH",
    )
    need(
        context.symbol == original["symbol"]
        and context.analysis_at == current["current_observation_cutoff_utc"],
        "VOLATILITY_SOURCE_MISMATCH",
    )
    need(
        context.configuration_sha256
        == original["bindings"]["configuration_hashes"]["context"],
        "CONFIGURATION_MISMATCH",
    )
    if policy.atr_timeframe is None:
        return unavailable
    tf = policy.atr_timeframe
    frame = context.interpretations["frames"].get(tf, {})
    vol = frame.get("volatility", {})
    es = [
        e for e in context.evidence if e.category == "VOLATILITY" and e.timeframe == tf
    ]
    if vol.get("status") != "AVAILABLE" or vol.get("atr") is None or len(es) != 1:
        return unavailable
    e = es[0]
    value = number(vol["atr"])
    if value <= 0:
        return unavailable
    need(
        e.details.get("atr") == vol["atr"]
        and utc(e.available_at)
        == utc(context.observed_facts[tf]["data_as_of"])
        <= utc(context.analysis_at),
        "VOLATILITY_SOURCE_MISMATCH",
    )
    with localcontext(ARITHMETIC):
        return dict(
            status="AVAILABLE_DESCRIPTIVE_ONLY",
            timeframe=tf,
            atr_period=context.configuration["atr_period"],
            atr_value=text_number(value),
            observed_at_utc=e.observed_at,
            available_at_utc=e.available_at,
            evidence_id=e.id,
            source_references=list(e.references),
            configuration_sha256=context.configuration_sha256,
            units="INSTRUMENT_PRICE_UNITS",
            ratio_units="DIMENSIONLESS",
            risk_to_atr=text_number(number(geometry["risk_distance"]) / value),
            reward_to_atr=(
                text_number(number(geometry["reward_distance"]) / value)
                if geometry["reward_distance"] is not None
                else None
            ),
            upstream_volatility=deepcopy(vol),
            upstream_momentum=deepcopy(frame.get("momentum")),
            scope="ORIGINAL_REFERENCE_GEOMETRY_OVER_CURRENT_SOURCE_ATR_NOT_ATR_STOP_RULE",
        )


def cost_availability(package, *, symbol, e2_sha256, cutoff):
    """Mechanical synthetic declarations only; never an observed/qualified cost model."""
    missing = dict(
        status="COST_MODEL_UNAVAILABLE",
        qualified_model_available=False,
        fields={
            k: dict(status="UNAVAILABLE", value=None)
            for k in COST_NUMBERS + ("account_currency",)
        },
        reason_codes=["COST_EVIDENCE_UNAVAILABLE"],
        spread_application="SIDE_SPECIFIC_PRICES_ALREADY_INCLUDE_SPREAD_DO_NOT_ADD_AGAIN",
    )
    if package is None:
        return missing
    need(type(package) is dict, "COST_DECLARATION_INVALID")
    need(
        package.get("symbol") == symbol and package.get("e2_sha256") == e2_sha256,
        "COST_SOURCE_MISMATCH",
    )
    allowed = set(COST_NUMBERS) | {
        "version",
        "symbol",
        "e2_sha256",
        "provenance",
        "quote_at_utc",
        "quote_available_at_utc",
        "price_basis",
        "account_currency",
        "evidence_sha256",
        "units",
    }
    try:
        need(
            set(package) <= allowed
            and type(package.get("version")) is int
            and package["version"] == 1,
            "COST_DECLARATION_INVALID",
        )
        need(
            package.get("provenance") == "SYNTHETIC_RESEARCH_DECLARATION",
            "COST_DECLARATION_INVALID",
        )
        need(
            package.get("price_basis") in (None, "BID", "ASK", "MID", "BID_ASK"),
            "COST_DECLARATION_INVALID",
        )
        for name in ("quote_at_utc", "quote_available_at_utc"):
            need(
                package.get(name) is None
                or isinstance(package[name], str)
                and len(package[name]) <= 64,
                "COST_DECLARATION_INVALID",
            )
        units = package.get("units", {})
        need(
            type(units) is dict and set(units) <= set(COST_NUMBERS),
            "COST_DECLARATION_INVALID",
        )
        need(
            all(
                v
                in (
                    "INSTRUMENT_PRICE_UNITS",
                    "ACCOUNT_CURRENCY",
                    "CONTRACT_UNITS",
                    "PRICE_UNITS_PER_POINT",
                    "PRICE_UNITS_PER_TICK",
                    "ACCOUNT_CURRENCY_PER_TICK",
                    "MULTIPLIER",
                )
                for v in units.values()
            ),
            "COST_DECLARATION_INVALID",
        )
        parsed = {}
        for k in COST_NUMBERS:
            v = package.get(k)
            if v is not None:
                parsed[k] = number(v)
                need(
                    parsed[k] >= 0
                    and (
                        parsed[k] > 0
                        or k in ("spread", "commission", "slippage", "swap")
                    ),
                    "COST_DECLARATION_INVALID",
                )
        if "bid" in parsed or "ask" in parsed:
            need(package.get("price_basis") == "BID_ASK", "COST_DECLARATION_INVALID")
            need(
                utc(package["quote_at_utc"])
                <= utc(package["quote_available_at_utc"])
                <= cutoff,
                "COST_DECLARATION_INVALID",
            )
        if "bid" in parsed and "ask" in parsed:
            need(parsed["ask"] >= parsed["bid"], "COST_DECLARATION_INVALID")
            with localcontext(ARITHMETIC):
                need(
                    "spread" not in parsed
                    or parsed["spread"] == parsed["ask"] - parsed["bid"],
                    "COST_DECLARATION_INVALID",
                )
        currency = package.get("account_currency")
        need(
            currency is None
            or isinstance(currency, str)
            and re.fullmatch("[A-Z]{3}", currency),
            "COST_DECLARATION_INVALID",
        )
        evidence = package.get("evidence_sha256")
        need(
            evidence is None
            or isinstance(evidence, str)
            and re.fullmatch("[a-f0-9]{64}", evidence),
            "COST_DECLARATION_INVALID",
        )
        out = deepcopy(missing)
        out.update(
            status="DECLARED_SYNTHETIC_NOT_QUALIFIED",
            mechanical_validation="PASS",
            declaration_sha256=digest(package),
            price_basis=package.get("price_basis"),
            quote_at_utc=package.get("quote_at_utc"),
            quote_available_at_utc=package.get("quote_available_at_utc"),
            evidence_sha256=evidence,
            freshness_status="NOT_ESTABLISHED_NO_REVIEWED_QUOTE_POLICY",
            reason_codes=[
                "DECLARATIONS_ARE_NOT_INDEPENDENT_COST_EVIDENCE",
                "NO_FILL_OR_NET_COST_MODEL",
            ],
        )
        for k, v in parsed.items():
            out["fields"][k] = dict(
                status=(
                    "DECLARED_SYNTHETIC_NOT_QUALIFIED"
                    if k in units
                    else "DECLARED_UNITS_UNAVAILABLE"
                ),
                value=text_number(v),
                units=units.get(k),
            )
        if currency is not None:
            out["fields"]["account_currency"] = dict(
                status="DECLARED_SYNTHETIC_NOT_QUALIFIED", value=currency
            )
        return out
    except (ValueError, TypeError, KeyError, AttributeError, DecimalException):
        out = deepcopy(missing)
        out.update(
            status="INVALID_DECLARATION", reason_codes=["COST_DECLARATION_INVALID"]
        )
        return out


def assess_risk(
    original_e1,
    original_e2,
    current_e2,
    *,
    entry_source=None,
    exit_source=None,
    as_of=None,
    setup_id=None,
    policy=None,
    context=None,
    view=None,
    view_inputs=None,
    costs=None
):
    try:
        selected = RiskPolicy() if policy is None else policy
        need(type(selected) is RiskPolicy, "RISK_TYPED_POLICY_REQUIRED")
        if current_source() is not None:
            need(
                asdict(selected) == asdict(RiskPolicy()),
                "E5_FROZEN_RISK_POLICY_MISMATCH",
            )
        plan, bar, at = _authenticate(
            original_e1,
            original_e2,
            current_e2,
            entry_source,
            exit_source,
            as_of,
            setup_id,
        )
        z = plan["structural_invalidation"]
        target = current_e2["frozen_target"]
        direction = plan["research_direction"]
        near = (
            None
            if target is None
            else target["lower"] if direction == "BULLISH" else target["upper"]
        )
        geometry = reference_geometry(
            direction, bar["close"], z["lower"], z["upper"], z["break_tolerance"], near
        )
        geometry["authentication"] = "SOURCE_BOUND_REFERENCE_GEOMETRY"
        vol = _volatility(
            context, view, view_inputs, current_e2, original_e1, selected, geometry
        )
        cost = cost_availability(
            costs,
            symbol=original_e1["symbol"],
            e2_sha256=current_e2["sha256"],
            cutoff=at,
        )
        states = {
            "REFERENCE_GEOMETRY_AVAILABLE",
            "COST_MODEL_UNAVAILABLE",
            "FILL_MODEL_UNAVAILABLE",
        }
        if target is None:
            states.add("TARGET_UNAVAILABLE")
        if vol["status"] == "VOLATILITY_UNAVAILABLE":
            states.add("VOLATILITY_UNAVAILABLE")
        lifecycle = current_e2["original_hypothesis_lifecycle"]["state"]
        if lifecycle == "INVALIDATED":
            states.add("HYPOTHESIS_INVALIDATED")
        if lifecycle == "EXPIRED":
            states.add("HYPOTHESIS_EXPIRED")
        if current_e2["ambiguity"]["status"] == "UNRESOLVED_EVENT_ORDER":
            states.add("OBSERVATION_ORDER_UNRESOLVED")
        if current_e2["missing_evidence"]:
            states.add("ABSTAINED")
        out = _base()
        out.update(
            source_eligibility="VALID",
            risk_policy=asdict(selected),
            symbol=original_e1["symbol"],
            original_setup=deepcopy(current_e2["original"]),
            research_direction=direction,
            qualification_at_utc=current_e2["original"]["qualification_at_utc"],
            evaluation_at_utc=at.isoformat(),
            confirmation_reference=dict(
                candle_id=bar["id"],
                value=bar["close"],
                opened_at_utc=bar["opened_at"],
                available_at_utc=bar["closed_at"],
                scope="OBSERVED_CONFIRMATION_NOT_ENTRY_FILL",
                units="INSTRUMENT_PRICE_UNITS",
            ),
            frozen_invalidation=deepcopy(z),
            frozen_target=deepcopy(target),
            target_candidates=deepcopy(current_e2["target_candidates"]),
            reference_geometry=geometry,
            reference_price_basis=deepcopy(original_e1["price_observation"]),
            volatility=vol,
            costs=cost,
            hypothesis_lifecycle=deepcopy(current_e2["original_hypothesis_lifecycle"]),
            ambiguity=deepcopy(current_e2["ambiguity"]),
            source_restrictions=deepcopy(current_e2["source_restrictions"]),
            states=sorted(states),
            missing_evidence=sorted(
                set(
                    current_e2["missing_evidence"]
                    + [s for s in states if s.endswith("UNAVAILABLE")]
                )
            ),
            supporting_evidence=sorted(
                set(
                    current_e2["supporting_evidence"]
                    + (
                        [vol["evidence_id"]]
                        if vol["status"] != "VOLATILITY_UNAVAILABLE"
                        else []
                    )
                )
            ),
            contradictory_evidence=deepcopy(current_e2["contradictory_evidence"]),
            reason_codes=["REFERENCE_RR_ONLY_NO_TRADE_SUITABILITY"],
        )
        if current_source() is not None:
            out["validation_status"] = "FILE_BOUND_RESEARCH_NOT_STRATEGY_VALIDATED"
        out["bindings"].update(
            original_e1=original_e1["sha256"],
            original_e2=original_e2["sha256"],
            current_e2=current_e2["sha256"],
            context=current_e2["bindings"]["context"],
            view=current_e2["bindings"]["view"],
            configurations=deepcopy(current_e2["bindings"]["configurations"]),
            exit_policy=current_e2["bindings"]["exit_policy"],
            risk_policy=digest(asdict(selected)),
        )
        sealed = seal(out)
        need(
            len(
                json.dumps(
                    sealed, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode("utf-8")
            )
            <= LIMITS["max_report_bytes"],
            "RISK_RESOURCE_LIMIT",
        )
        return sealed
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
        OverflowError,
        RecursionError,
        DecimalException,
    ) as exc:
        code = str(exc) if isinstance(exc, RiskInputError) else "SOURCE_MISMATCH"
        out = _base(code)
        if isinstance(exc, GeometryError):
            out["states"] += ["REFERENCE_GEOMETRY_INVALID"]
        elif "MISMATCH" in code or code == "SOURCE_PRODUCERS_REQUIRED":
            out["states"] += ["SOURCE_MISMATCH"]
        return seal(out)


def validate_risk_report(report, **source_inputs):
    try:
        need(
            type(report) is dict
            and report["sha256"]
            == digest({k: v for k, v in report.items() if k != "sha256"}),
            "RISK_REPORT_CHECKSUM_INVALID",
        )
        if source_inputs:
            expected = assess_risk(**source_inputs)
        else:
            need(
                report["source_eligibility"] == "BLOCKED", "RISK_SOURCE_INPUTS_REQUIRED"
            )
            expected = blocked_risk(report["reason_codes"][0])
            if "REFERENCE_GEOMETRY_INVALID" in report["states"]:
                e = _base(report["reason_codes"][0])
                e["states"] += ["REFERENCE_GEOMETRY_INVALID"]
                expected = seal(e)
            elif "SOURCE_MISMATCH" in report["states"]:
                e = _base(report["reason_codes"][0])
                e["states"] += ["SOURCE_MISMATCH"]
                expected = seal(e)
        need(report == expected, "RISK_REPORT_SOURCE_BINDING_INVALID")
    except (TypeError, KeyError, AttributeError, IndexError, RecursionError):
        raise ValueError("RISK_REPORT_SCHEMA_INVALID") from None
    return True
