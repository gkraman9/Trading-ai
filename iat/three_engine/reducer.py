"""Pure event reduction: immutable evidence, budgets and independent causal paper state."""

from copy import deepcopy
from decimal import Decimal
import json
from iat.three_engine import ENGINES
from iat.three_engine.config import PROTOCOL
from iat.three_engine import simulation
from iat.three_engine.contracts import proposal, validate_response, response_schema
from iat.three_engine.providers import PROMPT
from iat.three_engine.rules import baseline
from iat.three_engine.evidence import validate as validate_bundle
from iat.live_shadow.policy import session_diagnostics
from iat.replay_dataset import utc
from iat.strategy_qualification.backtest import dec
from iat.intelligence.strategy_replay import digest


def initial(config, source_binding):
    return dict(
        source_cursor=0,
        source_hash=source_binding,
        watermark=None,
        last_source_id=None,
        source_latched=False,
        last_market_quote=None,
        rules={},
        bundles={},
        baseline_candidates={},
        requests={},
        queue=[],
        engines={name: simulation.initial(config) for name in ENGINES},
        proposals={name: None for name in ENGINES},
        budget=dict(calls=0, tokens=0, cost_usd="0"),
        latest_bundle=None,
        points=0,
    )


def queue(s, kind, at, data):
    s["queue"].append(dict(kind=kind, at=at, data=data, id=digest([kind, at, data])))


def market(s, packet, config, calendar):
    effects = []
    for name in ENGINES:
        s["engines"][name]["counts"]["source_observations"] += 1
    capture = packet["capture"]
    end = utc(capture["end"])
    bad = (
        bool(packet["errors"])
        or capture["status"] != "OBSERVED_RANGE"
        or s["source_latched"]
    )
    ticks = capture["ticks"]
    previous = None
    try:
        q = packet["quote"]
        if (
            q is None
            or q["id"] != digest({k: v for k, v in q.items() if k != "id"})
            or not 0
            <= (utc(packet["received_at"]) - utc(q["timestamp"])).total_seconds()
            <= 2
        ):
            raise ValueError()
        for t in ticks:
            at = utc(t["timestamp"])
            if (
                t["id"] != digest({k: v for k, v in t.items() if k != "id"})
                or not utc(capture["start"]) <= at <= end
                or previous is not None
                and at <= previous
            ):
                raise ValueError()
            if (
                not all(dec(t[k]).is_finite() for k in ("bid", "ask", "spread"))
                or not 0 < dec(t["bid"]) <= dec(t["ask"])
                or dec(t["spread"]) != dec(t["ask"]) - dec(t["bid"])
            ):
                raise ValueError()
            previous = at
        if utc(q["timestamp"]) >= utc(capture["start"]) and q["id"] not in {
            t["id"] for t in ticks
        }:
            raise ValueError()
        if s["watermark"] and (
            end < utc(s["watermark"]) or utc(capture["start"]) > utc(s["watermark"])
        ):
            raise ValueError()
    except Exception:
        bad = True
    if bad:
        for name in ENGINES:
            s["engines"][name]["counts"]["source_missing_data"] += 1
            s["engines"][name], e = simulation.missing(
                s["engines"][name], "SOURCE_DATA_UNCERTAIN"
            )
            effects.extend(dict(engine=name, **v) for v in e)
    due = [e for e in s["queue"] if utc(e["at"]) <= end]
    s["queue"] = [e for e in s["queue"] if utc(e["at"]) > end]
    events = [(utc(e["at"]), 1 if e["kind"] == "CONTEXT" else 2, e) for e in due]
    if not bad:
        events.extend((utc(t["timestamp"]), 0, t) for t in ticks)
    for at, kind, value in sorted(events, key=lambda r: (r[0], r[1], digest(r[2]))):
        if kind == 0:
            phase = session_diagnostics(calendar, at, quote=value)
            for name in ENGINES:
                s["engines"][name], e = simulation.quote(
                    s["engines"][name], value, config, phase
                )
                effects.extend(dict(engine=name, **v) for v in e)
        elif value["kind"] == "CONTEXT":
            for name in ENGINES:
                s["engines"][name], e = simulation.invalidate(
                    s["engines"][name], s["bundles"][value["data"]]
                )
                effects.extend(dict(engine=name, **v) for v in e)
        else:
            p = value["data"]
            name = p["engine"]
            s["engines"][name], e = simulation.decision(
                s["engines"][name], p, s["bundles"][p["bundle_id"]]
            )
            effects.extend(dict(engine=name, **v) for v in e)
    if s["watermark"] is None or end >= utc(s["watermark"]):
        s["watermark"] = capture["end"]
    return effects


