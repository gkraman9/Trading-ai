"""Offline, invented E4.6 examples. Never market data or profitability evidence."""

import json
from pathlib import Path
import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from time import perf_counter
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from protection_fixtures import (
    setup,
    open_position,
    quote,
    observe,
    stop_policy,
    liquidation_policy,
)
from paper_fixtures import policy, later
from iat.intelligence.protection_contracts import stop_gap_arithmetic
from iat.intelligence.strategy_replay import digest


def examples():
    cases = {}

    def save(name, k, result):
        cases[name] = dict(
            outcome=result,
            account=k["account"].snapshot(),
            metrics=k["account"].metrics(),
            journal_sha256=k["account"].journal()["sha256"],
        )

    for name, price in [("A_normal_stop", "2097.74"), ("B_adverse_gap", "2090.1")]:
        k, _, _ = setup()
        open_position(k)
        save(name, k, observe(k, quote(k, bid=price, ask=str(Decimal(price) + Decimal("0.2")))))
    for name, complete in [("C_delayed_fill", True), ("D_missing_fill", False)]:
        k, _, _ = setup()
        k["stop_policy"] = stop_policy(2000, False)
        open_position(k)
        observe(k, quote(k, bid="2097.7", ask="2097.9"))
        if complete:
            observe(k, quote(k, 3, bid="2097.6", ask="2097.8"))
            result = observe(k, quote(k, 4, bid="2097.5", ask="2097.7"))
        else:
            result = k["account"].review_cutoff(
                k["as_of"] + timedelta(seconds=10), end_of_input=True
            )
        save(name, k, result)
    for name, price in [("E_margin_warning", "2099.7"), ("F_stop_out", "2099.2")]:
        k, _, _ = setup()
        k["specification"] = replace(
            k["specification"],
            leverage="10",
            margin_call_equity_ratio="1.132",
            stop_out_equity_ratio="1.13",
        )
        open_position(k)
        save(name, k, observe(k, quote(k, bid=price, ask=str(Decimal(price) + Decimal("0.2")))))
    k, a, b = setup()
    open_position(k)
    result = k["account"].observe(
        **later(
            k,
            a,
            b,
            bid="2097.7",
            ask="2097.9",
            mutate=dict(open=2100, high=2100.2, low=2097, close=2097.1),
        )
    )
    save("G_structural_stop_conflict", k, result)
    for name, distinct in [
        ("H_liquidation_stop_conflict", True),
        ("I_negative_balance", False),
        ("J_exhaustion", False),
    ]:
        k, _, _ = setup()
        if distinct:
            k["liquidation_policy"] = liquidation_policy(1000, False)
        open_position(k)
        save(name, k, observe(k, quote(k, bid="1000", ask="1000.2")))
    k, _, _ = setup()
    k["specification"] = replace(k["specification"], contract_size="100")
    save("K_minimum_lot", k, open_position(k))
    account = None
    for n in range(3):
        k, _, _ = setup(offset=timedelta(minutes=10 * n))
        k["policy"] = policy(max_consecutive_losses=2)
        if account is not None:
            k["account"] = account
        result = open_position(k)
        if n < 2:
            observe(k, quote(k, bid="2097.74", ask="2097.94"))
        account = k["account"]
    save("L_repeated_loss_restriction", k, result)
    k, _, _ = setup()
    open_position(k)
    observe(k, quote(k, bid="2097.74", ask="2097.94"))
    account = k["account"]
    k, a, b = setup(offset=timedelta(minutes=10))
    k["account"] = account
    open_position(k)
    result = account.observe(
        **later(
            k,
            a,
            b,
            bid="2106.2",
            ask="2106.4",
            mutate=dict(open=2100, high=2106.3, low=2099.8, close=2106.2),
        )
    )
    save("M_recovery_preserves_drawdown", k, result)
    k, _, _ = setup()
    open_position(k)
    quote(k, 2)
    save("N_missing_interval", k, observe(k, quote(k, 3)))
    from iat.intelligence.paper_contracts import report

    return report(
        "IAT_E46_SYNTHETIC_EXAMPLES_V1",
        label="INVENTED_SYNTHETIC_NOT_MARKET_VALIDATION",
        cases=cases,
        isolated_gap_arithmetic=stop_gap_arithmetic(),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; select a new path")
    tracemalloc.start()
    start = perf_counter()
    result = examples()
    elapsed = perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            dict(
                cases=len(result["cases"]),
                sha256=result["sha256"],
                elapsed_seconds=elapsed,
                traced_peak_bytes=peak,
                report_bytes=args.output.stat().st_size,
                benchmark_scope="14 synthetic source-authenticated scenarios; includes fixture construction, no MT5 or network",
            )
        )
    )
