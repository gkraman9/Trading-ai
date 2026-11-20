"""Schema, evidence-grounded plans and common feasibility validation for every engine."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from math import isfinite
from iat.three_engine import ENGINES, VERSION
from iat.three_engine.config import PROTOCOL, PROTOCOL_SHA256
from iat.three_engine.evidence import validate as validate_bundle
from iat.live_shadow.policy import costs_match_symbol
from iat.strategy_qualification.backtest import Costs, dec
from iat.replay_dataset import utc
from iat.intelligence.strategy_replay import digest

RESPONSE_KEYS = (
    "response_version",
    "bundle_id",
    "decision",
    "entry_type",
    "entry_anchor_id",
    "stop_anchor_id",
    "target_refs",
    "tp_allocations",
    "risk_percent",
    "confidence_estimate",
    "requested_band",
    "market_reasoning",
    "supporting_evidence_ids",
    "contradicting_evidence_ids",
    "invalidation_conditions",
    "expiry_seconds",
    "hold_seconds",
    "risk_reduction",
)


def response_schema():
    nullable = lambda t: dict(type=[t, "null"])
    p = dict(
        response_version=dict(type="integer", enum=[1]),
        bundle_id=dict(type="string"),
        decision=dict(type="string", enum=["BUY", "SELL", "WAIT", "BLOCKED"]),
        entry_type=dict(type="string", enum=PROTOCOL["entry_modes"]),
        entry_anchor_id=nullable("string"),
        stop_anchor_id=nullable("string"),
        target_refs=dict(type="array", items=dict(type="string")),
        tp_allocations=dict(type="array", items=dict(type="string")),
        risk_percent=dict(type="string"),
        confidence_estimate=nullable("number"),
        requested_band=dict(
            type=["string", "null"], enum=[None, "40_60", "60_80", "80_90"]
        ),
        market_reasoning=dict(
            type="array",
            items=dict(
                type="object",
                additionalProperties=False,
                required=["interpretation", "evidence_id", "role"],
                properties=dict(
                    interpretation=dict(
                        type="string", enum=PROTOCOL["interpretation_codes"]
                    ),
                    evidence_id=dict(type="string"),
                    role=dict(
                        type="string", enum=["SUPPORT", "CONFLICT", "UNCERTAINTY"]
                    ),
                ),
            ),
        ),
        supporting_evidence_ids=dict(type="array", items=dict(type="string")),
        contradicting_evidence_ids=dict(type="array", items=dict(type="string")),
        invalidation_conditions=dict(
            type="array", items=dict(type="string", enum=PROTOCOL["invalidation_codes"])
        ),
        expiry_seconds=dict(type="integer"),
        hold_seconds=dict(type="integer"),
        risk_reduction=dict(type="string", enum=["NONE", "BREAKEVEN_AT_R1"]),
    )
    return dict(
        type="object",
        additionalProperties=False,
        required=list(RESPONSE_KEYS),
        properties=p,
    )


def empty_response(bundle, decision="WAIT"):
    return dict(
        response_version=1,
        bundle_id=bundle["id"],
        decision=decision,
        entry_type="MARKET",
        entry_anchor_id=None,
        stop_anchor_id=None,
        target_refs=[],
        tp_allocations=[],
        risk_percent=PROTOCOL["baseline_risk_percent"],
        confidence_estimate=None,
        requested_band=None,
        market_reasoning=[],
        supporting_evidence_ids=[],
        contradicting_evidence_ids=[],
        invalidation_conditions=["OPPOSING_M1_CHOCH", "TIME_LIMIT"],
        expiry_seconds=PROTOCOL["expiry_seconds"],
        hold_seconds=PROTOCOL["max_hold_seconds"],
        risk_reduction="NONE",
    )


def validate_response(raw, bundle):
    if (
        type(raw) is not dict
        or set(raw) != set(RESPONSE_KEYS)
        or type(raw["response_version"]) is not int
        or raw["response_version"] != 1
        or raw["bundle_id"] != bundle["id"]
    ):
        raise ValueError("MODEL_SCHEMA_INVALID")
    if (
        raw["decision"] not in ("BUY", "SELL", "WAIT", "BLOCKED")
        or raw["entry_type"] not in PROTOCOL["entry_modes"]
        or raw["risk_reduction"] not in ("NONE", "BREAKEVEN_AT_R1")
    ):
        raise ValueError("MODEL_ENUM_INVALID")
    if raw["requested_band"] not in (None, "40_60", "60_80", "80_90"):
        raise ValueError("CONFIDENCE_BAND_INVALID")
    confidence = raw["confidence_estimate"]
    if confidence is not None and (
        type(confidence) not in (int, float)
        or not isfinite(confidence)
        or not 0 <= confidence <= 100
    ):
        raise ValueError("CONFIDENCE_UNCALIBRATED_VALUE_INVALID")
    if not 0 < dec(raw["risk_percent"]) <= dec(PROTOCOL["max_risk_percent"]):
        raise ValueError("RISK_PERCENT_EXCEEDS_POLICY")
    if (
        type(raw["expiry_seconds"]) is not int
        or not 1 <= raw["expiry_seconds"] <= 30
        or type(raw["hold_seconds"]) is not int
        or not 1 <= raw["hold_seconds"] <= 900
    ):
        raise ValueError("TIMING_POLICY_INVALID")
    ids = (
        set(bundle["evidence_index"])
        | set(bundle["price_catalog"])
        | ({bundle["quote"]["id"]} if bundle["quote"] else set())
    )
    for key in ("supporting_evidence_ids", "contradicting_evidence_ids"):
        if (
            type(raw[key]) is not list
            or len(raw[key]) > 32
            or any(type(v) is not str or v not in ids for v in raw[key])
            or len(set(raw[key])) != len(raw[key])
        ):
            raise ValueError("EVIDENCE_REFERENCE_INVALID")
    if type(raw["market_reasoning"]) is not list or len(raw["market_reasoning"]) > 12:
        raise ValueError("REASONING_INVALID")
    for r in raw["market_reasoning"]:
        if (
            type(r) is not dict
            or set(r) != {"interpretation", "evidence_id", "role"}
            or r["interpretation"] not in PROTOCOL["interpretation_codes"]
            or r["evidence_id"] not in ids
            or r["role"] not in ("SUPPORT", "CONFLICT", "UNCERTAINTY")
        ):
            raise ValueError("REASONING_REFERENCE_INVALID")
        expected = (
            raw["supporting_evidence_ids"]
            if r["role"] == "SUPPORT"
            else raw["contradicting_evidence_ids"] if r["role"] == "CONFLICT" else None
        )
        if expected is not None and r["evidence_id"] not in expected:
            raise ValueError("REASONING_ROLE_INCONSISTENT")
    if type(raw["invalidation_conditions"]) is not list or any(
        c not in PROTOCOL["invalidation_codes"] for c in raw["invalidation_conditions"]
    ):
        raise ValueError("INVALIDATION_INVALID")
    if (
        type(raw["target_refs"]) is not list
        or type(raw["tp_allocations"]) is not list
        or len(raw["target_refs"]) != len(raw["tp_allocations"])
        or len(raw["target_refs"]) > 3
    ):
        raise ValueError("TARGET_ARRAY_INVALID")
    for key in ("entry_anchor_id", "stop_anchor_id"):
        if raw[key] is not None and (
            type(raw[key]) is not str or raw[key] not in bundle["price_catalog"]
        ):
            raise ValueError("PRICE_REFERENCE_INVALID")
    if any(
        type(v) is not str
        or v not in bundle["price_catalog"]
        and v not in PROTOCOL["target_rules"]
        for v in raw["target_refs"]
    ):
        raise ValueError("TARGET_REFERENCE_INVALID")
    if any(not 0 <= dec(x) <= 1 for x in raw["tp_allocations"]):
        raise ValueError("ALLOCATION_INVALID")
    if raw["decision"] in ("BUY", "SELL"):
        required_opposition = {
            k
            for k, e in bundle["evidence_index"].items()
            if e.get("category") == "TRANSITION"
            and e.get("details", {}).get("fresh")
            and e.get("direction")
            == ("BEARISH" if raw["decision"] == "BUY" else "BULLISH")
            and e.get("details", {}).get("event_type") == e.get("direction") + "_CHOCH"
        }
        if not required_opposition <= set(raw["contradicting_evidence_ids"]):
            raise ValueError("CONTRADICTION_NOT_ACKNOWLEDGED")
        if not {"OPPOSING_M1_CHOCH", "TIME_LIMIT"} <= set(
            raw["invalidation_conditions"]
        ):
            raise ValueError("INVALIDATION_POLICY_REQUIRED")
        if (
            not raw["supporting_evidence_ids"]
            or not raw["market_reasoning"]
            or raw["stop_anchor_id"] is None
            or not raw["target_refs"]
            or sum(map(dec, raw["tp_allocations"])) != 1
        ):
            raise ValueError("DIRECTIONAL_PLAN_INCOMPLETE")
        if raw["entry_type"] != "MARKET" and raw["entry_anchor_id"] is None:
            raise ValueError("ENTRY_ANCHOR_REQUIRED")
    return deepcopy(raw)


def stop_from_level(price, side, tick):
    x = dec(price) - tick if side == "BUY" else dec(price) + tick
    return (x / tick).to_integral_value(
        rounding=ROUND_FLOOR if side == "BUY" else ROUND_CEILING
    ) * tick


def feasibility(
    bundle,
    config,
    side,
    entry,
    stop,
    targets,
    allocations,
    risk_percent,
    *,
    equity=None,
    free_margin=None,
    entry_quote_required=True
):
    if config["costs"] is None or config["account"] is None:
        raise ValueError("COST_ACCOUNT_MARGIN_METADATA_REQUIRED")
    a = config["account"]
    c = dict(config["costs"])
    c["rollovers"] = tuple(c["rollovers"])
    cost = Costs(**c)
    if bundle["costs"] != config["costs"] or bundle["account"] != a:
        raise ValueError("COST_ACCOUNT_BINDING_MISMATCH")
    if not costs_match_symbol(cost, bundle["symbol_specifications"]):
        raise ValueError("CONTRACT_OR_CURRENCY_UNSUPPORTED")
    if utc(a["declared_at"]) > utc(bundle["cutoff"]) or utc(cost.known_at) > utc(
        bundle["cutoff"]
    ):
        raise ValueError("FUTURE_COST_OR_ACCOUNT_EVIDENCE")
    tick = dec(cost.tick_size)
    contract = dec(cost.contract_size)
    if dec(a["tick_value_per_lot"]) != tick * contract:
        raise ValueError("TICK_VALUE_CONTRACT_MISMATCH")
    if any(v <= 0 or v % tick for v in (entry, stop, *targets)):
        raise ValueError("PRICE_GRID_INVALID")
    direction = 1 if side == "BUY" else -1
    risk = (entry - stop) * direction
    if (
        risk <= 0
        or any((v - entry) * direction <= 0 for v in targets)
        or any((b - a) * direction <= 0 for a, b in zip(targets, targets[1:]))
    ):
        raise ValueError("SL_TP_ORDER_INVALID")
    if risk < max(tick, dec(cost.minimum_stop_distance)):
        raise ValueError("STOP_DISTANCE_INVALID")
    q = bundle["quote"]
    if entry_quote_required:
        gap = dec(q["bid"]) - stop if side == "BUY" else stop - dec(q["ask"])
        if gap < max(tick, dec(cost.minimum_stop_distance)):
            raise ValueError("STOP_DISTANCE_INVALID")
    if dec(q["spread"]) > dec(cost.max_spread):
        raise ValueError("SPREAD_EXCEEDS_POLICY")
    unit_cost = (
        2 * (dec(cost.commission_per_side_per_lot) + dec(cost.fee_per_side_per_lot))
        + 2 * tick * cost.slippage_ticks * contract
    )
    if (
        min((v - entry) * direction for v in targets) * contract
        <= unit_cost + dec(q["spread"]) * contract
    ):
        raise ValueError("MOVE_CANNOT_COVER_DECLARED_COSTS")
    rr = min((v - entry) * direction for v in targets) / risk
    if rr < dec(PROTOCOL["min_reward_risk"]):
        raise ValueError("REWARD_RISK_INSUFFICIENT")
    capital = dec(a["equity"]) if equity is None else dec(equity)
    margin = dec(a["free_margin"]) if free_margin is None else dec(free_margin)
    budget = capital * dec(risk_percent) / 100
    unit_loss = risk * contract + unit_cost
    step = dec(cost.volume_step)
    volume = (
        min(budget / unit_loss, dec(PROTOCOL["max_volume"])) / step
    ).to_integral_value(rounding=ROUND_FLOOR) * step
    minimum = Decimal(str(bundle["symbol_specifications"]["volume_min"]))
    if volume < minimum:
        raise ValueError("MINIMUM_LOT_EXCEEDS_RISK_BUDGET")
    amounts = [volume * dec(v) for v in allocations]
    if any(x and (x < minimum or x % step) for x in amounts):
        raise ValueError("PARTIAL_VOLUME_UNSUPPORTED")
    required = volume * dec(a["margin_per_lot"][side])
    if required > margin:
        raise ValueError("INSUFFICIENT_DECLARED_FREE_MARGIN")
    # Per-component broker rounding can exceed linear estimates; recalculate before approval.
    money = lambda v: v.quantize(
        dec(cost.currency_quantum), rounding=cost.money_rounding
    )
    fees = 2 * (
        money(dec(cost.commission_per_side_per_lot) * volume)
        + money(dec(cost.fee_per_side_per_lot) * volume)
    )
    loss = (
        risk * contract * volume
        + fees
        + 2 * tick * cost.slippage_ticks * contract * volume
    )
    if loss > budget:
        raise ValueError("ROUNDED_COSTS_EXCEED_RISK_BUDGET")
    return dict(
        lot_size=str(volume),
        risk_amount=str(loss),
        risk_budget=str(budget),
        margin_required=str(required),
        free_margin=str(margin),
        equity=str(capital),
        reward_risk=str(rr),
        commission_and_fees=str(fees),
        tick_value_per_lot=a["tick_value_per_lot"],
        assurance="DECLARED_PAPER_FEASIBILITY_NOT_BROKER_APPROVAL",
    )


def proposal(
    engine,
    bundle,
    raw,
    available_at,
    config,
    *,
    model="DETERMINISTIC",
    request_at=None,
    response_at=None,
    blocked_reason=None
):
    validate_bundle(bundle)
    if engine not in ENGINES:
        raise ValueError("ENGINE_INVALID")
    out = dict(
        proposal_version=1,
        engine=engine,
        engine_version=VERSION,
        symbol="XAUUSD",
        timeframe="M1",
        confirmation_timeframe="M5",
        bundle_id=bundle["id"],
        analysis_at=bundle["analysis_at"],
        decision="BLOCKED",
        provider_response_valid=False,
        setup_id=None,
        stop_anchor_price=None,
        entry_type=None,
        entry_price=None,
        stop_loss=None,
        take_profit_1=None,
        take_profit_2=None,
        take_profit_3=None,
        tp_allocations=None,
        risk_percent=None,
        risk_amount=None,
        lot_size=None,
        reward_risk=None,
        confidence_band="UNCALIBRATED",
        confidence_probability=None,
        model_confidence_assessment=None,
        requested_research_band=None,
        market_reasoning=[],
        supporting_evidence_ids=[],
        contradicting_evidence_ids=[],
        invalidation_conditions=[],
        decision_available_at=available_at,
        expires_at=None,
        request_at=request_at,
        response_at=response_at,
        model=model,
        prompt_version=PROTOCOL["prompt_version"],
        latency_seconds=None,
        provider_latency_seconds=None,
        market_to_decision_seconds=None,
        feasibility=None,
        reason_codes=[],
        source_kind=bundle["source_kind"],
        hold_seconds=None,
        risk_reduction="NONE",
        execution_allowed=False,
        orders_requested=0,
        signal="WAIT",
        protocol_sha256=PROTOCOL_SHA256,
    )
    out["latency_seconds"] = str(
        Decimal(str((utc(available_at) - utc(bundle["cutoff"])).total_seconds()))
    )
    out["market_to_decision_seconds"] = str(
        Decimal(
            str((utc(available_at) - utc(bundle["source_received_at"])).total_seconds())
        )
    )
    if request_at is not None and response_at is not None:
        out["provider_latency_seconds"] = str(
            Decimal(str((utc(response_at) - utc(request_at)).total_seconds()))
        )
    try:
        if blocked_reason:
            raise ValueError(blocked_reason)
        if not bundle["quality"]["valid"]:
            raise ValueError("BLOCKED_MARKET_EVIDENCE")
        r = validate_response(raw, bundle)
        out["provider_response_valid"] = True
        out.update(
            decision=r["decision"],
            entry_type=r["entry_type"],
            market_reasoning=r["market_reasoning"],
            supporting_evidence_ids=sorted(r["supporting_evidence_ids"]),
            contradicting_evidence_ids=sorted(r["contradicting_evidence_ids"]),
            invalidation_conditions=r["invalidation_conditions"],
            model_confidence_assessment=(
                str(r["confidence_estimate"])
                if r["confidence_estimate"] is not None
                else None
            ),
            requested_research_band=r["requested_band"],
            hold_seconds=r["hold_seconds"],
            risk_reduction=r["risk_reduction"],
        )
        if engine != "A_RULES" and r["hold_seconds"] > PROTOCOL["max_hold_seconds"]:
            raise ValueError("HOLD_POLICY_EXCEEDED")
        if r["decision"] in ("WAIT", "BLOCKED"):
            out["reason_codes"] = ["ENGINE_ABSTENTION"]
            return seal(out)
        if utc(available_at) < utc(bundle["cutoff"]):
            raise ValueError("DECISION_PRECEDES_CUTOFF")
        expires = utc(bundle["cutoff"]) + timedelta(seconds=r["expiry_seconds"])
        out["expires_at"] = expires.isoformat()
        if utc(available_at) >= expires:
            raise ValueError("OPPORTUNITY_EXPIRED")
        q = bundle["quote"]
        if (
            not 0
            <= (utc(available_at) - utc(q["timestamp"])).total_seconds()
            <= PROTOCOL["quote_age_seconds"]
        ):
            raise ValueError("QUOTE_STALE_AT_DECISION")
        if bundle["session"]["new_positions"] is False:
            raise ValueError("SESSION_NEW_POSITIONS_RESTRICTED")
        if config["costs"] is None:
            raise ValueError("COST_ACCOUNT_MARGIN_METADATA_REQUIRED")
        tick = dec(config["costs"]["tick_size"])
        side = r["decision"]
        catalog = bundle["price_catalog"]
        entry = (
            dec(q["ask"] if side == "BUY" else q["bid"])
            if r["entry_type"] == "MARKET"
            else dec(catalog[r["entry_anchor_id"]]["price"])
        )
        stop = stop_from_level(catalog[r["stop_anchor_id"]]["price"], side, tick)
        risk = abs(entry - stop)
        targets = [
            (
                entry + (1 if side == "BUY" else -1) * risk * Decimal(ref[1:])
                if ref in PROTOCOL["target_rules"]
                else dec(catalog[ref]["price"])
            )
            for ref in r["target_refs"]
        ]
        if r["entry_type"] == "REVERSAL" and not any(
            e.get("category") == "LIQUIDITY" for e in bundle["evidence_index"].values()
        ):
            raise ValueError("CONFIRMED_REVERSAL_EVIDENCE_REQUIRED")
        f = feasibility(
            bundle,
            config,
            side,
            entry,
            stop,
            targets,
            r["tp_allocations"],
            r["risk_percent"],
            entry_quote_required=r["entry_type"] == "MARKET",
        )
        out.update(
            setup_id=digest(
                [
                    engine,
                    side,
                    r["entry_type"],
                    r["entry_anchor_id"],
                    r["stop_anchor_id"],
                    r["target_refs"],
                ]
            ),
            stop_anchor_price=catalog[r["stop_anchor_id"]]["price"],
            entry_price=str(entry),
            stop_loss=str(stop),
            tp_allocations=r["tp_allocations"],
            risk_percent=r["risk_percent"],
            risk_amount=f["risk_amount"],
            lot_size=f["lot_size"],
            reward_risk=f["reward_risk"],
            feasibility=f,
            reason_codes=[
                "UNQUALIFIED_RESEARCH_PLAN_FEASIBLE_NOT_EXECUTION_AUTHORIZATION"
            ],
        )
        for index, t in enumerate(targets, 1):
            out["take_profit_" + str(index)] = str(t)
    except Exception as exc:
        code = str(exc)
        known = {
            "COST_ACCOUNT_MARGIN_METADATA_REQUIRED",
            "CONTRACT_OR_CURRENCY_UNSUPPORTED",
            "FUTURE_COST_OR_ACCOUNT_EVIDENCE",
            "TICK_VALUE_CONTRACT_MISMATCH",
            "PRICE_GRID_INVALID",
            "SL_TP_ORDER_INVALID",
            "STOP_DISTANCE_INVALID",
            "SPREAD_EXCEEDS_POLICY",
            "MOVE_CANNOT_COVER_DECLARED_COSTS",
            "REWARD_RISK_INSUFFICIENT",
            "MINIMUM_LOT_EXCEEDS_RISK_BUDGET",
            "PARTIAL_VOLUME_UNSUPPORTED",
            "INSUFFICIENT_DECLARED_FREE_MARGIN",
            "ROUNDED_COSTS_EXCEED_RISK_BUDGET",
            "BLOCKED_MARKET_EVIDENCE",
            "DECISION_PRECEDES_CUTOFF",
            "OPPORTUNITY_EXPIRED",
            "QUOTE_STALE_AT_DECISION",
            "SESSION_NEW_POSITIONS_RESTRICTED",
            "CONFIRMED_REVERSAL_EVIDENCE_REQUIRED",
            "MODEL_SCHEMA_INVALID",
            "PROVIDER_DISABLED",
            "PROVIDER_TIMEOUT",
            "PROVIDER_ERROR",
            "NO_RULE_CANDIDATE",
            "REQUEST_INTERRUPTED",
            "BUDGET_EXHAUSTED",
            "AI_INPUT_TOO_LARGE",
            "AI_PRICING_UNAVAILABLE",
        }
        out.update(
            decision="BLOCKED",
            reason_codes=[code if code in known else "PROPOSAL_VALIDATION_FAILED"],
        )
        for key in (
            "entry_price",
            "stop_loss",
            "take_profit_1",
            "take_profit_2",
            "take_profit_3",
            "risk_amount",
            "lot_size",
            "reward_risk",
            "feasibility",
        ):
            out[key] = None
    return seal(out)


def seal(v):
    v["decision_id"] = digest(v)
    return v


def validate_proposal(p):
    if type(p) is not dict or p.get("decision_id") != digest(
        {k: v for k, v in p.items() if k != "decision_id"}
    ):
        raise ValueError("PROPOSAL_CHECKSUM_INVALID")
    if (
        p["execution_allowed"] is not False
        or type(p["orders_requested"]) is not int
        or p["orders_requested"] != 0
        or p["signal"] != "WAIT"
        or p["confidence_probability"] is not None
        or p["confidence_band"] != "UNCALIBRATED"
    ):
        raise ValueError("PROPOSAL_SAFETY_INVALID")
    if (
        p["engine"] not in ENGINES
        or p["proposal_version"] != 1
        or p["engine_version"] != VERSION
        or p["protocol_sha256"] != PROTOCOL_SHA256
    ):
        raise ValueError("PROPOSAL_VERSION_INVALID")
    if p["decision"] not in ("BUY", "SELL", "WAIT", "BLOCKED") or utc(
        p["analysis_at"]
    ) > utc(p["decision_available_at"]):
        raise ValueError("PROPOSAL_CHRONOLOGY_INVALID")
    if p["decision"] in ("BUY", "SELL"):
        if (
            p["lot_size"] is None
            or dec(p["lot_size"]) <= 0
            or p["feasibility"] is None
            or dec(p["risk_amount"]) > dec(p["feasibility"]["risk_budget"])
        ):
            raise ValueError("PROPOSAL_RISK_INVALID")
        entry, stop = dec(p["entry_price"]), dec(p["stop_loss"])
        direction = 1 if p["decision"] == "BUY" else -1
        targets = [
            dec(p[k])
            for k in ("take_profit_1", "take_profit_2", "take_profit_3")
            if p[k] is not None
        ]
        if (
            not targets
            or (entry - stop) * direction <= 0
            or any((t - entry) * direction <= 0 for t in targets)
            or utc(p["expires_at"]) <= utc(p["decision_available_at"])
        ):
            raise ValueError("PROPOSAL_PLAN_INVALID")
    else:
        if any(
            p[k] is not None
            for k in (
                "entry_price",
                "stop_loss",
                "take_profit_1",
                "take_profit_2",
                "take_profit_3",
                "lot_size",
                "risk_amount",
                "feasibility",
            )
        ):
            raise ValueError("ABSTENTION_CONTAINS_TRADE")
    return True


def proposal_schema():
    strings = [
        "engine_version",
        "symbol",
        "timeframe",
        "confirmation_timeframe",
        "bundle_id",
        "analysis_at",
        "decision_available_at",
        "model",
        "prompt_version",
        "source_kind",
        "protocol_sha256",
        "decision_id",
        "confidence_band",
        "risk_reduction",
        "signal",
    ]
    nullable = [
        "setup_id",
        "stop_anchor_price",
        "entry_type",
        "entry_price",
        "stop_loss",
        "take_profit_1",
        "take_profit_2",
        "take_profit_3",
        "risk_percent",
        "risk_amount",
        "lot_size",
        "reward_risk",
        "model_confidence_assessment",
        "requested_research_band",
        "expires_at",
        "request_at",
        "response_at",
        "latency_seconds",
        "provider_latency_seconds",
        "market_to_decision_seconds",
    ]
    properties = {k: dict(type="string") for k in strings}
    properties.update({k: dict(type=["string", "null"]) for k in nullable})
    properties.update(
        proposal_version=dict(const=1),
        engine=dict(type="string", enum=list(ENGINES)),
        decision=dict(type="string", enum=["BUY", "SELL", "WAIT", "BLOCKED"]),
        confidence_probability=dict(type="null"),
        provider_response_valid=dict(type="boolean"),
        execution_allowed=dict(const=False),
        orders_requested=dict(type="integer", const=0),
        signal=dict(const="WAIT"),
        confidence_band=dict(const="UNCALIBRATED"),
        tp_allocations=dict(type=["array", "null"], items=dict(type="string")),
        market_reasoning=response_schema()["properties"]["market_reasoning"],
        supporting_evidence_ids=dict(type="array", items=dict(type="string")),
        contradicting_evidence_ids=dict(type="array", items=dict(type="string")),
        invalidation_conditions=dict(type="array", items=dict(type="string")),
        reason_codes=dict(type="array", items=dict(type="string")),
        hold_seconds=dict(type=["integer", "null"]),
        feasibility=dict(type=["object", "null"]),
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://iat.local/schemas/three-engine-proposal-v1",
        "type": "object",
        "additionalProperties": False,
        "required": sorted(properties),
        "properties": properties,
    }
