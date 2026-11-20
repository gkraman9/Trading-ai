"""Causal quote-event research simulator. No broker functions or execution grants."""

from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from collections import Counter
from iat.replay_dataset import utc
from iat.intelligence.strategy_replay import digest
from iat.strategy_qualification.quotes import Quote


def dec(v):
    if type(v) not in (str, Decimal):
        raise ValueError("Explicit decimal strings required")
    n = Decimal(v)
    if not n.is_finite():
        raise ValueError("Finite decimals required")
    return n


@dataclass(frozen=True)
class Costs:
    initial_equity: str
    currency: str
    contract_size: str
    tick_size: str
    minimum_stop_distance: str
    volume_min: str
    volume_step: str
    max_spread: str
    slippage_ticks: int
    commission_per_side_per_lot: str
    fee_per_side_per_lot: str
    rollovers: tuple
    evidence_sha256: str
    known_at: str
    currency_quantum: str
    money_rounding: str
    spread_stress_multiplier: str = "1"

    def __post_init__(self):
        utc(self.known_at)
        if not Decimal("1") <= dec(self.spread_stress_multiplier) <= Decimal("3"):
            raise ValueError("Invalid spread cost stress")
        if (
            dec(self.currency_quantum) <= 0
            or dec(self.currency_quantum).normalize().as_tuple().digits != (1,)
            or self.money_rounding not in ("ROUND_HALF_EVEN", "ROUND_HALF_UP")
        ):
            raise ValueError("Explicit broker money precision required")
        if self.currency != "USD":
            raise ValueError("CURRENCY_CONVERSION_DATA_REQUIRED")
        for key in (
            "initial_equity",
            "contract_size",
            "tick_size",
            "minimum_stop_distance",
            "volume_min",
            "volume_step",
            "max_spread",
            "commission_per_side_per_lot",
            "fee_per_side_per_lot",
        ):
            if dec(getattr(self, key)) < 0:
                raise ValueError("Negative declared costs")
        if (
            min(
                dec(self.initial_equity),
                dec(self.contract_size),
                dec(self.tick_size),
                dec(self.volume_step),
            )
            <= 0
            or dec(self.volume_min) > Decimal(".01")
            or Decimal(".01") % dec(self.volume_step)
        ):
            raise ValueError("Unsupported sizing")
        if (
            type(self.slippage_ticks) is not int
            or not 0 <= self.slippage_ticks <= 1000
            or not isinstance(self.rollovers, tuple)
        ):
            raise ValueError("Invalid cost policy")
        prior = None
        for row in self.rollovers:
            if (
                set(row)
                != {"timestamp", "announced_at", "long_per_lot", "short_per_lot"}
                or prior is not None
                and utc(row["timestamp"]) <= prior
            ):
                raise ValueError("Rollover schedule invalid")
            prior = utc(row["timestamp"])
            utc(row["announced_at"])
            dec(row["long_per_lot"])
            dec(row["short_per_lot"])
        if not isinstance(self.evidence_sha256, str) or len(self.evidence_sha256) != 64:
            raise ValueError("Cost evidence identity required")

    @property
    def sha256(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class Decision:
    timestamp: str
    setup_id: str | None
    side: str
    stop: str | None
    invalidated: bool
    valid: bool
    regime: str
    volatility: str
    reasons: tuple = ()
    invalidated_setup_ids: tuple = ()

    def __post_init__(self):
        at = utc(self.timestamp)
        if (
            at.second
            or at.microsecond
            or self.side not in ("BUY", "SELL", "WAIT")
            or type(self.valid) is not bool
            or type(self.invalidated) is not bool
        ):
            raise ValueError("Invalid closed-M1 decision")
        if self.side != "WAIT" and (
            not isinstance(self.setup_id, str)
            or not self.setup_id
            or self.stop is None
            or dec(self.stop) <= 0
        ):
            raise ValueError("Anchored stop required")


def ambiguous_ohlc_exit(side, stop, target, bid_bar, ask_bar):
    bar = bid_bar if side == "BUY" else ask_bar
    stop_hit = (
        dec(bar["low"]) <= dec(stop) if side == "BUY" else dec(bar["high"]) >= dec(stop)
    )
    target_hit = (
        dec(bar["high"]) >= dec(target)
        if side == "BUY"
        else dec(bar["low"]) <= dec(target)
    )
    return (
        "UNRESOLVED_INTRABAR_ORDER"
        if stop_hit and target_hit
        else (
            "STOP_TOUCHED_ORDER_UNPROVEN"
            if stop_hit
            else "TARGET_TOUCHED_ORDER_UNPROVEN" if target_hit else "NO_BARRIER_TOUCH"
        )
    )


def simulate(
    spec, costs, quotes, decisions, *, permissions, cutoff, scope="SYNTHETIC_ONLY"
):
    """Pure simulation; provenance/qualification belongs to the manifest wrapper.

    Existing positions see quotes before same-time decisions. Entries/invalidation
    exits require a strictly later quote. Terminal summaries are not causal events.
    """
    if scope != "SYNTHETIC_ONLY":
        raise ValueError("Caller provenance cannot qualify historical research")
    return _simulate(
        spec, costs, quotes, decisions, permissions=permissions, cutoff=cutoff
    )


def _simulate(
    spec, costs, quotes, decisions, *, permissions, cutoff, source_binding=None
):
    end = utc(cutoff)
    all_quotes = tuple(quotes)
    all_decisions = tuple(decisions)
    for rows in (all_quotes, all_decisions):
        if any(utc(a.timestamp) >= utc(b.timestamp) for a, b in zip(rows, rows[1:])):
            raise ValueError("Strict chronological events required")
    qs = tuple(q for q in all_quotes if utc(q.timestamp) <= end)
    ds = tuple(d for d in all_decisions if utc(d.timestamp) <= end)
    rollover_instants = {utc(r["timestamp"]) for r in costs.rollovers}
    events = sorted(
        [(utc(q.timestamp), 0, q) for q in qs]
        + [(utc(d.timestamp), 2, d) for d in ds]
        + [
            (utc(r["timestamp"]), 1, r)
            for r in costs.rollovers
            if utc(r["timestamp"]) <= end
        ],
        key=lambda x: (x[0], x[1]),
    )
    lot = Decimal(".01")
    contract = dec(costs.contract_size)
    tick = dec(costs.tick_size)
    slip = tick * costs.slippage_ticks

    def ask(q):
        # Explicit cost stress only: original observed quote bytes/identity are unchanged.
        value = dec(q.ask) + (dec(q.ask) - dec(q.bid)) * (
            dec(costs.spread_stress_multiplier) - 1
        )
        return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick

    money = lambda v: v.quantize(
        dec(costs.currency_quantum), rounding=costs.money_rounding
    )
    per_leg = money(dec(costs.commission_per_side_per_lot) * lot) + money(
        dec(costs.fee_per_side_per_lot) * lot
    )
    equity = balance = dec(costs.initial_equity)
    position = None
    pending = None
    retired = set()
    trades = []
    log = []
    days = {}
    last_quote = None
    blocked = Counter()
    uncertain = set()

    def emit(at, kind, data):
        previous = log[-1]["sha256"] if log else None
        row = dict(
            timestamp=at.isoformat(),
            kind=kind,
            data=deepcopy(data),
            previous_sha256=previous,
            specification_sha256=spec.sha256,
            costs_sha256=costs.sha256,
        )
        row["sha256"] = digest(row)
        log.append(row)

    def mark(q):
        if position is None:
            return Decimal(0)
        px = dec(q.bid) if position["side"] == "BUY" else ask(q)
        return money(
            (px - dec(position["entry"]))
            * (1 if position["side"] == "BUY" else -1)
            * contract
            * lot
        )

    def day_at(at):
        key = at.date().isoformat()
        if key not in days:
            # Overnight mark must be observed at the exact UTC boundary, never carried stale.
            known = (
                position is None
                or last_quote is not None
                and utc(last_quote.timestamp)
                == at.replace(hour=0, minute=0, second=0, microsecond=0)
            )
            baseline = balance + (
                mark(last_quote) if position is not None and last_quote else Decimal(0)
            )
            days[key] = dict(
                starting_equity=str(baseline) if known else None,
                opens=0,
                latched=False,
                baseline_known=known,
            )
            if not known:
                uncertain.add("UTC_OPENING_EQUITY_MARK_UNAVAILABLE")
        return days[key]

    def close(at, q, reason):
        nonlocal position, balance, equity
        raw = dec(q.bid) if position["side"] == "BUY" else ask(q)
        px = raw - slip if position["side"] == "BUY" else raw + slip
        if reason == "TP":
            px = dec(position["target"])  # limit target: no optimistic gap improvement
        if reason == "SL":
            px = (
                min(px, dec(position["stop"]))
                if position["side"] == "BUY"
                else max(px, dec(position["stop"]))
            )
        gross = money(
            (px - dec(position["entry"]))
            * (1 if position["side"] == "BUY" else -1)
            * contract
            * lot
        )
        balance += gross - per_leg
        trade = {
            **position,
            "exit_session_phase": (
                "FULL_OPEN" if allowed["open"] is True else "CLOSE_ONLY"
            ),
            "exit_at": at.isoformat(),
            "exit": str(px),
            "reason": reason,
            "gross_pnl": str(gross),
            "costs": str(dec(position["paid_costs"]) + per_leg),
            "net_pnl": str(gross - dec(position["paid_costs"]) - per_leg),
        }
        trades.append(trade)
        position = None
        equity = balance
        emit(at, "EXIT", trade)

    for at, kind, value in events:
        if kind == 2:
            d = value
            emit(at, "DECISION", asdict(d))
            if not d.valid:
                blocked["DATA_QUALITY_BLOCKED"] += 1
                pending = None
                if position:
                    uncertain.add("OPEN_POSITION_DURING_BLOCKED_EVIDENCE")
                continue
            if d.invalidated:
                if position and (
                    not d.invalidated_setup_ids
                    or position["setup_id"] in d.invalidated_setup_ids
                ):
                    position["exit_after"] = d.timestamp
                pending = None
                continue
            if not position and d.side != "WAIT" and d.setup_id not in retired:
                if pending is None or pending.setup_id != d.setup_id:
                    pending = d
            elif d.side == "WAIT" or d.invalidated:
                pending = None
            continue
        if kind == 1:
            if position:
                charge = money(
                    dec(
                        value[
                            (
                                "long_per_lot"
                                if position["side"] == "BUY"
                                else "short_per_lot"
                            )
                        ]
                    )
                    * lot
                )
                balance += charge
                position["paid_costs"] = str(dec(position["paid_costs"]) - charge)
                emit(at, "ROLLOVER", dict(cashflow=str(charge), schedule=value))
            continue
        q = value
        allowed = permissions(at)
        if set(allowed) != {"quotes", "open", "close"} or any(
            v is not None and type(v) is not bool for v in allowed.values()
        ):
            raise ValueError("Explicit session permissions required")
        # New UTC baseline uses THIS observed quote if exactly midnight.
        if at.hour == 0 and at.minute == 0 and at.second == 0 and at.microsecond == 0:
            last_quote = q
        day = day_at(at)
        if allowed["quotes"] is not True:
            blocked["QUOTE_OUTSIDE_VERIFIED_SESSION"] += 1
            if position:
                uncertain.add("OPEN_EXPOSURE_WITHOUT_SESSION_QUOTE_ASSURANCE")
            pending = None
            continue
        last_quote = q
        if position and allowed["close"] is None:
            uncertain.add("POSITION_EXIT_PERMISSION_UNVERIFIED")
        if position and at in rollover_instants:
            uncertain.add("ROLLOVER_QUOTE_ORDER_UNRESOLVED")
        if position and allowed["close"] is True:
            price = dec(q.bid) if position["side"] == "BUY" else ask(q)
            stop = (
                price <= dec(position["stop"])
                if position["side"] == "BUY"
                else price >= dec(position["stop"])
            )
            target = (
                price >= dec(position["target"])
                if position["side"] == "BUY"
                else price <= dec(position["target"])
            )
            expired = at >= utc(position["entry_at"]) + timedelta(
                minutes=spec.max_hold_minutes
            )
            invalidated = position.get("exit_after") is not None and at > utc(
                position["exit_after"]
            )
            if stop or target or expired or invalidated:
                close(
                    at,
                    q,
                    (
                        "SL"
                        if stop
                        else (
                            "TP" if target else "INVALIDATED" if invalidated else "TIME"
                        )
                    ),
                )
        equity = balance + mark(q)
        if day["baseline_known"] and equity <= dec(day["starting_equity"]) * Decimal(
            ".99"
        ):
            if not day["latched"]:
                emit(
                    at,
                    "DAILY_LOSS_LATCH",
                    dict(day=at.date().isoformat(), equity=str(equity)),
                )
            day["latched"] = True
            pending = None
        emit(
            at,
            "MARK",
            dict(
                equity=str(equity),
                position=position["setup_id"] if position else None,
                quote_id=q.identity,
            ),
        )
        if pending is None or position is not None:
            continue
        decision = pending
        if at <= utc(decision.timestamp):
            continue
        pending = None
        if (at - utc(decision.timestamp)).total_seconds() > 2:
            blocked["ENTRY_QUOTE_UNAVAILABLE_WITHIN_TWO_SECONDS"] += 1
            continue
        if allowed["open"] is not True:
            blocked["NEW_POSITION_SESSION_BLOCKED"] += 1
            continue
        if not day["baseline_known"] or day["latched"]:
            blocked["DAILY_LOSS_OR_BASELINE_BLOCKED"] += 1
            continue
        if utc(costs.known_at) > utc(decision.timestamp):
            blocked["COST_MODEL_NOT_KNOWN_AT_DECISION"] += 1
            continue
        if (
            permissions(at + timedelta(minutes=spec.max_hold_minutes))["close"]
            is not True
        ):
            blocked["HOLD_EXIT_SESSION_UNVERIFIED"] += 1
            continue
        if any(
            at < utc(r["timestamp"]) <= at + timedelta(minutes=spec.max_hold_minutes)
            and utc(r["announced_at"]) > at
            for r in costs.rollovers
        ):
            blocked["ROLLOVER_COST_NOT_KNOWN_AT_ENTRY"] += 1
            continue
        if day["opens"] >= 5:
            blocked["DAILY_TRADE_CAP"] += 1
            continue
        if ask(q) - dec(q.bid) > dec(costs.max_spread):
            blocked["SPREAD_FILTER"] += 1
            continue
        entry = ask(q) + slip if decision.side == "BUY" else dec(q.bid) - slip
        stop = dec(decision.stop)
        if entry <= 0 or stop % tick or entry % tick:
            blocked["BROKER_PRECISION_UNSUPPORTED"] += 1
            continue
        risk = entry - stop if decision.side == "BUY" else stop - entry
        if risk <= 0 or (
            stop >= dec(q.bid) or dec(q.bid) - stop < dec(costs.minimum_stop_distance)
            if decision.side == "BUY"
            else stop <= ask(q) or stop - ask(q) < dec(costs.minimum_stop_distance)
        ):
            blocked["STOP_GEOMETRY_INVALID"] += 1
            continue
        target = (
            entry + risk * dec(spec.reward_risk)
            if decision.side == "BUY"
            else entry - risk * dec(spec.reward_risk)
        )
        target = (target / tick).to_integral_value(
            rounding=ROUND_CEILING if decision.side == "BUY" else ROUND_FLOOR
        ) * tick
        if target <= 0:
            blocked["TARGET_GEOMETRY_INVALID"] += 1
            continue
        rollover_reserve = sum(
            (
                max(
                    Decimal(0),
                    -dec(
                        r["long_per_lot" if decision.side == "BUY" else "short_per_lot"]
                    ),
                )
                * lot
                for r in costs.rollovers
                if at
                < utc(r["timestamp"])
                <= at + timedelta(minutes=spec.max_hold_minutes)
            ),
            Decimal(0),
        )
        worst = (
            risk * contract * lot
            + 2 * per_leg
            + slip * contract * lot
            + rollover_reserve
        )
        if equity - worst <= dec(day["starting_equity"]) * Decimal(".99"):
            blocked["PROJECTED_DAILY_LOSS_CAP"] += 1
            continue
        if at in rollover_instants:
            uncertain.add("ROLLOVER_QUOTE_ORDER_UNRESOLVED")
        balance -= per_leg
        day["opens"] += 1
        retired.add(decision.setup_id)
        position = dict(
            setup_id=decision.setup_id,
            side=decision.side,
            entry_at=at.isoformat(),
            decision_at=decision.timestamp,
            entry=str(entry),
            stop=str(stop),
            target=str(target),
            volume="0.01",
            paid_costs=str(per_leg),
            planned_risk=str(risk * contract * lot),
            regime=decision.regime,
            volatility=decision.volatility,
            observed_spread=str(dec(q.ask) - dec(q.bid)),
            modeled_spread=str(ask(q) - dec(q.bid)),
            spread_stress_multiplier=costs.spread_stress_multiplier,
            entry_session_phase="FULL_OPEN",
            assumed_slippage_ticks=costs.slippage_ticks,
        )
        equity = balance + mark(q)
        emit(at, "ENTRY", position)
        emit(
            at,
            "MARK",
            dict(
                equity=str(equity), position=position["setup_id"], quote_id=q.identity
            ),
        )
    if position:
        uncertain.add("OPEN_POSITION_AT_OBSERVATION_CUTOFF")
    if pending:
        uncertain.add("ENTRY_HORIZON_INCOMPLETE")
    final_mark = (
        None
        if position
        and (
            last_quote is None or (end - utc(last_quote.timestamp)).total_seconds() > 2
        )
        else str(balance + (mark(last_quote) if position else Decimal(0)))
    )
    if final_mark is None:
        uncertain.add("FINAL_EQUITY_MARK_UNAVAILABLE")
    report = dict(
        backtest_version=1,
        data_kind="HISTORICAL_RESEARCH_MODEL" if source_binding else "SYNTHETIC_ONLY",
        source_binding=deepcopy(source_binding),
        scope="RESEARCH_SIMULATION_NOT_BROKER_EXECUTION",
        specification_sha256=spec.sha256,
        costs_sha256=costs.sha256,
        cutoff=cutoff,
        trade_log=trades,
        events=log,
        events_sha256=digest(log),
        open_position=deepcopy(position),
        final_equity=final_mark,
        daily=days,
        blocked_reasons=dict(sorted(blocked.items())),
        unresolved_reasons=sorted(uncertain),
        signal="WAIT",
        execution_allowed=False,
        orders_requested=0,
    )
    report["sha256"] = digest(report)
    return report
