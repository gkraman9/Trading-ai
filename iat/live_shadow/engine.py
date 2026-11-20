"""Incremental hypothetical fills from observed quotes; no broker dependencies."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from iat.replay_dataset import utc
from iat.strategy_qualification.backtest import Costs, dec
from iat.strategy_qualification.specs import Specification
from iat.intelligence.strategy_replay import digest
from iat.live_shadow import LABEL
from iat.live_shadow.policy import costs_match_symbol


def initial():
    return dict(
        position=None,
        pending=None,
        last_quote=None,
        retired=[],
        daily={},
        balance=None,
        peak=None,
        drawdown="0",
        totals=dict(
            closed=0,
            wins=0,
            losses=0,
            gross="0",
            net="0",
            profit="0",
            loss="0",
            commission="0",
            spread="0",
            holding_seconds="0",
        ),
        segments={},
        rejections={},
        candidates={},
        unresolved=0,
    )


def reject(s, effects, code):
    s["rejections"][code] = s["rejections"].get(code, 0) + 1
    effects.append(dict(kind="REJECTION", code=code))


def segment(position):
    return digest(position["segmentation"])


def quote_event(state, q, config, session, symbol, *, capture_ok=True):
    s = deepcopy(state)
    effects = []
    at = utc(q["timestamp"])
    if s["last_quote"]:
        prior = s["last_quote"]
        if q["id"] == prior["id"]:
            return s, []
        if at <= utc(prior["timestamp"]):
            return missing_event(s, "QUOTE_ORDER_OR_REVISION_AMBIGUOUS")
    s["last_quote"] = q
    if config["costs"] is None:
        reject(s, effects, "SIMULATION_COSTS_NOT_CONFIGURED")
        return s, effects
    c = dict(config["costs"])
    c["rollovers"] = tuple(c["rollovers"])
    cost = Costs(**c)
    spec = Specification(config["strategy_id"])
    lot = Decimal(".01")
    contract = dec(cost.contract_size)
    tick = dec(cost.tick_size)
    slip = tick * cost.slippage_ticks
    money = lambda v: v.quantize(
        dec(cost.currency_quantum), rounding=cost.money_rounding
    )
    per_leg = money(dec(cost.commission_per_side_per_lot) * lot) + money(
        dec(cost.fee_per_side_per_lot) * lot
    )
    if s["balance"] is None:
        s["balance"] = cost.initial_equity
        s["peak"] = cost.initial_equity
    if not costs_match_symbol(cost, symbol):
        s, e = missing_event(s, "SYMBOL_CONTRACT_OR_COSTS_MISMATCH")
        return s, e
    if not capture_ok:
        return missing_event(s, "TICK_CAPTURE_UNCERTAIN")
    if session["quote_available"] is False:
        return missing_event(s, "QUOTE_OUTSIDE_DECLARED_SESSION")
    if dec(q["bid"]) % tick or dec(q["ask"]) % tick:
        return missing_event(s, "QUOTE_TICK_GRID_INVALID")
    p = s["position"]
    balance = dec(s["balance"])
    day = at.date().isoformat()
    if day not in s["daily"]:
        baseline = balance
        if p:
            if at.hour or at.minute or at.second or at.microsecond:
                return missing_event(s, "UTC_OPENING_EQUITY_MARK_UNAVAILABLE")
            px = dec(q["bid"] if p["side"] == "BUY" else q["ask"])
            baseline += money(
                (px - dec(p["entry"]))
                * (1 if p["side"] == "BUY" else -1)
                * contract
                * lot
            )
        s["daily"][day] = dict(baseline=str(baseline), opens=0, latched=False)
    riskday = s["daily"][day]
    if p and p["state"] == "OPEN":
        # Rollover cashflow not inferred. Crossing a rollover requires a separately reviewed sequenced model.
        if any(
            utc(s["position"]["entry_at"]) < utc(r["timestamp"]) <= at
            for r in cost.rollovers
        ):
            return missing_event(s, "ROLLOVER_EVENT_ORDER_REQUIRES_REVIEW")
        px = dec(q["bid"] if p["side"] == "BUY" else q["ask"])
        stop = px <= dec(p["stop"]) if p["side"] == "BUY" else px >= dec(p["stop"])
        target = (
            px >= dec(p["target"]) if p["side"] == "BUY" else px <= dec(p["target"])
        )
        reason = (
            "SL"
            if stop
            else (
                "TP"
                if target
                else (
                    "INVALIDATED"
                    if p.get("invalidated_at") and at > utc(p["invalidated_at"])
                    else (
                        "TIME"
                        if at
                        >= utc(p["entry_at"]) + timedelta(minutes=spec.max_hold_minutes)
                        else None
                    )
                )
            )
        )
        if reason:
            if session["close_positions"] is False:
                return missing_event(s, "EXIT_SESSION_PERMISSION_BLOCKED")
            exit_ = (
                dec(p["target"])
                if reason == "TP"
                else px - slip if p["side"] == "BUY" else px + slip
            )
            if exit_ <= 0:
                return missing_event(s, "SIMULATED_EXIT_PRICE_UNSUPPORTED")
            gross = money(
                (exit_ - dec(p["entry"]))
                * (1 if p["side"] == "BUY" else -1)
                * contract
                * lot
            )
            net = gross - 2 * per_leg
            balance += gross - per_leg
            s["balance"] = str(balance)
            trade = {
                **p,
                "state": "CLOSED",
                "exit": str(exit_),
                "exit_at": q["timestamp"],
                "exit_quote_id": q["id"],
                "reason": reason,
                "gross_pnl": str(gross),
                "net_pnl": str(net),
                "commission_and_fees": str(2 * per_leg),
                "holding_seconds": str(
                    Decimal(str((at - utc(p["entry_at"])).total_seconds()))
                ),
                "qualified_performance_eligible": False,
                "qualification_reason": "LIVE_SHADOW_NOT_INDEPENDENTLY_QUALIFIED",
            }
            effects.append(dict(kind="EXIT", id=p["id"], trade=trade))
            s["position"] = None
            total = s["totals"]
            total["closed"] += 1
            total["wins"] += net > 0
            total["losses"] += net < 0
            for key, value in (
                ("gross", gross),
                ("net", net),
                ("profit", max(Decimal(0), net)),
                ("loss", max(Decimal(0), -net)),
                ("commission", 2 * per_leg),
                ("spread", dec(p["entry_spread"]) * contract * lot),
                ("holding_seconds", dec(trade["holding_seconds"])),
            ):
                total[key] = str(dec(total[key]) + value)
            key = segment(p)
            g = s["segments"].setdefault(
                key,
                dict(
                    segmentation=p["segmentation"],
                    closed=0,
                    wins=0,
                    net="0",
                    qualified_count=0,
                ),
            )
            g["closed"] += 1
            g["wins"] += net > 0
            g["net"] = str(dec(g["net"]) + net)
    p = s["position"]
    unrealized = None
    if p and p["state"] == "OPEN":
        px = dec(q["bid"] if p["side"] == "BUY" else q["ask"])
        unrealized = money(
            (px - dec(p["entry"])) * (1 if p["side"] == "BUY" else -1) * contract * lot
        )
    equity = balance + (unrealized or Decimal(0))
    s["peak"] = str(max(dec(s["peak"]), equity))
    s["drawdown"] = str(
        max(dec(s["drawdown"]), (dec(s["peak"]) - equity) / dec(s["peak"]))
    )
    if equity <= dec(riskday["baseline"]) * Decimal(".99"):
        riskday["latched"] = True
    pending = s["pending"]
    if not pending or p:
        return s, effects
    if at <= utc(pending["available_at"]):
        return s, effects
    s["pending"] = None
    if (at - utc(pending["available_at"])).total_seconds() > 2:
        reject(s, effects, "NEXT_QUOTE_HORIZON_EXCEEDED")
        return s, effects
    if session["new_positions"] is False:
        reject(s, effects, "NEW_POSITION_SESSION_BLOCKED")
        return s, effects
    if not session.get("operational_eligible"):
        pending = deepcopy(pending)
        pending["calendar_qualified"] = False
    if riskday["latched"] or riskday["opens"] >= 5:
        reject(s, effects, "DAILY_LOSS_LATCH_OR_FIVE_TRADE_CAP")
        return s, effects
    if utc(cost.known_at) > utc(pending["available_at"]):
        reject(s, effects, "COSTS_NOT_KNOWN_AT_DECISION")
        return s, effects
    if dec(q["spread"]) > dec(cost.max_spread):
        reject(s, effects, "SPREAD_FILTER")
        return s, effects
    if pending["setup_id"] in s["retired"]:
        reject(s, effects, "SAME_SETUP_RETIRED")
        return s, effects
    if any(
        at < utc(r["timestamp"]) <= at + timedelta(minutes=spec.max_hold_minutes)
        for r in cost.rollovers
    ):
        reject(s, effects, "ROLLOVER_MODEL_NOT_SUPPORTED_FOR_LIVE_SHADOW")
        return s, effects
    side = pending["side"]
    entry = dec(q["ask"]) + slip if side == "BUY" else dec(q["bid"]) - slip
    stop = dec(pending["stop"])
    risk = entry - stop if side == "BUY" else stop - entry
    distance = dec(q["bid"]) - stop if side == "BUY" else stop - dec(q["ask"])
    if (
        entry <= 0
        or risk <= 0
        or stop % tick
        or entry % tick
        or distance < max(tick, dec(cost.minimum_stop_distance))
    ):
        reject(s, effects, "STOP_OR_PRECISION_INVALID")
        return s, effects
    if equity - risk * contract * lot - 2 * per_leg - slip * contract * lot <= dec(
        riskday["baseline"]
    ) * Decimal(".99"):
        reject(s, effects, "PROJECTED_DAILY_LOSS_BUDGET")
        return s, effects
    target = (
        entry + risk * dec(spec.reward_risk)
        if side == "BUY"
        else entry - risk * dec(spec.reward_risk)
    )
    target = (target / tick).to_integral_value(
        rounding=ROUND_CEILING if side == "BUY" else ROUND_FLOOR
    ) * tick
    if target <= 0:
        reject(s, effects, "TARGET_INVALID")
        return s, effects
    key = digest([config, pending["setup_id"]])
    s["retired"].append(pending["setup_id"])
    riskday["opens"] += 1
    s["balance"] = str(balance - per_leg)
    p = dict(
        id=key,
        label=LABEL,
        state="OPEN",
        side=side,
        setup_id=pending["setup_id"],
        strategy_id=config["strategy_id"],
        specification_sha256=spec.sha256,
        entry=str(entry),
        entry_at=q["timestamp"],
        entry_quote_id=q["id"],
        decision_id=pending["id"],
        decision_available_at=pending["available_at"],
        stop=str(stop),
        target=str(target),
        volume="0.01",
        contract_size=cost.contract_size,
        currency_quantum=cost.currency_quantum,
        money_rounding=cost.money_rounding,
        entry_spread=q["spread"],
        paid_costs=str(per_leg),
        slippage_assumption_ticks=cost.slippage_ticks,
        segmentation=pending["segmentation"],
        qualified_performance_eligible=False,
    )
    s["position"] = p
    opening_unrealized = money(
        (dec(q["bid"] if side == "BUY" else q["ask"]) - entry)
        * (1 if side == "BUY" else -1)
        * contract
        * lot
    )
    opening_equity = dec(s["balance"]) + opening_unrealized
    s["drawdown"] = str(
        max(dec(s["drawdown"]), (dec(s["peak"]) - opening_equity) / dec(s["peak"]))
    )
    effects.extend(
        [
            dict(kind="INTENT", id=key, decision=pending),
            dict(kind="FILL", id=key, position=p),
        ]
    )
    return s, effects


def decision_event(state, decision):
    s = deepcopy(state)
    effects = [dict(kind="DECISION", id=decision["id"], decision=decision)]
    candidate = decision["candidate"]
    s["candidates"][candidate] = s["candidates"].get(candidate, 0) + 1
    if candidate == "BLOCKED":
        return missing_event(s, "BLOCKED_RESEARCH_EVIDENCE", effects)
    p = s["position"]
    if p and p["setup_id"] in decision.get("invalidated_setup_ids", []):
        p["invalidated_at"] = decision["available_at"]
    s["pending"] = (
        decision if candidate in ("BUY_CANDIDATE", "SELL_CANDIDATE") and not p else None
    )
    return s, effects


def missing_event(state, reason, effects=None):
    s = deepcopy(state)
    effects = [] if effects is None else effects
    s["pending"] = None
    reject(s, effects, reason)
    if s["position"] and s["position"]["state"] == "OPEN":
        s["position"]["state"] = "UNRESOLVED"
        s["position"]["unresolved_reason"] = reason
        s["unresolved"] += 1
        effects.append(
            dict(kind="UNRESOLVED", id=s["position"]["id"], position=s["position"])
        )
    return s, effects


def summary(s):
    n = s["totals"]["closed"]
    t = s["totals"]
    p = s["position"]
    q = s["last_quote"]
    unrealized = None
    if p and p["state"] == "OPEN" and q:
        unrealized = str(
            (
                (dec(q["bid"] if p["side"] == "BUY" else q["ask"]) - dec(p["entry"]))
                * (1 if p["side"] == "BUY" else -1)
                * dec(p["contract_size"])
                * Decimal(".01")
            ).quantize(dec(p["currency_quantum"]), rounding=p["money_rounding"])
        )
    return dict(
        label=LABEL,
        closed_trades=n,
        open_positions=int(p is not None),
        unresolved_positions=s["unresolved"],
        win_rate=str(Decimal(t["wins"]) / n) if n else None,
        average_win=str(dec(t["profit"]) / t["wins"]) if t["wins"] else None,
        average_loss=str(-dec(t["loss"]) / t["losses"]) if t["losses"] else None,
        realized_net_pnl=t["net"] if n else None,
        unrealized_pnl=unrealized,
        profit_factor=(
            str(dec(t["profit"]) / dec(t["loss"])) if dec(t["loss"]) else None
        ),
        expectancy=str(dec(t["net"]) / n) if n else None,
        maximum_drawdown=s["drawdown"] if s["balance"] else None,
        average_holding_seconds=str(dec(t["holding_seconds"]) / n) if n else None,
        entry_spread_cost=t["spread"],
        spread_accounting="ENTRY_SPREAD_DIAGNOSTIC_ALREADY_EMBEDDED_IN_BID_ASK_PNL_NOT_ADDITIVE",
        commission_and_fees=t["commission"],
        rejections=s["rejections"],
        rejection_count=sum(s["rejections"].values()),
        signal_frequency=s["candidates"],
        signal_denominator=sum(s["candidates"].values()),
        segments=sorted(s["segments"].values(), key=digest),
        qualified_performance_metrics=None,
    )
