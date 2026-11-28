"""Chronological, offline USD50 M1/M5 adapter; never a live service or order bridge."""

from collections import Counter
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from iat.intelligence.entry_intelligence import EntryResearchSession
from iat.intelligence.exit_intelligence import ExitResearchSession
from iat.intelligence.risk_intelligence import assess_risk
from iat.intelligence.protected_paper import (
    ProtectedPaperAccount,
    validate_protected_journal,
)
from iat.intelligence.paper_contracts import (
    SyntheticQuoteTape,
    SyntheticQuote,
    FillPolicy,
    require,
    PaperError,
    financial_context,
)
from iat.intelligence.paper_account import PaperExitPolicy
from iat.intelligence.capital_intelligence import CapitalPolicy
from iat.intelligence.protection_contracts import (
    ProtectiveStopPolicy,
    LiquidationPolicy,
)
from iat.intelligence.market_view import SAFETY
from iat.intelligence.strategy_replay import digest
from iat.replay_dataset import utc, DatasetError
from iat.paper_source_scope import source_scope
from iat.paper_readiness import performance_readiness
from iat.e5_source import load_source, AdmissionError, PLAN_INPUTS, ASSERTIONS
from iat.e5_protocol import protocol


def seal(value):
    return dict(value, sha256=digest(value))


def empty_report():
    return seal(
        dict(
            report_version=1,
            kind="E5_HISTORICAL_PAPER_REPLAY",
            status="BLOCKED",
            performance_status="UNMEASURED",
            historical_metrics=None,
            source=None,
            protocol=protocol(),
            replay=None,
            comparisons=dict(full_full="NOT_RUN", prefix="NOT_RUN"),
            reason_codes=["E5_QUALIFIED_INPUTS_UNAVAILABLE"],
            evidence_requirements=dict(
                inputs=list(PLAN_INPUTS),
                independent_adapter_assertions=list(ASSERTIONS),
                native_bid_ask="OCCURRENCE_AVAILABILITY_SEQUENCE_FINALITY_NO_OHLC_SUBSTITUTION",
                missing_data="NO_FABRICATED_RECEIPTS_CANDLES_COSTS_OR_FILLS",
            ),
            **SAFETY
        )
    )


@financial_context
def cost_breakdown(state):
    positions = state["closed_positions"] + state["open_positions"]
    commission = other = financing = slippage = Decimal(0)
    for p in positions:
        volume = Decimal(p["volume"])
        c = p["costs"]
        fills = 1 + (p["exit_fill"] is not None)
        commission += volume * Decimal(c["commission_per_lot_side"]) * fills
        other += volume * Decimal(c["other_per_lot_side"]) * fills
        slippage += (
            volume
            * Decimal(p["specification"]["contract_size"])
            * Decimal(c["slippage_price_per_fill"])
            * fills
        )
        if p["exit_fill"] is not None:
            financing += (
                volume
                * Decimal(c["financing_per_lot_day"])
                * Decimal(p["holding_seconds"])
                / Decimal(86400)
            )
    require(
        commission + other + financing == Decimal(state["transaction_costs"]),
        "E5_COST_RECONCILIATION_MISMATCH",
    )
    return dict(
        charged_commission=str(commission),
        charged_other_fees=str(other),
        charged_financing=str(financing),
        total_explicit_charges=state["transaction_costs"],
        modeled_slippage_embedded_in_fill_prices=str(slippage),
        spread="EMBEDDED_IN_NATIVE_SIDE_PRICES_NOT_CHARGED_AGAIN",
        open_financing=(
            "UNRESOLVED_OR_MARK_TO_LIQUIDATION_ONLY_NOT_YET_CHARGED"
            if state["open_positions"]
            else "NO_OPEN_POSITION"
        ),
    )


