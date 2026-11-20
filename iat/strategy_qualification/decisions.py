"""Reuse causal IAT observations and original strategy predicates, never model text."""

from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from datetime import timedelta
from iat.replay_dataset import utc
from iat.intelligence.context import context_at
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.strategy_replay import StrategyReplayLedger, digest
from iat.strategy_qualification.backtest import Decision, dec


def decisions_from_candles(
    spec,
    costs,
    m1,
    m5,
    *,
    evaluation,
    calendar=None,
    provenance="SYNTHETIC_RESEARCH",
    finality=True,
    context_config=None,
    intelligence_config=None,
    feed_id="SYNTHETIC_ONLY"
):
    ctx = context_config or ContextConfig()
    p7 = intelligence_config or IntelligenceConfig()
    ledger = StrategyReplayLedger("XAUUSD", config=ctx, intelligence_config=p7)
    start, end = (utc(evaluation[k]) for k in ("start", "end"))
    out = []
    for row in m1:
        at = utc(row["timestamp"]) + timedelta(minutes=1)
        if at > end:
            break
        report = context_at(
            "XAUUSD",
            m1,
            m5,
            at,
            config=ctx,
            intelligence_config=p7,
            calendar=calendar,
            provenance=provenance,
            observed_finality=finality,
        )
        entry = ledger.record(report)
        if at <= start:
            continue  # Preserve warm-up state; no warm-up paper position.
        records = [
            r for r in entry["evaluations"] if r["strategy_id"] == spec.strategy_id
        ]
        valid = report.data_quality["valid"]
        reasons = []
        side = "WAIT"
        stop = None
        key = None
        qualified = (
            [r for r in records if r["snapshot_outcome"] == "QUALIFIES"]
            if valid
            else []
        )
        retired_ids = tuple(
            sorted(
                digest([feed_id, spec.sha256, event["setup_id"]])
                for event in entry["lifecycle_events"]
                if event["event"] in ("EXPIRED", "INVALIDATED_QUALIFIED_SETUP")
                and ledger.setups[event["setup_id"]]["strategy_id"] == spec.strategy_id
            )
        )
        invalid = bool(retired_ids)
        m5_state = report.context.get("m5_structure", "UNKNOWN")
        regime = (
            "TREND_UP"
            if m5_state == "BULLISH"
            else (
                "TREND_DOWN"
                if m5_state == "BEARISH"
                else (
                    "RANGE"
                    if m5_state == "RANGING"
                    else "TRANSITION" if m5_state == "TRANSITIONAL" else "UNKNOWN"
                )
            )
        )
        volatility = (
            report.interpretations.get("frames", {}).get("M1", {}).get("volatility", {})
        )
        if not valid:
            reasons.append("EXISTING_DATA_QUALITY_GATE_BLOCKED")
        elif len(qualified) != 1:
            reasons.append("NO_UNIQUE_QUALIFYING_DIRECTION")
        else:
            result = qualified[0]
            direction = result["direction"]
            sources = report.interpretations["source_registry"]
            rel = volatility.get("relative_volatility")
            if rel is None or not dec(spec.minimum_relative_volatility) <= Decimal(
                str(rel)
            ) <= dec(spec.maximum_relative_volatility):
                reasons.append("RELATIVE_VOLATILITY_FILTER")
            else:
                pivots = [
                    (utc(s["available_at"]), key_, Decimal(str(s["price"])))
                    for key_, s in sources.items()
                    if s["kind"] == "CONFIRMED_PIVOT"
                    and s["timeframe"] == "M1"
                    and s["pivot_kind"] == ("LOW" if direction == "BULLISH" else "HIGH")
                    and utc(s["available_at"]) <= at
                ]
                if not pivots:
                    reasons.append("CONFIRMED_STOP_PIVOT_UNAVAILABLE")
                else:
                    extreme = max(pivots)[2]
                    if spec.strategy_id == "SWEEP_M1_STRUCTURE_CHANGE":
                        sweep_id = result["anchor"]["references"][0]
                        events = report.interpretations["frames"]["M1"][
                            "liquidity_events"
                        ]
                        sweep = next((e for e in events if e.id == sweep_id), None)
                        if sweep is None:
                            reasons.append("CANONICAL_SWEEP_UNAVAILABLE")
                        else:
                            extreme = (
                                min(extreme, Decimal(str(sweep.level)))
                                if direction == "BULLISH"
                                else max(extreme, Decimal(str(sweep.level)))
                            )
                    if not reasons:
                        tick = dec(costs.tick_size)
                        value = (
                            extreme - tick * spec.stop_buffer_ticks
                            if direction == "BULLISH"
                            else extreme + tick * spec.stop_buffer_ticks
                        )
                        value = (value / tick).to_integral_value(
                            rounding=(
                                ROUND_FLOOR if direction == "BULLISH" else ROUND_CEILING
                            )
                        ) * tick
                        if value <= 0:
                            reasons.append("STOP_GEOMETRY_INVALID")
                        else:
                            side = "BUY" if direction == "BULLISH" else "SELL"
                            stop = str(value)
                            key = digest([feed_id, spec.sha256, result["setup_id"]])
        if invalid:
            side = "WAIT"
            stop = None
            key = None
            reasons.append("ORIGINAL_ANCHOR_INVALIDATED_OR_RETIRED")
        out.append(
            Decision(
                at.isoformat(),
                key,
                side,
                stop,
                invalid,
                valid,
                regime,
                volatility.get("regime", "UNKNOWN"),
                tuple(reasons),
                retired_ids,
            )
        )
    return tuple(out), dict(
        context_sha256=ctx.digest,
        intelligence_sha256=p7.digest,
        source_strategy_registry_sha256=ledger.hashes["registry"],
        source_lifecycle_policy_sha256=ledger.hashes["lifecycle_policy"],
        warmup_decisions=sum(utc(e["timestamp_utc"]) <= start for e in ledger.entries),
    )
