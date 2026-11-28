"""Invented sources for software tests. Never admitted by historical file gates."""

from copy import deepcopy
from datetime import timedelta
from dataclasses import asdict
from types import SimpleNamespace
import json
from test_e47_readiness import schema_bundle
from risk_fixtures import fixture, START
from test_session_v2 import synthetic_v2
from iat.session_config import compile_session_config
from iat.e5_source import Source
from iat.paper_source_scope import _register_source
from iat.intelligence.strategy_replay import digest
from iat.e5_protocol import baseline
from tempfile import TemporaryDirectory
from pathlib import Path


def source(
    *,
    mirror=False,
    prices=None,
    minimum_contract=False,
    late_bar=False,
    future=False,
    receipt_delay=0,
    slippage=None,
    historical=False,
):
    one, five = fixture(mirror)
    one = one[:40]
    five = [
        r
        for r in five
        if __import__("datetime").datetime.fromisoformat(r["timestamp"])
        + timedelta(minutes=5)
        <= START + timedelta(minutes=40)
    ]
    cal = compile_session_config(synthetic_v2())
    meta = dict(
        dataset_kind="SYNTHETIC_FIXTURE",
        lineage=dict(feed_id="SYNTHETIC_SCHEMA_FIXTURE", price_basis="BID"),
        utc_range=dict(
            start=five[0]["timestamp"], end=(START + timedelta(minutes=40)).isoformat()
        ),
    )
    data = SimpleNamespace(metadata=meta, rows=dict(M1=one, M5=five), calendar=cal)
    with TemporaryDirectory() as tmp:
        bundle, _ = schema_bundle(Path(tmp))
        contents = {
            k: (Path(tmp) / v["file"]).read_bytes()
            for k, v in bundle["artifacts"].items()
        }
    for key in ("specification", "costs"):
        doc = json.loads(contents[key])
        doc.update(
            available_at_utc=(START - timedelta(days=1)).isoformat(),
            effective_from_utc=(START - timedelta(days=1)).isoformat(),
            effective_until_utc=(START + timedelta(days=1)).isoformat(),
        )
        if key == "specification" and not minimum_contract:
            doc["values"].update(contract_size="1", tick_value="0.01")
        if key == "costs" and slippage is not None:
            doc["values"]["slippage_price_per_fill"] = slippage
        contents[key] = json.dumps(doc).encode()
    contents["policies"] = json.dumps(baseline()).encode()
    bundle["windows"] = dict(
        warmup={
            tf: dict(
                start=data.rows[tf][0]["timestamp"],
                end=(START + timedelta(minutes=34)).isoformat(),
            )
            for tf in ("M1", "M5")
        },
        evaluation=dict(
            start=(START + timedelta(minutes=34)).isoformat(),
            end=(START + timedelta(minutes=38)).isoformat(),
        ),
        outcome=dict(
            start=(START + timedelta(minutes=38)).isoformat(),
            end=(START + timedelta(minutes=40)).isoformat(),
        ),
    )
    availability = {}
    for tf, period in (("M1", 1), ("M5", 5)):
        for r in data.rows[tf]:
            close = __import__("datetime").datetime.fromisoformat(
                r["timestamp"]
            ) + timedelta(minutes=period)
            available = close + (
                timedelta(seconds=10)
                if late_bar and tf == "M5" and close == START + timedelta(minutes=35)
                else timedelta(0)
            )
            availability[(tf, r["timestamp"])] = dict(
                timeframe=tf,
                opened_at_utc=r["timestamp"],
                closed_at_utc=close.isoformat(),
                available_at_utc=available.isoformat(),
                revision="0",
                finality="FINAL",
            )
    prices = prices or [
        ("2099.9", "2100.1"),
        ("2097.7", "2097.9"),
        ("2097.6", "2097.8"),
    ]
    rows = []
    for i, (bid, ask) in enumerate(prices):
        at = (START + timedelta(minutes=36, seconds=i + 1)).isoformat()
        rows.append(
            dict(
                sequence=str(i),
                occurred_at_utc=at,
                available_at_utc=(
                    START + timedelta(minutes=36, seconds=i + 1 + receipt_delay)
                ).isoformat(),
                bid=bid,
                ask=ask,
                revision="0",
                finality="FINAL",
            )
        )
    return _register_source(
        Source(
            data,
            bundle,
            contents,
            rows,
            availability,
            digest("EXPLICIT_SYNTHETIC_E5_FIXTURE"),
            historical=historical,
        )
    )
