"""Generate explicitly synthetic worked E1 examples from independent OHLC."""

from entry_fixtures import snapshot
from iat.intelligence.entry_intelligence import EntryResearchSession


def examples():
    cases = {}
    worked = None
    for name, ns, options in (
        ("bullish", [23], {}),
        ("bearish", [23], {"mirror": True}),
        ("awaiting_confirmation", [22], {}),
        ("expired", list(range(22, 29)), {}),
        ("no_setup", [24], {}),
        ("blocked_live", [23], {"provenance": "VALIDATED_LIVE"}),
    ):
        session = EntryResearchSession()
        for n in ns:
            v, c, inputs = snapshot(n, **options)
            report = session.record(v, c, view_inputs=inputs)
        cases[name] = dict(
            report_sha256=report["sha256"],
            status=report["status"],
            research_states=report["research_states"],
            setup_count=len(report["plans"]),
            setup_ids=[p["setup_id"] for p in report["plans"]],
            reason_codes=report["reason_codes"],
        )
        if name == "bullish":
            worked = report["plans"][0]
    return dict(
        example_version=1,
        evidence="INDEPENDENT_INVENTED_OHLC_SYNTHETIC_ONLY",
        not_historical_validation=True,
        not_profitability_evidence=True,
        cases=cases,
        worked_bullish_plan=worked,
    )
