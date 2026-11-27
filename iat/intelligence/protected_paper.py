"""Version 2 synthetic protected ledger. No live data, broker or order dependencies."""

from copy import deepcopy
from datetime import timedelta
import json
from iat.intelligence.paper_account import (
    PaperAccount,
    PaperExitPolicy,
    fixed_decimal,
    dec_signed,
)
from iat.intelligence.paper_contracts import (
    PaperError,
    require,
    at,
    dec,
    report,
    canonical,
    SyntheticQuoteTape,
    BrokerSpecification,
    SyntheticCosts,
    FillPolicy,
    reports_equal,
)
from iat.intelligence.protection_contracts import (
    ProtectiveStopPolicy,
    LiquidationPolicy,
    assess_protection_plan,
    margin_assessment,
    exit_intent,
    intent_fill,
)
from iat.intelligence.risk_intelligence import validate_risk_report, text_number
from iat.intelligence.strategy_replay import digest


def version2(model, **fields):
    value = report(model)
    value.pop("sha256")
    for key in (
        "provenance",
        "research_only",
        "mode",
        "signal",
        "execution_allowed",
        "qualification",
        "exness",
        "historical_validation",
        "historical_comparisons",
    ):
        if key in fields:
            require(
                type(fields[key]) is type(value[key]) and fields[key] == value[key],
                "PROTECTION_REPORT_SAFETY_INVALID",
            )
    value.update(deepcopy(fields))
    value.update(model_version=model, report_version=2)
    return dict(value, sha256=digest(value))


