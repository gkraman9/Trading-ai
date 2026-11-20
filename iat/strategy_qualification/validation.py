"""Predeclared disjoint IS/OOS windows and fixed sensitivity runs, never tuning."""

from dataclasses import replace
from decimal import Decimal
from iat.replay_dataset import utc
from iat.strategy_qualification.backtest import _simulate, dec
from iat.strategy_qualification.metrics import metrics
from iat.intelligence.strategy_replay import digest


def validate_plan(plan):
    if (
        set(plan)
        != {
            "version",
            "registered_protocol_sha256",
            "in_sample",
            "out_of_sample",
            "walk_forward",
        }
        or type(plan["version"]) is not int
        or plan["version"] != 1
    ):
        raise ValueError("VALIDATION_PLAN_INVALID")
    from iat.strategy_qualification.specs import PROTOCOL_SHA256

    if plan["registered_protocol_sha256"] != PROTOCOL_SHA256:
        raise ValueError("PREDECLARED_PROTOCOL_MISMATCH")

    def interval(v):
        if set(v) != {"start", "end"} or not utc(v["start"]) < utc(v["end"]):
            raise ValueError("SPLIT_INVALID")
        return utc(v["start"]), utc(v["end"])

    a, b = interval(plan["in_sample"]), interval(plan["out_of_sample"])
    if a[1] > b[0]:
        raise ValueError("IS_OOS_LEAKAGE")
    prior = None
    for fold in plan["walk_forward"]:
        if set(fold) != {"train", "test"}:
            raise ValueError("FOLD_INVALID")
        train, test = interval(fold["train"]), interval(fold["test"])
        if train[1] > test[0] or prior is not None and test[0] < prior:
            raise ValueError("WALK_FORWARD_LEAKAGE")
        prior = test[1]
    return True


def validation_runs(spec, costs, quotes, decisions, permissions, plan):
    validate_plan(plan)

    def window(interval, spec_=spec, costs_=costs):
        start, end = map(utc, (interval["start"], interval["end"]))
        qs = [q for q in quotes if start <= utc(q.timestamp) <= end]
        ds = [d for d in decisions if start < utc(d.timestamp) <= end]
        run = _simulate(
            spec_, costs_, qs, ds, permissions=permissions, cutoff=interval["end"]
        )
        return dict(
            run_sha256=run["sha256"],
            metrics=metrics(run),
            unresolved_reasons=run["unresolved_reasons"],
        )

    report = dict(
        plan_sha256=digest(plan),
        scope="PREDECLARED_FIXED_POLICY_NO_PARAMETER_SELECTION",
        in_sample=window(plan["in_sample"]),
        out_of_sample=window(plan["out_of_sample"]),
        walk_forward=[
            dict(train=window(f["train"]), test=window(f["test"]))
            for f in plan["walk_forward"]
        ],
        sensitivity=[],
    )
    # All perturbations are reported; no best parameter is selected from OOS.
    from iat.strategy_qualification.specs import PROTOCOL

    for multiplier in PROTOCOL["robustness_cost_multipliers"]:
        m = Decimal(multiplier)
        changed = replace(
            costs,
            commission_per_side_per_lot=str(dec(costs.commission_per_side_per_lot) * m),
            fee_per_side_per_lot=str(dec(costs.fee_per_side_per_lot) * m),
            slippage_ticks=int(
                (Decimal(costs.slippage_ticks) * m).to_integral_value(
                    rounding="ROUND_CEILING"
                )
            ),
        )
        report["sensitivity"].append(
            dict(
                kind="COSTS",
                value=multiplier,
                result=window(plan["out_of_sample"], costs_=changed),
            )
        )
    for value in PROTOCOL["spread_stress_multipliers"]:
        report["sensitivity"].append(
            dict(
                kind="SPREAD_COST_MODEL_NOT_OBSERVED_QUOTES",
                value=value,
                result=window(
                    plan["out_of_sample"],
                    costs_=replace(costs, spread_stress_multiplier=value),
                ),
            )
        )
    for value in PROTOCOL["reward_risk_sensitivity"]:
        report["sensitivity"].append(
            dict(
                kind="REWARD_RISK",
                value=value,
                result=window(
                    plan["out_of_sample"], spec_=replace(spec, reward_risk=value)
                ),
            )
        )
    for value in PROTOCOL["hold_minutes_sensitivity"]:
        report["sensitivity"].append(
            dict(
                kind="HOLD_MINUTES",
                value=value,
                result=window(
                    plan["out_of_sample"], spec_=replace(spec, max_hold_minutes=value)
                ),
            )
        )
    report["sha256"] = digest(report)
    return report
