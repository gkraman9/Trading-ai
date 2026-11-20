"""Explicit denominators and day-block uncertainty; no missing values become zero."""

from collections import defaultdict
from decimal import Decimal
from random import Random
from iat.strategy_qualification.specs import PROTOCOL
from iat.strategy_qualification.backtest import dec


def metrics(run):
    trades = run["trade_log"]
    n = len(trades)
    net = [dec(t["net_pnl"]) for t in trades]
    gross = [dec(t["gross_pnl"]) for t in trades]
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x < 0]
    profit = sum(wins, Decimal(0))
    loss = -sum(losses, Decimal(0))
    equity = [dec(e["data"]["equity"]) for e in run["events"] if e["kind"] == "MARK"]
    peak = None
    dd = Decimal(0)
    for value in equity:
        peak = value if peak is None else max(peak, value)
        if peak > 0:
            dd = max(dd, (peak - value) / peak)
    sequence = maximum = 0
    for value in net:
        sequence = sequence + 1 if value < 0 else 0
        maximum = max(maximum, sequence)
    days = defaultdict(list)
    regimes = defaultdict(list)
    volatility = defaultdict(list)
    sessions = defaultdict(list)
    for t in trades:
        days[t["exit_at"][:10]].append(dec(t["net_pnl"]))
        regimes[t["regime"]].append(dec(t["net_pnl"]))
        volatility[t["volatility"]].append(dec(t["net_pnl"]))
        sessions[
            t.get("entry_session_phase", "UNVERIFIED")
            + " / "
            + t.get("exit_session_phase", "UNVERIFIED")
        ].append(dec(t["net_pnl"]))

    def grouped(rows):
        return {
            k: dict(closed_trades=len(v), net_pnl=str(sum(v, Decimal(0))))
            for k, v in sorted(rows.items())
        }

    rr = [
        dec(t["gross_pnl"]) / dec(t["planned_risk"])
        for t in trades
        if dec(t["planned_risk"]) > 0
    ]
    result = dict(
        closed_trades=n,
        open_positions=1 if run["open_position"] else 0,
        resolved_trade_denominator=n,
        win_rate=str(Decimal(len(wins)) / n) if n else None,
        profit_factor=str(profit / loss) if loss else None,
        profit_factor_status=(
            "FINITE"
            if loss
            else "NO_LOSSES_DENOMINATOR" if profit else "NO_CLOSED_TRADES_OR_ZERO_PNL"
        ),
        expectancy=str(sum(net, Decimal(0)) / n) if n else None,
        gross_pnl=str(sum(gross, Decimal(0))) if n else None,
        net_pnl=str(sum(net, Decimal(0))) if n else None,
        average_win=str(profit / len(wins)) if wins else None,
        average_loss=str(-loss / len(losses)) if losses else None,
        average_realized_r=str(sum(rr) / len(rr)) if rr else None,
        maximum_drawdown_fraction=str(dd) if equity else None,
        max_consecutive_losses=maximum if n else None,
        daily=grouped(days),
        regimes=grouped(regimes),
        volatility=grouped(volatility),
        session_performance=grouped(sessions),
        session_reason="VERIFIED_PERMISSION_PHASES_NOT_INVENTED_GEOGRAPHIC_SESSIONS",
        confidence_interval=None,
        confidence_reason="INSUFFICIENT_INDEPENDENT_DAY_BLOCKS",
        unresolved_reasons=run["unresolved_reasons"],
    )
    if len(days) >= 30:
        rng = Random(PROTOCOL["bootstrap_seed"])
        blocks = list(days.values())
        means = []
        for _ in range(PROTOCOL["bootstrap_day_blocks"]):
            selected = [blocks[rng.randrange(len(blocks))] for _ in blocks]
            count = sum(map(len, selected))
            means.append(
                sum((sum(v, Decimal(0)) for v in selected), Decimal(0)) / count
            )
        means.sort()
        result.update(
            confidence_interval=dict(
                method="UTC_DAY_CLUSTER_BOOTSTRAP_RESEARCH_NOT_IID_PROOF",
                level="0.95",
                lower=str(means[int(len(means) * 0.025)]),
                upper=str(means[min(len(means) - 1, int(len(means) * 0.975))]),
                days=len(blocks),
                replicates=len(means),
            ),
            confidence_reason=None,
        )
    return result


