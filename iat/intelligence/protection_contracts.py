"""E4.6 synthetic-only protection contracts; no broker or execution adapter."""

from iat.paper_source_scope import current_source
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from iat.intelligence.paper_contracts import (
    require,
    at,
    dec,
    canonical,
    report,
    BrokerSpecification,
    SyntheticCosts,
    SyntheticQuoteTape,
    financial_context,
)
from iat.intelligence.risk_intelligence import number, text_number
from iat.intelligence.strategy_replay import digest


@dataclass(frozen=True)
class ProtectiveStopPolicy:
    mapping: str
    trigger_basis: str
    latency_ms: int
    trigger_quote_can_fill: bool
    establishment_timing: str
    version: int = 1

    def __post_init__(self):
        require(
            type(self.version) is int and self.version == 1, "STOP_VERSION_UNSUPPORTED"
        )
        require(
            self.mapping == "DECLARED_SYNTHETIC_STRUCTURE_TO_QUOTE_STOP",
            "STOP_MAPPING_REQUIRED",
        )
        require(
            self.trigger_basis == "LONG_BID_SHORT_ASK", "STOP_TRIGGER_BASIS_UNSUPPORTED"
        )
        require(
            type(self.latency_ms) is int and 0 <= self.latency_ms <= 86400000,
            "STOP_LATENCY_REQUIRED",
        )
        require(type(self.trigger_quote_can_fill) is bool, "STOP_FILL_RULE_REQUIRED")
        require(
            not self.trigger_quote_can_fill or self.latency_ms == 0,
            "TRIGGER_FILL_REQUIRES_EXPLICIT_ZERO_LATENCY",
        )
        require(
            self.establishment_timing == "AT_ENTRY_QUOTE_RECEIPT_BEFORE_OPEN",
            "STOP_ESTABLISHMENT_POLICY_REQUIRED",
        )


@dataclass(frozen=True)
class LiquidationPolicy:
    model: str
    equity_basis: str
    action: str
    latency_ms: int
    trigger_quote_can_fill: bool
    version: int = 1

    def __post_init__(self):
        require(
            type(self.version) is int and self.version == 1,
            "LIQUIDATION_VERSION_UNSUPPORTED",
        )
        require(
            self.model == "SYNTHETIC_EQUITY_OVER_FROZEN_ENTRY_MARGIN",
            "LIQUIDATION_MODEL_UNSUPPORTED",
        )
        require(
            self.equity_basis == "NET_LIQUIDATION_EQUITY_WITH_DECLARED_COSTS",
            "MARGIN_EQUITY_BASIS_REQUIRED",
        )
        require(
            self.action == "SYNTHETIC_EXIT_ON_STOP_OUT_ONLY",
            "LIQUIDATION_ACTION_UNSUPPORTED",
        )
        require(
            type(self.latency_ms) is int and 0 <= self.latency_ms <= 86400000,
            "LIQUIDATION_LATENCY_REQUIRED",
        )
        require(
            type(self.trigger_quote_can_fill) is bool, "LIQUIDATION_FILL_RULE_REQUIRED"
        )
        require(
            not self.trigger_quote_can_fill or self.latency_ms == 0,
            "TRIGGER_FILL_REQUIRES_EXPLICIT_ZERO_LATENCY",
        )


