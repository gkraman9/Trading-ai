"""SYNTHETIC prebuilt-input E1 benchmark, not terminal or market validation."""

import json
from pathlib import Path
import sys
from time import perf_counter
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entry_fixtures import snapshot
from iat.intelligence.entry_intelligence import (
    EntryResearchSession,
    validate_entry_report,
)
from iat.intelligence.market_view import validate_market_view_v3


def benchmark():
    view, context, inputs = snapshot()
    tracemalloc.start()
    start = perf_counter()
    validate_market_view_v3(view, context_report=context, **inputs)
    binding = round((perf_counter() - start) * 1000, 3)
    session = EntryResearchSession()
    start = perf_counter()
    report = session.record(view, context, view_inputs=inputs)
    elapsed = round((perf_counter() - start) * 1000, 3)
    assert report["research_states"] == ["RESEARCH_QUALIFIED"]
    repeats = []
    for i in range(3):
        start = perf_counter()
        same = session.record(view, context, view_inputs=inputs)
        repeats.append(round((perf_counter() - start) * 1000, 3))
        assert same == report
    assert validate_entry_report(report, source=session)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(session.sr_log()["entries"]) == 1 and len(session._produced) == 1
    return dict(
        evidence="SYNTHETIC_ONLY_PREBUILT_INPUTS",
        source_binding_validation_ms=binding,
        entry_evaluation_ms=elapsed,
        repeated_snapshot_ms=repeats,
        peak_traced_bytes=peak,
        current_traced_bytes=current,
        sr_snapshots=1,
        setup_count=len(report["plans"]),
        retained_entry_hashes=1,
        report_sha256=report["sha256"],
        limitations="Tracing adds overhead; excludes upstream context construction, RSS, Windows and MT5.",
    )


if __name__ == "__main__":
    print(json.dumps(benchmark(), sort_keys=True, indent=2))
