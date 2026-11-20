"""Explicit SYNTHETIC examples only; no terminal/network/strategy qualification."""

import argparse, json, sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.live_shadow.feed import observed_tick
from iat.live_shadow.policy import configuration
from iat.live_shadow.store import Journal
from iat.live_shadow import engine, LABEL
from iat.strategy_qualification.backtest import Costs
from iat.strategy_qualification.specs import specifications
from iat.intelligence.strategy_replay import digest

T = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)


def run(directory):
    root = Path(directory)
    if root.resolve().is_relative_to(Path(__file__).resolve().parents[1]) or any(
        p.is_symlink() for p in (root, *root.parents)
    ):
        raise ValueError("Private new directory required")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
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
        evidence_sha256="a" * 64,
        known_at=(T - timedelta(days=1)).isoformat(),
        currency_quantum=".01",
        money_rounding="ROUND_HALF_EVEN",
    )
    config = dict(
        version=1,
        strategy_id=specifications()[0].strategy_id,
        costs=asdict(costs),
        mode="UNQUALIFIED_SHADOW_RESEARCH",
        label=LABEL,
    )
    symbol = dict(
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
    )
    identity = dict(
        broker="EXNESS_COMPANY_LABEL_MATCH",
        symbol="XAUUSD",
        account_mode="DEMO",
        assurance="OBSERVED_COMPANY_LABEL_NOT_AUTHENTICATED_ACCOUNT_BINDING",
        trading_permissions_disabled=True,
    )

    def quote(second, bid=99.9, ask=100.0):
        at = T + timedelta(seconds=second)
        return observed_tick(
            dict(
                time=int(at.timestamp()),
                time_msc=int(at.timestamp() * 1000),
                bid=bid,
                ask=ask,
            ),
            at,
        )

    session = dict(
        phase="UNKNOWN",
        calendar_status="MISSING",
        quote_available=None,
        new_positions=None,
        close_positions=None,
        operational_eligible=False,
    )
    examples = []
    for side in ("BUY", "SELL"):
        decision = dict(
            candidate=side + "_CANDIDATE",
            side=side,
            stop="99" if side == "BUY" else "101",
            setup_id="SYNTHETIC:" + side,
            available_at=T.isoformat(),
            invalidated_setup_ids=[],
            segmentation=dict(
                strategy_version=specifications()[0].sha256,
                session="UNKNOWN",
                calendar_status="MISSING",
                alignment="SYNTHETIC",
                regime="UNKNOWN",
            ),
        )
        decision["id"] = digest(decision)
        state, _ = engine.decision_event(engine.initial(), decision)
        state, _ = engine.quote_event(
            state,
            quote(1, 99.9, 100.0) if side == "BUY" else quote(1, 100.0, 100.1),
            config,
            session,
            symbol,
        )
        state, effects = engine.quote_event(
            state,
            quote(2, 102.0, 102.1) if side == "BUY" else quote(2, 97.9, 98.0),
            config,
            session,
            symbol,
        )
        examples.append(
            dict(
                fixture="SYNTHETIC_DECISION_QUOTE_CONTRACT_NOT_OHLC_STRATEGY_VALIDATION",
                side=side,
                exit=next(e["trade"] for e in effects if e["kind"] == "EXIT"),
                summary=engine.summary(state),
            )
        )
    journal = Journal(
        root / "journal", configuration(), create=True, source_kind="SYNTHETIC_FIXTURE"
    )
    candles = {
        tf: [
            dict(
                timestamp=(T - timedelta(minutes=period * (count - i))).isoformat(),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
            )
            for i in range(count)
        ]
        for tf, period, count in [("M1", 1, 100), ("M5", 5, 40)]
    }
    for second in (0, 1, 2):
        at = T + timedelta(seconds=second)
        q = quote(second)
        packet = dict(
            received_at=at.isoformat(),
            quote=q,
            capture=dict(
                start=(at - timedelta(seconds=1)).isoformat(),
                end=at.isoformat(),
                status="OBSERVED_RANGE",
                reason_codes=[],
                ticks=[q],
                assurance="TERMINAL_RETURNED_OBSERVATIONS_NOT_PROVIDER_CAPTURE_COMPLETENESS_PROOF",
            ),
            candles=candles,
            raw_candles={},
            identity=identity,
            symbol_specification=symbol,
            errors=[],
            observer_snapshot_id="a" * 64,
            observer_reason_codes=[],
        )
        journal.record(packet)
    report = dict(
        example_version=1,
        source_kind="SYNTHETIC_FIXTURE",
        label=LABEL,
        scope="SOFTWARE_CONTRACTS_NOT_MARKET_OR_PROFITABILITY_EVIDENCE",
        engine_contracts=examples,
        journal_replay=journal.verify(replay=True),
        signal="WAIT",
        execution_allowed=False,
        orders_requested=0,
        exness="BLOCKED",
        historical_validation="PENDING",
        historical_comparisons="NOT_RUN",
    )
    report["sha256"] = digest(report)
    with (root / "SYNTHETIC-example.json").open(
        "x", encoding="utf-8", newline="\n"
    ) as f:
        json.dump(report, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-directory", required=True)
    a = p.parse_args(argv)
    try:
        r = run(a.output_directory)
        print(
            "SYNTHETIC ONLY; replay "
            + r["journal_replay"]["status"]
            + "; broker orders 0."
        )
        return 0
    except Exception:
        print(
            "BLOCKED: use a NEW private output directory; no existing artifact is overwritten."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