@financial_context
def replay_source(source, *, cutoff=None):
    """Single immutable admitted source, independent ledger/session state per call."""
    end = utc(source.windows["outcome"]["end"])
    cutoff = end if cutoff is None else utc(cutoff)
    require(cutoff <= end, "E5_CUTOFF_OUTSIDE_COVERAGE")
    eval_a, eval_b = map(
        utc,
        (source.windows["evaluation"]["start"], source.windows["evaluation"]["end"]),
    )
    first = min(utc(v["start"]) for v in source.windows["warmup"].values())
    require(cutoff >= eval_a, "E5_CUTOFF_BEFORE_EVALUATION")
    p = source.policies
    with source_scope(source):
        account = ProtectedPaperAccount(
            started_at=first,
            starting_balance="50",
            account_id="E5_USD50",
            max_events=protocol()["resources"]["max_events"],
            max_report_bytes=protocol()["resources"]["max_report_bytes"],
        )
        tape = SyntheticQuoteTape(
            "XAUUSD",
            source.specification.feed,
            source.binding,
            max_quotes=protocol()["resources"]["max_quotes"],
        )
        entries = EntryResearchSession()
        episodes, opportunities, snapshots = {}, [], []
        active = None
        times = [
            (utc(row["available_at_utc"]), 0, "BAR", row)
            for row in source.bar_events()
            if utc(row["available_at_utc"]) <= cutoff
        ]
        times += [
            (utc(q["available_at_utc"]), 1, "QUOTE", q)
            for q in source.quote_rows()
            if utc(q["available_at_utc"]) <= cutoff
        ]
        times.sort(key=lambda x: (x[0], x[1]))
        pending = []
        opportunity_events = []

        def record_op(op, at):
            opportunity_events.append(
                dict(
                    sequence=len(opportunity_events),
                    at_utc=at.isoformat(),
                    setup_id=op["setup_id"],
                    outcome=op["outcome"],
                    reason_codes=deepcopy(op["reason_codes"]),
                    entry_sha256=op["entry"]["sha256"] if op["entry"] else None,
                    exit_sha256=op["exit"]["sha256"] if op["exit"] else None,
                )
            )

        for at, _, kind, value in times:
            if kind == "BAR":
                anchor = utc(value["closed_at_utc"])
                c, v, vi = source.context(anchor.isoformat(), known_at=at.isoformat())
                entry = entries.record(v, c, view_inputs=vi)
                if "ENTRY_RESOURCE_LIMIT" in entry["reason_codes"]:
                    raise ValueError("E5_ENTRY_SESSION_RESOURCE_LIMIT")
                snapshots.append(
                    dict(
                        timestamp_utc=at.isoformat(),
                        analysis_close_utc=anchor.isoformat(),
                        observed_at_utc=at.isoformat(),
                        phase=(
                            "WARMUP"
                            if anchor <= eval_a
                            else "EVALUATION" if at <= eval_b else "OUTCOME"
                        ),
                        context_sha256=digest(c.to_dict()),
                        entry_sha256=entry["sha256"],
                        status=entry["status"],
                        reason_codes=entry["reason_codes"],
                    )
                )
                for sid, episode in episodes.items():
                    if episode["finished"]:
                        continue
                    current = episode["exit_source"].record(v, c, view_inputs=vi)
                    inputs = dict(
                        original_e1=episode["original_e1"],
                        original_e2=episode["original_e2"],
                        current_e2=current,
                        entry_source=episode["entry_source"],
                        exit_source=episode["exit_source"],
                        as_of=anchor,
                        context=c,
                        view=v,
                        view_inputs=vi,
                    )
                    episode.update(risk_inputs=inputs, risk=assess_risk(**inputs))
                if (
                    eval_a < anchor <= eval_b
                    and at <= eval_b
                    and entry["status"] == "EVALUATED"
                ):
                    for plan in sorted(entry["plans"], key=lambda x: x["setup_id"]):
                        sid = plan["setup_id"]
                        if (
                            sid in episodes
                            or plan["research_state"] != "RESEARCH_QUALIFIED"
                        ):
                            continue
                        # A warm-up qualification is not a new evaluation opportunity.
                        if (
                            utc(
                                plan["confirmation"][
                                    "earliest_research_qualification_at_utc"
                                ]
                            )
                            != anchor
                        ):
                            continue
                        es = entries.fork_at(entry)
                        xs = ExitResearchSession(entry, sid, entry_source=es)
                        original_exit = xs.report()
                        inputs = dict(
                            original_e1=entry,
                            original_e2=original_exit,
                            current_e2=original_exit,
                            entry_source=es,
                            exit_source=xs,
                            as_of=anchor,
                            context=c,
                            view=v,
                            view_inputs=vi,
                        )
                        op = dict(
                            setup_id=sid,
                            direction=plan["research_direction"],
                            qualified_at_utc=at.isoformat(),
                            qualification_close_utc=anchor.isoformat(),
                            outcome="PENDING_NATIVE_QUOTE",
                            reason_codes=[],
                            entry=None,
                            exit=None,
                        )
                        opportunities.append(op)
                        record_op(op, at)
                        episode = dict(
                            original_e1=entry,
                            original_e2=original_exit,
                            entry_source=es,
                            exit_source=xs,
                            risk_inputs=inputs,
                            risk=assess_risk(**inputs),
                            finished=False,
                            opportunity=op,
                        )
                        episodes[sid] = episode
                        if active is not None:
                            op.update(
                                outcome="REJECTED",
                                reason_codes=["MAX_CONCURRENT_POSITIONS"],
                            )
                            episode["finished"] = True
                            record_op(op, at)
                        else:
                            pending.append(sid)
                continue
            q = value
            quotation, opening = source.permissions(
                q["occurred_at_utc"], q["available_at_utc"]
            )
            row = tape.append(
                SyntheticQuote(
                    "XAUUSD",
                    source.specification.feed,
                    int(q["sequence"]),
                    q["occurred_at_utc"],
                    q["available_at_utc"],
                    q["bid"],
                    q["ask"],
                    quotation,
                    quotation and opening,
                    provenance=source.provenance,
                )
            )
            if active is not None and not episodes[active]["finished"]:
                episode = episodes[active]
                try:
                    if episode["risk"]["source_eligibility"] != "VALID":
                        account.block_observation(
                            "E5_ANALYTICAL_SOURCE_BLOCKED", as_of=at
                        )
                        result = dict(
                            status="UNRESOLVED",
                            reason_codes=["E5_ANALYTICAL_SOURCE_BLOCKED"],
                        )
                    else:
                        result = account.observe(
                            episode["risk"],
                            risk_inputs=episode["risk_inputs"],
                            tape=tape,
                            quote=row,
                            as_of=at,
                        )
                except (ValueError, TypeError, KeyError) as exc:
                    code = (
                        str(exc)
                        if isinstance(exc, PaperError)
                        else "E5_UNRESOLVED_QUOTE_SPEC_OR_CLOCK"
                    )
                    account.block_observation(code, as_of=at)
                    result = dict(
                        status="UNRESOLVED",
                        reason_codes=[code],
                    )
                if result["status"] in (
                    "HYPOTHETICALLY_CLOSED",
                    "UNRESOLVED",
                    "BLOCKED",
                ):
                    op = episode["opportunity"]
                    op["outcome"] = (
                        "CLOSED"
                        if result["status"] == "HYPOTHETICALLY_CLOSED"
                        else "UNRESOLVED"
                    )
                    op["reason_codes"] = result["reason_codes"]
                    op["exit"] = deepcopy(result.get("position", {}).get("exit_fill"))
                    episode["finished"] = True
                    record_op(op, at)
                    # An unresolved position occupies the sole slot until independent review.
                    active = (
                        None if result["status"] == "HYPOTHETICALLY_CLOSED" else active
                    )
            for sid in list(pending):
                episode = episodes[sid]
                op = episode["opportunity"]
                decision = utc(op["qualified_at_utc"])
                if at <= decision:
                    continue
                pending.remove(sid)
                if at > eval_b or active is not None:
                    op.update(
                        outcome="REJECTED",
                        reason_codes=[
                            (
                                "E5_EVALUATION_ENDED"
                                if at > eval_b
                                else "MAX_CONCURRENT_POSITIONS"
                            )
                        ],
                    )
                    episode["finished"] = True
                    record_op(op, at)
                    continue
                result = account.open(
                    episode["risk"],
                    risk_inputs=episode["risk_inputs"],
                    tape=tape,
                    quote=row,
                    specification=source.specification,
                    costs=source.costs,
                    policy=CapitalPolicy(**p["capital"]),
                    fill_policy=FillPolicy(**p["fill"]),
                    exit_policy=PaperExitPolicy(**p["exit"]),
                    stop_policy=ProtectiveStopPolicy(**p["stop"]),
                    liquidation_policy=LiquidationPolicy(**p["liquidation"]),
                    as_of=at,
                )
                op["reason_codes"] = result["reason_codes"]
                if result["status"] == "HYPOTHETICALLY_OPEN":
                    active = sid
                    op.update(
                        outcome="ACCEPTED_OPEN",
                        entry=deepcopy(result["position"]["entry_fill"]),
                    )
                else:
                    op["outcome"] = (
                        "REJECTED"
                        if result["status"] == "ENTRY_REJECTED"
                        else "BLOCKED"
                    )
                    episode["finished"] = True
                record_op(op, at)
        journal = account.journal()
        validate_protected_journal(journal, source=account)
        metrics = performance_readiness(account)
        if source.historical:
            metrics.pop("sha256")
            metrics["scope"] = "FILE_BOUND_HISTORICAL_HYPOTHETICAL_ACCOUNTING"
            metrics = seal(metrics)
        state = journal["account"]
        return seal(
            dict(
                replay_version=1,
                provenance=source.provenance,
                source_binding=source.binding,
                cutoff_utc=cutoff.isoformat(),
                protocol_sha256=protocol()["sha256"],
                snapshots=snapshots,
                opportunities=deepcopy(opportunities),
                opportunity_events=opportunity_events,
                setup_summary=dict(
                    opportunities=len(opportunities),
                    accepted=sum(o["entry"] is not None for o in opportunities),
                    rejected=sum(o["outcome"] == "REJECTED" for o in opportunities),
                    blocked=sum(o["outcome"] == "BLOCKED" for o in opportunities),
                    unresolved=sum(
                        o["outcome"]
                        in ("UNRESOLVED", "ACCEPTED_OPEN", "PENDING_NATIVE_QUOTE")
                        for o in opportunities
                    ),
                ),
                blocked_evaluation_snapshots=sum(
                    s["phase"] == "EVALUATION" and s["status"] == "BLOCKED"
                    for s in snapshots
                ),
                snapshot_reason_counts=dict(
                    sorted(
                        Counter(
                            r
                            for s in snapshots
                            if s["phase"] == "EVALUATION"
                            for r in s["reason_codes"]
                        ).items()
                    )
                ),
                journal=journal,
                performance=metrics,
                cost_breakdown=cost_breakdown(state),
                cutoff_review=account.review_cutoff(cutoff, end_of_input=True),
                open_at_cutoff=len(state["open_positions"]),
                equity_observed_at_utc=state["as_of_utc"],
                equity_at_cutoff=(
                    state["equity"] if utc(state["as_of_utc"]) == cutoff else None
                ),
                opportunity_counts=dict(
                    sorted(Counter(o["outcome"] for o in opportunities).items())
                ),
                reason_counts=dict(
                    sorted(
                        Counter(
                            r for o in opportunities for r in o["reason_codes"]
                        ).items()
                    )
                ),
                window_counts=dict(
                    sorted(Counter(s["phase"] for s in snapshots).items())
                ),
                **SAFETY
            )
        )