def reduce(state, event, config, calendar=None):
    s = deepcopy(state)
    effects = []
    kind = event["kind"]
    data = event["data"]
    if kind == "SOURCE":
        if utc(data["packet"]["received_at"]) > utc(data["consumed_at"]) or utc(
            data["packet"]["capture"]["end"]
        ) > utc(data["consumed_at"]):
            raise ValueError("FUTURE_SOURCE_CONSUMPTION")
        if (
            data["seq"] != s["source_cursor"] + 1
            or data["previous_sha256"] != s["source_hash"]
        ):
            raise ValueError("SOURCE_PREFIX_MISMATCH")
        if data.get("correction_detected"):
            s["source_latched"] = True
        s["last_market_quote"] = deepcopy(data["packet"]["quote"])
        s["source_cursor"] = data["seq"]
        s["source_hash"] = data["source_event_sha256"]
        s["last_source_id"] = data["candle_source_id"]
        effects += market(s, data["packet"], config, calendar)
    elif kind == "POINT":
        b = data["bundle"]
        validate_bundle(b)
        if utc(data["available_at"]) < utc(b["cutoff"]):
            raise ValueError("AVAILABILITY_PRECEDES_CUTOFF")
        if b["id"] in s["bundles"]:
            raise ValueError("DUPLICATE_COMPARISON_POINT")
        if b["costs"] != config["costs"] or b["account"] != config["account"]:
            raise ValueError("COMMON_CONFIG_MISMATCH")
        if s["source_latched"] and b["quality"]["valid"]:
            raise ValueError("SOURCE_CORRECTION_QUARANTINED")
        if s["points"] >= 10000:
            raise ValueError("COMPARISON_CAPACITY_REACHED")
        s["bundles"][b["id"]] = b
        s["latest_bundle"] = b["id"]
        s["points"] += 1
        s["rules"], raw, details = baseline(b, s["rules"], config, calendar)
        s["baseline_candidates"][b["id"]] = dict(raw=raw, details=details)
        p = proposal(
            "A_RULES", b, raw, data["available_at"], config, request_at=b["cutoff"]
        )
        if details and details.get("setup_id") and p["decision"] in ("BUY", "SELL"):
            p.pop("decision_id")
            p["setup_id"] = digest(["A_RULES", details["setup_id"]])
            p["decision_id"] = digest(p)
        queue(s, "CONTEXT", b["cutoff"], b["id"])
        s["proposals"][p["engine"]] = deepcopy(p)
        queue(s, "PROPOSAL", p["decision_available_at"], p)
        effects.append(dict(kind="FROZEN_PROPOSAL", proposal=p))
    elif kind == "REQUEST":
        key = data["request_id"]
        engine = data["engine"]
        b = s["bundles"][data["bundle_id"]]
        if (
            engine not in ENGINES[1:]
            or key in s["requests"]
            or key
            != digest([engine, b["id"], data["model"], PROTOCOL["prompt_version"]])
        ):
            raise ValueError("REQUEST_IDENTITY_INVALID")
        if utc(data["at"]) < utc(b["cutoff"]):
            raise ValueError("REQUEST_BEFORE_EVIDENCE")
        reason = data.get("blocked_reason")
        if engine == "B_HYBRID" and s["baseline_candidates"][b["id"]]["raw"][
            "decision"
        ] not in ("BUY", "SELL"):
            reason = "NO_RULE_CANDIDATE"
        elif not b["quality"]["valid"]:
            reason = "BLOCKED_MARKET_EVIDENCE"
        elif not data["enabled"]:
            reason = "PROVIDER_DISABLED"
        encoded = json.dumps(
            request_packet(s, b, engine),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        # Reserve for the whole supplied prompt/schema, not just the evidence packet.
        # Vendor framing is additionally bounded by a declared reserve, not a billing guarantee.
        input_bound = (
            len(encoded)
            + len(PROMPT.encode())
            + len(
                json.dumps(
                    response_schema(), sort_keys=True, separators=(",", ":")
                ).encode()
            )
            + PROTOCOL["provider_envelope_token_reserve"]
        )
        tokens = input_bound + PROTOCOL["output_tokens"]
        cost = (
            Decimal(input_bound) * dec(config["budgets"]["input_usd_per_million"])
            + Decimal(PROTOCOL["output_tokens"])
            * dec(config["budgets"]["output_usd_per_million"])
        ) / 1000000
        if reason is None and len(encoded) > PROTOCOL["input_byte_bound"]:
            reason = "AI_INPUT_TOO_LARGE"
        if (
            reason is None
            and data["actual_ai"]
            and min(
                dec(config["budgets"]["input_usd_per_million"]),
                dec(config["budgets"]["output_usd_per_million"]),
            )
            <= 0
        ):
            reason = "AI_PRICING_UNAVAILABLE"
        budget = s["budget"]
        limits = config["budgets"]
        if reason is None and (
            budget["calls"] + 1 > limits["max_calls"]
            or budget["tokens"] + tokens > limits["max_tokens"]
            or dec(budget["cost_usd"]) + cost > dec(limits["max_cost_usd"])
        ):
            reason = "BUDGET_EXHAUSTED"
        s["requests"][key] = dict(
            **data,
            status="BLOCKED" if reason else "PENDING",
            reason=reason,
            reserved_tokens=tokens,
            reserved_cost_usd=str(cost)
        )
        if reason:
            p = proposal(
                engine,
                b,
                None,
                data["at"],
                config,
                model="DISABLED" if not data["enabled"] else data["model"],
                request_at=data["at"],
                blocked_reason=reason,
            )
            s["proposals"][p["engine"]] = deepcopy(p)
            queue(s, "PROPOSAL", data["at"], p)
            effects.append(dict(kind="FROZEN_PROPOSAL", proposal=p))
        else:
            budget["calls"] += 1
            budget["tokens"] += tokens
            budget["cost_usd"] = str(dec(budget["cost_usd"]) + cost)
    elif kind == "RESULT":
        req = s["requests"][data["request_id"]]
        if req["status"] != "PENDING":
            raise ValueError("RESULT_DUPLICATE_OR_UNREQUESTED")
        if not utc(req["at"]) <= utc(data["response_at"]) <= utc(data["available_at"]):
            raise ValueError("RESPONSE_TIME_INVALID")
        if s["watermark"] and utc(data["available_at"]) < utc(s["watermark"]):
            raise ValueError("RESULT_PRECEDES_MARKET_WATERMARK")
        b = s["bundles"][req["bundle_id"]]
        code = data["code"]
        if (utc(data["response_at"]) - utc(req["at"])).total_seconds() > PROTOCOL[
            "provider_timeout_seconds"
        ]:
            code = "PROVIDER_TIMEOUT"
        p = proposal(
            req["engine"],
            b,
            data["raw"],
            data["available_at"],
            config,
            model=req["model"],
            request_at=req["at"],
            response_at=data["response_at"],
            blocked_reason=code,
        )
        req["status"] = "COMPLETED"
        req["proposal_id"] = p["decision_id"]
        req["response_at"] = data["response_at"]
        req["actual_ai_success"] = bool(
            req["actual_ai"]
            and code is None
            and p["reason_codes"] != ["PROPOSAL_VALIDATION_FAILED"]
        )
        s["proposals"][p["engine"]] = deepcopy(p)
        queue(s, "PROPOSAL", p["decision_available_at"], p)
        effects.append(dict(kind="FROZEN_PROPOSAL", proposal=p))
    elif kind == "RECOVERY":
        for key, req in s["requests"].items():
            if req["status"] == "PENDING":
                req["status"] = "INTERRUPTED"
                p = proposal(
                    req["engine"],
                    s["bundles"][req["bundle_id"]],
                    None,
                    data["at"],
                    config,
                    model=req["model"],
                    request_at=req["at"],
                    blocked_reason="REQUEST_INTERRUPTED",
                )
                s["proposals"][p["engine"]] = deepcopy(p)
                queue(s, "PROPOSAL", data["at"], p)
                effects.append(dict(kind="FROZEN_PROPOSAL", proposal=p))
    else:
        raise ValueError("EVENT_KIND_INVALID")
    keep = {s["latest_bundle"]}
    keep.update(
        r["bundle_id"] for r in s["requests"].values() if r["status"] == "PENDING"
    )
    keep.update(
        q["data"] if q["kind"] == "CONTEXT" else q["data"]["bundle_id"]
        for q in s["queue"]
    )
    keep.update(
        e["pending"]["bundle"]["id"] for e in s["engines"].values() if e["pending"]
    )
    s["bundles"] = {k: v for k, v in s["bundles"].items() if k in keep}
    s["baseline_candidates"] = {
        k: v for k, v in s["baseline_candidates"].items() if k in keep
    }
    return s, effects


def request_packet(state, bundle, engine):
    result = dict(
        engine=engine,
        evidence=deepcopy(bundle),
        prompt_version=PROTOCOL["prompt_version"],
    )
    if engine == "B_HYBRID":
        result["baseline_hint"] = deepcopy(state["baseline_candidates"][bundle["id"]])
    return result
