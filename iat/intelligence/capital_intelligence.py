"""E4 capital arithmetic and authenticated synthetic affordability; never sizing orders."""

from iat.paper_source_scope import current_source
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, localcontext
from iat.intelligence.paper_contracts import (
    PaperError,
    require,
    at,
    dec,
    canonical,
    report,
    BrokerSpecification,
    SyntheticCosts,
    FillPolicy,
    SyntheticQuoteTape,
    quote_fill,
    financial_context,
)
from iat.intelligence.risk_intelligence import (
    ARITHMETIC,
    text_number,
    validate_risk_report,
    number,
)
from iat.intelligence.strategy_replay import digest


@dataclass(frozen=True)
class CapitalPolicy:
    risk_fraction: str
    aggregate_risk_fraction: str
    daily_loss_fraction: str
    drawdown_fraction: str
    free_margin_reserve: str
    max_positions: int
    max_consecutive_losses: int
    max_cost_fraction_of_budget: str
    reserve_holding_seconds: int
    adverse_gap_price: str
    min_reference_rr: str | None
    reference_mapping: str
    version: int = 1

    def validate(self):
        require(
            type(self.version) is int and self.version == 1,
            "CAPITAL_POLICY_VERSION_INVALID",
        )
        require(
            self.reference_mapping
            == "DECLARED_SYNTHETIC_ABSTRACT_REFERENCE_TO_QUOTE_UNITS",
            "STRUCTURAL_QUOTE_BASIS_MAPPING_REQUIRED",
        )
        v = {
            k: dec(getattr(self, k), positive=True)
            for k in (
                "risk_fraction",
                "aggregate_risk_fraction",
                "daily_loss_fraction",
                "drawdown_fraction",
                "max_cost_fraction_of_budget",
            )
        }
        require(all(x <= 1 for x in v.values()), "CAPITAL_POLICY_INVALID")
        require(
            v["aggregate_risk_fraction"] >= v["risk_fraction"], "CAPITAL_POLICY_INVALID"
        )
        v.update(
            {
                k: dec(getattr(self, k))
                for k in ("free_margin_reserve", "adverse_gap_price")
            }
        )
        require(
            type(self.max_positions) is int and self.max_positions == 1,
            "MULTIPLE_POSITIONS_NOT_REVIEWED",
        )
        require(
            type(self.max_consecutive_losses) is int
            and 0 < self.max_consecutive_losses <= 10000,
            "CAPITAL_POLICY_INVALID",
        )
        require(
            type(self.reserve_holding_seconds) is int
            and 0 <= self.reserve_holding_seconds <= 604800,
            "CAPITAL_POLICY_INVALID",
        )
        if self.min_reference_rr is not None:
            v["min_reference_rr"] = dec(self.min_reference_rr, positive=True)
        return v


