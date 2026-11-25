"""Explicitly invented quotes/specifications; never Exness metadata or real prices."""

from dataclasses import replace
from datetime import timedelta
from risk_fixtures import sources, snapshot, START
from iat.intelligence.risk_intelligence import assess_risk
from iat.intelligence.paper_contracts import (
    BrokerSpecification,
    SyntheticCosts,
    FillPolicy,
    SyntheticQuote,
    SyntheticQuoteTape,
)
from iat.intelligence.capital_intelligence import CapitalPolicy
from iat.intelligence.paper_account import PaperAccount, PaperExitPolicy
from iat.intelligence.strategy_replay import digest


def specification(symbol, *, feed="INVENTED_FEED"):
    return BrokerSpecification(
        symbol=symbol,
        feed=feed,
        contract_size="100",
        min_lot="0.01",
        max_lot="10",
        volume_step="0.01",
        tick_size="0.01",
        tick_value="1",
        point_size="0.01",
        account_currency="USD",
        profit_currency="USD",
        margin_currency="USD",
        margin_method="LINEAR_NOTIONAL_LEVERAGE",
        leverage="100",
        min_stop_distance="0",
        freeze_level="0",
        commission_convention="ACCOUNT_CURRENCY_PER_LOT_PER_SIDE",
        financing_convention="ACCOUNT_CURRENCY_PER_LOT_PER_24H",
        margin_call_equity_ratio="0.5",
        stop_out_equity_ratio="0.2",
        session_eligible=True,
        source="INVENTED_SPEC_V1",
        effective_at_utc=START.isoformat(),
        expires_at_utc=(START + timedelta(days=1)).isoformat(),
    )


def costs():
    # Explicit toy zero assumptions, never implicit defaults or actual broker claims.
    return SyntheticCosts("0", "0", "0", "0", "1")


def policy(risk="0.01", **kw):
    return replace(
        CapitalPolicy(risk, "0.1", "0.1", "0.2", "1", 1, 3, "0.5", 120, "0", None), **kw
    )


def setup(mirror=False, starting_balance="50", offset=timedelta(0)):
    s, o, e, oe, a, b = sources(mirror=mirror)
    if offset:
        from iat.intelligence.entry_intelligence import EntryResearchSession
        from iat.intelligence.exit_intelligence import ExitResearchSession
        from iat.replay_dataset import utc

        a = [dict(r, timestamp=(utc(r["timestamp"]) + offset).isoformat()) for r in a]
        b = [dict(r, timestamp=(utc(r["timestamp"]) + offset).isoformat()) for r in b]
        s = EntryResearchSession()
        v, c, i = shifted_snapshot(35, a, b, offset)
        o = s.record(v, c, view_inputs=i)
        sid = next(
            p["setup_id"]
            for p in o["plans"]
            if p["research_state"] == "RESEARCH_QUALIFIED"
        )
        e = ExitResearchSession(o, sid, entry_source=s)
        oe = e.report()
    v, c, i = shifted_snapshot(36, a, b, offset)
    current = e.record(v, c, view_inputs=i)
    inputs = dict(
        original_e1=o,
        original_e2=oe,
        current_e2=current,
        entry_source=s,
        exit_source=e,
        as_of=c.analysis_at,
    )
    risk = assess_risk(**inputs)
    tape = SyntheticQuoteTape(
        risk["symbol"], "INVENTED_FEED", digest("EXPLICITLY_INVENTED_QUOTES")
    )
    when = START + offset + timedelta(minutes=36, seconds=1)
    q = tape.append(
        SyntheticQuote(
            risk["symbol"],
            "INVENTED_FEED",
            0,
            when.isoformat(),
            when.isoformat(),
            "2099.9",
            "2100.1",
            True,
            True,
        )
    )
    spec = specification(risk["symbol"])
    # Smaller toy contract enables testing a complete lifecycle on USD50. Example A uses100.
    spec = replace(spec, contract_size="1", tick_value="0.01")
    return (
        dict(
            risk=risk,
            risk_inputs=inputs,
            tape=tape,
            quote=q,
            specification=spec,
            costs=costs(),
            policy=policy(),
            fill_policy=FillPolicy(0, 2000, 120000, 30000),
            account=PaperAccount(started_at=START, starting_balance=starting_balance),
            as_of=when,
        ),
        a,
        b,
    )


def later(k, a, b, n=37, *, bid="2100", ask="2100.2", mutate=None):
    if mutate:
        a = [dict(x) for x in a]
        a[n - 1].update(mutate)
    offset = (
        __import__("iat.replay_dataset", fromlist=["utc"]).utc(
            k["risk"]["qualification_at_utc"]
        )
        - START
        - timedelta(minutes=35)
    )
    v, c, i = shifted_snapshot(n, a, b, offset)
    current = k["risk_inputs"]["exit_source"].record(v, c, view_inputs=i)
    inputs = dict(k["risk_inputs"], current_e2=current, as_of=c.analysis_at)
    risk = assess_risk(**inputs)
    when = START + offset + timedelta(minutes=n, seconds=1)
    seq = k["tape"].rows()[-1]["quote"]["sequence"] + 1
    q = k["tape"].append(
        SyntheticQuote(
            risk["symbol"],
            "INVENTED_FEED",
            seq,
            when.isoformat(),
            when.isoformat(),
            bid,
            ask,
            True,
            True,
        )
    )
    return dict(risk=risk, risk_inputs=inputs, tape=k["tape"], quote=q, as_of=when)


def open_position(k):
    kw = {name: v for name, v in k.items() if name != "account"}
    return k["account"].open(**kw, exit_policy=PaperExitPolicy(True, True, True))


def shifted_snapshot(n, a, b, offset):
    if not offset:
        return snapshot(n, one=a, five=b)
    from iat.intelligence.context import context_at
    from risk_fixtures import CONFIG, INTELLIGENCE, SYMBOL
    from iat.intelligence.market_view import build_market_view_v3

    c = context_at(
        SYMBOL,
        a,
        b,
        START + offset + timedelta(minutes=n),
        config=CONFIG,
        intelligence_config=INTELLIGENCE,
    )
    return build_market_view_v3(c), c, {}
