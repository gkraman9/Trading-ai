"""One immutable, causal evidence package. No invented prices or inferred Ask."""

from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from iat.intelligence.strategy_replay import digest
from iat.intelligence.context import context_at
from iat.intelligence.context_evidence import candle_id
from iat.intelligence.adaptive import assess_adaptive
from iat.live_observer import _report_tree
from iat.live_shadow.store import safe_packet
from iat.live_shadow.policy import session_diagnostics
from iat.quality import assess_candles
from iat.replay_dataset import utc


def build(
    packet, config, cutoff, *, calendar=None, source_kind="LIVE_MT5_OBSERVATIONS"
):
    safe_packet(packet)
    at = utc(cutoff)
    errors = list(packet["errors"])
    rows = packet["candles"]
    quote = packet["quote"]
    if utc(packet["received_at"]) > at:
        errors.append("FUTURE_SOURCE_PACKET")
    if packet["identity"] is None:
        errors.append("DEMO_IDENTITY_UNAVAILABLE")
    if quote is None:
        errors.append("BID_ASK_UNAVAILABLE")
    elif (
        quote["id"] != digest({k: v for k, v in quote.items() if k != "id"})
        or not 0 <= (at - utc(quote["timestamp"])).total_seconds() <= 2
    ):
        errors.append("STALE_OR_FUTURE_QUOTE")
    if quote and (
        not 0 < Decimal(quote["bid"]) <= Decimal(quote["ask"])
        or Decimal(quote["spread"]) != Decimal(quote["ask"]) - Decimal(quote["bid"])
    ):
        errors.append("BID_ASK_INVALID")
    for tf in ("M1", "M5"):
        quality = assess_candles(
            rows[tf], tf, at, session_calendar=calendar, observed_finality=True
        )
        if not quality.valid:
            errors.extend(d.code for d in quality.diagnostics)
    if packet["capture"]["status"] != "OBSERVED_RANGE":
        errors.append("TICK_CAPTURE_INCOMPLETE")
    for tf in rows:
        if any(
            utc(r["timestamp"]) + timedelta(minutes=1 if tf == "M1" else 5) > at
            for r in rows[tf]
        ):
            errors.append("UNCLOSED_OR_FUTURE_CANDLE")
    # Native M5 is never substituted by aggregation.
    compared = 0
    index = {utc(r["timestamp"]): r for r in rows["M1"]}
    for five in rows["M5"]:
        group = [
            index.get(utc(five["timestamp"]) + timedelta(minutes=i)) for i in range(5)
        ]
        if not all(group):
            continue
        compared += 1
        expected = dict(
            open=group[0]["open"],
            high=max(r["high"] for r in group),
            low=min(r["low"] for r in group),
            close=group[-1]["close"],
        )
        if any(
            abs(Decimal(str(expected[k])) - Decimal(str(five[k])))
            > Decimal(".00000001")
            for k in expected
        ):
            errors.append("M1_M5_OHLC_MISMATCH")
    if not compared:
        errors.append("M1_M5_COMPARISON_UNAVAILABLE")
    analysis = (
        utc(rows["M1"][-1]["timestamp"]) + timedelta(minutes=1) if rows["M1"] else at
    )
    report = context_at(
        "XAUUSD",
        rows["M1"],
        rows["M5"],
        analysis,
        provenance="HISTORICAL_RESEARCH",
        calendar=calendar,
        observed_finality=True,
    )
    if not report.data_quality["valid"]:
        errors.append("EXISTING_RESEARCH_QUALITY_BLOCKED")
    source = report.interpretations.get("source_registry", {})
    evidence = {e.id: _report_tree(asdict(e)) for e in report.evidence}
    levels = {}

    def level(source_id, field, price, time, kind):
        if utc(time) > at:
            raise ValueError("FUTURE_LEVEL")
        item = dict(
            source_id=source_id,
            field=field,
            price=str(price),
            available_at=time,
            kind=kind,
        )
        levels["LEVEL:" + digest(item)] = item

    for tf in ("M1", "M5"):
        for row in rows[tf][-20:]:
            from iat.analysis import Candle

            sid = candle_id(
                "XAUUSD",
                tf,
                Candle(
                    utc(row["timestamp"]),
                    *[float(row[k]) for k in ("open", "high", "low", "close")]
                ),
            )
            available = (
                utc(row["timestamp"]) + timedelta(minutes=1 if tf == "M1" else 5)
            ).isoformat()
            evidence.setdefault(
                sid,
                dict(
                    id=sid,
                    category="CLOSED_CANDLE",
                    timeframe=tf,
                    available_at=available,
                ),
            )
            for key in ("high", "low"):
                level(sid, key, row[key], available, "CLOSED_CANDLE_" + key.upper())
    for sid, s in source.items():
        if utc(s["available_at"]) > at:
            errors.append("FUTURE_SOURCE_EVIDENCE")
            continue
        if s["kind"] == "CONFIRMED_PIVOT":
            level(
                sid,
                "price",
                s["price"],
                s["available_at"],
                "CONFIRMED_PIVOT_" + s["pivot_kind"],
            )
    for e in report.evidence:
        if utc(e.available_at) > at:
            errors.append("FUTURE_EVIDENCE")
        for key in ("lower", "upper", "level"):
            value = e.details.get(key)
            if type(value) in (int, float):
                level(e.id, key, value, e.available_at, e.category)
    adaptive = assess_adaptive(report)
    bundle = dict(
        bundle_version=1,
        symbol="XAUUSD",
        timeframe="M1",
        confirmation_timeframe="M5",
        cutoff=cutoff,
        analysis_at=analysis.isoformat(),
        source_received_at=packet["received_at"],
        source_kind=source_kind,
        source_packet_sha256=digest(packet),
        quote=quote,
        candles=_report_tree(rows),
        context=_report_tree(report.context),
        features=_report_tree(report.interpretations.get("frames", {})),
        evidence_index=evidence,
        price_catalog=dict(sorted(levels.items())),
        regime=adaptive["regime"],
        volatility=adaptive["volatility"],
        session=session_diagnostics(calendar, at, quote=quote, errors=errors),
        symbol_specifications=packet["symbol_specification"],
        identity=packet["identity"],
        costs=config["costs"],
        account=config["account"],
        quality=dict(valid=not errors, reason_codes=sorted(set(errors))),
        limitations=[
            "LIVE_CAPTURE_NOT_INDEPENDENTLY_QUALIFIED",
            "TERMINAL_CAPTURE_COMPLETENESS_UNVERIFIED",
            "ACCOUNT_AND_COSTS_ARE_DECLARED_RESEARCH_INPUTS",
            "HISTORICAL_RESEARCH_ENUM_IS_NOT_SOURCE_QUALIFICATION",
            "ALL_CONFIDENCE_UNCALIBRATED",
        ],
        signal="WAIT",
        execution_allowed=False,
        orders_requested=0,
    )
    bundle["id"] = digest(bundle)
    return bundle


