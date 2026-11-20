"""Existing offline experimental rules on frozen live captures, never operational signals."""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta, datetime, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from iat.intelligence.context import context_at
from iat.intelligence.strategy_replay import StrategyReplayLedger, digest
from iat.intelligence.strategy_registry import registry
from iat.replay_dataset import utc
from iat.strategy_qualification.specs import specifications
from iat.strategy_qualification.backtest import dec
from iat.live_observer import _report_tree


def normalized(raw):
    out = {}
    for tf in ("M1", "M5"):
        rows = raw.get(tf, {}).get("rates", [])
        out[tf] = [
            dict(
                timestamp=datetime.fromtimestamp(r["time"], timezone.utc).isoformat(),
                **{k: r[k] for k in ("open", "high", "low", "close")}
            )
            for r in rows
        ]
    return out


def assess(candles, received_at, state, config, calendar=None):
    at = utc(received_at)
    last = candles["M1"][-1] if candles["M1"] else None
    cutoff = (
        utc(last["timestamp"]) + timedelta(minutes=1)
        if last
        else at.replace(second=0, microsecond=0)
    )
    previous = state.get("last_analysis_at")
    if previous and cutoff <= utc(previous):
        return state, None
    # HISTORICAL_RESEARCH is the existing offline API mode, not a claim of source qualification.
    # Never remove a supplied calendar. Missing calendar is unqualified descriptive research only.
    report = context_at(
        "XAUUSD",
        candles["M1"],
        candles["M5"],
        cutoff,
        provenance="HISTORICAL_RESEARCH",
        calendar=calendar,
        observed_finality=True,
    )
    ledger = StrategyReplayLedger("XAUUSD")
    ledger.setups = deepcopy(state.get("setups", {}))
    ledger.provenance = state.get("provenance")
    if previous:
        ledger.entries = [dict(timestamp_utc=previous)]
    entry = ledger.record(report)
    if len(ledger.setups) > 10000:
        raise ValueError("RESEARCH_STATE_CAPACITY_REACHED")
    new = dict(
        last_analysis_at=report.analysis_at,
        setups=ledger.setups,
        provenance=ledger.provenance,
        data_quality_valid=report.data_quality["valid"],
    )
    selected = config["strategy_id"]
    all_results = []
    by_strategy = []
    for spec in specifications():
        rows = [r for r in entry["evaluations"] if r["strategy_id"] == spec.strategy_id]
        qualifying = [r for r in rows if r["snapshot_outcome"] == "QUALIFIES"]
        reasons = sorted({c for r in rows for c in r["reason_codes"]})
        side = None
        stop = None
        key = None
        retired = sorted(
            digest(["LOCAL_MT5_FROZEN_CAPTURE", spec.sha256, e["setup_id"]])
            for e in entry["lifecycle_events"]
            if e["event"] in ("EXPIRED", "INVALIDATED_QUALIFIED_SETUP")
            and ledger.setups[e["setup_id"]]["strategy_id"] == spec.strategy_id
        )
        label = "WAIT" if report.data_quality["valid"] else "BLOCKED"
        if report.data_quality["valid"] and len(qualifying) == 1:
            result = qualifying[0]
            direction = result["direction"]
            frame = report.interpretations["frames"]["M1"]
            rel = frame["volatility"].get("relative_volatility")
            if rel is None or not dec(spec.minimum_relative_volatility) <= Decimal(
                str(rel)
            ) <= dec(spec.maximum_relative_volatility):
                reasons.append("RELATIVE_VOLATILITY_FILTER")
            elif config["costs"] is None:
                reasons.append("STOP_TICK_SIZE_NOT_CONFIGURED")
            else:
                pivots = [
                    (utc(v["available_at"]), k, Decimal(str(v["price"])))
                    for k, v in report.interpretations["source_registry"].items()
                    if v["kind"] == "CONFIRMED_PIVOT"
                    and v["timeframe"] == "M1"
                    and v["pivot_kind"] == ("LOW" if direction == "BULLISH" else "HIGH")
                    and utc(v["available_at"]) <= cutoff
                ]
                if not pivots:
                    reasons.append("CONFIRMED_STOP_PIVOT_REQUIRED")
                else:
                    extreme = max(pivots)[2]
                    if spec.strategy_id == "SWEEP_M1_STRUCTURE_CHANGE":
                        sweep = next(
                            (
                                v
                                for v in frame["liquidity_events"]
                                if v.id == result["anchor"]["references"][0]
                            ),
                            None,
                        )
                        if sweep is None:
                            reasons.append("CONFIRMED_SWEEP_REQUIRED")
                            extreme = None
                        else:
                            extreme = (
                                min(extreme, Decimal(str(sweep.level)))
                                if direction == "BULLISH"
                                else max(extreme, Decimal(str(sweep.level)))
                            )
                    if extreme is not None:
                        tick = dec(config["costs"]["tick_size"])
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
                        if value > 0:
                            side = "BUY" if direction == "BULLISH" else "SELL"
                            label = side + "_CANDIDATE"
                            stop = str(value)
                            key = digest(
                                [
                                    "LOCAL_MT5_FROZEN_CAPTURE",
                                    spec.sha256,
                                    result["setup_id"],
                                ]
                            )
                            reasons = [
                                "ORIGINAL_EXPERIMENTAL_PREDICATES_AND_FIXED_RESEARCH_POLICY_MET"
                            ]
        by_strategy.append(
            dict(
                strategy_id=spec.strategy_id,
                specification_sha256=spec.sha256,
                candidate=label,
                side=side,
                stop=stop,
                setup_id=key,
                invalidated_setup_ids=retired,
                reason_codes=sorted(set(reasons)),
                evaluations=rows,
            )
        )
    chosen = next((r for r in by_strategy if r["strategy_id"] == selected), None)
    context = report.context
    from iat.intelligence.adaptive import assess_adaptive

    adaptive = assess_adaptive(report)
    decision = dict(
        version=1,
        analysis_at=report.analysis_at,
        available_at=received_at,
        candidate=chosen["candidate"] if chosen else "BLOCKED",
        side=chosen["side"] if chosen else None,
        stop=chosen["stop"] if chosen else None,
        setup_id=chosen["setup_id"] if chosen else None,
        invalidated_setup_ids=chosen["invalidated_setup_ids"] if chosen else [],
        reason_codes=(
            chosen["reason_codes"] if chosen else ["SIMULATION_STRATEGY_NOT_CONFIGURED"]
        ),
        strategies=by_strategy,
        descriptive_direction=context.get("phase7_alignment", "UNKNOWN"),
        market_regime=adaptive["regime"],
        volatility=adaptive["volatility"],
        operational_signal="WAIT",
        execution_allowed=False,
        provenance="LOCAL_MT5_LIVE_FROZEN_CAPTURE_NOT_QUALIFIED",
        analytical_adapter="EXISTING_HISTORICAL_RESEARCH_API_MODE_NOT_SOURCE_QUALIFICATION",
        observations=_report_tree(
            dict(context=context, frames=report.interpretations.get("frames", {}))
        ),
        source_context_sha256=digest(_report_tree(asdict(report))),
        source_registry_sha256=registry()["sha256"],
        segmentation=dict(
            strategy_version=chosen["specification_sha256"] if chosen else None,
            alignment=context.get("phase7_alignment", "UNKNOWN"),
            regime=adaptive["regime"]["directional"],
            volatility=adaptive["volatility"]["overall"],
        ),
    )
    decision["id"] = digest(decision)
    return new, decision