@financial_context
def capital_arithmetic(
    *,
    balance,
    equity,
    fill_price,
    stop_reference,
    direction,
    specification,
    costs,
    policy
):
    """Isolated toy arithmetic; establishes no source, account or setup eligibility."""
    require(
        type(policy) is CapitalPolicy
        and type(costs) is SyntheticCosts
        and type(specification) is BrokerSpecification,
        "TYPED_FINANCIAL_POLICIES_REQUIRED",
    )
    p, c = policy.validate(), costs.validate()
    # The authenticated assessment separately checks the dated specification against its quote.
    with localcontext(ARITHMETIC):
        capital = min(dec(balance), dec(equity))
        require(capital > 0, "NO_AVAILABLE_CAPITAL")
        fill, stop = dec(fill_price, positive=True), dec(stop_reference, positive=True)
        require(direction in ("BULLISH", "BEARISH"), "CAPITAL_DIRECTION_INVALID")
        distance = fill - stop if direction == "BULLISH" else stop - fill
        require(distance > 0, "STRUCTURAL_STOP_WRONG_SIDE")
        cs = dec(specification.contract_size, positive=True)
        require(distance >= dec(specification.min_stop_distance), "MIN_STOP_DISTANCE")
        budget = capital * p["risk_fraction"]
        fees = 2 * (c["commission_per_lot_side"] + c["other_per_lot_side"])
        financing = (
            c["financing_per_lot_day"]
            * Decimal(policy.reserve_holding_seconds)
            / Decimal(86400)
        )
        # Entry slippage already in fill. Reserve exit slippage once, plus declared adverse gap.
        exit_adverse = c["slippage_price_per_fill"] * cs
        cost_per_lot = fees + financing + exit_adverse
        loss_per_lot = (distance + p["adverse_gap_price"]) * cs + cost_per_lot
        theoretical = budget / loss_per_lot
        step = dec(specification.volume_step, positive=True)
        lot = min(
            (theoretical / step).to_integral_value(rounding=ROUND_FLOOR) * step,
            dec(specification.max_lot, positive=True),
        )
        minlot = dec(specification.min_lot, positive=True)
        margin = lot * cs * fill / dec(specification.leverage, positive=True)
        est_cost = lot * cost_per_lot
        reasons = []
        if lot < minlot:
            reasons.append("MINIMUM_LOT_EXCEEDS_RISK_BUDGET")
        if est_cost > budget * p["max_cost_fraction_of_budget"]:
            reasons.append("TRANSACTION_COST_LIMIT")
        return dict(
            authentication="NOT_ESTABLISHED_BY_ARITHMETIC",
            available_capital=text_number(capital),
            risk_budget=text_number(budget),
            structural_stop_reference=text_number(stop),
            structural_stop_distance=text_number(distance),
            adverse_gap_price=policy.adverse_gap_price,
            adverse_price_exposure=text_number(
                lot * (distance + p["adverse_gap_price"]) * cs
            ),
            estimated_transaction_costs=text_number(est_cost),
            theoretical_position_size=text_number(theoretical),
            step_adjusted_position_size=text_number(lot),
            minimum_lot_affordable=lot >= minlot,
            estimated_loss=text_number(lot * loss_per_lot),
            estimated_required_margin=text_number(margin),
            reason_codes=reasons,
            currency="USD",
            size_unit="SYNTHETIC_LOTS_NOT_ORDER_VOLUME",
            spread_accounting="INCLUDED_IN_SIDE_SPECIFIC_FILL_NO_SECOND_DEDUCTION",
        )


