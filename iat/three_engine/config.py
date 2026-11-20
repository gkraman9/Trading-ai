"""Predeclared research protocol and explicit paper-account/margin assumptions."""

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from iat.replay_dataset import strict_json, read_bytes, utc
from iat.strategy_qualification.backtest import Costs, dec
from iat.intelligence.strategy_replay import digest

PROTOCOL = dict(
    version=1,
    quote_age_seconds=2,
    expiry_seconds=30,
    max_hold_seconds=180,
    baseline_hold_seconds=900,
    min_reward_risk="1",
    max_risk_percent="1",
    baseline_risk_percent="0.5",
    max_volume="0.01",
    daily_loss_fraction="0.01",
    daily_openings=5,
    provider_timeout_seconds=10,
    provider_retries=0,
    output_tokens=2048,
    prompt_version="evidence-plan-1",
    input_byte_bound=256000,
    max_reasoning_items=12,
    confidence="UNCALIBRATED",
    partial_fills="UNSUPPORTED_REMAIN_UNRESOLVED",
    entry_modes=["MARKET", "PULLBACK", "BREAKOUT", "REVERSAL"],
    target_rules=["R1", "R2", "R3"],
    invalidation_codes=[
        "OPPOSING_M1_CHOCH",
        "ANCHOR_LOST",
        "HIGH_VOLATILITY",
        "TIME_LIMIT",
    ],
    interpretation_codes=[
        "BUYERS_CONTROL",
        "SELLERS_CONTROL",
        "BREAKOUT_CONTINUATION",
        "LIQUIDITY_TRAP_RISK",
        "MOMENTUM_ACCELERATING",
        "MOMENTUM_WEAKENING",
        "M1_M5_CONFLICT",
        "REACTION_ZONE",
        "TOO_LATE",
        "COSTS_TOO_LARGE",
        "INSUFFICIENT_EVIDENCE",
    ],
)
PROTOCOL_SHA256 = digest(PROTOCOL)


def validate_config(v):
    if (
        type(v) is not dict
        or set(v) != {"version", "costs", "account", "budgets", "baseline_strategy_id"}
        or type(v["version"]) is not int
        or v["version"] != 1
    ):
        raise ValueError("CONFIG_SCHEMA_INVALID")
    if v["baseline_strategy_id"] not in (
        "M5_TREND_M1_CONFIRMATION",
        "SWEEP_M1_STRUCTURE_CHANGE",
    ):
        raise ValueError("BASELINE_STRATEGY_INVALID")
    if v["costs"] is not None:
        obj = dict(v["costs"])
        obj["rollovers"] = tuple(obj["rollovers"])
        c = Costs(**obj)
        if c.spread_stress_multiplier != "1":
            raise ValueError("OBSERVED_SPREAD_REQUIRED")
    if v["account"] is not None:
        a = v["account"]
        if (
            set(a)
            != {
                "version",
                "equity",
                "free_margin",
                "currency",
                "tick_value_per_lot",
                "margin_per_lot",
                "declared_at",
                "evidence_sha256",
                "assurance",
            }
            or type(a["version"]) is not int
            or a["version"] != 1
        ):
            raise ValueError("ACCOUNT_SCHEMA_INVALID")
        if (
            a["currency"] != "USD"
            or a["assurance"] != "DECLARED_PAPER_ACCOUNT_NOT_BROKER_VERIFIED"
        ):
            raise ValueError("ACCOUNT_ASSURANCE_INVALID")
        for key in ("equity", "free_margin", "tick_value_per_lot"):
            if dec(a[key]) <= 0:
                raise ValueError("ACCOUNT_VALUE_INVALID")
        if (
            dec(a["free_margin"]) > dec(a["equity"])
            or set(a["margin_per_lot"]) != {"BUY", "SELL"}
            or any(dec(x) <= 0 for x in a["margin_per_lot"].values())
        ):
            raise ValueError("MARGIN_UNAVAILABLE")
        utc(a["declared_at"])
        if len(a["evidence_sha256"]) != 64:
            raise ValueError("ACCOUNT_EVIDENCE_REQUIRED")
    b = v["budgets"]
    if set(b) != {
        "max_calls",
        "max_tokens",
        "max_cost_usd",
        "input_usd_per_million",
        "output_usd_per_million",
    }:
        raise ValueError("BUDGET_SCHEMA_INVALID")
    if (
        type(b["max_calls"]) is not int
        or not 0 <= b["max_calls"] <= 10000
        or type(b["max_tokens"]) is not int
        or not 0 <= b["max_tokens"] <= 10**8
    ):
        raise ValueError("BUDGET_INVALID")
    if any(
        dec(b[k]) < 0
        for k in ("max_cost_usd", "input_usd_per_million", "output_usd_per_million")
    ):
        raise ValueError("BUDGET_INVALID")
    return json.loads(json.dumps(v, allow_nan=False))


def configuration(path=None):
    if path is None:
        return validate_config(
            dict(
                version=1,
                costs=None,
                account=None,
                baseline_strategy_id="M5_TREND_M1_CONFIRMATION",
                budgets=dict(
                    max_calls=0,
                    max_tokens=0,
                    max_cost_usd="0",
                    input_usd_per_million="0",
                    output_usd_per_million="0",
                ),
            )
        )
    v = validate_config(strict_json(read_bytes(path)))
    root = Path(path).parent
    for name, key in (
        ("cost-evidence.txt", "costs"),
        ("account-research-evidence.txt", "account"),
    ):
        if (
            v[key] is not None
            and sha256(read_bytes(root / name)).hexdigest() != v[key]["evidence_sha256"]
        ):
            raise ValueError("RESEARCH_EVIDENCE_HASH_MISMATCH")
    return json.loads(json.dumps(v, allow_nan=False))