def common_prefix(full, prefix):
    for log in (full, prefix):
        require(
            log.get("sha256")
            == digest({k: v for k, v in log.items() if k != "sha256"}),
            "E5_REPLAY_HASH_INVALID",
        )
    cutoff = utc(prefix["cutoff_utc"])
    require(
        full["source_binding"] == prefix["source_binding"]
        and full["protocol_sha256"] == prefix["protocol_sha256"],
        "E5_REPLAY_BINDING_MISMATCH",
    )
    events = [e for e in full["journal"]["events"] if utc(e["at_utc"]) <= cutoff]
    snapshots = [s for s in full["snapshots"] if utc(s["timestamp_utc"]) <= cutoff]
    opportunity_events = [
        e for e in full["opportunity_events"] if utc(e["at_utc"]) <= cutoff
    ]
    return (
        events == prefix["journal"]["events"]
        and snapshots == prefix["snapshots"]
        and opportunity_events == prefix["opportunity_events"]
    )


def run_historical(plan_path=None, adapter_review_path=None, *, prefix_cutoff=None):
    result = empty_report()
    result.pop("sha256")
    try:
        source, admission = load_source(plan_path, adapter_review_path)
        result["source"] = deepcopy(admission)
        first = replay_source(source)
        other, other_admission = load_source(plan_path, adapter_review_path)
        second = replay_source(other)
        require(
            first == second and admission == other_admission, "E5_FULL_REPLAY_MISMATCH"
        )
        # Use a declared common cutoff, or the evaluation end before the outcome tail.
        cutoff = (
            source.windows["evaluation"]["end"]
            if prefix_cutoff is None
            else prefix_cutoff
        )
        third, _ = load_source(plan_path, adapter_review_path)
        prefix = replay_source(third, cutoff=cutoff)
        require(common_prefix(first, prefix), "E5_PREFIX_REPLAY_MISMATCH")
        result.update(
            status="PASS",
            performance_status=(
                "PARTIALLY_MEASURED_UNRESOLVED"
                if first["setup_summary"]["unresolved"]
                or first["setup_summary"]["blocked"]
                or first["blocked_evaluation_snapshots"]
                else "MEASURED_UNDER_REVIEWED_MODEL"
            ),
            historical_comparisons="FULL_FULL_PREFIX_MATCH",
            source=admission,
            replay=first,
            historical_metrics=first["performance"],
            reason_codes=[],
            comparisons=dict(
                full_full="MATCH",
                prefix="MATCH",
                full_log_sha256=first["journal"]["sha256"],
                second_log_sha256=second["journal"]["sha256"],
                prefix_log_sha256=prefix["journal"]["sha256"],
                prefix_cutoff_utc=prefix["cutoff_utc"],
            ),
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OSError,
        ArithmeticError,
    ) as exc:
        import re

        code = str(exc)
        if (
            not code.startswith("E5_")
            and isinstance(exc, (PaperError, DatasetError))
            and re.fullmatch("[A-Z0-9_]{1,95}", code)
        ):
            code = "E5_" + code
        if isinstance(exc, AdmissionError):
            result["source"] = exc.diagnostics
        result["reason_codes"] = [
            (
                code
                if re.fullmatch("E5_[A-Z0-9_]{1,100}", code)
                else "E5_INPUT_OR_REPLAY_UNRESOLVED"
            )
        ]
        if isinstance(exc, AdmissionError) and type(exc.diagnostics) is dict:
            result["reason_codes"] += exc.diagnostics.get("reason_codes", [])
    return seal(result)