@financial_context
def assess_protection_plan(
    risk,
    *,
    risk_inputs,
    account,
    tape,
    quote,
    specification,
    costs,
    policy,
    fill_policy,
    stop_policy,
    liquidation_policy,
    as_of
):
    """Plan is proposed before opening, not an order or qualification approval."""
    from iat.intelligence.capital_intelligence import assess_capital

    require(
        type(stop_policy) is ProtectiveStopPolicy
        and type(liquidation_policy) is LiquidationPolicy,
        "TYPED_PROTECTION_POLICIES_REQUIRED",
    )
    if current_source() is not None:
        require(
            canonical(stop_policy) == current_source().policies["stop"]
            and canonical(liquidation_policy)
            == current_source().policies["liquidation"],
            "E5_FROZEN_PROTECTION_POLICY_MISMATCH",
        )
    require(type(tape) is SyntheticQuoteTape, "QUOTE_PRODUCER_REQUIRED")
    require(
        at(as_of) == at(quote["quote"]["available_at_utc"]),
        "PROTECTED_ENTRY_REQUIRES_RECEIPT_CUTOFF",
    )
    capital = assess_capital(
        risk,
        risk_inputs=risk_inputs,
        account=account,
        tape=tape,
        quote=quote,
        specification=specification,
        costs=costs,
        policy=policy,
        fill_policy=fill_policy,
        as_of=as_of,
    )
    if capital["status"] == "CAPITAL_ASSESSMENT_UNAVAILABLE":
        return report(
            "IAT_PROTECTION_PLAN_V1",
            status="BLOCKED",
            capital=capital,
            stop=None,
            reason_codes=capital["reason_codes"],
        )
    require(
        type(specification) is BrokerSpecification and type(costs) is SyntheticCosts,
        "TYPED_FINANCIAL_POLICIES_REQUIRED",
    )
    q = quote["quote"]
    values = specification.validate(q, as_of)
    threshold = dec(risk["reference_geometry"]["invalidation_threshold"], positive=True)
    require(threshold % values["tick_size"] == 0, "STOP_OFF_TICK_GRID")
    direction = risk["research_direction"]
    side = "bid" if direction == "BULLISH" else "ask"
    distance = (
        dec(q[side], positive=True) - threshold
        if direction == "BULLISH"
        else threshold - dec(q[side], positive=True)
    )
    require(distance > 0, "STOP_ALREADY_TRIGGERED_OR_WRONG_SIDE_AT_ENTRY")
    require(distance >= values["min_stop_distance"], "STOP_MINIMUM_DISTANCE")
    return report(
        "IAT_PROTECTION_PLAN_V1",
        status=(
            "READY_TO_ESTABLISH"
            if capital["status"] == "HYPOTHETICAL_POSITION_ELIGIBLE"
            else "CAPITAL_REJECTED"
        ),
        capital=capital,
        stop=dict(
            threshold=text_number(threshold),
            direction=direction,
            trigger_side=side.upper(),
            structural_reference=deepcopy(risk["frozen_invalidation"]),
            structural_source_price_basis=deepcopy(risk["reference_price_basis"]),
            mapping=stop_policy.mapping,
            reference_available_at_utc=risk["evaluation_at_utc"],
            establishment_at_utc=at(as_of).isoformat(),
            establishment_order="ESTABLISH_BEFORE_OPEN_IN_SAME_RECEIPT_TRANSACTION",
            not_a_broker_stop=True,
            policy=canonical(stop_policy),
        ),
        liquidation_policy=canonical(liquidation_policy),
        bindings=dict(
            risk=risk["sha256"],
            original_e1=risk["bindings"]["original_e1"],
            original_e2=risk["bindings"]["original_e2"],
            account=account.snapshot()["sha256"],
            entry_quote=quote["sha256"],
            quote_source=deepcopy(quote["source"]),
            specification=digest(canonical(specification)),
            costs=digest(canonical(costs)),
            capital=capital["sha256"],
            stop_policy=digest(canonical(stop_policy)),
            liquidation_policy=digest(canonical(liquidation_policy)),
        ),
        reason_codes=["SYNTHETIC_PROTECTION_ONLY_NOT_EXNESS_EXECUTION_BEHAVIOR"],
    )


def validate_protection_plan(value, **inputs):
    require(
        value == assess_protection_plan(**inputs), "PROTECTION_PLAN_SOURCE_MISMATCH"
    )
    return True


@financial_context
def margin_assessment(*, equity, used_margin, margin_call_ratio, stop_out_ratio):
    """Isolated declared-model arithmetic; not source or account authentication."""
    e = number(equity)
    m = dec(used_margin)
    call = dec(margin_call_ratio)
    stop = dec(stop_out_ratio)
    require(call >= stop, "MARGIN_THRESHOLDS_INVALID")
    ratio = None if m == 0 else e / m
    warning = ratio is not None and ratio <= call
    stop_out = ratio is not None and ratio <= stop
    return report(
        "IAT_SYNTHETIC_MARGIN_V1",
        authentication="NOT_ESTABLISHED_BY_ARITHMETIC",
        equity=text_number(e),
        used_margin=text_number(m),
        free_margin=text_number(e - m),
        margin_level_percent=text_number(ratio * 100) if ratio is not None else None,
        status=(
            "NO_USED_MARGIN"
            if ratio is None
            else (
                "STOP_OUT_CONDITION"
                if stop_out
                else "MARGIN_WARNING" if warning else "NORMAL"
            )
        ),
        warning=warning,
        stop_out=stop_out,
        new_positions_restricted=warning or e <= 0,
        margin_call_percent=text_number(call * 100),
        stop_out_percent=text_number(stop * 100),
        equity_basis="NET_LIQUIDATION_EQUITY_WITH_DECLARED_COSTS",
        margin_call_is_not_a_fill=True,
    )


def exit_intent(
    *,
    roles,
    direction,
    available_at,
    occurred_at,
    occurred_interval,
    trigger_quote,
    quote_source,
    entry_sequence,
    latency_ms,
    can_fill_trigger,
    evidence
):
    return report(
        "IAT_PROTECTION_EXIT_INTENT_V1",
        roles=sorted(roles),
        direction=direction,
        decision_available_at_utc=at(available_at).isoformat(),
        trigger_occurred_at_utc=occurred_at,
        trigger_interval_utc=occurred_interval,
        trigger_quote=deepcopy(trigger_quote),
        quote_source=deepcopy(quote_source),
        entry_sequence=entry_sequence,
        latency_ms=latency_ms,
        can_fill_trigger=can_fill_trigger,
        deadline_utc=(
            at(available_at) + timedelta(milliseconds=latency_ms)
        ).isoformat(),
        evidence=deepcopy(evidence),
    )


