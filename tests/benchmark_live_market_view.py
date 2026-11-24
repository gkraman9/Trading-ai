"""Offline SYNTHETIC benchmark; never imports/initializes the MT5 SDK."""

import json
from pathlib import Path
import sys
import tempfile
from datetime import timedelta
from time import perf_counter
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_live_market_view import SyntheticTerminal, NOW
from iat.live_data import ReadOnlyMarketData
from iat.live_observer import LiveObserver, ShadowLog


def benchmark():
    now = [NOW]
    with tempfile.TemporaryDirectory(prefix="iat SYNTHETIC benchmark ") as folder:
        provider = ReadOnlyMarketData(SyntheticTerminal(lambda: now[0]))
        observer = LiveObserver(
            provider, ShadowLog(Path(folder) / "private"), clock=lambda: now[0]
        )
        tracemalloc.start()

        def measure():
            start = perf_counter()
            snapshot = observer.step()
            assert snapshot["feed_status"] == "CONNECTED"
            view = observer.market_intelligence()
            assert (
                view["status"] == "DESCRIPTIVE_ONLY"
                and view["execution_allowed"] is False
            )
            return round((perf_counter() - start) * 1000, 3)

        first = measure()
        hits = []
        for i in range(8):
            now[0] += timedelta(seconds=1)
            hits.append(measure())
        now[0] = NOW + timedelta(minutes=1)
        new = measure()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert observer.analysis_computations == 2 and observer.analysis_cache_hits == 8
        assert len(observer._closed_cache["rows"]["M1"]) == 500
        return dict(
            evidence="SYNTHETIC_OFFLINE_ONLY",
            polls=10,
            first_ms=first,
            cached_ms=hits,
            new_closed_m1_ms=new,
            peak_traced_bytes=peak,
            current_traced_bytes=current,
            computations=observer.analysis_computations,
            cache_hits=observer.analysis_cache_hits,
            cache_entries=1,
            cache_m1_rows=500,
            cache_m5_rows=100,
            limitations="Tracemalloc adds overhead; not Windows/MT5/network latency or RSS.",
        )


if __name__ == "__main__":
    print(json.dumps(benchmark(), sort_keys=True, indent=2))
