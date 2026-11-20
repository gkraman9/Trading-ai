"""Reproducible SYNTHETIC comparison fixture; not AI, historical data or an edge claim."""

from pathlib import Path
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from copy import deepcopy
import json
from iat.live_shadow.store import Journal as SourceJournal
from iat.live_shadow.policy import configuration as source_configuration
from iat.live_shadow.feed import observed_tick
from iat.strategy_qualification.backtest import Costs
from iat.three_engine.config import validate_config, PROTOCOL
from iat.three_engine.evidence import build
from iat.three_engine.contracts import empty_response
from iat.three_engine.journal import SourceReader, ComparisonJournal
from iat.intelligence.strategy_replay import digest

T = datetime(2026, 11, 12, 12, 0, 10, tzinfo=timezone.utc)


def research_config():
    cost_hash = sha256(b"SYNTHETIC cost terms, not broker evidence.\n").hexdigest()
    account_hash = sha256(b"SYNTHETIC paper account, not broker data.\n").hexdigest()
    costs = Costs(
        initial_equity="10000",
        currency="USD",
        contract_size="100",
        tick_size=".01",
        minimum_stop_distance=".01",
        volume_min=".01",
        volume_step=".01",
        max_spread=".20",
        slippage_ticks=0,
        commission_per_side_per_lot="1",
        fee_per_side_per_lot="0",
        rollovers=(),
        evidence_sha256=cost_hash,
        known_at=(T - timedelta(days=1)).isoformat(),
        currency_quantum=".01",
        money_rounding="ROUND_HALF_EVEN",
    )
    return validate_config(
        dict(
            version=1,
            baseline_strategy_id="M5_TREND_M1_CONFIRMATION",
            costs=asdict(costs),
            account=dict(
                version=1,
                equity="10000",
                free_margin="10000",
                currency="USD",
                tick_value_per_lot="1",
                margin_per_lot={"BUY": "1000", "SELL": "1000"},
                declared_at=(T - timedelta(days=1)).isoformat(),
                evidence_sha256=account_hash,
                assurance="DECLARED_PAPER_ACCOUNT_NOT_BROKER_VERIFIED",
            ),
            budgets=dict(
                max_calls=20,
                max_tokens=10000000,
                max_cost_usd="10",
                input_usd_per_million="0",
                output_usd_per_million="0",
            ),
        )
    )


def packet(second, bid=99.9, ask=100.0):
    at = T + timedelta(seconds=second)
    quote = observed_tick(
        dict(
            time=int(at.timestamp()),
            time_msc=round(at.timestamp() * 1000),
            bid=bid,
            ask=ask,
        ),
        at,
    )
    end = T.replace(second=0)
    candles = {
        tf: [
            dict(
                timestamp=(end - timedelta(minutes=period * (count - i))).isoformat(),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
            )
            for i in range(count)
        ]
        for tf, period, count in [("M1", 1, 100), ("M5", 5, 40)]
    }
    return dict(
        received_at=at.isoformat(),
        quote=quote,
        capture=dict(
            start=(at - timedelta(seconds=1)).isoformat(),
            end=at.isoformat(),
            status="OBSERVED_RANGE",
            reason_codes=[],
            ticks=[quote],
            assurance="TERMINAL_RETURNED_OBSERVATIONS_NOT_PROVIDER_CAPTURE_COMPLETENESS_PROOF",
        ),
        candles=candles,
        raw_candles={},
        identity=dict(
            broker="EXNESS_COMPANY_LABEL_MATCH",
            symbol="XAUUSD",
            account_mode="DEMO",
            assurance="OBSERVED_COMPANY_LABEL_NOT_AUTHENTICATED_ACCOUNT_BINDING",
            trading_permissions_disabled=True,
        ),
        symbol_specification=dict(
            trade_contract_size=100.0,
            trade_tick_size=0.01,
            trade_stops_level=1,
            point=0.01,
            digits=2,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            currency_profit="USD",
            trade_calc_mode=0,
        ),
        errors=[],
        observer_snapshot_id="a" * 64,
        observer_reason_codes=[],
    )


