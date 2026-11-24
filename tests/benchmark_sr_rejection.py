"""Small synthetic research benchmark; not profitability or live-latency evidence.

Run: python tests/benchmark_sr_rejection.py --iterations 3
"""

import argparse
import gc
from hashlib import sha256
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter_ns
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_sr_rejection import snapshot
from iat.intelligence.sr_rejection import (
    evaluate_sr_rejection,
    SRRejectionLedger,
    validate_sr_log,
)


def measure(name, call, iterations):
    call()
    times = []
    peaks = []
    hashes = []
    for _ in range(iterations):
        gc.collect()
        tracemalloc.start()
        start = perf_counter_ns()
        r = call()
        times.append((perf_counter_ns() - start) / 1e6)
        peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
        hashes.append(r["sha256"])
    return dict(
        workload=name,
        iterations=iterations,
        median_ms=statistics.median(times),
        peak_traced_bytes=max(peaks),
        identical_hashes=len(set(hashes)) == 1,
        sha256=hashes[0],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 20:
        parser.error("iterations must be in [1,20]")
    view, context, inputs = snapshot()
    stream = [snapshot(n=n) for n in range(22, 30)]

    def run():
        ledger = SRRejectionLedger()
        for v, c, i in stream:
            ledger.record(v, c, view_inputs=i)
        r = ledger.to_dict()
        validate_sr_log(r)
        return r

    data = dict(
        kind="SYNTHETIC_SR_RESEARCH_BENCHMARK",
        python=platform.python_version(),
        platform=platform.system(),
        method="Prebuilt independent synthetic contexts/views; one excluded warm-up; perf_counter_ns and tracemalloc; GC before each iteration; snapshot source validation remains enabled; lifecycle benchmark includes full log validation.",
        source_sha256=sha256(
            (
                Path(__file__).resolve().parents[1] / "iat/intelligence/sr_rejection.py"
            ).read_bytes()
        ).hexdigest(),
        results=[
            measure(
                "source_bound_snapshot",
                lambda: evaluate_sr_rejection(view, context, view_inputs=inputs),
                args.iterations,
            ),
            measure("eight_close_lifecycle_and_validation", run, args.iterations),
        ],
        signal="WAIT",
        execution_allowed=False,
        historical_validation="PENDING",
        historical_comparisons="NOT_RUN",
    )
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
