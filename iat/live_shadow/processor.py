"""Deterministic frozen-observation reduction, shared by live journaling and offline replay."""

from copy import deepcopy
from iat.replay_dataset import utc
from iat.live_shadow import engine
from iat.live_shadow.research import assess
from iat.live_shadow.policy import session_diagnostics
from iat.live_shadow.feed import observed_tick
from iat.intelligence.strategy_replay import digest


def initial_state():
    return dict(
        engine=engine.initial(),
        research={},
        last_received=None,
        last_capture_end=None,
        last_source=None,
        polls=0,
        valid_quotes=0,
        valid_candles=0,
        last_successful_observation=None,
        last_decision=None,
        session=None,
        integrity_latched=False,
    )


def reduce_packet(state, packet, config, calendar, *, previous_candles=None):
    s = deepcopy(state)
    effects = []
    at = utc(packet["received_at"])
    s["polls"] += 1
    if s["last_received"] and at <= utc(s["last_received"]):
        s["engine"], effects = engine.missing_event(
            s["engine"], "CLOCK_MOVED_BACKWARD_OR_REPEAT"
        )
        return s, effects
    s["last_received"] = packet["received_at"]
    errors = list(packet["errors"])
    quote = packet["quote"]
    capture = packet["capture"]
    candles = packet["candles"]
    if quote:
        try:
            if not 0 <= (at - utc(quote["timestamp"])).total_seconds() <= 2:
                raise ValueError()
            from decimal import Decimal

            if (
                not all(Decimal(quote[k]).is_finite() for k in ("bid", "ask", "spread"))
                or not 0 < Decimal(quote["bid"]) <= Decimal(quote["ask"])
                or Decimal(quote["spread"])
                != Decimal(quote["ask"]) - Decimal(quote["bid"])
            ):
                raise ValueError()
            if quote["id"] != digest({k: v for k, v in quote.items() if k != "id"}):
                raise ValueError()
        except Exception:
            quote = None
            errors.append("QUOTE_INVALID_STALE_OR_FUTURE")
    session = session_diagnostics(calendar, at, quote=quote, errors=errors)
    s["session"] = session
    if not errors and quote:
        s["valid_quotes"] += 1
        s["last_successful_observation"] = packet["received_at"]
    if previous_candles:
        for tf in ("M1", "M5"):
            known = {r["timestamp"]: r for r in previous_candles[tf]}
            if any(
                r["timestamp"] in known and r != known[r["timestamp"]]
                for r in candles[tf]
            ):
                s["integrity_latched"] = True
                errors.append("CLOSED_CANDLE_CORRECTION_DETECTED")
    # Preserve native M5; compare only complete overlapping M1 groups.
    try:
        from datetime import timedelta
        from iat.intelligence.models import iso

        index = {r["timestamp"]: r for r in candles["M1"]}
        compared = 0
        for five in candles["M5"]:
            opened = utc(five["timestamp"])
            group = [index.get(iso(opened + timedelta(minutes=i))) for i in range(5)]
            if not all(group):
                continue
            compared += 1
            expected = dict(
                open=group[0]["open"],
                high=max(v["high"] for v in group),
                low=min(v["low"] for v in group),
                close=group[-1]["close"],
            )
            if any(abs(expected[k] - five[k]) > 1e-8 for k in expected):
                errors.append("M1_M5_OHLC_MISMATCH")
        if not compared:
            errors.append("M1_M5_COMPARISON_UNAVAILABLE")
    except Exception:
        errors.append("M1_M5_COMPARISON_UNAVAILABLE")
    prepared = None
    try:
        from iat.quality import assess_candles

        for tf in ("M1", "M5"):
            quality = assess_candles(
                candles[tf], tf, at, session_calendar=calendar, observed_finality=True
            )
            if not quality.valid:
                errors.extend(d.code for d in quality.diagnostics)
        if not errors:
            prepared = assess(
                candles, packet["received_at"], s["research"], config, calendar
            )
            if not prepared[0].get("data_quality_valid", False):
                errors.append("RESEARCH_DATA_QUALITY_BLOCKED")
    except Exception:
        errors.append("MARKET_RESEARCH_UNAVAILABLE")
    if packet["identity"] != dict(
        broker="EXNESS_COMPANY_LABEL_MATCH",
        symbol="XAUUSD",
        account_mode="DEMO",
        assurance="OBSERVED_COMPANY_LABEL_NOT_AUTHENTICATED_ACCOUNT_BINDING",
        trading_permissions_disabled=True,
    ):
        errors.append("DEMO_BROKER_IDENTITY_OR_PERMISSION_UNVERIFIED")
    captured = (
        capture["status"] == "OBSERVED_RANGE" and not errors and quote is not None
    )
    if s["last_capture_end"] and capture["start"] != s["last_capture_end"]:
        captured = False
        errors.append("CAPTURE_COVERAGE_GAP")
    if utc(capture["end"]) > at or utc(capture["start"]) > utc(capture["end"]):
        captured = False
        errors.append("CAPTURE_WINDOW_INVALID")
    # Validate the entire batch before applying any hypothetical fills.
    try:
        from decimal import Decimal

        previous_tick = None
        for tick in capture["ticks"]:
            t = utc(tick["timestamp"])
            if tick["id"] != digest(
                {k: v for k, v in tick.items() if k != "id"}
            ) or not utc(capture["start"]) <= t <= utc(capture["end"]):
                raise ValueError()
            if (
                not all(Decimal(tick[k]).is_finite() for k in ("bid", "ask", "spread"))
                or not 0 < Decimal(tick["bid"]) <= Decimal(tick["ask"])
                or Decimal(tick["spread"])
                != Decimal(tick["ask"]) - Decimal(tick["bid"])
            ):
                raise ValueError()
            if previous_tick is not None and t <= previous_tick:
                raise ValueError()
            previous_tick = t
        if (
            quote
            and utc(quote["timestamp"]) >= utc(capture["start"])
            and quote["id"] not in {t["id"] for t in capture["ticks"]}
        ):
            raise ValueError()
    except Exception:
        captured = False
        errors.append("CAPTURE_TICK_INVALID_OR_INCOMPLETE")
    session = session_diagnostics(calendar, at, quote=quote, errors=errors)
    s["session"] = session
    if errors or not captured or s["integrity_latched"]:

        code = (
            "CLOSED_CANDLE_CORRECTION_DETECTED"
            if s["integrity_latched"]
            else (
                errors[0]
                if errors
                else (
                    capture["reason_codes"][0]
                    if capture["reason_codes"]
                    else "TICK_CAPTURE_UNAVAILABLE"
                )
            )
        )
        s["engine"], effects = engine.missing_event(s["engine"], code)
    else:
        previous = None
        for q in capture["ticks"]:
            tick_at = utc(q["timestamp"])
            # Reject fabricated/reordered tape records, including differently priced ticks at one millisecond.
            if (
                q["id"] != digest({k: v for k, v in q.items() if k != "id"})
                or not utc(capture["start"]) <= tick_at <= utc(capture["end"])
                or previous is not None
                and tick_at <= previous
            ):
                s["engine"], e = engine.missing_event(
                    s["engine"], "CAPTURE_TICK_INVALID_OR_AMBIGUOUS"
                )
                effects += e
                captured = False
                break
            previous = tick_at
            phase = session_diagnostics(calendar, tick_at, quote=q)
            s["engine"], e = engine.quote_event(
                s["engine"], q, config, phase, packet["symbol_specification"]
            )
            effects += e
    s["last_capture_end"] = capture["end"]
    try:
        if errors or s["integrity_latched"]:
            raise ValueError("MARKET_OBSERVATION_BLOCKED")
        research, decision = prepared
        s["research"] = research
        s["valid_candles"] += bool(research.get("data_quality_valid"))
        if decision:
            decision["segmentation"].update(
                session=session["phase"], calendar_status=session["calendar_status"]
            )
            # Rebind after adding actual session context, before freezing the decision.
            decision["id"] = digest({k: v for k, v in decision.items() if k != "id"})
            s["last_decision"] = decision
            s["engine"], e = engine.decision_event(s["engine"], decision)
            effects += e
    except Exception:
        s["engine"], e = engine.missing_event(
            s["engine"], "MARKET_RESEARCH_UNAVAILABLE"
        )
        effects += e
        s["last_decision"] = dict(
            candidate="BLOCKED",
            reason_codes=["MARKET_RESEARCH_UNAVAILABLE"],
            operational_signal="WAIT",
        )
    return s, effects
