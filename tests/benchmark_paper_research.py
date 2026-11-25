"""Prebuilt invented-source E4 component costs; excludes MT5, network and live services."""

import json
import platform
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_fixtures import setup, later, open_position
from iat.intelligence.capital_intelligence import assess_capital, capital_arithmetic
from iat.intelligence.paper_contracts import quote_fill


def measure(fn):
    tracemalloc.start()
    start = time.perf_counter()
    r = fn()
    ms = (time.perf_counter() - start) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return dict(milliseconds=round(ms, 3), peak_traced_bytes=peak), r


def benchmark():
    k, a, b = setup()
    fill, _ = measure(
        lambda: quote_fill(
            k["quote"],
            tape=k["tape"],
            direction=k["risk"]["research_direction"],
            phase="ENTRY",
            decision_at=k["risk"]["evaluation_at_utc"],
            as_of=k["as_of"],
            policy=k["fill_policy"],
            costs=k["costs"],
        )
    )
    args = dict(
        balance="50",
        equity="50",
        fill_price="2100.1",
        stop_reference=k["risk"]["reference_geometry"]["invalidation_threshold"],
        direction=k["risk"]["research_direction"],
        specification=k["specification"],
        costs=k["costs"],
        policy=k["policy"],
    )
    arithmetic, _ = measure(lambda: capital_arithmetic(**args))
    repeats = []
    r = None
    for _ in range(3):
        m, r = measure(lambda: assess_capital(**k))
        repeats.append(m)
    opened, _ = measure(lambda: open_position(k))
    m = later(
        k,
        a,
        b,
        bid="2097",
        ask="2097.2",
        mutate=dict(open=2100, high=2100.2, low=2096, close=2097),
    )
    closed, _ = measure(lambda: k["account"].observe(**m))
    j = k["account"].journal()
    encoded = json.dumps(j, sort_keys=True, separators=(",", ":")).encode()
    return dict(
        python=platform.python_version(),
        platform=platform.system(),
        provenance="INVENTED_SYNTHETIC_ONLY",
        quote_fill=fill,
        capital_arithmetic=arithmetic,
        authenticated_capital_repeats=repeats,
        account_open=opened,
        source_bound_structural_close=closed,
        journal_bytes=len(encoded),
        journal_sha256=j["sha256"],
        limits=dict(
            max_quotes=k["tape"].max_quotes,
            max_events=k["account"].max_events,
            max_report_bytes=k["account"].max_report_bytes,
        ),
        limitations=[
            "PREBUILT_UPSTREAM_REPORTS_SOURCE_CONSTRUCTION_EXCLUDED",
            "TRACED_ALLOCATIONS_NOT_RSS",
            "NO_MT5_OR_WINDOWS_LATENCY_CLAIM",
            "NOT_MAXIMUM_DATASET_THROUGHPUT",
            "NOT_STRATEGY_PERFORMANCE",
        ],
    )


if __name__ == "__main__":
    print(json.dumps(benchmark(), sort_keys=True, indent=2))
