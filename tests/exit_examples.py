"""Frozen examples from invented OHLC only, not market/fill validation."""

from exit_fixtures import snapshot, fixture
from iat.intelligence.entry_intelligence import EntryResearchSession
from iat.intelligence.exit_intelligence import ExitResearchSession


def examples():
    cases = {}
    worked = None
    for name, mirror in (
        ("bullish_target", False),
        ("bearish_target", True),
        ("invalidation", False),
        ("ambiguous", False),
        ("expiry", False),
    ):
        a, b = fixture(mirror)
        source = EntryResearchSession()
        v, c, i = snapshot(one=a, five=b)
        original = source.record(v, c, view_inputs=i)
        sid = next(
            p["setup_id"]
            for p in original["plans"]
            if p["research_state"] == "RESEARCH_QUALIFIED"
        )
        e = ExitResearchSession(original, sid, entry_source=source)
        if name == "bullish_target":
            a[23]["high"] = 5753.3
        elif name == "bearish_target":
            a[23]["low"] = 5746.7
        elif name == "invalidation":
            a[23].update(high=5750.2, low=5745.8, close=5746)
        elif name == "ambiguous":
            a[23].update(high=5753.6, low=5745.8, close=5746)
        for n in range(24, 29) if name == "expiry" else (24,):
            v, c, i = snapshot(n, one=a, five=b)
            report = e.record(v, c, view_inputs=i)
        cases[name] = dict(
            report_sha256=report["sha256"],
            analytical_states=report["analytical_states"],
            observation_count=len(report["observations"]),
            ambiguity=report["ambiguity"]["status"],
            original_setup_id=report["original"]["setup_id"],
        )
        if name == "ambiguous":
            worked = {
                k: report[k]
                for k in (
                    "original",
                    "frozen_target",
                    "frozen_invalidation",
                    "observations",
                    "ambiguity",
                )
            }
    return dict(
        example_version=1,
        evidence="INVENTED_OHLC_SYNTHETIC_ONLY_NO_FILLS",
        cases=cases,
        worked_ambiguity=worked,
    )