class ProtectedPaperAccount(PaperAccount):
    """One quote per causal receipt; skipping known observations fails closed.

    This new producer and journal are distinct from PaperAccount v1. Source data,
    prices and specifications are independently invented synthetic fixtures only.
    """

    def __init__(
        self,
        *,
        started_at,
        starting_balance="50",
        account_id="SYNTHETIC_PROTECTED_USD50",
        max_events=1000,
        max_report_bytes=2000000
    ):
        self._proposal = None
        super().__init__(
            started_at=started_at,
            starting_balance=starting_balance,
            account_id=account_id,
            max_events=max_events,
            max_report_bytes=max_report_bytes,
        )

    def _snapshot(self, state, events):
        value = super()._snapshot(state, events)
        for key in ("sha256", "report_version", "model_version"):
            value.pop(key)
        return version2(
            "IAT_PROTECTED_PAPER_ACCOUNT_V2",
            **value,
            protection_contract_version=1,
            new_positions_restricted=state.get("protection_restricted", False),
            account_exhaustion_observed=state.get("protection_exhausted", False),
            margin=deepcopy(state.get("protection_margin"))
        )

    def _journal(self, state, events):
        return version2(
            "IAT_PROTECTED_PAPER_JOURNAL_V2",
            account=self._snapshot(state, events),
            events=deepcopy(events),
            metrics=self._metrics(state, events),
            result_scope="SYNTHETIC_PROTECTION_ACCOUNTING_NOT_STRATEGY_PERFORMANCE",
        )

    def _commit(self, state, events):
        require(
            len(self._events) + len(events) <= self.max_events, "ACCOUNT_RESOURCE_LIMIT"
        )
        history = deepcopy(self._events)
        for raw in events:
            e = deepcopy(raw)
            frame = e.pop("_frame", None)
            time = state["as_of_utc"] if frame is None else frame["at_utc"]
            require(
                not history or at(time) >= at(history[-1]["at_utc"]),
                "PROTECTION_EVENT_CLOCK_BACKWARD",
            )
            history.append(
                dict(
                    sequence=len(history),
                    event_version=2,
                    at_utc=time,
                    equity=state["equity"] if frame is None else frame["equity"],
                    balance=state["balance"] if frame is None else frame["balance"],
                    previous_event_sha256=digest(history[-1]) if history else None,
                    **e
                )
            )
        result = self._journal(state, history)
        require(
            len(
                json.dumps(
                    result, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            )
            <= self.max_report_bytes,
            "ACCOUNT_RESOURCE_LIMIT",
        )
        self._state, self._events = deepcopy(state), history
        return self.snapshot()

    def _prepare_position(self, position, assessment):
        require(
            self._proposal is not None
            and self._proposal["capital"]["sha256"] == assessment["sha256"],
            "STOP_PLAN_CAPITAL_BINDING_MISMATCH",
        )
        stop = deepcopy(self._proposal["stop"])
        require(
            stop["threshold"] == position["structural_threshold"],
            "STOP_CANNOT_MOVE_STRUCTURAL_REFERENCE",
        )
        require(
            at(stop["establishment_at_utc"])
            == at(position["entry_fill"]["filled_at_utc"]),
            "STOP_ESTABLISHMENT_MUST_PRECEDE_OPEN_IN_RECEIPT_TRANSACTION",
        )
        position["entry_risk_budget"] = assessment["assessment"]["risk_budget"]
        position.update(
            proposed_protective_stop=stop["threshold"],
            protection=dict(
                model_version="IAT_POSITION_PROTECTION_V1",
                plan_sha256=self._proposal["sha256"],
                plan_bindings=deepcopy(self._proposal["bindings"]),
                stop=stop,
                liquidation_policy=deepcopy(self._proposal["liquidation_policy"]),
                entry_sequence=self._proposal["entry_sequence"],
                last_sequence=self._proposal["entry_sequence"],
                stop_status="ESTABLISHED",
                liquidation_status="NOT_TRIGGERED",
                pending=None,
                stop_triggered=False,
                stop_out_detected=False,
                margin_warning=False,
                seen_e2_events=[],
                closed_roles=[],
                margin=None,
            ),
        )
        return position

    def _entry_events(self, events, position):
        return [
            dict(
                kind="PROTECTIVE_STOP_ESTABLISHED",
                position_id=position["position_id"],
                plan_sha256=position["protection"]["plan_sha256"],
                established_at_utc=position["protection"]["stop"][
                    "establishment_at_utc"
                ],
                logical_order="BEFORE_HYPOTHETICALLY_OPEN_AT_SAME_RECEIPT",
                threshold=position["proposed_protective_stop"],
            )
        ] + events

    @fixed_decimal
    def open(self, risk, *, stop_policy, liquidation_policy, exit_policy, **inputs):
        require(self._proposal is None, "REENTRANT_PROTECTION_TRANSACTION")
        try:
            plan = assess_protection_plan(
                risk,
                risk_inputs=inputs["risk_inputs"],
                account=self,
                tape=inputs["tape"],
                quote=inputs["quote"],
                specification=inputs["specification"],
                costs=inputs["costs"],
                policy=inputs["policy"],
                fill_policy=inputs["fill_policy"],
                stop_policy=stop_policy,
                liquidation_policy=liquidation_policy,
                as_of=inputs["as_of"],
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            ArithmeticError,
        ) as exc:
            return version2(
                "IAT_PROTECTED_ENTRY_V2",
                status="BLOCKED",
                position=None,
                reason_codes=[
                    (
                        str(exc)
                        if isinstance(exc, PaperError)
                        else "PROTECTION_INPUT_UNAVAILABLE"
                    )
                ],
            )
        if plan["status"] == "BLOCKED":
            return version2(
                "IAT_PROTECTED_ENTRY_V2",
                status="BLOCKED",
                position=None,
                plan=plan,
                reason_codes=plan["reason_codes"],
            )
        self._proposal = dict(plan, entry_sequence=inputs["quote"]["quote"]["sequence"])
        try:
            result = super().open(risk, exit_policy=exit_policy, **inputs)
        finally:
            self._proposal = None
        fields = {
            k: v
            for k, v in result.items()
            if k not in ("sha256", "report_version", "model_version")
        }
        return version2("IAT_PROTECTED_ENTRY_V2", **fields)

    def _event(self, events, state, kind, **fields):
        events.append(
            dict(
                kind=kind,
                _frame=dict(
                    at_utc=state["as_of_utc"],
                    equity=state["equity"],
                    balance=state["balance"],
                ),
                **fields
            )
        )

    def _unresolved(self, state, position, code, events):
        position.update(
            state="UNRESOLVED", reason_codes=[code], unrealized_hypothetical_pnl=None
        )
        p = position["protection"]
        p["stop_status"] = "UNRESOLVED"
        p["liquidation_status"] = "UNRESOLVED"
        state.update(unrealized_hypothetical_pnl=None, protection_restricted=True)
        self._equity(state)
        self._event(
            events,
            state,
            "UNRESOLVED_PROTECTIVE_EXIT",
            position_id=position["position_id"],
            reason_codes=[code],
            pending_intent=deepcopy(p["pending"]),
            competing_intents=deepcopy(p.get("competing_intents", [])),
        )
        self._commit(state, events)
        return self._observation(position)

    def _observation(self, position):
        return version2(
            "IAT_PROTECTED_OBSERVATION_V2",
            status=position["state"],
            position=deepcopy(position),
            reason_codes=position["reason_codes"],
        )

    @fixed_decimal
    def observe(self, risk, *, risk_inputs, tape, quote, as_of):
        require(
            len(self._state["open_positions"]) == 1, "NO_OPEN_HYPOTHETICAL_POSITION"
        )
        require(type(tape) is SyntheticQuoteTape, "QUOTE_PRODUCER_REQUIRED")
        require(
            type(quote) is dict and type(quote.get("quote")) is dict,
            "QUOTE_SOURCE_MISMATCH",
        )
        require(
            at(as_of) == at(quote["quote"]["available_at_utc"]),
            "PROTECTION_REPLAY_REQUIRES_RECEIPT_CUTOFF",
        )
        state = self._advance(as_of)
        position = state["open_positions"][0]
        p = position["protection"]
        require(
            position["state"] not in ("UNRESOLVED", "BLOCKED"),
            "POSITION_REQUIRES_INDEPENDENT_REVIEW",
        )
        validate_risk_report(risk, **risk_inputs)
        require(
            risk["source_eligibility"] == "VALID"
            and position["original_bindings"]
            == dict(
                original_e1=risk["bindings"]["original_e1"],
                original_e2=risk["bindings"]["original_e2"],
            ),
            "POSITION_SOURCE_MISMATCH",
        )
        require(at(risk["evaluation_at_utc"]) <= at(as_of), "E2_NOT_AVAILABLE")
        require(
            tape.symbol == risk["symbol"]
            and quote["source"] == position["quote_source"],
            "QUOTE_FEED_OR_DATASET_MISMATCH",
        )
        fp = FillPolicy(**position["fill_policy"])
        costs = SyntheticCosts(**position["costs"])
        events = []
        # Authenticate the committed prefix before any unresolved-state mutation.
        self._check_quote_history(position, tape)
        try:
            q = tape.authenticate(quote, as_of=as_of, policy=fp)
        except PaperError as exc:
            if str(exc) == "QUOTATIONS_CLOSED":
                return self._unresolved(
                    state, position, "SESSION_QUOTATIONS_UNAVAILABLE", events
                )
            raise
        BrokerSpecification(**position["specification"]).validate(q, as_of)
        prefix_signature = self._quote_prefix_signature(tape, q["sequence"])
        if quote["sha256"] == position["last_quote_sha256"]:
            require(
                at(as_of) == at(position["last_observation_utc"]),
                "UNCHANGED_QUOTE_NOT_NEW_OBSERVATION",
            )
            return version2(
                "IAT_PROTECTED_OBSERVATION_V2",
                status="DUPLICATE",
                position=deepcopy(position),
                reason_codes=[],
            )
        if q["sequence"] != p["last_sequence"] + 1:
            return self._unresolved(
                state, position, "KNOWN_QUOTE_SEQUENCE_SKIPPED", events
            )
        if at(q["occurred_at_utc"]) < at(position["entry_fill"]["filled_at_utc"]):
            return self._unresolved(
                state, position, "QUOTE_OCCURRENCE_PRECEDES_POSITION_FILL", events
            )
        if at(as_of) - at(position["last_observation_utc"]) > timedelta(
            milliseconds=fp.max_gap_ms
        ):
            return self._unresolved(state, position, "QUOTE_COVERAGE_GAP", events)
        if at(as_of) - at(risk["evaluation_at_utc"]) > timedelta(
            milliseconds=fp.max_analysis_age_ms
        ):
            return self._unresolved(
                state, position, "STRUCTURAL_ANALYSIS_STALE", events
            )
        if (
            risk["ambiguity"]["status"] == "UNRESOLVED_EVENT_ORDER"
            or "ABSTAINED" in risk["states"]
        ):
            return self._unresolved(
                state, position, "E2_ORDER_OR_DATA_QUALITY_UNRESOLVED", events
            )
        if risk["hypothesis_lifecycle"]["state"] == "EXPIRED":
            return self._unresolved(
                state, position, "EXPIRED_HYPOTHESIS_NO_EXIT_MODEL", events
            )
        position["last_quote_sha256"] = quote["sha256"]
        p["last_sequence"] = q["sequence"]
        self._mark(state, position, q, as_of)
        self._equity(state)
        m = margin_assessment(
            equity=state["equity"],
            used_margin=state["used_margin"],
            margin_call_ratio=position["specification"]["margin_call_equity_ratio"],
            stop_out_ratio=position["specification"]["stop_out_equity_ratio"],
        )
        state["protection_margin"] = m
        state["protection_restricted"] = m["new_positions_restricted"]
        p["margin"] = m
        if m["warning"] and not p["margin_warning"]:
            self._event(
                events,
                state,
                "MARGIN_WARNING",
                position_id=position["position_id"],
                margin=m,
            )
        if not m["warning"] and p["margin_warning"]:
            self._event(
                events,
                state,
                "MARGIN_WARNING_CLEARED",
                position_id=position["position_id"],
                margin=m,
            )
        p["margin_warning"] = m["warning"]
        if dec_signed(state["equity"]) <= 0 and not state.get(
            "protection_exhausted", False
        ):
            state["protection_exhausted"] = True
            self._event(
                events,
                state,
                "ACCOUNT_EXHAUSTED",
                position_id=position["position_id"],
                basis="OBSERVED_NET_LIQUIDATION_EQUITY",
            )
        signals = []
        long = position["direction"] == "BULLISH"
        stop = p["stop"]
        threshold = dec(stop["threshold"])
        crossed = dec(q["bid"]) <= threshold if long else dec(q["ask"]) >= threshold
        if crossed and not p["stop_triggered"]:
            p["stop_triggered"] = True
            p["stop_status"] = "ACTIVATED"
            self._event(
                events,
                state,
                "PROTECTIVE_STOP_ACTIVATED",
                position_id=position["position_id"],
                trigger_quote_sha256=quote["sha256"],
                trigger_occurred_at_utc=q["occurred_at_utc"],
                trigger_available_at_utc=q["available_at_utc"],
                threshold=stop["threshold"],
            )
            sp = stop["policy"]
            signals.append(
                exit_intent(
                    roles=["PROTECTIVE_STOP"],
                    direction=position["direction"],
                    available_at=as_of,
                    occurred_at=q["occurred_at_utc"],
                    occurred_interval=None,
                    trigger_quote=quote,
                    quote_source=position["quote_source"],
                    entry_sequence=p["entry_sequence"],
                    latency_ms=sp["latency_ms"],
                    can_fill_trigger=sp["trigger_quote_can_fill"],
                    evidence=dict(
                        plan_sha256=p["plan_sha256"], threshold=stop["threshold"]
                    ),
                )
            )
        if m["stop_out"] and not p["stop_out_detected"]:
            p["stop_out_detected"] = True
            p["liquidation_status"] = "STOP_OUT_DETECTED"
            self._event(
                events,
                state,
                "STOP_OUT_DETECTED",
                position_id=position["position_id"],
                margin=m,
                trigger_quote_sha256=quote["sha256"],
            )
            lp = p["liquidation_policy"]
            signals.append(
                exit_intent(
                    roles=["LIQUIDATION"],
                    direction=position["direction"],
                    available_at=as_of,
                    occurred_at=q["occurred_at_utc"],
                    occurred_interval=None,
                    trigger_quote=quote,
                    quote_source=position["quote_source"],
                    entry_sequence=p["entry_sequence"],
                    latency_ms=lp["latency_ms"],
                    can_fill_trigger=lp["trigger_quote_can_fill"],
                    evidence=dict(margin=m, policy_sha256=digest(lp)),
                )
            )
        enabled = {
            "STRUCTURAL_INVALIDATION_OBSERVED": position["exit_policy"][
                "structural_invalidation"
            ],
            "STRUCTURAL_TARGET_OBSERVED": position["exit_policy"]["structural_target"],
            "OPPOSING_STRUCTURE_OBSERVED": position["exit_policy"][
                "opposing_structure"
            ],
        }
        for e in risk_inputs["current_e2"]["observations"]:
            if e["id"] in p["seen_e2_events"]:
                continue
            p["seen_e2_events"].append(e["id"])
            if not enabled.get(e["kind"], False) or at(e["available_at_utc"]) <= at(
                position["entry_fill"]["filled_at_utc"]
            ):
                continue
            decision = max(at(e["available_at_utc"]), at(e["first_observed_at_utc"]))
            require(decision <= at(as_of), "FUTURE_E2_EXIT_EVIDENCE")
            signals.append(
                exit_intent(
                    roles=["E2_" + e["kind"]],
                    direction=position["direction"],
                    available_at=decision,
                    occurred_at=e["occurred_at_utc"],
                    occurred_interval=e["occurred_interval_utc"],
                    trigger_quote=None,
                    quote_source=position["quote_source"],
                    entry_sequence=p["entry_sequence"],
                    latency_ms=fp.latency_ms,
                    can_fill_trigger=False,
                    evidence=dict(
                        e2_sha256=risk_inputs["current_e2"]["sha256"], event=deepcopy(e)
                    ),
                )
            )
        pending = p["pending"]
        if pending is not None and signals:
            p["competing_intents"] = signals
            return self._unresolved(
                state, position, "COMPETING_EXIT_DURING_PENDING_FILL", events
            )
        if pending is None and len(signals) > 1:
            # Only stop + stop-out with identical declared fill functions are equivalent.
            equal = (
                len(signals) == 2
                and {tuple(x["roles"]) for x in signals}
                == {("PROTECTIVE_STOP",), ("LIQUIDATION",)}
                and all(
                    signals[0][k] == signals[1][k]
                    for k in (
                        "decision_available_at_utc",
                        "trigger_quote",
                        "latency_ms",
                        "can_fill_trigger",
                        "deadline_utc",
                    )
                )
            )
            if not equal:
                p["competing_intents"] = signals
                return self._unresolved(
                    state, position, "COMPETING_EXIT_POLICIES_UNRESOLVED", events
                )
            core = {k: v for k, v in signals[0].items() if k not in ("sha256", "roles")}
            core["roles"] = ["LIQUIDATION", "PROTECTIVE_STOP"]
            core["evidence"] = dict(
                coincident_intents=signals,
                proof="IDENTICAL_SIDE_PRICE_LATENCY_COST_FILL_FUNCTION",
            )
            pending = dict(core, sha256=digest(core))
            self._event(
                events,
                state,
                "COINCIDENT_IDENTICAL_EXIT_POLICIES",
                position_id=position["position_id"],
                intent_sha256=pending["sha256"],
            )
        elif pending is None and signals:
            pending = signals[0]
        if pending is not None:
            new_pending = p["pending"] is None
            p["pending"] = deepcopy(pending)
            if new_pending:
                kinds = []
                if "PROTECTIVE_STOP" in pending["roles"]:
                    kinds.append("PROTECTIVE_STOP_EXIT_PENDING")
                    p["stop_status"] = "EXIT_PENDING"
                if "LIQUIDATION" in pending["roles"]:
                    kinds.append("LIQUIDATION_PENDING")
                    p["liquidation_status"] = "LIQUIDATION_PENDING"
                if any(x.startswith("E2_") for x in pending["roles"]):
                    kinds.append("STRUCTURAL_EXIT_PENDING")
                for kind in kinds:
                    self._event(
                        events,
                        state,
                        kind,
                        position_id=position["position_id"],
                        intent=deepcopy(pending),
                    )
            fill = intent_fill(
                pending, quote, tape=tape, policy=fp, costs=costs, as_of=as_of
            )
            if fill is None:
                position["state"] = "EXIT_PENDING"
                state["protection_restricted"] = True
                if not new_pending:
                    self._event(
                        events,
                        state,
                        "PROTECTION_EXIT_WAITING",
                        position_id=position["position_id"],
                        quote_sha256=quote["sha256"],
                        intent_sha256=pending["sha256"],
                        deadline_utc=pending["deadline_utc"],
                    )
            else:
                p["closed_roles"] = pending["roles"]
                p["stop_status"] = (
                    "FILLED"
                    if "PROTECTIVE_STOP" in pending["roles"]
                    else p["stop_status"]
                )
                p["liquidation_status"] = (
                    "HYPOTHETICALLY_LIQUIDATED"
                    if "LIQUIDATION" in pending["roles"]
                    else p["liquidation_status"]
                )
                position["protective_stop_fill"] = (
                    fill if "PROTECTIVE_STOP" in pending["roles"] else None
                )
                self._settle(
                    state,
                    position,
                    fill,
                    quote,
                    dict(
                        kind=(
                            "COINCIDENT_PROTECTIVE_STOP_AND_LIQUIDATION"
                            if len(pending["roles"]) > 1
                            else pending["roles"][0]
                        ),
                        intent=deepcopy(pending),
                    ),
                )
                net = dec_signed(position["net_hypothetical_pnl"])
                loss = max(0, -net)
                position["realized_hypothetical_loss"] = text_number(loss)
                position["risk_budget_exceedance"] = text_number(
                    max(0, loss - dec(position["entry_risk_budget"]))
                )
                cs = dec(position["specification"]["contract_size"])
                vol = dec(position["volume"])
                position["gap_through_loss"] = text_number(
                    max(0, (threshold - dec(fill["price"])) * (1 if long else -1))
                    * cs
                    * vol
                )
                position["gap_measurement_basis"] = (
                    "STOP_TO_MODELED_FILL_INCLUDES_LATENCY_AND_DECLARED_SLIPPAGE"
                )
                state["closed_positions"][-1] = deepcopy(position)
                self._equity(state)
                state["protection_restricted"] = state["account_lifecycle"] != "ACTIVE"
                state["protection_margin"] = margin_assessment(
                    equity=state["equity"],
                    used_margin="0",
                    margin_call_ratio=position["specification"][
                        "margin_call_equity_ratio"
                    ],
                    stop_out_ratio=position["specification"]["stop_out_equity_ratio"],
                )
                for kind in (
                    (
                        ["PROTECTIVE_STOP_HYPOTHETICAL_FILL"]
                        if "PROTECTIVE_STOP" in pending["roles"]
                        else []
                    )
                    + (
                        ["HYPOTHETICAL_LIQUIDATION"]
                        if "LIQUIDATION" in pending["roles"]
                        else []
                    )
                    + ["HYPOTHETICALLY_CLOSED"]
                ):
                    self._event(
                        events,
                        state,
                        kind,
                        position_id=position["position_id"],
                        fill_sha256=fill["sha256"],
                        realized_hypothetical_loss=position[
                            "realized_hypothetical_loss"
                        ],
                        risk_budget_exceedance=position["risk_budget_exceedance"],
                    )
        else:
            position["state"] = "MONITORING"
            self._event(
                events,
                state,
                "PROTECTION_MONITORING",
                position_id=position["position_id"],
                quote_sha256=quote["sha256"],
            )
        self._commit(state, events)
        self._quote_history[position["position_id"]] = (q["sequence"], prefix_signature)
        return self._observation(position)

    def review_cutoff(self, as_of, *, end_of_input):
        require(
            type(end_of_input) is bool and at(as_of) >= at(self._state["as_of_utc"]),
            "REVIEW_CUTOFF_INVALID",
        )
        # Later source availability adds outcomes, never mutates this frozen prefix review.
        unresolved = [
            p["position_id"]
            for p in self._state["open_positions"]
            if p["state"] in ("EXIT_PENDING", "UNRESOLVED")
        ]
        return version2(
            "IAT_PROTECTION_CUTOFF_REVIEW_V2",
            observation_cutoff_utc=at(as_of).isoformat(),
            end_of_input=end_of_input,
            journal_sha256=self.journal()["sha256"],
            status="UNRESOLVED" if unresolved else "NO_UNRESOLVED_EXIT",
            unresolved_position_ids=unresolved,
            unresolved_exit_denominator=len(unresolved),
            resolved_exit_denominator=len(self._state["closed_positions"]),
            reason_codes=(
                ["INCOMPLETE_EXIT_HORIZON_OR_MISSING_OBSERVATIONS"]
                if unresolved
                else []
            ),
            current_equity_at_cutoff=(
                self._state["equity"]
                if at(as_of) == at(self._state["as_of_utc"])
                else None
            ),
            last_account_observation_utc=self._state["as_of_utc"],
        )

    def _metrics(self, state, events):
        result = super()._metrics(state, events)
        closed = state["closed_positions"]
        result.update(
            protective_stop_exit_count=sum(
                "PROTECTIVE_STOP" in p.get("protection", {}).get("closed_roles", [])
                for p in closed
            ),
            structural_exit_count=sum(
                any(
                    x.startswith("E2_")
                    for x in p.get("protection", {}).get("closed_roles", [])
                )
                for p in closed
            ),
            liquidation_count=sum(
                "LIQUIDATION" in p.get("protection", {}).get("closed_roles", [])
                for p in closed
            ),
            unresolved_exit_count=sum(
                p["state"] in ("UNRESOLVED", "EXIT_PENDING")
                for p in state["open_positions"]
            ),
            margin_warning_count=sum(e["kind"] == "MARGIN_WARNING" for e in events),
            account_exhaustion_count=sum(
                e["kind"] == "ACCOUNT_EXHAUSTED" for e in events
            ),
            exit_risk_observations=[
                dict(
                    position_id=p["position_id"],
                    estimated_risk_at_entry=p["estimated_risk"],
                    realized_hypothetical_loss=p.get("realized_hypothetical_loss"),
                    risk_budget_exceedance=p.get("risk_budget_exceedance"),
                    gap_through_loss=p.get("gap_through_loss"),
                )
                for p in closed
            ],
        )
        return result


def validate_protected_journal(value, *, source):
    require(
        type(source) is ProtectedPaperAccount and reports_equal(value, source.journal()),
        "PROTECTED_JOURNAL_SOURCE_MISMATCH",
    )
    return True


def replay_protected(*, account, entry, observations, cutoff):
    """Causal synthetic episode, supplied in receipt order; no dataset importer.

    A later input failure leaves the previously committed verified prefix. An old
    closed/unresolved episode never reopens. No future observation is inspected
    past the requested cutoff. Real dataset qualification remains a prerequisite
    for a future adapter, not established by this invented-source helper.
    """
    require(
        type(account) is ProtectedPaperAccount
        and account.snapshot()["event_count"] == 1,
        "REPLAY_REQUIRES_NEW_PROTECTED_ACCOUNT",
    )
    require(at(entry["as_of"]) <= at(cutoff), "REPLAY_BEFORE_ENTRY")
    opened = account.open(**entry)
    outputs = [opened]
    if opened["status"] == "HYPOTHETICALLY_OPEN":
        for observation in observations:
            if at(observation["as_of"]) > at(cutoff):
                break
            result = account.observe(**observation)
            outputs.append(result)
            if result["status"] in ("HYPOTHETICALLY_CLOSED", "UNRESOLVED", "BLOCKED"):
                break
    return version2(
        "IAT_PROTECTION_REPLAY_V2",
        observation_cutoff_utc=at(cutoff).isoformat(),
        entry_result=opened,
        outcomes=outputs,
        journal=account.journal(),
        cutoff_review=account.review_cutoff(cutoff, end_of_input=True),
        historical_metrics="UNMEASURED",
        source_scope="SUPPLIED_AUTHENTICATED_SYNTHETIC_QUOTE_EPISODE_ONLY",
    )
