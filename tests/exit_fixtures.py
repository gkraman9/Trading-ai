"""Independent invented E1/E2 OHLC, not real XAUUSD/feed/fill evidence."""

from datetime import datetime, timedelta, timezone
from iat.intelligence.context import context_at
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.market_view import build_market_view_v3

START = datetime(2026, 11, 13, 10, tzinfo=timezone.utc)
SYMBOL = "SYNTHETIC_E2_XAUUSD"
CONFIG = ContextConfig()
INTELLIGENCE = IntelligenceConfig(left_strength=1, right_strength=1)


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

    one = bars([5750, 5753, 5750, 5747] * 5, 1, START)
    one += [
        dict(timestamp=(START + timedelta(minutes=i)).isoformat(), **r)
        for i, r in (
            (20, dict(open=5750, high=5750.2, low=5749.8, close=5750)),
            (21, dict(open=5746.9, high=5747.1, low=5746.6, close=5746.8)),
            (22, dict(open=5747.1, high=5750.1, low=5747, close=5750)),
        )
    ]
    one += bars([5750] * 12, 1, START + timedelta(minutes=23))
    five = bars([5750, 5753, 5750, 5747] * 12, 5, START - timedelta(minutes=200))
    if mirror:
        for row in one + five:
            o, h, l, c = (row[k] for k in ("open", "high", "low", "close"))
            row.update(open=11500 - o, high=11500 - l, low=11500 - h, close=11500 - c)
    return one, five


def snapshot(
    n=23, *, one=None, five=None, mirror=False, intelligence=INTELLIGENCE, **options
):
    if one is None:
        one, five = fixture(mirror)
    at = START + timedelta(minutes=n)
    context = context_at(
        SYMBOL,
        one,
        five,
        at,
        config=CONFIG,
        intelligence_config=intelligence,
        **options
    )
    inputs = (
        dict(session_snapshot=options["calendar"].public_state(at))
        if getattr(options.get("calendar"), "version", 1) == 2
        else {}
    )
    return build_market_view_v3(context, **inputs), context, inputs