def validate(bundle):
    if (
        bundle["bundle_version"] != 1
        or type(bundle["bundle_version"]) is not int
        or bundle["symbol"] != "XAUUSD"
        or bundle["timeframe"] != "M1"
        or bundle["confirmation_timeframe"] != "M5"
    ):
        raise ValueError("BUNDLE_IDENTITY_INVALID")
    if (
        bundle["id"] != digest({k: v for k, v in bundle.items() if k != "id"})
        or bundle["execution_allowed"] is not False
        or bundle["orders_requested"] != 0
        or bundle["signal"] != "WAIT"
    ):
        raise ValueError("EVIDENCE_BUNDLE_INVALID")
    at = utc(bundle["cutoff"])
    if utc(bundle["analysis_at"]) > at or utc(bundle["source_received_at"]) > at:
        raise ValueError("FUTURE_BUNDLE_TIME")
    for tf, rows in bundle["candles"].items():
        prior = None
        for r in rows:
            opened = utc(r["timestamp"])
            end = opened + timedelta(minutes=1 if tf == "M1" else 5)
            if end > at or prior is not None and opened <= prior:
                raise ValueError("FUTURE_OR_UNORDERED_CANDLES")
            prior = opened
    if any(
        utc(v["available_at"]) > at for v in bundle["price_catalog"].values()
    ) or any(utc(v["available_at"]) > at for v in bundle["evidence_index"].values()):
        raise ValueError("FUTURE_EVIDENCE")
    return True
