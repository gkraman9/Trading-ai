"""SYNTHETIC prebuilt inputs: binding, E1/E2 latency and traced allocation comparison."""

from pathlib import Path
import json, sys, tracemalloc
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exit_fixtures import fixture, snapshot
from iat.intelligence.entry_intelligence import (
    EntryResearchSession,
    validate_entry_report,
)
from iat.intelligence.exit_intelligence import ExitResearchSession, validate_exit_report
from iat.intelligence.market_view import validate_market_view_v3


def measure(fn):
    tracemalloc.start()
    start = perf_counter()
    out = fn()
    ms = round((perf_counter() - start) * 1000, 3)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return out, dict(
        milliseconds=ms, peak_traced_bytes=peak, current_traced_bytes=current
    )


def benchmark():
    a, b = fixture()
    source = EntryResearchSession()
    v, c, i = snapshot(one=a, five=b)
    original = source.record(v, c, view_inputs=i)
    sid = original["plans"][0]["setup_id"]
    a[23]["high"] = 5753.3
    view, context, inputs = snapshot(24, one=a, five=b)

    def validate():
        validate_entry_report(original, source=source)
        validate_market_view_v3(view, context_report=context, **inputs)

    _, binding = measure(validate)
    entry = source.fork_at(original)
    _, baseline = measure(lambda: entry.record(view, context, view_inputs=inputs))
    exit, freeze = measure(
        lambda: ExitResearchSession(original, sid, entry_source=source)
    )
    report, first = measure(lambda: exit.record(view, context, view_inputs=inputs))
    repeated = []
    for n in range(3):
        same, stats = measure(lambda: exit.record(view, context, view_inputs=inputs))
        repeated.append(stats)
        assert same == report
    assert validate_exit_report(report, source=exit)
    assert len(report["observations"]) == 1 and len(exit._produced) == 2
    return dict(
        evidence="INVENTED_OHLC_SYNTHETIC_ONLY",
        binding_validation=binding,
        e1_same_current_input=baseline,
        e2_freeze_original=freeze,
        e2_current_evaluation=first,
        e2_revalidated_duplicates=repeated,
        event_count=1,
        produced_report_hashes=2,
        report_sha256=report["sha256"],
        limitations="Prebuilt inputs; tracing overhead; not RSS, Windows, MT5 latency, fills or profitability.",
    )


if __name__ == "__main__":
    print(json.dumps(benchmark(), sort_keys=True, indent=2))
