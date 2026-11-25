"""Independent invented protective quote sequences, never a broker export."""

from datetime import timedelta
from paper_fixtures import setup as base_setup, later, policy
from risk_fixtures import START
from iat.intelligence.protected_paper import ProtectedPaperAccount
from iat.intelligence.paper_account import PaperExitPolicy
from iat.intelligence.paper_contracts import SyntheticQuote
from iat.intelligence.protection_contracts import (
    ProtectiveStopPolicy,
    LiquidationPolicy,
)


def stop_policy(latency=0, can_fill=True):
    return ProtectiveStopPolicy(
        "DECLARED_SYNTHETIC_STRUCTURE_TO_QUOTE_STOP",
        "LONG_BID_SHORT_ASK",
        latency,
        can_fill,
        "AT_ENTRY_QUOTE_RECEIPT_BEFORE_OPEN",
    )


def liquidation_policy(latency=0, can_fill=True):
    return LiquidationPolicy(
        "SYNTHETIC_EQUITY_OVER_FROZEN_ENTRY_MARGIN",
        "NET_LIQUIDATION_EQUITY_WITH_DECLARED_COSTS",
        "SYNTHETIC_EXIT_ON_STOP_OUT_ONLY",
        latency,
        can_fill,
    )


def setup(mirror=False, **kw):
    k, a, b = base_setup(mirror, **kw)
    k.update(
        account=ProtectedPaperAccount(
            started_at=START, starting_balance=kw.get("starting_balance", "50")
        ),
        stop_policy=stop_policy(),
        liquidation_policy=liquidation_policy(),
    )
    return k, a, b


def open_position(k):
    return k["account"].open(
        **{n: v for n, v in k.items() if n != "account"},
        exit_policy=PaperExitPolicy(True, True, True)
    )


def quote(
    k,
    second=2,
    *,
    bid="2100",
    ask="2100.2",
    quotation=True,
    opening=True,
    occurred=None
):
    when = k["as_of"] + timedelta(seconds=second - 1)
    sequence = k["tape"].rows()[-1]["quote"]["sequence"] + 1
    return k["tape"].append(
        SyntheticQuote(
            k["tape"].symbol,
            k["tape"].feed,
            sequence,
            (when if occurred is None else occurred).isoformat(),
            when.isoformat(),
            bid,
            ask,
            quotation,
            opening,
        )
    )


def observe(k, row, *, risk=None, risk_inputs=None):
    return k["account"].observe(
        k["risk"] if risk is None else risk,
        risk_inputs=k["risk_inputs"] if risk_inputs is None else risk_inputs,
        tape=k["tape"],
        quote=row,
        as_of=row["quote"]["available_at_utc"],
    )
