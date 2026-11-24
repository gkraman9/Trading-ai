"""Independent invented OHLC for E1; not broker/native-feed evidence."""

from datetime import datetime, timedelta, timezone
from iat.intelligence.context import context_at
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.market_view import build_market_view_v3

START = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
SYMBOL = "SYNTHETIC_E1_XAUUSD"
CONFIG = ContextConfig()
INTELLIGENCE = IntelligenceConfig(left_strength=1, right_strength=1)


def fixture(mirror=False, tail=10):
    def bars(prices, minutes, begin):
        return [
            dict(
                timestamp=(begin + timedelta(minutes=minutes * i)).isoformat(),
                open=p,
                high=p + 0.15,
                low=p - 0.15,
                close=p,
            )
            for i, p in enumerate(prices)
        ]

    one = bars([2100, 2102, 2100, 2098] * 5, 1, START)
    one.extend(
        [
            dict(
                timestamp=(START + timedelta(minutes=20)).isoformat(),
                open=2101,
                high=2101.15,
                low=2100.85,
                close=2101,
            ),
            dict(
                timestamp=(START + timedelta(minutes=21)).isoformat(),
                open=2097.9,
                high=2098.15,
                low=2097.7,
                close=2097.85,
            ),
            dict(
                timestamp=(START + timedelta(minutes=22)).isoformat(),
                open=2098.2,
                high=2100.5,
                low=2098.1,
                close=2100.3,
            ),
        ]
    )
    one += bars([2100.5] * tail, 1, START + timedelta(minutes=23))
    five = bars([2100, 2102, 2100, 2098] * 12, 5, START - timedelta(minutes=200))
    if mirror:
        for r in one + five:
            o, h, l, c = (r[k] for k in ("open", "high", "low", "close"))
            r.update(open=4200 - o, high=4200 - l, low=4200 - h, close=4200 - c)
    return one, five


def snapshot(n=23, *, one=None, five=None, mirror=False, **options):
    if one is None:
        one, five = fixture(mirror)
    c = context_at(
        SYMBOL,
        one,
        five,
        START + timedelta(minutes=n),
        config=CONFIG,
        intelligence_config=INTELLIGENCE,
        **options
    )
    inputs = (
        dict(
            session_snapshot=options["calendar"].public_state(
                START + timedelta(minutes=n)
            )
        )
        if getattr(options.get("calendar"), "version", 1) == 2
        else {}
    )
    return build_market_view_v3(c, **inputs), c, inputs
