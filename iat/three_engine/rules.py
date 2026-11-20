"""Engine A reuses Stage B.2; Engine B is gated by its original candidate only."""

from iat.live_shadow.research import assess
from iat.three_engine.contracts import empty_response, stop_from_level
from iat.strategy_qualification.backtest import dec
from iat.three_engine.config import PROTOCOL


def baseline(bundle, state, config, calendar=None):
    b2 = dict(
        version=1,
        strategy_id=config["baseline_strategy_id"],
        costs=config["costs"],
        mode="UNQUALIFIED_SHADOW_RESEARCH",
    )
    new, decision = assess(bundle["candles"], bundle["cutoff"], state, b2, calendar)
    raw = empty_response(bundle)
    details = decision
    if decision is None:
        return new, raw, None
    candidate = decision["candidate"]
    if candidate not in ("BUY_CANDIDATE", "SELL_CANDIDATE"):
        raw["decision"] = "BLOCKED" if candidate == "BLOCKED" else "WAIT"
        return new, raw, details
    side = decision["side"]
    tick = dec(config["costs"]["tick_size"])
    expected = dec(decision["stop"])
    anchors = [
        k
        for k, v in bundle["price_catalog"].items()
        if stop_from_level(v["price"], side, tick) == expected
    ]
    if not anchors:
        raw["decision"] = "BLOCKED"
        return new, raw, details
    raw.update(
        decision=side,
        stop_anchor_id=sorted(anchors)[0],
        target_refs=["R2"],
        tp_allocations=["1"],
        hold_seconds=PROTOCOL["baseline_hold_seconds"],
    )
    results = [
        r
        for s in decision["strategies"]
        if s["strategy_id"] == config["baseline_strategy_id"]
        for r in s["evaluations"]
        if r["status"] == "QUALIFIES"
    ]
    ids = set(bundle["evidence_index"]) | set(bundle["price_catalog"])
    support = sorted({i for r in results for i in r["supporting_evidence"] if i in ids})
    opposition = sorted(
        {i for r in results for i in r["contradictory_evidence"] if i in ids}
    )
    raw["supporting_evidence_ids"] = support or [raw["stop_anchor_id"]]
    raw["contradicting_evidence_ids"] = opposition
    raw["market_reasoning"] = [
        dict(
            interpretation="BUYERS_CONTROL" if side == "BUY" else "SELLERS_CONTROL",
            evidence_id=raw["supporting_evidence_ids"][0],
            role="SUPPORT",
        )
    ]
    return new, raw, details