def qualification_status(
    data_status,
    run=None,
    *,
    is_synthetic=False,
    validation=None,
    reproduction_review_path=None
):
    """Internal derivation from recomputed runs and file-bound independent reproduction.

    Public study entry accepts paths, never a desired status or approval boolean.
    Human identity/independence is attested, not cryptographically authenticated.
    """
    if (
        is_synthetic
        or run is not None
        and run.get("data_kind") != "HISTORICAL_RESEARCH_MODEL"
    ):
        return "EXPERIMENTAL", ["SYNTHETIC_CANNOT_QUALIFY"]
    if data_status != "HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED":
        return "DATA_NOT_QUALIFIED", ["QUALIFIED_DATA_REQUIRED"]
    if run is None:
        return "BACKTEST_INCONCLUSIVE", ["NO_COMPLETE_EXECUTION_EVIDENCE_RUN"]
    m = metrics(run)
    if (
        run["unresolved_reasons"]
        or m["closed_trades"] < PROTOCOL["min_closed_trades"]
        or len(m["daily"]) < PROTOCOL["min_distinct_utc_days"]
    ):
        return "BACKTEST_INCONCLUSIVE", ["INSUFFICIENT_RESOLVED_LONGITUDINAL_SAMPLE"]
    if (
        m["profit_factor"] is None
        or m["maximum_drawdown_fraction"] is None
        or m["confidence_interval"] is None
    ):
        return "BACKTEST_INCONCLUSIVE", [
            "PERFORMANCE_DENOMINATOR_OR_UNCERTAINTY_UNESTABLISHED"
        ]

    def passes(v):
        ci = v.get("confidence_interval")
        return (
            v.get("expectancy") is not None
            and dec(v["expectancy"]) > 0
            and v.get("profit_factor") is not None
            and dec(v["profit_factor"]) >= dec(PROTOCOL["minimum_profit_factor"])
            and v.get("maximum_drawdown_fraction") is not None
            and dec(v["maximum_drawdown_fraction"])
            <= dec(PROTOCOL["maximum_drawdown_fraction"])
            and ci is not None
            and dec(ci["lower"]) > 0
            and not v.get("unresolved_reasons")
        )

    if not passes(m):
        return "BACKTEST_FAILED", [
            "PREDECLARED_PERFORMANCE_OR_UNCERTAINTY_THRESHOLD_FAILED"
        ]
    if validation is None:
        return "BACKTEST_INCONCLUSIVE", ["OOS_AND_ROBUSTNESS_NOT_RUN"]
    oos = validation["out_of_sample"]["metrics"]
    if (
        oos["closed_trades"] < PROTOCOL["min_oos_trades"]
        or len(oos["daily"]) < PROTOCOL["min_oos_days"]
        or len(validation["walk_forward"]) < PROTOCOL["min_walk_forward_folds"]
    ):
        return "BACKTEST_INCONCLUSIVE", ["OOS_OR_WALK_FORWARD_SAMPLE_INSUFFICIENT"]
    if not passes(oos) or any(
        not passes(f["test"]["metrics"])
        or f["test"]["metrics"]["closed_trades"] < PROTOCOL["min_trades_per_fold"]
        for f in validation["walk_forward"]
    ):
        return "BACKTEST_FAILED", ["OOS_OR_WALK_FORWARD_THRESHOLD_FAILED"]
    if not validation["sensitivity"] or any(
        r["result"]["metrics"]["expectancy"] is None
        or dec(r["result"]["metrics"]["expectancy"]) <= 0
        or r["result"]["unresolved_reasons"]
        for r in validation["sensitivity"]
    ):
        return "BACKTEST_FAILED", ["COST_OR_PARAMETER_ROBUSTNESS_FAILED"]
    if reproduction_review_path is None:
        return "BACKTEST_INCONCLUSIVE", ["INDEPENDENT_BACKTEST_REPRODUCTION_REQUIRED"]
    try:
        from pathlib import Path
        from hashlib import sha256
        from iat.replay_dataset import read_bytes, strict_json, local_file, utc
        from iat.intelligence.strategy_replay import digest

        path = Path(reproduction_review_path)
        review = strict_json(read_bytes(path))
        if (
            set(review)
            != {
                "version",
                "preparer_code",
                "reviewer_code",
                "reviewed_at_utc",
                "run",
                "validation",
            }
            or type(review["version"]) is not int
            or review["version"] != 1
        ):
            raise ValueError()
        if (
            not all(
                isinstance(review[k], str) and review[k]
                for k in ("preparer_code", "reviewer_code")
            )
            or review["preparer_code"] == review["reviewer_code"]
        ):
            raise ValueError()
        utc(review["reviewed_at_utc"])
        for key, expected in (("run", run), ("validation", validation)):
            item = review[key]
            if set(item) != {"file", "sha256"}:
                raise ValueError()
            raw = read_bytes(local_file(path.parent, item["file"]))
            if (
                sha256(raw).hexdigest() != item["sha256"]
                or strict_json(raw) != expected
            ):
                raise ValueError()
        return "BACKTEST_QUALIFIED", [
            "PREDECLARED_THRESHOLDS_AND_FILE_BOUND_REPRODUCTION_PASSED_NOT_EXECUTION_AUTHORIZATION"
        ]
    except Exception:
        return "BACKTEST_INCONCLUSIVE", ["INDEPENDENT_BACKTEST_REPRODUCTION_INVALID"]


QUALIFICATION_STATES = (
    "EXPERIMENTAL",
    "DATA_NOT_QUALIFIED",
    "BACKTEST_INCONCLUSIVE",
    "BACKTEST_FAILED",
    "BACKTEST_QUALIFIED",
)