@financial_context
def assess_capital(
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
    as_of
):
    """Reauthenticate every source and current account; a caller's label cannot qualify it."""
    from iat.intelligence.paper_account import PaperAccount
    from iat.intelligence.protected_paper import ProtectedPaperAccount

    try:
        require(
            type(account) in (PaperAccount, ProtectedPaperAccount),
            "PAPER_ACCOUNT_PRODUCER_REQUIRED",
        )
        require(
            type(specification) is BrokerSpecification
            and type(policy) is CapitalPolicy
            and type(costs) is SyntheticCosts
            and type(tape) is SyntheticQuoteTape
            and type(fill_policy) is FillPolicy,
            "TYPED_FINANCIAL_POLICIES_REQUIRED",
        )
        if current_source() is not None:
            require(
                canonical(policy) == current_source().policies["capital"]
                and canonical(fill_policy) == current_source().policies["fill"],
                "E5_FROZEN_CAPITAL_OR_FILL_POLICY_MISMATCH",
            )
        validate_risk_report(risk, **risk_inputs)
        require(risk["source_eligibility"] == "VALID", "RISK_SOURCE_BLOCKED")
        require(
            risk["hypothesis_lifecycle"]["state"] == "RESEARCH_QUALIFIED",
            "HYPOTHESIS_NOT_CURRENTLY_QUALIFIED",
        )
        require(
            risk["ambiguity"]["status"] != "UNRESOLVED_EVENT_ORDER",
            "EXIT_ORDER_UNRESOLVED",
        )
        require("ABSTAINED" not in risk["states"], "RISK_EVIDENCE_INCOMPLETE")
        require(
            not risk_inputs["current_e2"]["observations"],
            "EXIT_OBSERVATIONS_ALREADY_AVAILABLE",
        )
        require(tape.symbol == risk["symbol"], "QUOTE_SYMBOL_MISMATCH")
        at_now, decision = at(as_of), at(risk["evaluation_at_utc"])
        require(
            at_now - decision
            <= timedelta(milliseconds=fill_policy.max_analysis_age_ms),
            "ANALYSIS_STALE",
        )
        state = account.snapshot()
        require(
            at(state["as_of_utc"]) <= decision <= at_now, "ACCOUNT_OR_DECISION_FUTURE"
        )
        require(state["account_lifecycle"] == "ACTIVE", "ACCOUNT_NOT_ACTIVE")
        require(
            not state.get("new_positions_restricted", False),
            "MARGIN_WARNING_NEW_POSITIONS_RESTRICTED",
        )
        require(state["account_currency"] == "USD", "ACCOUNT_CURRENCY_UNSUPPORTED")
        require(not state["open_positions"], "MAX_CONCURRENT_POSITIONS")
        action_at = (
            decision
            if current_source() is None
            else current_source().action_time(decision)
        )
        q = tape.authenticate(
            quote, as_of=at_now, policy=fill_policy, decision_at=action_at, opening=True
        )
        require(
            at(q["available_at_utc"]) - action_at
            <= timedelta(milliseconds=fill_policy.max_gap_ms),
            "ENTRY_QUOTE_COVERAGE_GAP",
        )
        require(
            at(specification.effective_at_utc) <= decision,
            "SPEC_NOT_EFFECTIVE_AT_DECISION",
        )
        spec_values = specification.validate(q, at_now)
        p, c = policy.validate(), costs.validate()
        require(
            c["slippage_price_per_fill"] % spec_values["tick_size"] == 0,
            "SLIPPAGE_OFF_TICK_GRID",
        )
        fill = quote_fill(
            quote,
            tape=tape,
            direction=risk["research_direction"],
            phase="ENTRY",
            decision_at=decision,
            as_of=at_now,
            policy=fill_policy,
            costs=costs,
        )
        result = capital_arithmetic(
            balance=state["balance"],
            equity=state["equity"],
            fill_price=fill["price"],
            stop_reference=risk["reference_geometry"]["invalidation_threshold"],
            direction=risk["research_direction"],
            specification=specification,
            costs=costs,
            policy=policy,
        )
        with localcontext(ARITHMETIC):
            reasons = list(result["reason_codes"])
            target_distance = None
            if risk["frozen_target"] is not None:
                target = risk["frozen_target"]
                near = number(
                    target["lower"]
                    if risk["research_direction"] == "BULLISH"
                    else target["upper"]
                )
                target_distance = (
                    near - dec(fill["price"])
                    if risk["research_direction"] == "BULLISH"
                    else dec(fill["price"]) - near
                )
                if target_distance <= 0:
                    reasons.append("FROZEN_TARGET_NOT_FAVORABLE_TO_ENTRY_FILL")
            capital = dec(result["available_capital"])
            current_day = at_now.date().isoformat()
            day_loss = dec(state["daily_losses"].get(current_day, "0"))
            if day_loss >= dec(state["starting_balance"]) * p["daily_loss_fraction"]:
                reasons.append("DAILY_LOSS_LIMIT")
            if dec(state["max_drawdown_fraction"]) >= p["drawdown_fraction"]:
                reasons.append("DRAWDOWN_LIMIT")
            if state["consecutive_losses"] >= policy.max_consecutive_losses:
                reasons.append("CONSECUTIVE_LOSS_LIMIT")
            if (
                dec(result["estimated_loss"]) + dec(state["aggregate_open_risk"])
                > capital * p["aggregate_risk_fraction"]
            ):
                reasons.append("AGGREGATE_RISK_LIMIT")
            entry_fee = dec(result["step_adjusted_position_size"]) * (
                c["commission_per_lot_side"] + c["other_per_lot_side"]
            )
            volume = dec(result["step_adjusted_position_size"])
            sign = 1 if risk["research_direction"] == "BULLISH" else -1
            exit_price = (
                dec(q["bid"] if sign == 1 else q["ask"])
                - sign * c["slippage_price_per_fill"]
            )
            require(exit_price > 0, "EXIT_MARK_PRICE_INVALID")
            immediate_gross = (
                (exit_price - dec(fill["price"]))
                * sign
                * spec_values["contract_size"]
                * volume
            )
            projected = (
                dec(state["free_margin"])
                - dec(result["estimated_required_margin"])
                - 2 * entry_fee
                + immediate_gross
            )
            if dec(result["estimated_loss"]) > dec(result["risk_budget"]):
                reasons.append("RISK_BUDGET_EXCEEDED")
            if (
                dec(result["estimated_required_margin"]) > 0
                and (dec(state["equity"]) - 2 * entry_fee + immediate_gross)
                / dec(result["estimated_required_margin"])
                <= spec_values["margin_call_equity_ratio"]
            ):
                reasons.append("PROJECTED_MARGIN_CALL")
            if projected < p["free_margin_reserve"]:
                reasons.append("INSUFFICIENT_FREE_MARGIN")
            if policy.min_reference_rr is not None:
                rr = risk["reference_geometry"]["reward_to_risk"]
                if rr is None or number(rr) < p["min_reference_rr"]:
                    reasons.append("REFERENCE_RR_POLICY_NOT_MET")
            result.update(
                projected_free_margin=text_number(projected),
                hypothetical_fill_to_target_reference_distance=text_number(
                    target_distance
                ),
                reason_codes=sorted(set(reasons)),
                authentication="SOURCE_AND_ACCOUNT_BOUND_SYNTHETIC_ONLY",
            )
        # E3 remains immutable; executable sizing fields there stay null.
        return report(
            "IAT_CAPITAL_INTELLIGENCE_V1",
            status=(
                "FINANCIALLY_UNSUITABLE"
                if reasons
                else "HYPOTHETICAL_POSITION_ELIGIBLE"
            ),
            capital_suitability=(
                "REJECTED"
                if reasons
                else "SUITABLE_UNDER_DECLARED_SYNTHETIC_ASSUMPTIONS"
            ),
            assessment=dict(
                result,
                structural_source_price_basis=risk["reference_price_basis"],
                reference_mapping=policy.reference_mapping,
            ),
            hypothetical_entry_fill=fill,
            setup_id=risk["original_setup"]["setup_id"],
            direction=risk["research_direction"],
            as_of_utc=at_now.isoformat(),
            bindings=dict(
                risk=risk["sha256"],
                account=state["sha256"],
                quote=quote["sha256"],
                specification=digest(canonical(specification)),
                costs=digest(canonical(costs)),
                policy=digest(canonical(policy)),
                fill_policy=digest(canonical(fill_policy)),
            ),
            evidence_strength=dict(
                status="DESCRIPTIVE_NOT_CALIBRATED",
                components=evidence_components(risk, risk_inputs),
                supporting_evidence=risk["supporting_evidence"],
                contradictory_evidence=risk["contradictory_evidence"],
                unavailable=[
                    "CALIBRATED_PROBABILITY",
                    "INDEPENDENT_HISTORICAL_QUALIFICATION",
                ],
                market_evidence_is_not_capital_suitability=True,
            ),
            reason_codes=result["reason_codes"],
            limitations=[
                "LOSS_CAN_EXCEED_ESTIMATE",
                "SYNTHETIC_SPECIFICATIONS_AND_COSTS_ONLY",
                "NO_TRADING_AUTHORIZATION",
            ],
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        ArithmeticError,
    ) as exc:
        return report(
            "IAT_CAPITAL_INTELLIGENCE_V1",
            status="CAPITAL_ASSESSMENT_UNAVAILABLE",
            capital_suitability="UNAVAILABLE",
            assessment=None,
            hypothetical_entry_fill=None,
            reason_codes=[
                str(exc) if isinstance(exc, PaperError) else "CAPITAL_INPUT_UNAVAILABLE"
            ],
        )


