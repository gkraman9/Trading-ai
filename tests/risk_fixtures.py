"""Independently invented risk fixtures; not real XAUUSD or native-feed evidence."""

from datetime import datetime, timedelta, timezone
from iat.intelligence.context import context_at
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.market_view import build_market_view_v3
from iat.intelligence.entry_intelligence import EntryResearchSession
from iat.intelligence.exit_intelligence import ExitResearchSession, ExitPolicy

START = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)
CONFIG = ContextConfig()
INTELLIGENCE = IntelligenceConfig(left_strength=1, right_strength=1)
SYMBOL = "SYNTHETIC_E3_XAUUSD"


def fixture(mirror=False):
    def bars(prices, step, start):
        return [
            dict(
                timestamp=(start + timedelta(minutes=i * step)).isoformat(),
                open=p,
                high=p + 0.2,
                low=p - 0.2,
                close=p,
            )
            for i, p in enumerate(prices)
        ]

    a = bars([2100, 2106, 2101, 2098] * 8, 1, START)
    a += [
        dict(timestamp=(START + timedelta(minutes=i)).isoformat(), **r)
        for i, r in (
            (32, dict(open=2100, high=2100.2, low=2099.8, close=2100)),
            (33, dict(open=2097.9, high=2098.1, low=2097.6, close=2097.8)),
            (34, dict(open=2098.1, high=2100.2, low=2098, close=2100)),
        )
    ]
    a += bars([2100] * 20, 1, START + timedelta(minutes=35))
    b = bars([2100, 2106, 2101, 2098] * 20, 5, START - timedelta(minutes=300))
    if mirror:
        for row in a + b:
            o, h, l, c = (row[k] for k in ("open", "high", "low", "close"))
            row.update(open=4200 - o, high=4200 - l, low=4200 - h, close=4200 - c)
    return a, b


def snapshot(n=35, *, one=None, five=None, mirror=False, config=CONFIG, **kw):
    if one is None:
        one, five = fixture(mirror)
    c = context_at(
        SYMBOL,
        one,
        five,
        START + timedelta(minutes=n),
        config=config,
        intelligence_config=INTELLIGENCE,
        **kw
    )
    inputs = (
        dict(session_snapshot=kw["calendar"].public_state(START + timedelta(minutes=n)))
        if getattr(kw.get("calendar"), "version", 1) == 2
        else {}
    )
    return build_market_view_v3(c, **inputs), c, inputs


def sources(mirror=False, one=None, five=None, policy=None):
    if one is None:
        one, five = fixture(mirror)
    source = EntryResearchSession()
    v, c, i = snapshot(one=one, five=five)
    original = source.record(v, c, view_inputs=i)
    sid = next(
        p["setup_id"]
        for p in original["plans"]
        if p["research_state"] == "RESEARCH_QUALIFIED"
    )
    exit = ExitResearchSession(original, sid, entry_source=source, policy=policy)
    return source, original, exit, exit.report(), one, five