def run(directory, *, prefix_records=3):
    root = Path(directory)
    if root.resolve().is_relative_to(Path(__file__).resolve().parents[2]) or any(
        p.is_symlink() for p in (root, *root.parents)
    ):
        raise ValueError("Private new example directory required")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    config = research_config()
    source = SourceJournal(
        root / "source",
        source_configuration(),
        create=True,
        source_kind="SYNTHETIC_FIXTURE",
    )
    p = packet(0)
    bundle = build(p, config, T.isoformat(), source_kind="SYNTHETIC_FIXTURE")
    raw = empty_response(bundle, "BUY")
    anchor = sorted(
        k
        for k, v in bundle["price_catalog"].items()
        if v["kind"] == "CLOSED_CANDLE_LOW"
    )[0]
    raw.update(
        stop_anchor_id=anchor,
        target_refs=["R2"],
        tp_allocations=["1"],
        supporting_evidence_ids=[anchor],
        market_reasoning=[
            dict(interpretation="BUYERS_CONTROL", evidence_id=anchor, role="SUPPORT")
        ],
    )
    stop = Decimal(bundle["price_catalog"][anchor]["price"]) - Decimal(".01")
    target = Decimal("100") + 2 * (Decimal("100") - stop)
    market = [p, packet(1), packet(2, float(target), float(target + Decimal(".1")))]
    for item in market[:prefix_records]:
        source.record(item)
    before = source.path.read_bytes()
    reader = SourceReader(source)
    j = ComparisonJournal(
        root / "comparison",
        config,
        source.binding_sha,
        create=True,
        source_kind="SYNTHETIC_FIXTURE",
        models={k: "SYNTHETIC_TEST_PROVIDER" for k in ("B_HYBRID", "C_AI_LED")},
    )
    for record in reader.records(0):
        record["consumed_at"] = record["packet"]["received_at"]
        j.record(dict(kind="SOURCE", data=record))
        if record["seq"] == 1:
            j.record(
                dict(
                    kind="POINT",
                    data=dict(
                        bundle=bundle,
                        available_at=(T + timedelta(seconds=0.1)).isoformat(),
                    ),
                )
            )
            for engine in ("B_HYBRID", "C_AI_LED"):
                key = digest(
                    [
                        engine,
                        bundle["id"],
                        "SYNTHETIC_TEST_PROVIDER",
                        PROTOCOL["prompt_version"],
                    ]
                )
                j.record(
                    dict(
                        kind="REQUEST",
                        data=dict(
                            request_id=key,
                            engine=engine,
                            bundle_id=bundle["id"],
                            model="SYNTHETIC_TEST_PROVIDER",
                            at=(T + timedelta(seconds=0.2)).isoformat(),
                            enabled=True,
                            actual_ai=False,
                            blocked_reason=None,
                        ),
                    )
                )
                if j.state()["requests"][key]["status"] == "PENDING":
                    j.record(
                        dict(
                            kind="RESULT",
                            data=dict(
                                request_id=key,
                                raw=raw,
                                response_at=(T + timedelta(seconds=0.5)).isoformat(),
                                available_at=(T + timedelta(seconds=0.5)).isoformat(),
                                code=None,
                            ),
                        )
                    )
    result = j.verify(replay=True)
    if before != source.path.read_bytes():
        raise ValueError("SOURCE_CHANGED")
    with (root / "research-config.json").open("x", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, sort_keys=True, indent=2)
        f.write("\n")
    (root / "cost-evidence.txt").write_bytes(
        b"SYNTHETIC cost terms, not broker evidence.\n"
    )
    (root / "account-research-evidence.txt").write_bytes(
        b"SYNTHETIC paper account, not broker data.\n"
    )
    snapshot = j.snapshot()
    report = dict(
        example_version=1,
        source_kind="SYNTHETIC_FIXTURE",
        actual_ai_calls=0,
        scope="DETERMINISTIC_SOFTWARE_FIXTURE_NOT_AI_PERFORMANCE_OR_PROFITABILITY",
        comparison_points=snapshot["comparison_points"],
        source_unchanged=True,
        verification=result,
        engines={
            name: dict(
                decision=snapshot["proposals"][name]["decision"],
                metrics=snapshot["engines"][name]["metrics"],
            )
            for name in snapshot["engines"]
        },
        signal="WAIT",
        execution_allowed=False,
        orders_requested=0,
        exness="BLOCKED",
        stage_b_qualification="PENDING",
        stages_c_d="BLOCKED",
        historical_validation="PENDING",
        historical_comparisons="NOT_RUN",
        ai_improvement="UNMEASURED",
    )
    report["sha256"] = digest(report)
    with (root / "SYNTHETIC-comparison.json").open(
        "x", encoding="utf-8", newline="\n"
    ) as f:
        json.dump(report, f, sort_keys=True, indent=2)
        f.write("\n")
    return report, j
