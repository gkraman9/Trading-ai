"""Reproducible synthetic-only automated review benchmark, not a latency SLA.

Run: python tests/benchmark_market_view_audit.py --iterations 3
Optional baseline: --baseline-module <local source extracted from reviewed commit>
"""

import argparse
import gc
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import platform
from importlib.metadata import version
import statistics
import sys
from time import perf_counter_ns
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_market_view_audit import fixture
from iat.intelligence.market_view import build_market_view_v3, validate_market_view_v3
from iat.intelligence.strategy_replay import digest


def run_case(builder, name, context, intelligence, iterations):
    kwargs = dict(intelligence_report=intelligence) if intelligence else {}
    builder(context, **kwargs)  # explicit warm-up; excluded from measurements
    timings = []
    peaks = []
    retained = []
    hashes = []
    for _ in range(iterations):
        gc.collect()
        tracemalloc.start()
        begin = perf_counter_ns()
        result = builder(context, **kwargs)
        timings.append((perf_counter_ns() - begin) / 1e6)
        _, peak = tracemalloc.get_traced_memory()
        peaks.append(peak)
        hashes.append(result["sha256"])
        del result
        gc.collect()
        retained.append(tracemalloc.get_traced_memory()[0])
        tracemalloc.stop()
    return dict(
        workload=name,
        iterations=iterations,
        median_ms=statistics.median(timings),
        min_ms=min(timings),
        max_ms=max(timings),
        peak_traced_bytes=max(peaks),
        retained_after_gc_bytes=retained,
        identical_output_hashes=len(set(hashes)) == 1,
        input_context_sha256=digest(context.to_dict()),
        configuration_hashes=dict(
            context=context.configuration_sha256,
            intelligence=context.intelligence_configuration_sha256,
        ),
        output_sha256=hashes[0],
        source_count=len(context.interpretations.get("source_registry", {})),
        evidence_count=len(context.evidence),
        frame_counts={
            tf: f["candle_count"] for tf, f in context.observed_facts.items()
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--baseline-module", type=Path)
    parser.add_argument("--repeat-calls", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 20:
        parser.error("iterations must be in [1,20]")
    if not 1 <= args.repeat_calls <= 100:
        parser.error("repeat-calls must be in [1,100]")
    normal, intel, _, _ = fixture(count=60)
    large, large_intel, _, _ = fixture(count=180)
    missing, _, _, _ = fixture(count=4, missing="M5")
    cases = [
        ("normal", normal, None),
        ("larger_registry", large, None),
        ("normal_with_v1", normal, intel),
        ("larger_with_v1", large, large_intel),
        ("missing_frame_warmup", missing, None),
    ]
    builders = [("corrected", build_market_view_v3)]
    baseline_sha = None
    if args.baseline_module:
        # Only a local reviewed code file; never download/execute remote code.
        baseline_sha = sha256(args.baseline_module.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location(
            "reviewed_market_view_baseline", args.baseline_module
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        builders.insert(0, ("reviewed_baseline", module.build_market_view_v3))
    results = {
        label: [run_case(builder, *case, args.iterations) for case in cases]
        for label, builder in builders
    }
    # Retain no outputs across calls: an explicit GC sample after each call.
    gc.collect()
    tracemalloc.start()
    current = []
    for _ in range(args.repeat_calls):
        v = build_market_view_v3(normal)
        del v
        gc.collect()
        current.append(tracemalloc.get_traced_memory()[0])
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    v = build_market_view_v3(normal, intelligence_report=intel)
    start = perf_counter_ns()
    validate_market_view_v3(v, context_report=normal, intelligence_report=intel)
    bound_ms = (perf_counter_ns() - start) / 1e6
    print(
        json.dumps(
            dict(
                kind="AUTOMATED_SYNTHETIC_CONTRACT_BENCHMARK",
                python=platform.python_version(),
                implementation=platform.python_implementation(),
                platform=platform.system(),
                jsonschema_version=version("jsonschema"),
                schema_sha256=sha256(
                    (
                        Path(__file__).resolve().parents[1]
                        / "config/market-intelligence-v3.schema.json"
                    ).read_bytes()
                ).hexdigest(),
                corrected_source_sha256=sha256(
                    (
                        Path(__file__).resolve().parents[1]
                        / "iat/intelligence/market_view.py"
                    ).read_bytes()
                ).hexdigest(),
                fixture_source_sha256=sha256(
                    Path(__file__).with_name("test_market_view_audit.py").read_bytes()
                ).hexdigest(),
                baseline_source_sha256=baseline_sha,
                methodology="perf_counter_ns with tracemalloc enabled; inputs built before timing; one warm-up per case; GC before each measured iteration; no retained outputs or hidden market cache",
                results=results,
                repeated_calls=dict(
                    calls=args.repeat_calls,
                    retained_after_gc_bytes=current,
                    peak_traced_bytes=peak,
                ),
                bound_validation_ms_without_tracemalloc=bound_ms,
                signal="WAIT",
                execution_allowed=False,
                historical_validation="PENDING",
                historical_comparisons="NOT_RUN",
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