def evidence_components(risk, inputs):
    """Reuse authenticated facts when supplied; no new scores or probabilities."""
    context = inputs.get("context")
    out = {
        k: dict(status="UNAVAILABLE", value=None)
        for k in (
            "market_structure",
            "m1_m5_alignment",
            "momentum",
            "volatility",
            "liquidity_context",
        )
    }
    if context is not None:
        out["market_structure"] = dict(
            status="UPSTREAM_AUTHENTICATED", value=context.context
        )
        out["m1_m5_alignment"] = dict(
            status="UPSTREAM_AUTHENTICATED",
            value=context.context.get("phase7_alignment"),
        )
        for key, category in [
            ("momentum", "MOMENTUM"),
            ("volatility", "VOLATILITY"),
            ("liquidity_context", "LIQUIDITY"),
        ]:
            items = [e.id for e in context.evidence if e.category == category]
            out[key] = dict(
                status="UPSTREAM_AUTHENTICATED" if items else "UNAVAILABLE",
                evidence_ids=sorted(set(items)),
            )
    out.update(
        entry_confirmation=dict(
            status="UPSTREAM_AUTHENTICATED", value=risk["confirmation_reference"]
        ),
        support_resistance=dict(
            status="UPSTREAM_AUTHENTICATED", value=risk["frozen_invalidation"]
        ),
        reference_risk_reward=dict(
            status="REFERENCE_ONLY_NOT_FILL_BASED", value=risk["reference_geometry"]
        ),
        data_integrity=dict(
            status=risk["source_eligibility"], value=risk["source_restrictions"]
        ),
        contradictory_observations=dict(
            status="UPSTREAM_AUTHENTICATED", evidence_ids=risk["contradictory_evidence"]
        ),
    )
    return out


def validate_capital_report(value, **inputs):
    require(value == assess_capital(**inputs), "CAPITAL_SOURCE_BINDING_INVALID")
    return True
