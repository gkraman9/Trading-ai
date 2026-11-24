"""Synthetic prebuilt-input E1/E2/E3 timing, arithmetic and resource-boundary harness."""

from pathlib import Path
import sys, json, tracemalloc
from time import perf_counter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from risk_fixtures import sources, snapshot
from iat.intelligence.risk_intelligence import (
    assess_risk,
    reference_geometry,
    _authenticate,
    RiskPolicy,
    LIMITS,
)
from iat.intelligence.exit_intelligence import ExitResearchSession
from iat.intelligence.market_view import validate_market_view_v3


def measure(fn):
    tracemalloc.start()
    started = perf_counter()
    out = fn()
    ms = round((perf_counter() - started) * 1000, 3)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return out, dict(
        milliseconds=ms, peak_traced_bytes=peak, current_traced_bytes=current
    )


def benchmark():
    source, original, exit, original_exit, a, b = sources()
    view, context, inputs = snapshot(36, one=a, five=b)
    current = exit.record(view, context, view_inputs=inputs)
    kw = dict(
        original_e1=original,
        original_e2=original_exit,
        current_e2=current,
        entry_source=source,
        exit_source=exit,
        as_of=context.analysis_at,
        context=context,
        view=view,
        view_inputs=inputs,
        policy=RiskPolicy(atr_timeframe="M1"),
    )
    before = (source.sr_log(), exit.report())

    def authenticate():
        result = _authenticate(
            original, original_exit, current, source, exit, context.analysis_at, None
        )
        validate_market_view_v3(view, context_report=context, **inputs)
        return result

    (plan, bar, at), auth = measure(authenticate)
    z = plan["structural_invalidation"]
    target = current["frozen_target"]
    _, arithmetic = measure(
        lambda: reference_geometry(
            plan["research_direction"],
            bar["close"],
            z["lower"],
            z["upper"],
            z["break_tolerance"],
            target["lower"],
        )
    )
    entry = source.fork_at(original)
    _, e1 = measure(lambda: entry.record(view, context, view_inputs=inputs))
    e2source = ExitResearchSession(original, plan["setup_id"], entry_source=source)
    _, e2 = measure(lambda: e2source.record(view, context, view_inputs=inputs))
    report, e3 = measure(lambda: assess_risk(**kw))
    assert report["source_eligibility"] == "VALID"
    repeated = []
    for n in range(3):
        same, stats = measure(lambda: assess_risk(**kw))
        assert same == report
        repeated.append(stats)
    size = len(
        json.dumps(
            report, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    )
    with patch.dict(LIMITS, max_report_bytes=size):
        assert assess_risk(**kw) == report
    with patch.dict(LIMITS, max_report_bytes=size - 1):
        assert assess_risk(**kw)["source_eligibility"] == "BLOCKED"
    assert before == (source.sr_log(), exit.report())
    return dict(
        evidence="INVENTED_SYNTHETIC_PREBUILT_INPUTS_NOT_MT5",
        source_authentication=auth,
        reference_calculation=arithmetic,
        e1_same_input=e1,
        e2_same_input=e2,
        e3_evaluation=e3,
        e3_repeated_evaluations=repeated,
        resource_boundary=dict(
            canonical_report_bytes=size,
            exact_limit="VALID",
            one_byte_below="BLOCKED",
            producer_state_unchanged=True,
        ),
        report_sha256=report["sha256"],
        limitations="Tracing overhead; source construction excluded; not RSS, maximum dataset throughput, Windows or MT5 performance.",
    )


if __name__ == "__main__":
    print(json.dumps(benchmark(), sort_keys=True, indent=2))
