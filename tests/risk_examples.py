"""Separate illustrative arithmetic from authenticated invented-data E3 examples."""

from risk_fixtures import sources, snapshot, fixture
from iat.intelligence.risk_intelligence import (
    assess_risk,
    reference_geometry,
    RiskPolicy,
)


def examples():
    arithmetic = {}
    for name, args in (
        ("A_bullish", ("BULLISH", 2100, 2098.01, 2098.11, 0.01, 2106)),
        ("B_bearish", ("BEARISH", 2100, 2101.89, 2101.99, 0.01, 2094)),
    ):
        arithmetic[name] = reference_geometry(*args)
    try:
        reference_geometry("BULLISH", 2097, 2098, 2098.1, 0, 2106)
    except ValueError as exc:
        arithmetic["D_invalid"] = dict(scope="ARITHMETIC_ONLY", reason_code=str(exc))
    cases = {}
    for name, mirror in (
        ("bullish_bound", False),
        ("bearish_bound", True),
        ("C_missing_target", False),
        ("E_ambiguous", False),
        ("F_missing_costs", False),
    ):
        a, b = fixture(mirror)
        if name == "C_missing_target":
            a[34].update(close=2107, high=2107.2)
        s, o, e, oe, a, b = sources(one=a, five=b)
        if name == "E_ambiguous":
            a[35].update(high=2106.5, low=2097, close=2097.1)
        v, c, i = snapshot(36, one=a, five=b)
        current = e.record(v, c, view_inputs=i)
        r = assess_risk(
            o,
            oe,
            current,
            entry_source=s,
            exit_source=e,
            as_of=c.analysis_at,
            context=c,
            view=v,
            view_inputs=i,
            policy=RiskPolicy(atr_timeframe="M1"),
        )
        assert r["source_eligibility"] == "VALID"
        cases[name] = {
            k: r[k]
            for k in (
                "sha256",
                "source_eligibility",
                "reference_geometry",
                "reference_price_basis",
                "states",
                "ambiguity",
                "hypothesis_lifecycle",
            )
        }
    return dict(
        example_version=1,
        evidence="INVENTED_OHLC_SYNTHETIC_ONLY_NOT_PROFITABILITY",
        illustrative_arithmetic_not_source_qualified=arithmetic,
        authenticated_synthetic_reports=cases,
    )
