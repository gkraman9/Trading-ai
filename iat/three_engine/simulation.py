"""Independent paper ledgers. Observed executable-side quotes only, never OHLC fills."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from iat.replay_dataset import utc
from iat.strategy_qualification.backtest import dec, Costs
from iat.three_engine.contracts import feasibility
from iat.three_engine.config import PROTOCOL
from iat.intelligence.strategy_replay import digest
from iat.live_shadow import LABEL


def initial(config):
    equity = config["account"]["equity"] if config["account"] else None
    return dict(
        balance=equity,
        peak=equity,
        drawdown="0",
        position=None,
        pending=None,
        retired=[],
        daily={},
        last_quote=None,
        last_proposal=None,
        counts=dict(
            BUY=0,
            SELL=0,
            WAIT=0,
            BLOCKED=0,
            entries=0,
            exits=0,
            unresolved=0,
            rejected=0,
            market_points=0,
            missing_data=0,
            source_observations=0,
            source_missing_data=0,
        ),
        reasons={},
        latencies=[],
        closed=dict(n=0, wins=0, losses=0, net="0", profit="0", loss="0"),
        provider_status="DISABLED",
        last_bundle=None,
    )


def rejected(s, code):
    s["counts"]["rejected"] += 1
    s["reasons"][code] = s["reasons"].get(code, 0) + 1


def missing(s, reason):
    s = deepcopy(s)
    s["pending"] = None
    s["counts"]["missing_data"] += 1
    rejected(s, reason)
    events = []
    if s["position"] and s["position"]["state"] == "OPEN":
        s["position"]["state"] = "UNRESOLVED"
        s["position"]["unresolved_reason"] = reason
        s["counts"]["unresolved"] += 1
        events.append(
            dict(kind="UNRESOLVED", position=deepcopy(s["position"]), label=LABEL)
        )
    return s, events


def decision(s, p, bundle):
    s = deepcopy(s)
    s["last_proposal"] = deepcopy(p)
    s["last_bundle"] = bundle["id"]
    s["counts"][p["decision"]] += 1
    if p["latency_seconds"] is not None and (
        p["engine"] == "A_RULES"
        or p["provider_response_valid"]
        or any(
            c in ("PROVIDER_TIMEOUT", "PROVIDER_ERROR", "MODEL_SCHEMA_INVALID")
            for c in p["reason_codes"]
        )
    ):
        s["latencies"].append(p["latency_seconds"])
    if len(s["latencies"]) > 10000:
        raise ValueError("STUDY_CAPACITY_REACHED")
    s["provider_status"] = (
        "BASELINE"
        if p["engine"] == "A_RULES"
        else (
            "VALIDATED_PROVIDER_RESPONSE"
            if p["provider_response_valid"]
            else "DISABLED" if p["reason_codes"] == ["PROVIDER_DISABLED"] else "BLOCKED"
        )
    )
    if p["decision"] in ("BUY", "SELL"):
        if s["position"]:
            rejected(s, "EXPOSURE_ALREADY_EXISTS")
        else:
            s["pending"] = dict(proposal=deepcopy(p), bundle=deepcopy(bundle))
    else:
        s["pending"] = None
        if p["decision"] == "BLOCKED":
            rejected(s, p["reason_codes"][0])
    return s, [dict(kind="PROPOSAL", proposal=deepcopy(p), label=LABEL)]


def invalidate(s, bundle):
    s = deepcopy(s)
    s["counts"]["market_points"] += 1
    p = s["position"]
    if not bundle["quality"]["valid"]:
        return missing(s, "COMMON_MARKET_EVIDENCE_BLOCKED")
    if p and p["state"] == "OPEN":
        opposite = "BEARISH" if p["side"] == "BUY" else "BULLISH"
        codes = p["invalidation_conditions"]
        fresh = [
            e
            for e in bundle["evidence_index"].values()
            if e.get("category") == "TRANSITION"
            and e.get("details", {}).get("fresh")
            and e.get("details", {}).get("event_type") == opposite + "_CHOCH"
        ]
        if (
            "OPPOSING_M1_CHOCH" in codes
            and fresh
            or "HIGH_VOLATILITY" in codes
            and bundle["volatility"]["overall"] == "HIGH"
        ):
            p["exit_after"] = bundle["cutoff"]
        if "ANCHOR_LOST" in codes and bundle["candles"]["M1"]:
            close = dec(str(bundle["candles"]["M1"][-1]["close"]))
            if (
                close < dec(p["anchor"])
                if p["side"] == "BUY"
                else close > dec(p["anchor"])
            ):
                p["exit_after"] = bundle["cutoff"]
    return s, []


def quote(s, q, config, session):
    s = deepcopy(s)
    events = []
    at = utc(q["timestamp"])
    previous = s["last_quote"]
    if previous:
        if q["id"] == previous["id"]:
            return s, []
        if at <= utc(previous["timestamp"]):
            return missing(s, "QUOTE_ORDER_AMBIGUOUS")
    s["last_quote"] = deepcopy(q)
    if config["costs"] is None or s["balance"] is None:
        return s, events
    obj = dict(config["costs"])
    obj["rollovers"] = tuple(obj["rollovers"])
    c = Costs(**obj)
    tick = dec(c.tick_size)
    slip = tick * c.slippage_ticks
    contract = dec(c.contract_size)
    money = lambda v: v.quantize(dec(c.currency_quantum), rounding=c.money_rounding)
    p = s["position"]
    balance = dec(s["balance"])
    day = at.date().isoformat()

    def mark():
        if not p or p["state"] != "OPEN":
            return Decimal(0)
        return money(
            (dec(q["bid"] if p["side"] == "BUY" else q["ask"]) - dec(p["entry"]))
            * (1 if p["side"] == "BUY" else -1)
            * contract
            * dec(p["volume"])
        )

    if day not in s["daily"]:
        if p and (at.hour or at.minute or at.second or at.microsecond):
            return missing(s, "UTC_OPENING_EQUITY_UNAVAILABLE")
        s["daily"][day] = dict(baseline=str(balance + mark()), opens=0, latched=False)
    d = s["daily"][day]
    if session["quote_available"] is False:
        return missing(s, "QUOTE_OUTSIDE_DECLARED_SESSION")
    if p and p["state"] == "OPEN":
        if any(utc(p["entry_at"]) < utc(r["timestamp"]) <= at for r in c.rollovers):
            return missing(s, "ROLLOVER_ORDER_UNSUPPORTED")
        px = dec(q["bid"] if p["side"] == "BUY" else q["ask"])
        direction = 1 if p["side"] == "BUY" else -1
        stop = (px - dec(p["stop"])) * direction <= 0
        touch = [
            i
            for i, t in enumerate(p["targets"])
            if (px - dec(t)) * direction >= 0 and dec(p["allocations"][i]) > 0
        ]
        if touch and not stop and any(dec(p["allocations"][i]) < 1 for i in touch):
            return missing(s, "PARTIAL_FILL_EVIDENCE_UNAVAILABLE")
        reason = (
            "SL"
            if stop
            else (
                "TP"
                if touch
                else (
                    "INVALIDATED"
                    if p.get("exit_after") and at > utc(p["exit_after"])
                    else (
                        "TIME"
                        if at
                        >= utc(p["entry_at"]) + timedelta(seconds=p["hold_seconds"])
                        else None
                    )
                )
            )
        )
        if reason:
            if session["close_positions"] is False:
                return missing(s, "EXIT_PERMISSION_RESTRICTED")
            exit_ = (
                dec(p["targets"][touch[0]])
                if reason == "TP"
                else px - slip if p["side"] == "BUY" else px + slip
            )
            if exit_ <= 0:
                return missing(s, "EXIT_PRICE_UNSUPPORTED")
            volume = dec(p["volume"])
            fees = money(dec(c.commission_per_side_per_lot) * volume) + money(
                dec(c.fee_per_side_per_lot) * volume
            )
            gross = money((exit_ - dec(p["entry"])) * direction * contract * volume)
            net = gross - dec(p["entry_fees"]) - fees
            balance += gross - fees
            s["balance"] = str(balance)
            trade = {
                **p,
                "state": "CLOSED",
                "exit": str(exit_),
                "exit_at": q["timestamp"],
                "exit_quote_id": q["id"],
                "exit_spread": q["spread"],
                "reason": reason,
                "gross_pnl": str(gross),
                "net_pnl": str(net),
                "fees": str(fees + dec(p["entry_fees"])),
                "qualified_performance_eligible": False,
            }
            events.append(dict(kind="EXIT", trade=trade, label=LABEL))
            s["position"] = None
            p = None
            s["counts"]["exits"] += 1
            z = s["closed"]
            z["n"] += 1
            z["wins"] += net > 0
            z["losses"] += net < 0
            for k, v in (
                ("net", net),
                ("profit", max(Decimal(0), net)),
                ("loss", max(Decimal(0), -net)),
            ):
                z[k] = str(dec(z[k]) + v)
        elif p["risk_reduction"] == "BREAKEVEN_AT_R1" and not p.get(
            "breakeven_applied"
        ):
            threshold = dec(p["entry"]) + direction * dec(p["initial_risk"])
            if (px - threshold) * direction >= 0 and (
                px - dec(p["entry"])
            ) * direction >= dec(c.minimum_stop_distance):
                p["stop"] = p["entry"]
                p["breakeven_applied"] = True
                events.append(
                    dict(
                        kind="STOP_REDUCTION",
                        position_id=p["id"],
                        stop=p["stop"],
                        effective_after=q["timestamp"],
                        quote_id=q["id"],
                        scope="GROSS_BREAKEVEN_NOT_COST_FREE",
                        label=LABEL,
                    )
                )
    equity = balance + mark()
    s["peak"] = str(max(dec(s["peak"]), equity))
    s["drawdown"] = str(
        max(dec(s["drawdown"]), (dec(s["peak"]) - equity) / dec(s["peak"]))
    )
    if equity <= dec(d["baseline"]) * (1 - dec(PROTOCOL["daily_loss_fraction"])):
        d["latched"] = True
    pending = s["pending"]
    if pending is None or p is not None:
        return s, events
    plan = pending["proposal"]
    bundle = pending["bundle"]
    available = utc(plan["decision_available_at"])
    if at <= available:
        return s, events
    if at >= utc(plan["expires_at"]):
        s["pending"] = None
        rejected(s, "PROPOSAL_EXPIRED_BEFORE_FILL")
        return s, events
    side = plan["decision"]
    executable = dec(q["ask"] if side == "BUY" else q["bid"])
    anchor = dec(plan["entry_price"])
    if plan["entry_type"] == "MARKET":
        if (at - available).total_seconds() > 2:
            s["pending"] = None
            rejected(s, "MARKET_ENTRY_TOO_LATE")
            return s, events
    elif plan["entry_type"] == "PULLBACK":
        if not (executable <= anchor if side == "BUY" else executable >= anchor):
            return s, events
    elif not (executable >= anchor if side == "BUY" else executable <= anchor):
        return s, events
    s["pending"] = None
    if d["latched"] or d["opens"] >= 5:
        rejected(s, "DAILY_RISK_LATCH_OR_CAP")
        return s, events
    if session["new_positions"] is False:
        rejected(s, "NEW_POSITION_SESSION_RESTRICTED")
        return s, events
    if plan["setup_id"] in s["retired"]:
        rejected(s, "DUPLICATE_SETUP")
        return s, events
    if any(
        at <= utc(r["timestamp"]) <= at + timedelta(seconds=plan["hold_seconds"])
        for r in c.rollovers
    ):
        rejected(s, "ROLLOVER_MODEL_UNSUPPORTED")
        return s, events
    entry = executable + slip if side == "BUY" else executable - slip
    targets = [
        dec(plan[k])
        for k in ("take_profit_1", "take_profit_2", "take_profit_3")
        if plan[k] is not None
    ]
    current = deepcopy(bundle)
    current["quote"] = q
    try:
        free = (
            dec(config["account"]["free_margin"])
            + balance
            - dec(config["account"]["equity"])
        )
        f = feasibility(
            current,
            config,
            side,
            entry,
            dec(plan["stop_loss"]),
            targets,
            plan["tp_allocations"],
            plan["risk_percent"],
            equity=str(equity),
            free_margin=str(free),
        )
        if dec(f["lot_size"]) != dec(plan["lot_size"]):
            raise ValueError("RISK_CHANGED_AT_ENTRY")
        if equity - dec(f["risk_amount"]) <= dec(d["baseline"]) * Decimal(".99"):
            raise ValueError("PROJECTED_DAILY_LOSS_BUDGET")
    except Exception:
        rejected(s, "ENTRY_FEASIBILITY_REJECTED")
        return s, events
    volume = dec(f["lot_size"])
    fees = money(dec(c.commission_per_side_per_lot) * volume) + money(
        dec(c.fee_per_side_per_lot) * volume
    )
    s["balance"] = str(balance - fees)
    d["opens"] += 1
    s["retired"].append(plan["setup_id"])
    p = dict(
        id=digest([plan["engine"], plan["setup_id"]]),
        engine=plan["engine"],
        state="OPEN",
        label=LABEL,
        proposal_id=plan["decision_id"],
        bundle_id=bundle["id"],
        side=side,
        contract_size=c.contract_size,
        entry=str(entry),
        entry_at=q["timestamp"],
        entry_quote_id=q["id"],
        entry_fees=str(fees),
        entry_risk_amount=f["risk_amount"],
        entry_margin_required=f["margin_required"],
        entry_spread=q["spread"],
        stop=plan["stop_loss"],
        anchor=plan["stop_anchor_price"],
        targets=[str(t) for t in targets],
        allocations=plan["tp_allocations"],
        volume=str(volume),
        initial_risk=str(abs(entry - dec(plan["stop_loss"]))),
        hold_seconds=plan["hold_seconds"],
        risk_reduction=plan["risk_reduction"],
        invalidation_conditions=plan["invalidation_conditions"],
        decision_available_at=plan["decision_available_at"],
        qualified_performance_eligible=False,
    )
    s["position"] = p
    s["counts"]["entries"] += 1
    events.append(dict(kind="ENTRY", position=deepcopy(p), label=LABEL))
    entry_equity = (
        dec(s["balance"])
        + (dec(q["bid"] if side == "BUY" else q["ask"]) - entry)
        * (1 if side == "BUY" else -1)
        * contract
        * volume
    )
    s["drawdown"] = str(
        max(dec(s["drawdown"]), (dec(s["peak"]) - entry_equity) / dec(s["peak"]))
    )
    return s, events


def metrics(s):
    z = s["closed"]
    n = z["n"]
    lat = s["latencies"]
    count = s["counts"]
    den = count["source_observations"]
    p = s["position"]
    q = s["last_quote"]
    unrealized = None
    if p and p["state"] == "OPEN" and q:
        unrealized = str(
            (dec(q["bid"] if p["side"] == "BUY" else q["ask"]) - dec(p["entry"]))
            * (1 if p["side"] == "BUY" else -1)
            * dec(p["contract_size"])
            * dec(p["volume"])
        )
    equity = (
        str(dec(s["balance"]) + (dec(unrealized) if unrealized else Decimal(0)))
        if s["balance"] is not None and (p is None or unrealized is not None)
        else None
    )
    return dict(
        label=LABEL,
        paper_balance=s["balance"],
        paper_equity=equity,
        unrealized_pnl=unrealized,
        account_assurance="DECLARED_PAPER_LEDGER_NOT_CURRENT_BROKER_ACCOUNT",
        proposal_counts={k: count[k] for k in ("BUY", "SELL", "WAIT", "BLOCKED")},
        rejected=count["rejected"],
        entries=count["entries"],
        exits=count["exits"],
        unresolved=count["unresolved"],
        completed_trade_denominator=n,
        all_decision_denominator=sum(
            count[k] for k in ("BUY", "SELL", "WAIT", "BLOCKED")
        ),
        win_rate=str(Decimal(z["wins"]) / n) if n else None,
        after_cost_expectancy=str(dec(z["net"]) / n) if n else None,
        net_pnl=z["net"] if n else None,
        maximum_observed_drawdown=s["drawdown"] if s["balance"] is not None else None,
        drawdown_scope="OBSERVED_MARKS_ONLY_UNRESOLVED_INTERVALS_INCOMPLETE",
        average_decision_latency_seconds=(
            str(sum(map(dec, lat)) / len(lat)) if lat else None
        ),
        latency_denominator=len(lat),
        missing_data_count=count["source_missing_data"],
        market_point_denominator=den,
        missing_data_rate=(
            str(Decimal(count["source_missing_data"]) / den) if den else None
        ),
        open_positions=int(s["position"] is not None),
        reasons=s["reasons"],
        qualified_performance_metrics=None,
        confidence_calibration="NOT_RUN",
        ai_improvement="UNMEASURED",
    )
