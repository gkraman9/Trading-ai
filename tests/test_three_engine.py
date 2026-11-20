"""SYNTHETIC tests only. No real provider, market, account, broker or profitability claims."""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from contextlib import closing, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from threading import Event
import json, sqlite3, tempfile, time, unittest, ast
from iat.three_engine.config import configuration, validate_config, PROTOCOL
from iat.three_engine.evidence import build, validate as validate_bundle
from iat.three_engine.contracts import (
    empty_response,
    proposal,
    validate_response,
    stop_from_level,
    response_schema,
)
from iat.three_engine import simulation
from iat.three_engine.journal import SourceReader, ComparisonJournal
from iat.three_engine.runtime import ComparisonRuntime
from iat.three_engine.reducer import request_packet
from iat.live_shadow.store import Journal as B2Journal
from iat.live_shadow.policy import configuration as b2config
from iat.intelligence.strategy_replay import digest
from test_live_shadow import raw_packet, cfg, symbol, tick, NOW, session


def config(equity="10000"):
    costs = deepcopy(cfg()["costs"])
    costs["initial_equity"] = equity
    return validate_config(
        dict(
            version=1,
            baseline_strategy_id="M5_TREND_M1_CONFIRMATION",
            costs=costs,
            account=dict(
                version=1,
                equity=equity,
                free_margin=equity,
                currency="USD",
                tick_value_per_lot="1",
                margin_per_lot={"BUY": "1000", "SELL": "1000"},
                declared_at=(NOW - timedelta(days=1)).isoformat(),
                evidence_sha256="a" * 64,
                assurance="DECLARED_PAPER_ACCOUNT_NOT_BROKER_VERIFIED",
            ),
            budgets=dict(
                max_calls=20,
                max_tokens=10000000,
                max_cost_usd="10",
                input_usd_per_million="0",
                output_usd_per_million="0",
            ),
        )
    )


def response(b, side="BUY", **kw):
    r = empty_response(b, side)
    candidates = [
        (k, v)
        for k, v in b["price_catalog"].items()
        if v["kind"] == ("CLOSED_CANDLE_LOW" if side == "BUY" else "CLOSED_CANDLE_HIGH")
    ]
    key = sorted(candidates)[0][0]
    r.update(
        stop_anchor_id=key,
        target_refs=["R2"],
        tp_allocations=["1"],
        supporting_evidence_ids=[key],
        market_reasoning=[
            dict(
                interpretation="BUYERS_CONTROL" if side == "BUY" else "SELLERS_CONTROL",
                evidence_id=key,
                role="SUPPORT",
            )
        ],
    )
    r.update(kw)
    return r


class TestReasoner:
    __test__ = False
    provider_name = "SYNTHETIC_TEST_REASONER"
    model = "SYNTHETIC_MODEL"
    actual_ai = False

    def __init__(self, fn=None):
        self.fn = fn or (lambda p: response(p["evidence"]))
        self.calls = []

    def request(self, p):
        self.calls.append(deepcopy(p))
        return self.fn(p)

    def close(self):
        pass


class ThreeEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="iat three-engine SYNTHETIC ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = config()
        self.p = raw_packet()
        self.b = build(
            self.p, self.cfg, NOW.isoformat(), source_kind="SYNTHETIC_FIXTURE"
        )

    def plan(
        self,
        side="BUY",
        engine="C_AI_LED",
        available=0.5,
        raw=None,
        bundle=None,
        config_=None,
    ):
        b = bundle or self.b
        return proposal(
            engine,
            b,
            raw or response(b, side),
            (NOW + timedelta(seconds=available)).isoformat(),
            config_ or self.cfg,
            model="SYNTHETIC_MODEL",
            request_at=b["cutoff"],
        )

    def journal(self, name="comparison", config_=None, models=None):
        return ComparisonJournal(
            self.root / name,
            config_ or self.cfg,
            "b" * 64,
            create=True,
            source_kind="SYNTHETIC_FIXTURE",
            models=models
            or {"B_HYBRID": "SYNTHETIC_MODEL", "C_AI_LED": "SYNTHETIC_MODEL"},
        )

    def point(self, j, b=None):
        b = b or self.b
        j.record(
            dict(
                kind="POINT",
                data=dict(
                    bundle=b, available_at=(NOW + timedelta(seconds=0.1)).isoformat()
                ),
            )
        )

    def request(self, j, engine="C_AI_LED", model="SYNTHETIC_MODEL", enabled=True):
        key = digest([engine, self.b["id"], model, PROTOCOL["prompt_version"]])
        j.record(
            dict(
                kind="REQUEST",
                data=dict(
                    request_id=key,
                    engine=engine,
                    bundle_id=self.b["id"],
                    model=model,
                    at=(NOW + timedelta(seconds=0.2)).isoformat(),
                    enabled=enabled,
                    actual_ai=False,
                    blocked_reason=None,
                ),
            )
        )
        return key

    def result(self, j, key, raw=None, seconds=0.5, code=None):
        j.record(
            dict(
                kind="RESULT",
                data=dict(
                    request_id=key,
                    raw=raw if raw is not None else response(self.b),
                    response_at=(NOW + timedelta(seconds=seconds)).isoformat(),
                    available_at=(NOW + timedelta(seconds=seconds)).isoformat(),
                    code=code,
                ),
            )
        )

    def enter(self, plan=None):
        p = plan or self.plan()
        s, _ = simulation.decision(simulation.initial(self.cfg), p, self.b)
        s, e = simulation.quote(s, tick(1), self.cfg, session())
        return s, e

    def test_common_bundle_canonical_frozen_and_all_evidence_causal(self):
        validate_bundle(self.b)
        saved = deepcopy(self.p)
        again = build(
            self.p, self.cfg, NOW.isoformat(), source_kind="SYNTHETIC_FIXTURE"
        )
        self.assertEqual(self.b, again)
        self.assertEqual(self.p, saved)
        self.assertTrue(self.b["price_catalog"])
        self.assertEqual(self.b["source_kind"], "SYNTHETIC_FIXTURE")

    def test_future_candle_and_evidence_rejected_even_after_checksum(self):
        b = deepcopy(self.b)
        b["candles"]["M5"][-1]["timestamp"] = (NOW + timedelta(minutes=5)).isoformat()
        b["id"] = digest({k: v for k, v in b.items() if k != "id"})
        with self.assertRaises(ValueError):
            validate_bundle(b)
        b = deepcopy(self.b)
        next(iter(b["price_catalog"].values()))["available_at"] = (
            NOW + timedelta(seconds=1)
        ).isoformat()
        b["id"] = digest({k: v for k, v in b.items() if k != "id"})
        with self.assertRaises(ValueError):
            validate_bundle(b)

    def test_c_can_propose_without_a_trigger_and_b_is_not_called(self):
        j = self.journal()
        self.point(j)
        self.assertEqual(j.state()["proposals"]["A_RULES"]["decision"], "WAIT")
        b = self.request(j, "B_HYBRID")
        c = self.request(j)
        self.assertEqual(j.state()["requests"][b]["reason"], "NO_RULE_CANDIDATE")
        self.assertEqual(j.state()["requests"][c]["status"], "PENDING")
        self.result(j, c)
        self.assertEqual(j.state()["proposals"]["C_AI_LED"]["decision"], "BUY")
        self.assertEqual(j.state()["proposals"]["A_RULES"]["decision"], "WAIT")
        self.assertEqual(j.state()["budget"]["calls"], 1)

    def test_c_request_contains_no_a_hint_and_common_evidence_identical(self):
        j = self.journal()
        self.point(j)
        s = j.state()
        a = request_packet(s, self.b, "B_HYBRID")
        b = request_packet(s, self.b, "C_AI_LED")
        self.assertEqual(a["evidence"], b["evidence"])
        self.assertIn("baseline_hint", a)
        self.assertNotIn("baseline_hint", b)

    def test_provider_output_cannot_inject_price_or_execution_flags(self):
        for key, value in [
            ("execution_allowed", True),
            ("entry_price", "1"),
            ("confidence_probability", 0.9),
            ("market_reasoning", [{"text": "SECRET"}]),
        ]:
            raw = response(self.b)
            raw[key] = value
            p = self.plan(raw=raw)
            self.assertEqual(p["decision"], "BLOCKED")
            self.assertFalse(p["execution_allowed"])
            self.assertIsNone(p["entry_price"])

    def test_evidence_ids_are_required_and_duplicates_do_not_inflate(self):
        for ids in (["FAKE"], [next(iter(self.b["price_catalog"]))] * 2):
            r = response(self.b, supporting_evidence_ids=ids)
            with self.assertRaises(ValueError):
                validate_response(r, self.b)

    def test_confidence_is_never_a_calibrated_probability(self):
        p = self.plan(
            raw=response(self.b, confidence_estimate=85, requested_band="80_90")
        )
        self.assertEqual(p["decision"], "BUY")
        self.assertEqual(p["confidence_band"], "UNCALIBRATED")
        self.assertEqual(p["model_confidence_assessment"], "85")
        self.assertIsNone(p["confidence_probability"])
        for v in (True, float("nan"), 101):
            self.assertEqual(
                self.plan(raw=response(self.b, confidence_estimate=v))["decision"],
                "BLOCKED",
            )

    def test_small_fifty_dollar_account_rejects_oversized_min_lot(self):
        c = config("50")
        b = build(self.p, c, NOW.isoformat(), source_kind="SYNTHETIC_FIXTURE")
        p = self.plan(bundle=b, config_=c)
        self.assertEqual(p["decision"], "BLOCKED")
        self.assertIn("MINIMUM_LOT_EXCEEDS_RISK_BUDGET", p["reason_codes"])
        self.assertIsNone(p["lot_size"])

    def test_free_margin_and_tick_value_validation(self):
        for change, code in [
            (dict(free_margin=".01"), "INSUFFICIENT_DECLARED_FREE_MARGIN"),
            (dict(tick_value_per_lot="2"), "TICK_VALUE_CONTRACT_MISMATCH"),
        ]:
            c = deepcopy(self.cfg)
            c["account"].update(change)
            b = build(self.p, c, NOW.isoformat(), source_kind="SYNTHETIC_FIXTURE")
            p = self.plan(bundle=b, config_=c)
            self.assertIn(code, p["reason_codes"])

    def test_missing_costs_contract_or_account_blocks(self):
        for field in ("costs", "account"):
            c = deepcopy(self.cfg)
            c[field] = None
            b = build(self.p, c, NOW.isoformat(), source_kind="SYNTHETIC_FIXTURE")
            self.assertEqual(self.plan(bundle=b, config_=c)["decision"], "BLOCKED")
        b = deepcopy(self.b)
        b["symbol_specifications"]["trade_contract_size"] = None
        b["id"] = digest({k: v for k, v in b.items() if k != "id"})
        self.assertIn(
            "CONTRACT_OR_CURRENCY_UNSUPPORTED", self.plan(bundle=b)["reason_codes"]
        )

    def test_invalid_sl_tp_order_and_multiple_targets(self):
        p = self.plan(
            raw=response(self.b, target_refs=["R3", "R2"], tp_allocations=["0", "1"])
        )
        self.assertEqual(p["decision"], "BLOCKED")
        c = deepcopy(self.cfg)
        c["costs"]["volume_min"] = ".001"
        c["costs"]["volume_step"] = ".001"
        packet = deepcopy(self.p)
        packet["symbol_specification"].update(volume_min=0.001, volume_step=0.001)
        b = build(packet, c, NOW.isoformat(), source_kind="SYNTHETIC_FIXTURE")
        p = self.plan(
            bundle=b,
            config_=c,
            raw=response(
                b, target_refs=["R1", "R2", "R3"], tp_allocations=[".5", ".3", ".2"]
            ),
        )
        self.assertEqual(p["decision"], "BUY")
        self.assertLess(Decimal(p["take_profit_1"]), Decimal(p["take_profit_2"]))
        self.assertLess(Decimal(p["take_profit_2"]), Decimal(p["take_profit_3"]))

    def test_partial_volume_never_rounded_up_to_minimum(self):
        p = self.plan(
            raw=response(
                self.b,
                target_refs=["R1", "R2", "R3"],
                tp_allocations=[".5", ".3", ".2"],
            )
        )
        self.assertEqual(p["decision"], "BLOCKED")
        self.assertIn("PARTIAL_VOLUME_UNSUPPORTED", p["reason_codes"])

    def test_provider_latency_and_expiry_measurable(self):
        p = self.plan(available=31)
        self.assertEqual(p["latency_seconds"], "31.0")
        self.assertIn("OPPORTUNITY_EXPIRED", p["reason_codes"])
        p = self.plan(available=3)
        self.assertIn("QUOTE_STALE_AT_DECISION", p["reason_codes"])

    def test_opposing_fresh_choch_cannot_be_omitted(self):
        b = deepcopy(self.b)
        key = "SYNTHETIC:opposing"
        b["evidence_index"][key] = dict(
            category="TRANSITION",
            direction="BEARISH",
            available_at=NOW.isoformat(),
            details=dict(fresh=True, event_type="BEARISH_CHOCH"),
        )
        b["id"] = digest({k: v for k, v in b.items() if k != "id"})
        self.assertEqual(self.plan(bundle=b)["decision"], "BLOCKED")
        p = self.plan(bundle=b, raw=response(b, contradicting_evidence_ids=[key]))
        self.assertEqual(p["decision"], "BUY")
        self.assertIn(key, p["contradicting_evidence_ids"])

    def test_correct_bid_ask_sides_for_both_directions(self):
        for side in ("BUY", "SELL"):
            p = self.plan(side)
            s, _ = simulation.decision(simulation.initial(self.cfg), p, self.b)
            s, e = simulation.quote(s, tick(1), self.cfg, session())
            self.assertIsNotNone(s["position"], s["reasons"])
            self.assertEqual(
                Decimal(s["position"]["entry"]),
                Decimal("100") if side == "BUY" else Decimal("99.9"),
            )
            target = Decimal(p["take_profit_1"])
            q = (
                tick(2, float(target), float(target + Decimal(".1")))
                if side == "BUY"
                else tick(2, float(target - Decimal(".1")), float(target))
            )
            s, e = simulation.quote(s, q, self.cfg, session())
            t = next(x["trade"] for x in e if x["kind"] == "EXIT")
            self.assertEqual(Decimal(t["exit"]), target)

    def test_no_entry_from_pre_decision_quote_and_expiry(self):
        p = self.plan()
        s, _ = simulation.decision(simulation.initial(self.cfg), p, self.b)
        s, e = simulation.quote(s, tick(0), self.cfg, session())
        self.assertIsNone(s["position"])
        s, e = simulation.quote(s, tick(31), self.cfg, session())
        self.assertIsNone(s["position"])
        self.assertIn("PROPOSAL_EXPIRED_BEFORE_FILL", s["reasons"])

    def test_independent_positions_and_daily_latches(self):
        a, _ = self.enter()
        b = simulation.initial(self.cfg)
        c = simulation.initial(self.cfg)
        frozen = deepcopy(b)
        a["daily"][NOW.date().isoformat()]["latched"] = True
        a, _ = simulation.missing(a, "SYNTHETIC_GAP")
        self.assertEqual(b, frozen)
        self.assertEqual(c, frozen)
        self.assertIsNone(b["position"])
        self.assertEqual(a["position"]["state"], "UNRESOLVED")

    def test_missing_ticks_never_turn_into_later_winners(self):
        s, _ = self.enter()
        s, _ = simulation.missing(s, "MISSING_TICKS")
        s, e = simulation.quote(s, tick(2, 110.0, 110.1), self.cfg, session())
        self.assertEqual(s["counts"]["exits"], 0)
        self.assertEqual(s["position"]["state"], "UNRESOLVED")

    def test_session_and_rollover_restrictions(self):
        p = self.plan()
        s, _ = simulation.decision(simulation.initial(self.cfg), p, self.b)
        phase = session()
        phase["new_positions"] = False
        s, e = simulation.quote(s, tick(1), self.cfg, phase)
        self.assertIsNone(s["position"])
        c = deepcopy(self.cfg)
        c["costs"]["rollovers"] = [
            dict(
                timestamp=(NOW + timedelta(seconds=100)).isoformat(),
                announced_at=(NOW - timedelta(days=1)).isoformat(),
                long_per_lot="-1",
                short_per_lot="-1",
            )
        ]
        b = build(self.p, c, NOW.isoformat(), source_kind="SYNTHETIC_FIXTURE")
        p = self.plan(bundle=b, config_=c)
        s, _ = simulation.decision(simulation.initial(c), p, b)
        s, e = simulation.quote(s, tick(1), c, session())
        self.assertIsNone(s["position"])
        self.assertIn("ROLLOVER_MODEL_UNSUPPORTED", s["reasons"])

    def test_journal_recovery_replay_idempotency_and_config_binding(self):
        j = self.journal()
        self.point(j)
        key = self.request(j)
        before = j.state()["budget"]["calls"]
        j.record(
            dict(
                kind="RECOVERY", data=dict(at=(NOW + timedelta(seconds=1)).isoformat())
            )
        )
        self.assertEqual(j.state()["requests"][key]["status"], "INTERRUPTED")
        self.assertEqual(j.state()["budget"]["calls"], before)
        self.assertEqual(j.verify(replay=True)["status"], "MATCH")
        j2 = ComparisonJournal(
            j.root,
            self.cfg,
            "b" * 64,
            source_kind="SYNTHETIC_FIXTURE",
            models=j.binding["models"],
        )
        self.assertEqual(j.state(), j2.state())
        with self.assertRaises(ValueError):
            ComparisonJournal(
                j.root, config("50"), "b" * 64, source_kind="SYNTHETIC_FIXTURE"
            )

    def test_budget_is_durable_and_disabled_provider_is_not_active(self):
        c = deepcopy(self.cfg)
        c["budgets"]["max_calls"] = 0
        j = self.journal(config_=c)
        self.point(j)
        key = self.request(j)
        self.assertEqual(j.state()["requests"][key]["reason"], "BUDGET_EXHAUSTED")
        self.assertEqual(j.state()["budget"]["calls"], 0)
        j = self.journal(name="disabled")
        self.point(j)
        key = self.request(j, enabled=False)
        self.assertEqual(j.state()["requests"][key]["reason"], "PROVIDER_DISABLED")

    def test_malformed_response_is_redacted_before_storage(self):
        j = self.journal()
        self.point(j)
        key = self.request(j)
        self.result(j, key, raw={"api_key": "SUPER_SECRET"})
        self.assertNotIn(b"SUPER_SECRET", j.path.read_bytes())
        self.assertEqual(j.state()["proposals"]["C_AI_LED"]["decision"], "BLOCKED")
        j.verify(replay=True)

    def test_journal_atomic_failure_and_tamper_detection(self):
        j = self.journal()
        before = j.state()
        with patch("iat.three_engine.journal.reduce", side_effect=ValueError("fault")):
            with self.assertRaises(ValueError):
                self.point(j)
        self.assertEqual(before, j.state())
        self.assertEqual(j.verify()["events"], 0)
        self.point(j)
        with closing(sqlite3.connect(j.path)) as db:
            db.execute("UPDATE checkpoint SET body='{}'")
            db.commit()
        with self.assertRaises(ValueError):
            j.verify()

    def test_source_stage_b2_unchanged_and_engine_c_quote_path_replays(self):
        source = B2Journal(
            self.root / "source",
            b2config(),
            create=True,
            source_kind="SYNTHETIC_FIXTURE",
        )
        source.record(self.p)
        before = source.path.read_bytes()
        reader = SourceReader(source)
        j = ComparisonJournal(
            self.root / "linked",
            self.cfg,
            source.binding_sha,
            source_kind="SYNTHETIC_FIXTURE",
            create=True,
            models={"B_HYBRID": "SYNTHETIC_MODEL", "C_AI_LED": "SYNTHETIC_MODEL"},
        )
        record = next(reader.records(0))
        record["consumed_at"] = NOW.isoformat()
        j.record(dict(kind="SOURCE", data=record))
        self.point(j)
        key = self.request(j)
        self.result(j, key)
        source.record(raw_packet(1))
        record = next(reader.records(1))
        record["consumed_at"] = (NOW + timedelta(seconds=1)).isoformat()
        j.record(dict(kind="SOURCE", data=record))
        self.assertEqual(j.state()["engines"]["C_AI_LED"]["counts"]["entries"], 1)
        plan = j.state()["proposals"]["C_AI_LED"]
        target = Decimal(plan["take_profit_1"])
        p = raw_packet(2)
        p["quote"] = tick(2, float(target), float(target + Decimal(".1")))
        p["capture"]["ticks"] = [p["quote"]]
        source.record(p)
        record = next(reader.records(2))
        record["consumed_at"] = (NOW + timedelta(seconds=2)).isoformat()
        j.record(dict(kind="SOURCE", data=record))
        self.assertEqual(j.state()["engines"]["C_AI_LED"]["counts"]["exits"], 1)
        self.assertEqual(j.state()["engines"]["A_RULES"]["counts"]["entries"], 0)
        self.assertEqual(j.verify(replay=True)["status"], "MATCH")
        source.verify(replay=True)

    def test_hybrid_can_accept_reject_or_revise_without_changing_a(self):
        key = next(
            k
            for k, v in self.b["price_catalog"].items()
            if v["kind"] == "CLOSED_CANDLE_LOW"
        )
        details = dict(
            candidate="BUY_CANDIDATE",
            side="BUY",
            stop="98.99",
            setup_id="SYNTHETIC:baseline",
            strategies=[
                dict(
                    strategy_id=self.cfg["baseline_strategy_id"],
                    evaluations=[
                        dict(
                            status="QUALIFIES",
                            supporting_evidence=[key],
                            contradictory_evidence=[],
                        )
                    ],
                )
            ],
        )
        with patch("iat.three_engine.rules.assess", return_value=({}, details)):
            j = self.journal()
            self.point(j)
            a = deepcopy(j.state()["proposals"]["A_RULES"])
            self.assertEqual(a["decision"], "BUY")
            req = self.request(j, "B_HYBRID")
            self.assertEqual(j.state()["requests"][req]["status"], "PENDING")
            self.result(j, req, raw=response(self.b, "SELL"))
            self.assertEqual(j.state()["proposals"]["B_HYBRID"]["decision"], "SELL")
            self.assertEqual(j.state()["proposals"]["A_RULES"], a)
            j.verify(replay=True)

    def test_budget_tokens_pricing_and_no_automatic_retry(self):
        c = deepcopy(self.cfg)
        c["budgets"]["max_tokens"] = 1
        j = self.journal(config_=c)
        self.point(j)
        key = self.request(j)
        self.assertEqual(j.state()["requests"][key]["reason"], "BUDGET_EXHAUSTED")
        j = self.journal(name="retry")
        self.point(j)
        key = self.request(j)
        event = dict(
            kind="RESULT",
            data=dict(
                request_id=key,
                raw=None,
                response_at=(NOW + timedelta(seconds=1)).isoformat(),
                available_at=(NOW + timedelta(seconds=1)).isoformat(),
                code="PROVIDER_ERROR",
            ),
        )
        self.assertTrue(j.record(event))
        self.assertFalse(j.record(event))
        self.assertEqual(j.state()["budget"]["calls"], 1)

    def test_timeout_thread_does_not_block_reader_or_retry(self):
        source = B2Journal(
            self.root / "timeout-source",
            b2config(),
            create=True,
            source_kind="SYNTHETIC_FIXTURE",
        )
        source.record(self.p)
        j = ComparisonJournal(
            self.root / "timeout-journal",
            self.cfg,
            source.binding_sha,
            source_kind="SYNTHETIC_FIXTURE",
            create=True,
            models={"B_HYBRID": "DISABLED", "C_AI_LED": "SYNTHETIC_MODEL"},
        )
        latch = Event()
        self.addCleanup(latch.set)
        provider = TestReasoner(lambda p: (latch.wait(1), response(p["evidence"]))[1])
        clock = [NOW + timedelta(seconds=0.5)]
        mono = [0]
        runtime = ComparisonRuntime(
            SourceReader(source),
            j,
            providers={"C_AI_LED": provider},
            clock=lambda: clock[0],
            monotonic=lambda: mono[0],
        )
        runtime.step()
        self.assertEqual(len(provider.calls), 1)
        mono[0] = 11
        clock[0] = NOW + timedelta(seconds=11)
        runtime.drain()
        self.assertIn(
            "PROVIDER_TIMEOUT", j.state()["proposals"]["C_AI_LED"]["reason_codes"]
        )
        self.assertEqual(j.state()["budget"]["calls"], 1)
        latch.set()
        time.sleep(0.01)
        runtime.drain()
        self.assertEqual(j.state()["budget"]["calls"], 1)
        runtime.close()
        j.verify(replay=True)

    def test_partial_exit_is_unresolved_not_fabricated_profit(self):
        c = deepcopy(self.cfg)
        c["costs"].update(volume_min=".001", volume_step=".001")
        packet = deepcopy(self.p)
        packet["symbol_specification"].update(volume_min=0.001, volume_step=0.001)
        b = build(packet, c, NOW.isoformat(), source_kind="SYNTHETIC_FIXTURE")
        p = self.plan(
            bundle=b,
            config_=c,
            raw=response(
                b, target_refs=["R1", "R2", "R3"], tp_allocations=[".5", ".3", ".2"]
            ),
        )
        s, _ = simulation.decision(simulation.initial(c), p, b)
        s, _ = simulation.quote(s, tick(1), c, session())
        target = Decimal(p["take_profit_1"])
        s, e = simulation.quote(
            s, tick(2, float(target), float(target + Decimal(".1"))), c, session()
        )
        self.assertEqual(s["position"]["state"], "UNRESOLVED")
        self.assertEqual(s["closed"]["n"], 0)

    def test_risk_reduction_takes_effect_only_after_observed_trigger(self):
        p = self.plan(raw=response(self.b, risk_reduction="BREAKEVEN_AT_R1"))
        s, _ = self.enter(p)
        old_stop = s["position"]["stop"]
        threshold = Decimal(s["position"]["entry"]) + Decimal(
            s["position"]["initial_risk"]
        )
        s, e = simulation.quote(
            s,
            tick(2, float(threshold), float(threshold + Decimal(".1"))),
            self.cfg,
            session(),
        )
        self.assertEqual(s["position"]["stop"], s["position"]["entry"])
        self.assertNotEqual(old_stop, s["position"]["stop"])
        self.assertEqual(s["counts"]["exits"], 0)
        s, e = simulation.quote(s, tick(3, 100.0, 100.1), self.cfg, session())
        self.assertEqual(s["counts"]["exits"], 1)

    def test_time_exit_and_opposing_choch_use_later_quotes(self):
        s, _ = self.enter()
        b = deepcopy(self.b)
        b["cutoff"] = (NOW + timedelta(seconds=2)).isoformat()
        b["evidence_index"]["SYNTH:op"] = dict(
            category="TRANSITION",
            direction="BEARISH",
            details=dict(fresh=True, event_type="BEARISH_CHOCH"),
        )
        s, _ = simulation.invalidate(s, b)
        s, e = simulation.quote(s, tick(2), self.cfg, session())
        self.assertEqual(s["counts"]["exits"], 0)
        s, e = simulation.quote(s, tick(3), self.cfg, session())
        self.assertEqual(
            next(x["trade"]["reason"] for x in e if x["kind"] == "EXIT"), "INVALIDATED"
        )
        s, _ = self.enter()
        s, e = simulation.quote(s, tick(181), self.cfg, session())
        self.assertEqual(
            next(x["trade"]["reason"] for x in e if x["kind"] == "EXIT"), "TIME"
        )

    def test_pullback_and_breakout_wait_for_observed_quote(self):
        b = deepcopy(self.b)
        anchor = next(
            k
            for k, v in b["price_catalog"].items()
            if v["price"] == "99.0" and v["kind"] == "CLOSED_CANDLE_LOW"
        )
        # Use an actual supplied high as the breakout entry, and low as its structural stop.
        entry = next(
            k
            for k, v in b["price_catalog"].items()
            if v["kind"] == "CLOSED_CANDLE_HIGH"
        )
        p = self.plan(
            bundle=b,
            raw=response(
                b, entry_type="BREAKOUT", entry_anchor_id=entry, stop_anchor_id=anchor
            ),
        )
        self.assertEqual(p["decision"], "BUY")
        s, _ = simulation.decision(simulation.initial(self.cfg), p, b)
        s, _ = simulation.quote(s, tick(1), self.cfg, session())
        self.assertIsNone(s["position"])
        s, e = simulation.quote(s, tick(2, 100.9, 101.0), self.cfg, session())
        self.assertIsNotNone(s["position"])

    def test_published_json_schemas_and_rechecksummed_safety_forgery(self):
        import jsonschema
        from iat.three_engine.contracts import proposal_schema, validate_proposal

        p = self.plan()
        jsonschema.Draft202012Validator(proposal_schema()).validate(p)
        validate_proposal(p)
        for key, value in [
            ("execution_allowed", True),
            ("confidence_probability", 0.85),
            ("signal", "BUY"),
        ]:
            changed = deepcopy(p)
            changed[key] = value
            changed["decision_id"] = digest(
                {k: v for k, v in changed.items() if k != "decision_id"}
            )
            with self.assertRaises(ValueError):
                validate_proposal(changed)
        path = (
            Path(__file__).resolve().parents[1]
            / "schemas/three-engine-proposal-v1.schema.json"
        )
        self.assertEqual(json.loads(path.read_text()), proposal_schema())

    def test_no_broker_or_order_capability_and_old_b2_interface_unchanged(self):
        root = Path(__file__).resolve().parents[1]
        for path in (root / "iat/three_engine").glob("*.py"):
            tree = ast.parse(path.read_text())
            attrs = {
                n.func.attr
                for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            }
            self.assertFalse(
                attrs
                & {
                    "order_send",
                    "order_check",
                    "positions_get",
                    "orders_get",
                    "login",
                    "initialize",
                }
            )
            imports = [
                n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
            ]
            self.assertFalse(
                any(
                    v.startswith(("MetaTrader5", "iat.demo_execution")) for v in imports
                )
            )

    def test_comparison_dashboard_loopback_get_only_and_safe_rendering(self):
        from iat.three_engine.dashboard import create_dashboard

        j = self.journal()
        self.point(j)
        runtime = SimpleNamespace(latest=lambda: j.snapshot())
        client = create_dashboard(runtime).test_client()
        data = client.get("/research/v1/comparison")
        self.assertEqual(data.status_code, 200)
        self.assertFalse(data.json["execution_allowed"])
        self.assertEqual(data.json["orders_requested"], 0)
        self.assertEqual(client.post("/research/v1/comparison").status_code, 405)
        self.assertEqual(
            client.get(
                "/research/v1/comparison", environ_base={"REMOTE_ADDR": "10.0.0.1"}
            ).status_code,
            403,
        )
        with client.get("/") as page:
            self.assertIn(b"Broker execution disabled", page.data)

    def test_stop_distance_uses_bid_for_buy_and_ask_for_sell(self):
        from iat.three_engine.contracts import feasibility

        for side, entry, stop, target in [
            ("BUY", "100", "99.95", "101"),
            ("SELL", "99.9", "99.95", "99"),
        ]:
            with self.assertRaisesRegex(ValueError, "STOP_DISTANCE_INVALID"):
                feasibility(
                    self.b,
                    self.cfg,
                    side,
                    Decimal(entry),
                    Decimal(stop),
                    [Decimal(target)],
                    ["1"],
                    "0.5",
                )

    def test_pricing_unknown_prevents_real_provider_call_and_snapshot_not_run(self):
        j = self.journal()
        self.point(j)
        key = digest(
            ["C_AI_LED", self.b["id"], "SYNTHETIC_MODEL", PROTOCOL["prompt_version"]]
        )
        j.record(
            dict(
                kind="REQUEST",
                data=dict(
                    request_id=key,
                    engine="C_AI_LED",
                    bundle_id=self.b["id"],
                    model="SYNTHETIC_MODEL",
                    at=(NOW + timedelta(seconds=0.2)).isoformat(),
                    enabled=True,
                    actual_ai=True,
                    blocked_reason=None,
                ),
            )
        )
        self.assertEqual(j.state()["requests"][key]["reason"], "AI_PRICING_UNAVAILABLE")
        self.assertEqual(
            j.snapshot()["engines"]["C_AI_LED"]["research_status"], "NOT_RUN"
        )

    def test_source_future_timestamp_and_dropped_prefix_fail_closed(self):
        source = B2Journal(
            self.root / "future-source",
            b2config(),
            create=True,
            source_kind="SYNTHETIC_FIXTURE",
        )
        source.record(self.p)
        record = next(SourceReader(source).records(0))
        record["consumed_at"] = (NOW - timedelta(seconds=1)).isoformat()
        j = ComparisonJournal(
            self.root / "future-target",
            self.cfg,
            source.binding_sha,
            source_kind="SYNTHETIC_FIXTURE",
            create=True,
        )
        with self.assertRaisesRegex(ValueError, "FUTURE_SOURCE"):
            j.record(dict(kind="SOURCE", data=record))
        record["consumed_at"] = NOW.isoformat()
        record["seq"] = 2
        with self.assertRaisesRegex(ValueError, "PREFIX"):
            j.record(dict(kind="SOURCE", data=record))
        self.assertEqual(j.state()["source_cursor"], 0)

    def test_disabled_latency_and_performance_are_not_invented_measurements(self):
        j = self.journal()
        self.point(j)
        self.request(j, enabled=False)
        q = next(
            v["data"]
            for v in j.state()["queue"]
            if v["kind"] == "PROPOSAL" and v["data"]["engine"] == "C_AI_LED"
        )
        s, _ = simulation.decision(simulation.initial(self.cfg), q, self.b)
        m = simulation.metrics(s)
        self.assertIsNone(m["average_decision_latency_seconds"])
        self.assertIsNone(m["win_rate"])
        self.assertIsNone(m["qualified_performance_metrics"])

    def test_sdk_openai_structured_plan_and_private_thoughts_not_returned(self):
        from iat.three_engine.providers import OpenAIReasoner

        captured = []
        raw = response(self.b)

        class Stream:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def iter_bytes(self, **kw):
                yield json.dumps(
                    dict(
                        status="completed",
                        output=[
                            dict(type="reasoning", summary="PRIVATE_THOUGHT_SECRET"),
                            dict(
                                type="message",
                                role="assistant",
                                content=[
                                    dict(type="output_text", text=json.dumps(raw))
                                ],
                            ),
                        ],
                    )
                ).encode()

        def create(**kw):
            captured.append(kw)
            return Stream()

        client = SimpleNamespace(
            responses=SimpleNamespace(
                with_streaming_response=SimpleNamespace(create=create)
            ),
            close=lambda: None,
        )
        provider = OpenAIReasoner("SYNTHETIC_ONLY_KEY", "test-model", client=client)
        out = provider.request({"evidence": self.b, "engine": "C_AI_LED"})
        self.assertEqual(out, raw)
        self.assertNotIn("PRIVATE_THOUGHT", json.dumps(out))
        self.assertEqual(captured[0]["tools"], [])
        self.assertFalse(captured[0]["store"])
        self.assertIn("untrusted", captured[0]["instructions"])

    def test_sdk_gemini_structured_plan_no_function_calls_or_thought_logging(self):
        from iat.three_engine.providers import GeminiReasoner

        captured = []
        raw = response(self.b)

        class Part:
            thought = False
            text = json.dumps(raw)

            def model_dump(self, **kw):
                return {"text": self.text}

        chunk = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    index=0,
                    content=SimpleNamespace(role="model", parts=[Part()]),
                    finish_reason="STOP",
                )
            ],
            prompt_feedback=None,
            model_dump_json=lambda **kw: "{}",
        )

        class Stream:
            def __iter__(self):
                return iter([chunk])

            def close(self):
                pass

        def generate(**kw):
            captured.append(kw)
            return Stream()

        client = SimpleNamespace(
            models=SimpleNamespace(generate_content_stream=generate), close=lambda: None
        )
        provider = GeminiReasoner("SYNTHETIC_ONLY_KEY", "gemini-test", client=client)
        self.assertEqual(
            provider.request({"evidence": self.b, "engine": "C_AI_LED"}), raw
        )
        self.assertEqual(captured[0]["config"]["tools"], [])
        self.assertTrue(captured[0]["config"]["automatic_function_calling"]["disable"])
        self.assertFalse(captured[0]["config"]["store"])

    def test_sdk_failures_are_redacted_not_echoed(self):
        from iat.three_engine.providers import OpenAIReasoner, ProviderError

        def fail(**kw):
            raise RuntimeError("SECRET_CREDENTIAL")

        client = SimpleNamespace(
            responses=SimpleNamespace(
                with_streaming_response=SimpleNamespace(create=fail)
            ),
            close=lambda: None,
        )
        with self.assertRaises(ProviderError) as caught:
            OpenAIReasoner("SYNTHETIC_ONLY_KEY", "test-model", client=client).request(
                {"evidence": self.b}
            )
        self.assertEqual(str(caught.exception), "PROVIDER_ERROR")
        self.assertNotIn("SECRET", str(caught.exception))

    def test_fifty_dollar_account_can_accept_a_genuinely_affordable_stop(self):
        c = config("50")
        packet = deepcopy(self.p)
        packet["candles"]["M1"][-1]["low"] = 99.89
        b = build(packet, c, NOW.isoformat(), source_kind="SYNTHETIC_FIXTURE")
        anchor = next(
            k
            for k, v in b["price_catalog"].items()
            if v["kind"] == "CLOSED_CANDLE_LOW" and v["price"] == "99.89"
        )
        raw = response(b)
        raw.update(
            stop_anchor_id=anchor,
            supporting_evidence_ids=[anchor],
            market_reasoning=[
                dict(interpretation="REACTION_ZONE", evidence_id=anchor, role="SUPPORT")
            ],
        )
        p = self.plan(bundle=b, config_=c, raw=raw)
        self.assertEqual(p["decision"], "BUY", p["reason_codes"])
        self.assertLessEqual(Decimal(p["risk_amount"]), Decimal(".25"))
        self.assertEqual(Decimal(p["lot_size"]), Decimal(".01"))

    def test_latency_uses_common_cutoff_not_just_provider_roundtrip(self):
        p = proposal(
            "C_AI_LED",
            self.b,
            response(self.b),
            (NOW + timedelta(seconds=1)).isoformat(),
            self.cfg,
            model="SYNTHETIC_MODEL",
            request_at=(NOW + timedelta(seconds=0.4)).isoformat(),
            response_at=(NOW + timedelta(seconds=0.9)).isoformat(),
        )
        self.assertEqual(Decimal(p["latency_seconds"]), 1)
        self.assertEqual(Decimal(p["provider_latency_seconds"]), Decimal(".5"))
        self.assertEqual(Decimal(p["market_to_decision_seconds"]), 1)

    def test_full_full_prefix_and_future_append_reproduce_frozen_assessments(self):
        from iat.three_engine.example import run

        a, full = run(self.root / "repeat-a")
        b, other = run(self.root / "repeat-b")
        prefix_report, prefix = run(self.root / "prefix", prefix_records=2)
        self.assertEqual(a, b)
        self.assertEqual(
            full.verify(replay=True)["log_sha256"],
            other.verify(replay=True)["log_sha256"],
        )
        with full.connection(readonly=True) as db:
            full_rows = [
                tuple(r) for r in db.execute("SELECT * FROM events ORDER BY seq")
            ]
        with prefix.connection(readonly=True) as db:
            prefix_rows = [
                tuple(r) for r in db.execute("SELECT * FROM events ORDER BY seq")
            ]
        self.assertEqual(full_rows[: len(prefix_rows)], prefix_rows)
        self.assertEqual(prefix.state()["proposals"], full.state()["proposals"])
        self.assertEqual(a["engines"]["A_RULES"]["decision"], "WAIT")
        self.assertEqual(a["engines"]["B_HYBRID"]["decision"], "BLOCKED")
        self.assertEqual(a["engines"]["C_AI_LED"]["decision"], "BUY")
        self.assertEqual(a["engines"]["C_AI_LED"]["metrics"]["entries"], 1)
        self.assertEqual(a["engines"]["C_AI_LED"]["metrics"]["exits"], 1)
        self.assertEqual(prefix_report["engines"]["C_AI_LED"]["metrics"]["exits"], 0)

    def test_offline_cli_replay_does_not_import_mt5_or_change_sources(self):
        from iat.three_engine.example import run
        from diagnostics.run_three_engine_research import main

        r, j = run(self.root / "cli-example")
        source = j.root.parent / "source/shadow.sqlite3"
        before = source.read_bytes()
        target_before = j.path.read_bytes()
        with redirect_stdout(StringIO()) as output:
            code = main(
                [
                    "--source-journal-directory",
                    str(source.parent),
                    "--journal-directory",
                    str(j.root),
                    "--research-config",
                    str(j.root.parent / "research-config.json"),
                    "--synthetic-source",
                    "--verify-only",
                ]
            )
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(before, source.read_bytes())
        self.assertEqual(target_before, j.path.read_bytes())

    def test_model_binding_is_immutable(self):
        j = self.journal()
        self.point(j)
        with self.assertRaisesRegex(ValueError, "MODEL_BINDING"):
            self.request(j, model="DIFFERENT_MODEL")
        self.assertEqual(j.state()["budget"]["calls"], 0)

    def test_reversal_requires_referenced_confirmed_directional_sweep(self):
        # Explicitly injected SYNTHETIC evidence tests the contract gate; not broker observations.
        for side, pool in (("BUY", "SWING_LOWS"), ("SELL", "SWING_HIGHS")):
            b = deepcopy(self.b)
            key = "SYNTHETIC:sweep"
            entry = next(
                k
                for k, v in b["price_catalog"].items()
                if v["kind"]
                == ("CLOSED_CANDLE_HIGH" if side == "BUY" else "CLOSED_CANDLE_LOW")
            )
            for event in (
                "LEVEL_PENETRATION",
                "AMBIGUOUS_EVENT",
                "SUSTAINED_BREAKOUT",
                "CONFIRMED_SWEEP",
            ):
                b["evidence_index"][key] = dict(
                    category="LIQUIDITY",
                    available_at=NOW.isoformat(),
                    details=dict(event_type=event, pool_kind=pool),
                )
                b["id"] = digest({k: v for k, v in b.items() if k != "id"})
                raw = response(b, side, entry_type="REVERSAL", entry_anchor_id=entry)
                raw["supporting_evidence_ids"].append(key)
                p = self.plan(side, bundle=b, raw=raw)
                self.assertEqual(
                    p["decision"],
                    side if event == "CONFIRMED_SWEEP" else "BLOCKED",
                    p["reason_codes"],
                )
            raw["supporting_evidence_ids"].remove(key)
            self.assertIn(
                "CONFIRMED_REVERSAL_EVIDENCE_REQUIRED",
                self.plan(side, bundle=b, raw=raw)["reason_codes"],
            )
            raw["supporting_evidence_ids"].append(key)
            b["evidence_index"][key]["details"]["pool_kind"] = (
                "SWING_HIGHS" if side == "BUY" else "SWING_LOWS"
            )
            b["id"] = digest({k: v for k, v in b.items() if k != "id"})
            raw["bundle_id"] = b["id"]
            self.assertEqual(self.plan(side, bundle=b, raw=raw)["decision"], "BLOCKED")

    def test_pullback_requires_a_later_executable_side_trigger(self):
        for side in ("BUY", "SELL"):
            b = deepcopy(self.b)
            # Add a genuine OHLC low/high at the pullback level in explicitly synthetic closed data.
            row = b["candles"]["M1"][-1]
            row["low" if side == "BUY" else "high"] = 99.8 if side == "BUY" else 100.2
            # Rebuild the complete evidence from this fixture instead of inventing a price catalog level.
            packet = deepcopy(self.p)
            packet["candles"]["M1"][-1] = row
            packet["candles"]["M5"][-1]["low" if side == "BUY" else "high"] = (
                99.0 if side == "BUY" else 101.0
            )
            b = build(
                packet, self.cfg, NOW.isoformat(), source_kind="SYNTHETIC_FIXTURE"
            )
            entry = next(
                k
                for k, v in b["price_catalog"].items()
                if v["price"] == ("99.8" if side == "BUY" else "100.2")
            )
            p = self.plan(
                side,
                bundle=b,
                raw=response(b, side, entry_type="PULLBACK", entry_anchor_id=entry),
            )
            self.assertEqual(p["decision"], side, p["reason_codes"])
            s, _ = simulation.decision(simulation.initial(self.cfg), p, b)
            s, _ = simulation.quote(s, tick(1), self.cfg, session())
            self.assertIsNone(s["position"])
            q = tick(2, 99.7, 99.8) if side == "BUY" else tick(2, 100.2, 100.3)
            s, events = simulation.quote(s, q, self.cfg, session())
            self.assertIsNotNone(s["position"], s["reasons"])
            self.assertEqual(
                next(
                    e["position"]["entry_quote_id"]
                    for e in events
                    if e["kind"] == "ENTRY"
                ),
                q["id"],
            )

    def test_budget_includes_prompt_schema_and_provider_envelope_before_transport(self):
        from iat.three_engine.providers import PROMPT

        j = self.journal()
        self.point(j)
        key = self.request(j)
        encoded = json.dumps(
            request_packet(j.state(), self.b, "C_AI_LED"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        schema = json.dumps(
            response_schema(), sort_keys=True, separators=(",", ":")
        ).encode()
        expected = (
            len(encoded)
            + len(PROMPT.encode())
            + len(schema)
            + PROTOCOL["provider_envelope_token_reserve"]
            + PROTOCOL["output_tokens"]
        )
        self.assertEqual(j.state()["requests"][key]["reserved_tokens"], expected)
        c = deepcopy(self.cfg)
        c["budgets"]["max_tokens"] = len(encoded) + PROTOCOL["output_tokens"]
        blocked = self.journal("budget-without-prompt", config_=c)
        self.point(blocked)
        key = self.request(blocked)
        self.assertEqual(blocked.state()["requests"][key]["reason"], "BUDGET_EXHAUSTED")
        self.assertEqual(blocked.state()["budget"]["calls"], 0)

    def test_final_availability_follows_risk_validation_not_just_model_receipt(self):
        from concurrent.futures import Future

        j = self.journal()
        self.point(j)
        key = self.request(j)
        future = Future()
        future.set_result(
            dict(
                raw=response(self.b),
                response_at=(NOW + timedelta(seconds=0.5)).isoformat(),
                code=None,
            )
        )
        clock_at = [NOW + timedelta(seconds=0.5)]
        runtime = ComparisonRuntime.__new__(ComparisonRuntime)
        runtime.journal = j
        runtime.jobs = {
            key: dict(future=future, recorded=False, engine="C_AI_LED", started=0)
        }
        runtime.clock = lambda: clock_at[0]
        runtime.monotonic = lambda: 0

        def slow_validation(*args, **kwargs):
            p = proposal(*args, **kwargs)
            clock_at[0] += timedelta(seconds=0.5)
            return p

        with patch("iat.three_engine.runtime.proposal", side_effect=slow_validation):
            runtime.drain()
        p = j.state()["proposals"]["C_AI_LED"]
        self.assertEqual(p["decision"], "BUY")
        self.assertEqual(
            p["decision_available_at"], (NOW + timedelta(seconds=1)).isoformat()
        )
        s, _ = simulation.decision(simulation.initial(self.cfg), p, self.b)
        s, _ = simulation.quote(s, tick(0.75), self.cfg, session())
        self.assertEqual(s["counts"]["entries"], 0)
        s, _ = simulation.quote(s, tick(1.1), self.cfg, session())
        self.assertEqual(s["counts"]["entries"], 1)
        self.assertEqual(j.verify(replay=True)["status"], "MATCH")