def _eligible(row, intent, cutoff):
    q = row["quote"]
    d = at(intent["decision_available_at_utc"])
    deadline = at(intent["deadline_utc"])
    trigger = intent["trigger_quote"]
    same = trigger is not None and row["sha256"] == trigger["sha256"]
    return (
        row["source"] == intent["quote_source"]
        and q["sequence"] > intent["entry_sequence"]
        and at(q["available_at_utc"]) <= at(cutoff)
        and at(q["occurred_at_utc"]) >= deadline
        and q["quotation_eligible"]
        and (
            (same and intent["can_fill_trigger"] and intent["latency_ms"] == 0)
            or (
                not same
                and at(q["available_at_utc"]) > d
                and (trigger is None or q["sequence"] > trigger["quote"]["sequence"])
            )
        )
    )


@financial_context
def intent_fill(intent, quote, *, tape, policy, costs, as_of):
    """Internal projection: caller must authenticate the frozen intent via its V2 ledger."""
    require(
        type(intent) is dict
        and intent.get("model_version") == "IAT_PROTECTION_EXIT_INTENT_V1"
        and intent.get("direction") in ("BULLISH", "BEARISH")
        and intent.get("sha256")
        == digest({k: v for k, v in intent.items() if k != "sha256"}),
        "PROTECTION_INTENT_INVALID",
    )
    require(
        type(tape) is SyntheticQuoteTape and type(costs) is SyntheticCosts,
        "TYPED_FILL_SOURCES_REQUIRED",
    )
    q = tape.authenticate(quote, as_of=as_of, policy=policy)
    if not _eligible(quote, intent, as_of):
        return None
    eligible = [r for r in tape.rows() if _eligible(r, intent, as_of)]
    require(eligible and eligible[0] == quote, "PROTECTION_NOT_FIRST_CAUSAL_QUOTE")
    c = costs.validate()
    long = intent["direction"] == "BULLISH"
    side = "BID" if long else "ASK"
    price = (
        dec(q[side.lower()], positive=True)
        + (-1 if long else 1) * c["slippage_price_per_fill"]
    )
    require(price > 0, "PROTECTION_FILL_PRICE_INVALID")
    return report(
        "IAT_PROTECTION_FILL_V1",
        direction=intent["direction"],
        phase="EXIT",
        side=side,
        price=text_number(price),
        quote_sha256=quote["sha256"],
        occurred_at_utc=q["occurred_at_utc"],
        available_at_utc=q["available_at_utc"],
        filled_at_utc=q["available_at_utc"],
        decision_at_utc=intent["decision_available_at_utc"],
        cutoff_utc=at(as_of).isoformat(),
        intent_sha256=intent["sha256"],
        roles=intent["roles"],
        trigger_quote_sha256=(
            intent["trigger_quote"]["sha256"] if intent["trigger_quote"] else None
        ),
        fill_time_basis="DECLARED_SYNTHETIC_RECEIPT_TIME",
        cost_policy=canonical(costs),
        fill_policy=canonical(policy),
        modeled_exit_latency_ms=intent["latency_ms"],
        trigger_quote_can_fill=intent["can_fill_trigger"],
        spread_already_in_side_prices=True,
        limitations=[
            "NO_GUARANTEED_STOP_OR_BROKER_LIQUIDITY",
            "NOT_EXNESS_SPECIFICATIONS",
        ],
    )


@financial_context
def stop_gap_arithmetic(
    *, entry, stop, exit_price, volume, contract_size, direction, additional_costs
):
    require(direction in ("BULLISH", "BEARISH"), "DIRECTION_INVALID")
    e, s, x, v, c = (
        dec(z, positive=True) for z in (entry, stop, exit_price, volume, contract_size)
    )
    sign = 1 if direction == "BULLISH" else -1
    require((e - s) * sign > 0, "STOP_GEOMETRY_INVALID")
    risk = (e - s) * sign * v * c
    loss = (e - x) * sign * v * c
    costs = None if additional_costs is None else dec(additional_costs)
    return report(
        "IAT_STOP_GAP_ARITHMETIC_V1",
        authentication="NOT_ESTABLISHED_BY_ARITHMETIC",
        estimated_price_risk=text_number(risk),
        gross_hypothetical_loss=text_number(loss),
        additional_costs=text_number(costs),
        net_hypothetical_loss=text_number(loss + costs) if costs is not None else None,
        gap_through_component=text_number(max(0, (s - x) * sign) * v * c),
        scope="EXPLICITLY_INVENTED_ARITHMETIC_NOT_MARKET_VALIDATION",
    )
