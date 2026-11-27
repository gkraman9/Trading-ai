"""Deterministic one-position synthetic ledger. Not a broker or live-paper service."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, localcontext
from functools import wraps
import json
from iat.intelligence.paper_contracts import (
    require,
    PaperError,
    at,
    dec,
    report,
    canonical,
    name,
    SyntheticQuoteTape,
    BrokerSpecification,
    SyntheticCosts,
    FillPolicy,
    quote_fill,
    reports_equal,
)
from iat.intelligence.capital_intelligence import assess_capital, CapitalPolicy
from iat.intelligence.risk_intelligence import (
    ARITHMETIC,
    text_number,
    validate_risk_report,
)
from iat.intelligence.strategy_replay import digest


def fixed_decimal(fn):
    @wraps(fn)
    def wrapped(*args, **kw):
        with localcontext(ARITHMETIC):
            return fn(*args, **kw)

    return wrapped


@dataclass(frozen=True)
class PaperExitPolicy:
    """Version 1 reacts only to authenticated E2, never an inferred intrabar order."""

    structural_target: bool
    structural_invalidation: bool
    opposing_structure: bool
    version: int = 1

    def __post_init__(self):
        require(
            type(self.version) is int
            and self.version == 1
            and all(
                type(v) is bool
                for v in (
                    self.structural_target,
                    self.structural_invalidation,
                    self.opposing_structure,
                )
            ),
            "EXIT_POLICY_INVALID",
        )
        require(
            self.structural_invalidation, "STRUCTURAL_INVALIDATION_PROTECTION_REQUIRED"
        )


class PaperAccount:
    @fixed_decimal
    def __init__(
        self,
        *,
        started_at,
        starting_balance="50",
        account_id="SYNTHETIC_USD50",
        max_events=1000,
        max_report_bytes=2000000
    ):
        require(
            type(max_events) is int
            and 0 < max_events <= 10000
            and type(max_report_bytes) is int
            and 1024 <= max_report_bytes <= 10000000,
            "ACCOUNT_RESOURCE_LIMIT",
        )
        start = dec(starting_balance, positive=True)
        self.account_id = name(account_id)
        self._max_events, self._max_report_bytes = max_events, max_report_bytes
        self._events = []
        self._quote_history = {}
        self._state = dict(
            account_id=self.account_id,
            account_currency="USD",
            account_lifecycle="ACTIVE",
            as_of_utc=at(started_at).isoformat(),
            starting_balance=text_number(start),
            balance=text_number(start),
            equity=text_number(start),
            unrealized_hypothetical_pnl="0",
            realized_hypothetical_pnl="0",
            used_margin="0",
            free_margin=text_number(start),
            peak_equity=text_number(start),
            drawdown="0",
            drawdown_fraction="0",
            max_drawdown="0",
            max_drawdown_fraction="0",
            transaction_costs="0",
            aggregate_open_risk="0",
            consecutive_losses=0,
            daily_losses={},
            open_positions=[],
            closed_positions=[],
            rejected_opportunities=[],
            seen_setups=[],
            cash_flow="0",
            cash_events=[],
            data_quality_exclusions=0,
        )
        self._commit(deepcopy(self._state), [dict(kind="ACCOUNT_CREATED")])

    @staticmethod
    def _quote_prefix_signature(tape, sequence):
        require(type(tape) is SyntheticQuoteTape, "QUOTE_PRODUCER_REQUIRED")
        return digest(
            [
                row["sha256"]
                for row in tape.rows()
                if row["quote"]["sequence"] <= sequence
            ]
        )

    def _check_quote_history(self, position, tape):
        previous = self._quote_history.get(position["position_id"])
        require(
            previous is not None
            and previous[1] == self._quote_prefix_signature(tape, previous[0]),
            "QUOTE_SOURCE_HISTORY_MISMATCH",
        )

    def _snapshot(self, state, events):
        return report(
            "IAT_PAPER_ACCOUNT_V1",
            **deepcopy(state),
            journal_sha256=digest(events),
            event_count=len(events),
            resource_limits=dict(
                max_events=self.max_events, max_report_bytes=self.max_report_bytes
            ),
            account_is_synthetic=True,
            connected_account_balance=None
        )

    @property
    def max_events(self):
        return self._max_events

    @property
    def max_report_bytes(self):
        return self._max_report_bytes

    def snapshot(self):
        return self._snapshot(self._state, self._events)

    def _journal(self, state, events):
        return report(
            "IAT_PAPER_JOURNAL_V1",
            account=self._snapshot(state, events),
            events=deepcopy(events),
            metrics=self._metrics(state, events),
            result_scope="SYNTHETIC_ACCOUNTING_NOT_STRATEGY_PERFORMANCE",
        )

    def journal(self):
        return self._journal(self._state, self._events)

    def _prepare_position(self, position, assessment):
        return position

    def _entry_events(self, events, position):
        return events

    def _commit(self, state, events):
        require(
            len(self._events) + len(events) <= self.max_events, "ACCOUNT_RESOURCE_LIMIT"
        )
        history = deepcopy(self._events)
        for e in events:
            event = dict(
                sequence=len(history),
                at_utc=state["as_of_utc"],
                equity=state["equity"],
                balance=state["balance"],
                previous_event_sha256=digest(history[-1]) if history else None,
                **deepcopy(e)
            )
            history.append(event)
        candidate = self._snapshot(state, history)
        # Budget checks precede ALL state/history writes; caller receives detached values.
        journal = self._journal(state, history)
        size = len(
            json.dumps(
                journal, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        )
        require(size <= self.max_report_bytes, "ACCOUNT_RESOURCE_LIMIT")
        self._state, self._events = deepcopy(state), history
        return candidate

    def _advance(self, when):
        require(at(when) >= at(self._state["as_of_utc"]), "ACCOUNT_CLOCK_BACKWARD")
        state = deepcopy(self._state)
        state["as_of_utc"] = at(when).isoformat()
        return state

    @fixed_decimal
    def _equity(self, state):
        if state["unrealized_hypothetical_pnl"] is None:
            state.update(equity=None, free_margin=None, account_lifecycle="UNRESOLVED")
            return
        equity = dec_signed(state["balance"]) + dec_signed(
            state["unrealized_hypothetical_pnl"]
        )
        peak = max(dec(state["peak_equity"]), equity)
        dd = max(Decimal(0), peak - equity)
        fraction = dd / peak
        state.update(
            equity=text_number(equity),
            free_margin=text_number(equity - dec(state["used_margin"])),
            peak_equity=text_number(peak),
            drawdown=text_number(dd),
            drawdown_fraction=text_number(fraction),
            max_drawdown=text_number(max(dec(state["max_drawdown"]), dd)),
            max_drawdown_fraction=text_number(
                max(dec(state["max_drawdown_fraction"]), fraction)
            ),
        )
        if equity <= 0:
            state["account_lifecycle"] = "EXHAUSTED"

    @fixed_decimal
    def cash_event(self, kind, amount, *, as_of, reference):
        require(kind in ("DEPOSIT", "WITHDRAWAL"), "CASH_EVENT_UNSUPPORTED")
        name(reference)
        require(
            not self._state["open_positions"],
            "CASH_EVENT_WITH_OPEN_POSITION_UNSUPPORTED",
        )
        require(
            not any(x["reference"] == reference for x in self._state["cash_events"]),
            "DUPLICATE_CASH_EVENT",
        )
        state = self._advance(as_of)
        value = dec(amount, positive=True) * (1 if kind == "DEPOSIT" else -1)
        require(dec_signed(state["balance"]) + value >= 0, "WITHDRAWAL_EXCEEDS_BALANCE")
        state["balance"] = text_number(dec_signed(state["balance"]) + value)
        state["cash_flow"] = text_number(dec_signed(state["cash_flow"]) + value)
        state["cash_events"].append(
            dict(kind=kind, amount=text_number(abs(value)), reference=reference)
        )
        # Never erase a prior drawdown/loss or automatically reset the account.
        self._equity(state)
        return self._commit(
            state,
            [dict(kind=kind, amount=text_number(abs(value)), reference=reference)],
        )

    @fixed_decimal
    def open(
        self,
        risk,
        *,
        risk_inputs,
        tape,
        quote,
        specification,
        costs,
        policy,
        fill_policy,
        exit_policy,
        as_of
    ):
        require(type(exit_policy) is PaperExitPolicy, "TYPED_EXIT_POLICY_REQUIRED")
        assessment = assess_capital(
            risk,
            risk_inputs=risk_inputs,
            account=self,
            tape=tape,
            quote=quote,
            specification=specification,
            costs=costs,
            policy=policy,
            fill_policy=fill_policy,
            as_of=as_of,
        )
        if assessment["status"] == "CAPITAL_ASSESSMENT_UNAVAILABLE":
            return report(
                "IAT_PAPER_ENTRY_V1",
                status="BLOCKED",
                capital=assessment,
                position=None,
                reason_codes=assessment["reason_codes"],
            )
        sid = assessment["setup_id"]
        require(
            sid not in self._state["seen_setups"], "DUPLICATE_SETUP_OR_TERMINAL_REOPEN"
        )
        state = self._advance(as_of)
        state["seen_setups"].append(sid)
        events = [
            dict(
                kind="ENTRY_PENDING", setup_id=sid, capital_sha256=assessment["sha256"]
            )
        ]
        if assessment["status"] == "FINANCIALLY_UNSUITABLE":
            state["rejected_opportunities"].append(assessment)
            self._commit(
                state,
                events
                + [
                    dict(
                        kind="ENTRY_REJECTED",
                        setup_id=sid,
                        reason_codes=assessment["reason_codes"],
                    )
                ],
            )
            return report(
                "IAT_PAPER_ENTRY_V1",
                status="ENTRY_REJECTED",
                capital=assessment,
                position=None,
                reason_codes=assessment["reason_codes"],
            )
        require(not state["open_positions"], "MAX_CONCURRENT_POSITIONS")
        fill = assessment["hypothetical_entry_fill"]
        volume = dec(
            assessment["assessment"]["step_adjusted_position_size"], positive=True
        )
        c = costs.validate()
        entry_fee = volume * (c["commission_per_lot_side"] + c["other_per_lot_side"])
        position = dict(
            position_id="PAPER:"
            + digest(
                [
                    self.account_id,
                    sid,
                    risk["bindings"],
                    canonical(policy),
                    canonical(exit_policy),
                ]
            ),
            setup_id=sid,
            direction=risk["research_direction"],
            state="HYPOTHETICALLY_OPEN",
            entry_fill=fill,
            exit_fill=None,
            volume=text_number(volume),
            structural_invalidation=deepcopy(risk["frozen_invalidation"]),
            structural_threshold=risk["reference_geometry"]["invalidation_threshold"],
            proposed_protective_stop=None,
            protective_stop_fill=None,
            target=deepcopy(risk["frozen_target"]),
            additional_targets="NOT_IMPLEMENTED",
            original_bindings=dict(
                original_e1=risk["bindings"]["original_e1"],
                original_e2=risk["bindings"]["original_e2"],
            ),
            entry_risk_sha256=risk["sha256"],
            capital_sha256=assessment["sha256"],
            quote_source=deepcopy(quote["source"]),
            specification=canonical(specification),
            costs=canonical(costs),
            fill_policy=canonical(fill_policy),
            capital_policy=canonical(policy),
            exit_policy=canonical(exit_policy),
            estimated_risk=assessment["assessment"]["estimated_loss"],
            required_margin=assessment["assessment"]["estimated_required_margin"],
            entry_fee=text_number(entry_fee),
            last_quote_sha256=quote["sha256"],
            last_observation_utc=at(as_of).isoformat(),
            observed_mfe="0",
            observed_mae="0",
            excursion_coverage="OBSERVED_QUOTES_ONLY_NOT_CONTINUOUS",
            unrealized_hypothetical_pnl="0",
            gross_hypothetical_pnl=None,
            net_hypothetical_pnl=None,
            holding_seconds=None,
            reason_codes=[],
        )
        position = self._prepare_position(position, assessment)
        state["balance"] = text_number(dec_signed(state["balance"]) - entry_fee)
        state["transaction_costs"] = text_number(
            dec(state["transaction_costs"]) + entry_fee
        )
        state["used_margin"] = position["required_margin"]
        state["aggregate_open_risk"] = position["estimated_risk"]
        state["open_positions"] = [position]
        prefix_signature = self._quote_prefix_signature(
            tape, quote["quote"]["sequence"]
        )
        self._mark(state, position, quote["quote"], as_of)
        self._equity(state)
        self._commit(
            state,
            self._entry_events(
                events
                + [
                    dict(
                        kind="HYPOTHETICALLY_OPEN",
                        position_id=position["position_id"],
                        fill_sha256=fill["sha256"],
                    )
                ],
                position,
            ),
        )
        self._quote_history[position["position_id"]] = (
            quote["quote"]["sequence"],
            prefix_signature,
        )
        return report(
            "IAT_PAPER_ENTRY_V1",
            status="HYPOTHETICALLY_OPEN",
            capital=assessment,
            position=deepcopy(position),
            reason_codes=[],
        )

    def _mark(self, state, position, q, cutoff):
        c = SyntheticCosts(**position["costs"]).validate()
        cs = dec(position["specification"]["contract_size"], positive=True)
        volume = dec(position["volume"], positive=True)
        sign = 1 if position["direction"] == "BULLISH" else -1
        # Mark-to-exit includes declared adverse exit slippage, but no second spread charge.
        side = dec(q["bid"] if sign == 1 else q["ask"], positive=True)
        mark = side - sign * c["slippage_price_per_fill"]
        require(mark > 0, "MARK_PRICE_INVALID")
        gross = (
            (mark - dec(position["entry_fill"]["price"], positive=True))
            * sign
            * cs
            * volume
        )
        elapsed = Decimal(
            str(
                (
                    at(cutoff) - at(position["entry_fill"]["available_at_utc"])
                ).total_seconds()
            )
        )
        require(elapsed >= 0, "POSITION_CLOCK_BACKWARD")
        exit_fee = volume * (c["commission_per_lot_side"] + c["other_per_lot_side"])
        financing = volume * c["financing_per_lot_day"] * elapsed / Decimal(86400)
        net = gross - exit_fee - financing
        position.update(
            unrealized_hypothetical_pnl=text_number(net),
            last_observation_utc=at(cutoff).isoformat(),
            observed_mfe=text_number(max(dec(position["observed_mfe"]), gross)),
            observed_mae=text_number(max(dec(position["observed_mae"]), -gross)),
        )
        state["unrealized_hypothetical_pnl"] = text_number(net)
        return gross, exit_fee, financing, elapsed

    @fixed_decimal
    def observe(self, risk, *, risk_inputs, tape, quote, as_of):
        require(
            len(self._state["open_positions"]) == 1, "NO_OPEN_HYPOTHETICAL_POSITION"
        )
        state = self._advance(as_of)
        position = state["open_positions"][0]
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
            type(tape) is SyntheticQuoteTape and tape.symbol == risk["symbol"],
            "QUOTE_PRODUCER_REQUIRED",
        )
        fp = FillPolicy(**position["fill_policy"])
        costs = SyntheticCosts(**position["costs"])
        require(
            at(as_of) - at(risk["evaluation_at_utc"])
            <= timedelta(milliseconds=fp.max_analysis_age_ms),
            "ANALYSIS_STALE",
        )
        q = tape.authenticate(quote, as_of=as_of, policy=fp)
        require(
            q["feed"] == position["specification"]["feed"]
            and quote["source"] == position["quote_source"],
            "QUOTE_FEED_OR_DATASET_MISMATCH",
        )
        self._check_quote_history(position, tape)
        prefix_signature = self._quote_prefix_signature(tape, q["sequence"])
        require(
            at(q["available_at_utc"]) >= at(position["last_observation_utc"]),
            "POSITION_QUOTE_BACKWARD",
        )
        # Revalidate the same frozen model for marks/exits, not only for entry.
        BrokerSpecification(**position["specification"]).validate(q, as_of)
        if quote["sha256"] == position["last_quote_sha256"]:
            require(
                at(as_of) == at(position["last_observation_utc"]),
                "UNCHANGED_QUOTE_NOT_NEW_OBSERVATION",
            )
            return report(
                "IAT_PAPER_OBSERVATION_V1",
                status="DUPLICATE",
                position=deepcopy(position),
                reason_codes=[],
            )
        elapsed = at(q["available_at_utc"]) - at(position["last_observation_utc"])
        unresolved = []
        if elapsed > timedelta(milliseconds=fp.max_gap_ms):
            unresolved.append("QUOTE_COVERAGE_GAP")
        if risk["ambiguity"]["status"] == "UNRESOLVED_EVENT_ORDER":
            unresolved.append("E2_EVENT_ORDER_UNRESOLVED")
        if "ABSTAINED" in risk["states"]:
            unresolved.append("E2_EVIDENCE_INCOMPLETE")
        if unresolved:
            position.update(
                state="UNRESOLVED",
                reason_codes=unresolved,
                unrealized_hypothetical_pnl=None,
            )
            state["unrealized_hypothetical_pnl"] = None
            self._equity(state)
            self._commit(
                state,
                [
                    dict(
                        kind="UNRESOLVED",
                        position_id=position["position_id"],
                        reason_codes=unresolved,
                    )
                ],
            )
            return report(
                "IAT_PAPER_OBSERVATION_V1",
                status="UNRESOLVED",
                position=deepcopy(position),
                reason_codes=unresolved,
            )
        position["last_quote_sha256"] = quote["sha256"]
        gross, exit_fee, financing, holding = self._mark(state, position, q, as_of)
        ep = position["exit_policy"]
        enabled = {
            "STRUCTURAL_INVALIDATION_OBSERVED": ep["structural_invalidation"],
            "STRUCTURAL_TARGET_OBSERVED": ep["structural_target"],
            "OPPOSING_STRUCTURE_OBSERVED": ep["opposing_structure"],
        }
        current = risk_inputs["current_e2"]
        events = [
            e
            for e in current["observations"]
            if enabled.get(e["kind"], False)
            and at(e["available_at_utc"])
            > at(position["entry_fill"]["available_at_utc"])
        ]
        if len({e["available_at_utc"] for e in events}) > 1:
            earliest = min(at(e["available_at_utc"]) for e in events)
            events = [e for e in events if at(e["available_at_utc"]) == earliest]
        if len(events) > 1:
            position.update(state="UNRESOLVED", reason_codes=["COMPETING_EXIT_EVENTS"])
            state["unrealized_hypothetical_pnl"] = None
            self._equity(state)
            self._commit(
                state,
                [
                    dict(
                        kind="UNRESOLVED",
                        position_id=position["position_id"],
                        reason_codes=position["reason_codes"],
                    )
                ],
            )
            return report(
                "IAT_PAPER_OBSERVATION_V1",
                status="UNRESOLVED",
                position=deepcopy(position),
                reason_codes=position["reason_codes"],
            )
        if events:
            # The observation becomes actionable only at its actual first-observed cutoff.
            decision = max(
                at(events[0]["available_at_utc"]),
                at(events[0]["first_observed_at_utc"]),
            )
            fill = quote_fill(
                quote,
                tape=tape,
                direction=position["direction"],
                phase="EXIT",
                decision_at=decision,
                as_of=as_of,
                policy=fp,
                costs=costs,
            )
            require(
                at(q["available_at_utc"]) - decision
                <= timedelta(milliseconds=fp.max_gap_ms),
                "EXIT_QUOTE_COVERAGE_GAP",
            )
            self._settle(state, position, fill, quote, events[0])
            kinds = ["EXIT_PENDING", "HYPOTHETICALLY_CLOSED"]
        else:
            position["state"] = "MONITORING"
            # E2 expiry/invalidated without an enabled executable observation is not a fabricated exit.
            if risk["hypothesis_lifecycle"]["state"] == "EXPIRED":
                position.update(
                    state="UNRESOLVED",
                    reason_codes=["HYPOTHESIS_EXPIRED_NO_FILL_POLICY"],
                )
                state["unrealized_hypothetical_pnl"] = None
            kinds = [position["state"]]
        self._equity(state)
        if (
            state["open_positions"]
            and state["equity"] is not None
            and dec(state["used_margin"]) > 0
        ):
            ratio = dec_signed(state["equity"]) / dec(state["used_margin"])
            if ratio <= dec(position["specification"]["margin_call_equity_ratio"]):
                position.update(
                    state="UNRESOLVED",
                    reason_codes=[
                        "MARGIN_CALL_OR_STOP_OUT_REQUIRES_REVIEWED_LIQUIDATION"
                    ],
                )
                state["unrealized_hypothetical_pnl"] = None
                self._equity(state)
                kinds = ["UNRESOLVED"]
        self._commit(
            state,
            [
                dict(
                    kind=k,
                    position_id=position["position_id"],
                    quote_sha256=quote["sha256"],
                )
                for k in kinds
            ],
        )
        self._quote_history[position["position_id"]] = (q["sequence"], prefix_signature)
        return report(
            "IAT_PAPER_OBSERVATION_V1",
            status=position["state"],
            position=deepcopy(position),
            reason_codes=position["reason_codes"],
        )

    @fixed_decimal
    def _settle(self, state, position, fill, quote, exit_evidence):
        gross, exit_fee, financing, holding = self._mark(
            state, position, quote["quote"], fill["filled_at_utc"]
        )
        net = gross - dec(position["entry_fee"]) - exit_fee - financing
        position.update(
            state="HYPOTHETICALLY_CLOSED",
            exit_fill=fill,
            gross_hypothetical_pnl=text_number(gross),
            net_hypothetical_pnl=text_number(net),
            holding_seconds=text_number(holding),
            exit_evidence=deepcopy(exit_evidence),
            reason_codes=[exit_evidence["kind"]],
        )
        state["balance"] = text_number(
            dec_signed(state["balance"]) + gross - exit_fee - financing
        )
        state["realized_hypothetical_pnl"] = text_number(
            dec_signed(state["realized_hypothetical_pnl"]) + net
        )
        state["transaction_costs"] = text_number(
            dec(state["transaction_costs"]) + exit_fee + financing
        )
        state.update(
            open_positions=[],
            used_margin="0",
            aggregate_open_risk="0",
            unrealized_hypothetical_pnl="0",
        )
        state["closed_positions"].append(deepcopy(position))
        state["consecutive_losses"] = state["consecutive_losses"] + 1 if net < 0 else 0
        if net < 0:
            day = at(fill["filled_at_utc"]).date().isoformat()
            state["daily_losses"][day] = text_number(
                dec(state["daily_losses"].get(day, "0")) - net
            )

    @fixed_decimal
    def metrics(self):
        return self._metrics(self._state, self._events)

    @fixed_decimal
    def _metrics(self, s, events):
        closed = s["closed_positions"]
        values = [dec_signed(p["net_hypothetical_pnl"]) for p in closed]
        wins = [v for v in values if v > 0]
        losses = [v for v in values if v < 0]
        n = len(values)
        pos = len(closed) + len(s["open_positions"])
        out = dict(
            scope="SYNTHETIC_ACCOUNTING_ONLY_NOT_STRATEGY_VALIDATION",
            starting_capital=s["starting_balance"],
            ending_balance=s["balance"],
            equity=s["equity"],
            realized_hypothetical_pnl=s["realized_hypothetical_pnl"],
            transaction_costs=s["transaction_costs"],
            maximum_drawdown=s["max_drawdown"],
            maximum_drawdown_fraction=s["max_drawdown_fraction"],
            total_opportunities=len(s["seen_setups"]),
            qualified_setups=len(s["seen_setups"]),
            capital_rejected_setups=len(s["rejected_opportunities"]),
            positions_opened=pos,
            positions_closed=n,
            winning_positions=len(wins),
            losing_positions=len(losses),
            flat_positions=sum(v == 0 for v in values),
            resolved_denominator=n,
            unresolved_positions=sum(
                p["state"] == "UNRESOLVED" for p in s["open_positions"]
            ),
            open_denominator=len(s["open_positions"]),
            win_rate=text_number(Decimal(len(wins)) / n) if n else None,
            average_win=text_number(sum(wins) / len(wins)) if wins else None,
            average_loss=text_number(sum(losses) / len(losses)) if losses else None,
            profit_factor=text_number(sum(wins) / -sum(losses)) if losses else None,
            expectancy=text_number(sum(values) / n) if n else None,
            risk_reward_distribution=[
                dict(
                    estimated_risk=p["estimated_risk"],
                    net_hypothetical_pnl=p["net_hypothetical_pnl"],
                )
                for p in closed
            ],
            consecutive_losses=s["consecutive_losses"],
            data_quality_exclusions=s["data_quality_exclusions"],
            net_return=None,
            net_return_status="UNAVAILABLE_UNRESOLVED_OR_EXTERNAL_CASH_FLOW",
            equity_curve=[
                dict(
                    at_utc=e["at_utc"],
                    equity=e["equity"],
                    balance=e["balance"],
                    kind=e["kind"],
                )
                for e in events
            ],
            analyst_agreement="UNMEASURED",
            historical_performance="UNMEASURED",
        )
        if s["equity"] is not None and not s["cash_events"]:
            out.update(
                net_return=text_number(
                    (dec_signed(s["equity"]) - dec(s["starting_balance"]))
                    / dec(s["starting_balance"])
                ),
                net_return_status="SYNTHETIC_ACCOUNTING_ONLY",
            )
        return out

    def block_observation(self, code, *, as_of):
        name(code)
        state = self._advance(as_of)
        state["data_quality_exclusions"] += 1
        if state["open_positions"]:
            state["open_positions"][0].update(state="UNRESOLVED", reason_codes=[code])
            state["unrealized_hypothetical_pnl"] = None
            self._equity(state)
        return self._commit(state, [dict(kind="BLOCKED", reason_codes=[code])])

    def partial_exit(self, *args, **kw):
        raise PaperError("PARTIAL_EXITS_NOT_IMPLEMENTED_NO_SUBMINIMUM_VOLUME_SPLITS")


def dec_signed(value):
    # Account balances may become negative after adverse gaps; do not clamp/hide a loss.
    from iat.intelligence.risk_intelligence import number

    require(type(value) in (str, int, Decimal), "EXACT_DECIMAL_REQUIRED")
    return number(value)


def validate_paper_journal(value, *, source):
    require(
        type(source) is PaperAccount and reports_equal(value, source.journal()),
        "JOURNAL_SOURCE_BINDING_INVALID",
    )
    return True
