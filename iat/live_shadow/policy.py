"""Frozen shadow configuration and session diagnostics; no new broker schedule."""

from dataclasses import asdict
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from iat.replay_dataset import read_bytes, strict_json, utc
from iat.strategy_qualification.specs import specifications
from iat.strategy_qualification.backtest import Costs, dec
from iat.intelligence.strategy_replay import digest
from iat.live_shadow import LABEL


def configuration(path=None):
    if path is None:
        return dict(
            version=1, strategy_id=None, costs=None, mode="RECORD_ONLY", label=LABEL
        )
    raw = read_bytes(path)
    v = strict_json(raw)
    if (
        set(v) != {"version", "strategy_id", "costs"}
        or type(v["version"]) is not int
        or v["version"] != 1
    ):
        raise ValueError("SHADOW_CONFIG_INVALID")
    if v["strategy_id"] not in {s.strategy_id for s in specifications()}:
        raise ValueError("STRATEGY_NOT_SUPPORTED")
    c = dict(v["costs"])
    c["rollovers"] = tuple(c["rollovers"])
    costs = Costs(**c)
    if costs.spread_stress_multiplier != "1":
        raise ValueError("OBSERVED_SPREAD_REQUIRED")
    # A checksum binds a supplied terms document; it does not establish independent qualification.
    evidence = Path(path).parent / "cost-evidence.txt"
    if sha256(read_bytes(evidence)).hexdigest() != costs.evidence_sha256:
        raise ValueError("COST_EVIDENCE_MISMATCH")
    return dict(
        version=1,
        strategy_id=v["strategy_id"],
        costs=asdict(costs),
        mode="UNQUALIFIED_SHADOW_RESEARCH",
        label=LABEL,
    )


def session_diagnostics(calendar, at, *, quote=None, errors=()):
    out = dict(
        phase="UNKNOWN",
        calendar_status="MISSING",
        quote_available=None,
        new_positions=None,
        close_positions=None,
        operational_eligible=False,
        reason_codes=["SESSION_CALENDAR_MISSING"],
        configuration_sha256=None,
    )
    if calendar is not None:
        out["configuration_sha256"] = getattr(calendar, "configuration_sha256", None)
        if hasattr(calendar, "public_state"):
            state = calendar.public_state(at)
            p = state["permissions"]
            out.update(
                phase=p["phase"],
                calendar_status=state["verification"],
                quote_available=p["market_data_expected"],
                new_positions=p["broker_open_positions"],
                close_positions=p["broker_close_positions"],
                reason_codes=list(state["reason_codes"]),
            )
            if p["phase"] == "CLOSED":
                out["reason_codes"].append("ACTUAL_MARKET_CLOSURE")
            if p["phase"] in ("CLOSE_ONLY", "QUOTE_ONLY"):
                out["reason_codes"].append("SESSION_TRANSITION_RESTRICTED")
        else:
            out.update(
                calendar_status="QUOTE_CALENDAR_WITHOUT_TRADE_PERMISSION_EVIDENCE",
                reason_codes=["TRADE_SESSION_METADATA_UNAVAILABLE"],
            )
        try:
            calendar.validate_request(
                "XAUUSD", at, __import__("datetime").timedelta(minutes=1)
            )
            out["operational_eligible"] = (
                out["calendar_status"] == "VERIFIED_DECLARATIONS"
                and out["new_positions"] is True
            )
        except Exception as exc:
            out["reason_codes"].append(getattr(exc, "code", "SESSION_UNVERIFIED"))
    out["reason_codes"] = sorted(set(out["reason_codes"]) | set(errors))
    if quote is None:
        out["reason_codes"] = sorted(set(out["reason_codes"]) | {"BID_ASK_UNAVAILABLE"})
        out["operational_eligible"] = False
    elif not 0 <= (at - utc(quote["timestamp"])).total_seconds() <= 2:
        out["reason_codes"] = sorted(
            set(out["reason_codes"]) | {"QUOTE_STALE_OR_FUTURE"}
        )
        out["operational_eligible"] = False
    if errors:
        out["operational_eligible"] = False
    return out


def costs_match_symbol(costs, symbol):
    try:
        if (
            symbol.get("currency_profit") != "USD"
            or type(symbol.get("trade_calc_mode")) is not int
            or symbol["trade_calc_mode"] not in (0, 1)
        ):
            return False
        required = (
            "trade_contract_size",
            "trade_tick_size",
            "trade_stops_level",
            "point",
            "digits",
            "volume_min",
            "volume_max",
            "volume_step",
        )
        if any(type(symbol.get(k)) not in (int, float) for k in required):
            return False
        if dec(costs.contract_size) != Decimal(
            str(symbol["trade_contract_size"])
        ) or dec(costs.tick_size) != Decimal(str(symbol["trade_tick_size"])):
            return False
        if (
            type(symbol["digits"]) is not int
            or not 0 <= symbol["digits"] <= 10
            or symbol["point"] <= 0
            or symbol["volume_min"] <= 0
        ):
            return False
        if Decimal(str(symbol["point"])) != Decimal(10) ** (-symbol["digits"]):
            return False
        if dec(costs.volume_min) != Decimal(str(symbol["volume_min"])) or dec(
            costs.volume_step
        ) != Decimal(str(symbol["volume_step"])):
            return False
        if (
            symbol["trade_stops_level"] < 0
            or not 0 <= symbol["digits"] <= 10
            or symbol["volume_step"] <= 0
        ):
            return False
        if not Decimal(str(symbol["volume_min"])) <= Decimal(".01") <= Decimal(
            str(symbol["volume_max"])
        ) or Decimal(".01") % Decimal(str(symbol["volume_step"])):
            return False
        return dec(costs.minimum_stop_distance) >= Decimal(
            str(symbol["trade_stops_level"])
        ) * Decimal(str(symbol["point"]))
    except Exception:
        return False
