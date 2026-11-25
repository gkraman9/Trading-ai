"""Invented E4 accounting examples only; no broker data or strategy performance."""

import json
import sys
from pathlib import Path
from dataclasses import replace
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_fixtures import setup, later, open_position, specification, costs, policy
from iat.intelligence.capital_intelligence import capital_arithmetic, assess_capital
from iat.intelligence.paper_contracts import report


def examples():
    args = dict(
        balance="50",
        equity="50",
        fill_price="2100",
        direction="BULLISH",
        specification=specification("SYNTHETIC_XAUUSD"),
    )
    a = capital_arithmetic(
        **args, stop_reference="2098", costs=costs(), policy=policy()
    )
    b = capital_arithmetic(
        **args, stop_reference="2099", costs=costs(), policy=policy("0.02")
    )
    expensive = capital_arithmetic(
        **args,
        stop_reference="2099",
        costs=replace(costs(), commission_per_lot_side="1"),
        policy=policy("0.02")
    )
    k, one, five = setup()
    k["specification"] = replace(k["specification"], min_lot="0.1", volume_step="0.1")
    opened = open_position(k)
    observation = later(
        k,
        one,
        five,
        bid="2090.1",
        ask="2090.3",
        mutate=dict(open=2100, high=2100.2, low=2096, close=2097),
    )
    closed = k["account"].observe(**observation)
    candidate, _, _ = setup(offset=timedelta(minutes=10))
    candidate["account"] = k["account"]
    next_budget = assess_capital(**candidate)["assessment"]["risk_budget"]
    return report(
        "IAT_E4_SYNTHETIC_EXAMPLES_V1",
        examples=dict(
            A_before_costs_min_lot_rejection=a,
            B_no_remaining_budget=b,
            B_with_declared_costs_rejection=expensive,
            C_source_bound_gap_loss=dict(
                starting_balance="50",
                volume=opened["position"]["volume"],
                structural_reference=opened["position"]["structural_threshold"],
                estimated_risk=opened["position"]["estimated_risk"],
                entry_fill=opened["position"]["entry_fill"]["price"],
                exit_fill=closed["position"]["exit_fill"]["price"],
                realized_hypothetical_pnl=closed["position"]["net_hypothetical_pnl"],
                updated_balance=k["account"].snapshot()["balance"],
                next_one_percent_budget=next_budget,
                journal_sha256=k["account"].journal()["sha256"],
                cash_events=k["account"].snapshot()["cash_events"],
            ),
        ),
        limitations=[
            "ALL_PRICES_QUOTES_SPECS_COSTS_ARE_INVENTED",
            "NOT_EXNESS_SPECIFICATIONS",
            "NO_HISTORICAL_OR_PROFITABILITY_VALIDATION",
            "EXAMPLE_ARITHMETIC_CANNOT_ESTABLISH_ELIGIBILITY",
        ],
    )


if __name__ == "__main__":
    print(json.dumps(examples(), sort_keys=True, indent=2, allow_nan=False))
