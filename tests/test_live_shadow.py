"""Labeled SYNTHETIC Stage-B.2 tests; no terminal, credential, model or broker access."""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from contextlib import closing, redirect_stdout
from io import StringIO
from unittest.mock import patch
import ast, json, sqlite3, tempfile, unittest
from iat.live_shadow.feed import observed_tick, ShadowFeed
from iat.live_shadow.policy import configuration, session_diagnostics
from iat.live_shadow import engine, LABEL
from iat.live_shadow.processor import initial_state, reduce_packet
from iat.live_shadow.store import Journal
from iat.live_shadow.runtime import ShadowRuntime
from iat.live_dashboard import create_dashboard
from iat.intelligence.strategy_replay import digest
from iat.strategy_qualification.specs import specifications
from iat.strategy_qualification.backtest import Costs
from test_live_observer import MockMT5, NOW, WaveMT5
from test_strategy_qualification import costs


def cfg():
    return dict(
        version=1,
        strategy_id=specifications()[0].strategy_id,
        costs=asdict(costs(known_at=(NOW - timedelta(days=1)).isoformat())),
        mode="UNQUALIFIED_SHADOW_RESEARCH",
        label=LABEL,
    )


def tick(offset=0, bid=99.9, ask=100.0):
    at = NOW + timedelta(seconds=offset)
    return observed_tick(
        dict(
            time=int(at.timestamp()),
            time_msc=int(at.timestamp() * 1000),
            bid=bid,
            ask=ask,
        ),
        at,
    )


def session(**kw):
    return dict(
        phase="FULL_TRADING",
        calendar_status="VERIFIED_DECLARATIONS",
        quote_available=True,
        new_positions=True,
        close_positions=True,
        operational_eligible=True,
        **kw
    )


def symbol():
    return dict(
        trade_contract_size=100.0,
        trade_tick_size=0.01,
        trade_stops_level=1,
        point=0.01,
        digits=2,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        currency_profit="USD",
        trade_calc_mode=0,
    )


def decision(side="BUY", setup="SYNTHETIC:anchor", at=NOW):
    r = dict(
        candidate=side + "_CANDIDATE",
        side=side,
        stop="99" if side == "BUY" else "101",
        setup_id=setup,
        available_at=at.isoformat(),
        segmentation={
            "strategy_version": specifications()[0].sha256,
            "session": "FULL_TRADING",
            "calendar_status": "VERIFIED_DECLARATIONS",
            "alignment": side,
            "regime": "SYNTHETIC",
        },
        invalidated_setup_ids=[],
    )
    r["id"] = digest(r)
    return r


def raw_packet(offset=0):
    at = NOW + timedelta(seconds=offset)
    q = tick(offset)
    end = at.replace(second=0, microsecond=0)
    candles = {
        tf: [
            dict(
                timestamp=(end - timedelta(minutes=period * (count - i))).isoformat(),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
            )
            for i in range(count)
        ]
        for tf, period, count in [("M1", 1, 100), ("M5", 5, 40)]
    }
    return dict(
        received_at=at.isoformat(),
        quote=q,
        capture=dict(
            start=(at - timedelta(seconds=1)).isoformat(),
            end=at.isoformat(),
            status="OBSERVED_RANGE",
            reason_codes=[],
            ticks=[q],
            assurance="TERMINAL_RETURNED_OBSERVATIONS_NOT_PROVIDER_CAPTURE_COMPLETENESS_PROOF",
        ),
        candles=candles,
        raw_candles={},
        identity=dict(
            broker="EXNESS_COMPANY_LABEL_MATCH",
            symbol="XAUUSD",
            account_mode="DEMO",
            assurance="OBSERVED_COMPANY_LABEL_NOT_AUTHENTICATED_ACCOUNT_BINDING",
            trading_permissions_disabled=True,
        ),
        symbol_specification=symbol(),
        errors=[],
        observer_snapshot_id="a" * 64,
        observer_reason_codes=[],
    )


class TickMT5(MockMT5):
    def account_info(self):
        a = super().account_info()
        a.company = "Exness Technologies Ltd"
        return a

    def symbol_info(self, name):
        return SimpleNamespace(visible=self.visible, **symbol())

    def symbol_info_tick(self, name):
        t = super().symbol_info_tick(name)
        t.ask = self.bid + 0.1
        return t

    COPY_TICKS_ALL = 0

    def copy_ticks_range(self, name, start, end, flags):
        t = self.symbol_info_tick(name)
        return (
            [dict(time=t.time, time_msc=t.time_msc, bid=t.bid, ask=t.ask)]
            if start.timestamp() <= t.time <= end.timestamp()
            else []
        )


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="iat shadow SYNTHETIC ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = cfg()

    def journal(self, config=None):
        return Journal(
            self.root / "journal",
            config or self.config,
            create=True,
            source_kind="SYNTHETIC_FIXTURE",
        )

    def enter(self, side="BUY"):
        state, _ = engine.decision_event(engine.initial(), decision(side))
        state, effects = engine.quote_event(
            state,
            tick(
                1, 99.9 if side == "BUY" else 100.0, 100.0 if side == "BUY" else 100.1
            ),
            self.config,
            session(),
            symbol(),
        )
        return state, effects

    def test_bid_ask_spread_and_provenance(self):
        q = tick()
        self.assertEqual(Decimal(q["spread"]), Decimal(".1"))
        self.assertEqual(q["price_basis"], "OBSERVED_MT5_BID_ASK")
        self.assertEqual(q["id"], digest({k: v for k, v in q.items() if k != "id"}))

    def test_missing_ask_never_estimated(self):
        with self.assertRaises(ValueError):
            observed_tick(dict(time=0, time_msc=0, bid=1), NOW)

    def test_invalid_bid_ask_rejected(self):
        for bid, ask in [
            (0, 1),
            (2, 1),
            (True, 2),
            (1, float("nan")),
            (float("inf"), 2),
        ]:
            with self.assertRaises(ValueError):
                tick(bid=bid, ask=ask)

    def test_stale_future_and_millisecond_timestamp_rejected(self):
        for shift in (-3, 1):
            at = NOW + timedelta(seconds=shift)
            with self.assertRaises(ValueError):
                observed_tick(
                    dict(
                        time=int(at.timestamp()),
                        time_msc=int(at.timestamp() * 1000),
                        bid=1.0,
                        ask=2.0,
                    ),
                    NOW,
                )
        with self.assertRaises(ValueError):
            observed_tick(
                dict(time=int(NOW.timestamp()), time_msc=1, bid=1.0, ask=2.0), NOW
            )

    def test_read_only_capability_demo_and_permission_gates(self):
        module = TickMT5()
        feed = ShadowFeed(module)
        feed.preflight()
        q = feed.quote(NOW)
        self.assertIn("ask", q)
        self.assertEqual(module.orders, 0)
        self.assertFalse(hasattr(feed, "order_send"))
        for mode in (1, 2, None):
            module.mode = mode
            with self.assertRaises(Exception):
                feed.preflight()
        module.mode = 0
        module.allowed = True
        with self.assertRaises(Exception):
            feed.preflight()

    def test_broker_mismatch_is_explicit(self):
        module = TickMT5()
        module.account_info = lambda: SimpleNamespace(trade_mode=0, company="Other")
        with self.assertRaisesRegex(Exception, "Company"):
            ShadowFeed(module).preflight()

    def test_duplicate_ticks_collapsed_but_same_time_different_prices_ambiguous(self):
        m = TickMT5()
        f = ShadowFeed(m)
        row = dict(
            time=int(NOW.timestamp()) - 1,
            time_msc=(int(NOW.timestamp()) - 1) * 1000,
            bid=100.0,
            ask=100.1,
        )
        m.copy_ticks_range = lambda *a: [row, row]
        f = ShadowFeed(m)
        self.assertEqual(len(f.capture(NOW - timedelta(seconds=2), NOW)["ticks"]), 1)
        m.copy_ticks_range = lambda *a: [row, dict(row, bid=99.0)]
        f = ShadowFeed(m)
        r = f.capture(NOW - timedelta(seconds=2), NOW)
        self.assertEqual(r["status"], "UNAVAILABLE")
        self.assertEqual(r["ticks"], [])

    def test_missing_tick_history_and_capture_gap_block(self):
        m = TickMT5()
        m.copy_ticks_range = None
        f = ShadowFeed(m)
        self.assertIn("TICK_HISTORY_UNAVAILABLE", f.capture(NOW, NOW)["reason_codes"])
        self.assertIn(
            "CAPTURE_INTERVAL_EXCEEDED",
            f.capture(NOW - timedelta(seconds=61), NOW)["reason_codes"],
        )

    def test_missing_calendar_diagnostic_is_not_market_closure(self):
        r = session_diagnostics(None, NOW, quote=tick())
        self.assertFalse(r["operational_eligible"])
        self.assertIn("SESSION_CALENDAR_MISSING", r["reason_codes"])
        self.assertNotIn("ACTUAL_MARKET_CLOSURE", r["reason_codes"])

    def test_buy_ask_sell_bid_correct_exit_sides(self):
        for side in ("BUY", "SELL"):
            s, e = self.enter(side)
            p = s["position"]
            self.assertEqual(Decimal(p["entry"]), Decimal("100"))
            self.assertEqual(p["label"], LABEL)
            q = tick(2, 102.0, 102.1) if side == "BUY" else tick(2, 97.9, 98.0)
            s, e = engine.quote_event(s, q, self.config, session(), symbol())
            exit_ = next(v["trade"] for v in e if v["kind"] == "EXIT")
            self.assertEqual(
                Decimal(exit_["exit"]),
                Decimal("102") if side == "BUY" else Decimal("98"),
            )
            self.assertEqual(exit_["reason"], "TP")
            self.assertFalse(exit_["qualified_performance_eligible"])

    def test_no_same_timestamp_or_retrospective_entry(self):
        s, _ = engine.decision_event(engine.initial(), decision())
        s, e = engine.quote_event(s, tick(), self.config, session(), symbol())
        self.assertIsNone(s["position"])
        s, e = engine.quote_event(s, tick(3), self.config, session(), symbol())
        self.assertIsNone(s["position"])
        self.assertIn("NEXT_QUOTE_HORIZON_EXCEEDED", s["rejections"])

    def test_stop_gap_and_target_no_optimistic_bonus(self):
        s, _ = self.enter()
        s, e = engine.quote_event(
            s, tick(2, 97.0, 97.1), self.config, session(), symbol()
        )
        self.assertEqual(
            next(x["trade"]["exit"] for x in e if x["kind"] == "EXIT"), "97.00"
        )
        s, _ = self.enter()
        s, e = engine.quote_event(
            s, tick(2, 110.0, 110.1), self.config, session(), symbol()
        )
        self.assertEqual(
            Decimal(next(x["trade"]["exit"] for x in e if x["kind"] == "EXIT")),
            Decimal("102"),
        )

    def test_missing_capture_freezes_unresolved_no_later_fabricated_exit(self):
        s, _ = self.enter()
        s, e = engine.missing_event(s, "TICK_CAPTURE_UNAVAILABLE")
        self.assertEqual(s["position"]["state"], "UNRESOLVED")
        s, e = engine.quote_event(
            s, tick(2, 110.0, 110.1), self.config, session(), symbol()
        )
        self.assertFalse(any(x["kind"] == "EXIT" for x in e))
        self.assertIsNone(engine.summary(s)["unrealized_pnl"])

    def test_contract_mismatch_blocks(self):
        s, _ = engine.decision_event(engine.initial(), decision())
        s, e = engine.quote_event(
            s, tick(1), self.config, session(), dict(symbol(), trade_contract_size=1.0)
        )
        self.assertIsNone(s["position"])

    def test_actual_closure_blocks_new_entry(self):
        s, _ = engine.decision_event(engine.initial(), decision())
        p = session()
        p["new_positions"] = False
        s, e = engine.quote_event(s, tick(1), self.config, p, symbol())
        self.assertIsNone(s["position"])
        self.assertIn("NEW_POSITION_SESSION_BLOCKED", s["rejections"])

    def test_commission_and_slippage_accounting(self):
        c = deepcopy(self.config)
        c["costs"].update(
            commission_per_side_per_lot="1", fee_per_side_per_lot="1", slippage_ticks=1
        )
        s, _ = engine.decision_event(engine.initial(), decision())
        s, _ = engine.quote_event(s, tick(1), c, session(), symbol())
        s, e = engine.quote_event(s, tick(2, 97.0, 97.1), c, session(), symbol())
        t = next(v["trade"] for v in e if v["kind"] == "EXIT")
        self.assertEqual(Decimal(t["net_pnl"]), Decimal("-3.06"))
        self.assertEqual(Decimal(t["commission_and_fees"]), Decimal(".04"))

    def test_duplicate_anchor_and_one_exposure(self):
        s, _ = self.enter()
        s, _ = engine.decision_event(s, decision(setup="other"))
        s, e = engine.quote_event(
            s, tick(2, 102.0, 102.1), self.config, session(), symbol()
        )
        self.assertIsNone(s["position"])
        s, _ = engine.decision_event(s, decision())
        s, e = engine.quote_event(s, tick(1.5), self.config, session(), symbol())
        self.assertIsNone(s["position"])

    def test_time_and_anchor_invalidation_exits(self):
        s, _ = self.enter()
        r = decision(at=NOW + timedelta(seconds=2))
        r.update(candidate="WAIT", invalidated_setup_ids=["SYNTHETIC:anchor"])
        s, _ = engine.decision_event(s, r)
        s, e = engine.quote_event(s, tick(3), self.config, session(), symbol())
        self.assertEqual(
            next(x["trade"]["reason"] for x in e if x["kind"] == "EXIT"), "INVALIDATED"
        )
        s, _ = self.enter()
        s, e = engine.quote_event(s, tick(901), self.config, session(), symbol())
        self.assertEqual(
            next(x["trade"]["reason"] for x in e if x["kind"] == "EXIT"), "TIME"
        )

    def test_journal_idempotency_restart_and_replay(self):
        j = self.journal()
        p = raw_packet()
        self.assertTrue(j.record(p))
        self.assertFalse(j.record(p))
        before = j.snapshot()
        j2 = Journal(j.root, self.config, source_kind="SYNTHETIC_FIXTURE")
        self.assertEqual(before, j2.snapshot())
        self.assertEqual(j2.verify(replay=True)["status"], "MATCH")

    def test_repeatable_and_future_append_does_not_change_frozen_decision(self):
        j = self.journal()
        p = raw_packet()
        j.record(p)
        original = j.state()["last_decision"]
        p2 = raw_packet(1)
        j.record(p2)
        self.assertEqual(original, j.state()["last_decision"])
        self.assertEqual(j.verify(replay=True)["status"], "MATCH")

    def test_journal_config_source_and_calendar_cannot_change_on_restart(self):
        j = self.journal()
        with self.assertRaises(ValueError):
            Journal(j.root, self.config, source_kind="LIVE_MT5_OBSERVATIONS")
        c = deepcopy(self.config)
        c["costs"]["max_spread"] = "1"
        with self.assertRaises(ValueError):
            Journal(j.root, c, source_kind="SYNTHETIC_FIXTURE")

    def test_transaction_failure_has_no_partial_event_or_checkpoint(self):
        j = self.journal()
        before = j.state()
        with patch(
            "iat.live_shadow.store.reduce_packet", side_effect=RuntimeError("fault")
        ):
            with self.assertRaises(RuntimeError):
                j.record(raw_packet())
        self.assertEqual(j.state(), before)
        self.assertEqual(j.verify()["event_count"], 0)
        self.assertTrue(j.record(raw_packet()))

    def test_checkpoint_audit_source_and_projection_tampering_rejected(self):
        j = self.journal()
        j.record(raw_packet())
        with closing(sqlite3.connect(j.path)) as db:
            db.execute("UPDATE checkpoint SET body='{}'")
            db.commit()
        with self.assertRaises(ValueError):
            Journal(j.root, self.config, source_kind="SYNTHETIC_FIXTURE")

    def test_unsafe_fields_never_written(self):
        j = self.journal()
        p = raw_packet()
        p["identity"]["server"] = "DO_NOT_STORE"
        with self.assertRaises(ValueError):
            j.record(p)
        self.assertEqual(j.verify()["event_count"], 0)
        self.assertNotIn(b"DO_NOT_STORE", j.path.read_bytes())

    def test_clock_backward_is_recorded_blocked(self):
        j = self.journal()
        j.record(raw_packet())
        j.record(raw_packet(-1))
        self.assertIn(
            "CLOCK_MOVED_BACKWARD_OR_REPEAT", j.state()["engine"]["rejections"]
        )
        j.verify(replay=True)

    def test_closed_bar_correction_latches_across_restarts(self):
        j = self.journal()
        j.record(raw_packet())
        p = raw_packet(1)
        p["candles"]["M1"][-1]["close"] = 100.1
        j.record(p)
        self.assertTrue(j.state()["integrity_latched"])
        j = Journal(j.root, self.config, source_kind="SYNTHETIC_FIXTURE")
        self.assertTrue(j.state()["integrity_latched"])

    def test_forming_future_m5_excluded_from_research(self):
        from iat.live_shadow.research import assess

        p = raw_packet()
        a, d = assess(p["candles"], p["received_at"], {}, self.config)
        bars = deepcopy(p["candles"])
        bars["M5"].append(
            dict(
                timestamp=NOW.replace(second=0).isoformat(),
                open=100.0,
                high=1000.0,
                low=1.0,
                close=999.0,
            )
        )
        b, e = assess(bars, p["received_at"], {}, self.config)
        self.assertEqual(d, e)

    def test_dashboard_endpoints_compatible_and_shadow_route_local_only(self):
        module = TickMT5()
        feed = ShadowFeed(module)
        j = self.journal(configuration())
        runtime = ShadowRuntime(feed, j, clock=lambda: NOW)
        runtime.step()
        app = create_dashboard(runtime, shadow=runtime)
        client = app.test_client()
        for route in (
            "/live/v1/snapshot",
            "/live/v2/snapshot",
            "/live/v3/snapshot",
            "/live/shadow/v1/snapshot",
        ):
            r = client.get(route)
            self.assertEqual(r.status_code, 200, route)
            self.assertFalse(r.json["execution_allowed"])
        self.assertEqual(
            client.get(
                "/live/shadow/v1/snapshot", environ_base={"REMOTE_ADDR": "10.0.0.1"}
            ).status_code,
            403,
        )
        with client.get("/") as home:
            self.assertIn(b"Broker execution disabled", home.data)
        self.assertEqual(client.post("/live/shadow/v1/snapshot").status_code, 405)

    def test_runtime_store_failure_stale_and_no_secret_exception(self):
        j = self.journal()
        runtime = ShadowRuntime(ShadowFeed(TickMT5()), j, clock=lambda: NOW)
        with patch.object(j, "record", side_effect=RuntimeError("SECRET")):
            r = runtime.step()
        self.assertEqual(r["status"], "BLOCKED")
        self.assertNotIn("SECRET", json.dumps(r))
        self.assertEqual(r["orders_requested"], 0)

    def test_no_broker_order_or_network_capabilities(self):
        root = Path(__file__).resolve().parents[1]
        files = [
            *(root / "iat/live_shadow").glob("*.py"),
            root / "diagnostics/run_live_shadow.py",
        ]
        for file in files:
            tree = ast.parse(file.read_text())
            attrs = {
                n.func.attr
                for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            }
            self.assertFalse(
                attrs
                & {"order_send", "order_check", "login", "positions_get", "orders_get"}
            )
            imports = [
                n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
            ]
            self.assertFalse(
                any(
                    v.startswith(("google", "openai", "requests", "iat.demo_execution"))
                    for v in imports
                )
            )

    def test_five_trade_cap_and_loss_latch(self):
        state = engine.initial()
        for i in range(6):
            state, _ = engine.decision_event(
                state,
                decision(setup="setup" + str(i), at=NOW + timedelta(seconds=i * 60)),
            )
            state, _ = engine.quote_event(
                state, tick(i * 60 + 1), self.config, session(), symbol()
            )
            state, _ = engine.quote_event(
                state, tick(i * 60 + 2, 102.0, 102.1), self.config, session(), symbol()
            )
        self.assertEqual(state["totals"]["closed"], 5)
        self.assertIn("DAILY_LOSS_LATCH_OR_FIVE_TRADE_CAP", state["rejections"])
        c = deepcopy(self.config)
        c["costs"]["initial_equity"] = "1000"
        s, _ = engine.decision_event(engine.initial(), decision())
        s, _ = engine.quote_event(s, tick(1), c, session(), symbol())
        s, _ = engine.quote_event(s, tick(2, 1.0, 1.1), c, session(), symbol())
        self.assertTrue(s["daily"][NOW.date().isoformat()]["latched"])

    def test_session_closed_close_only_reopen_and_expiry(self):
        from test_session_v2 import synthetic_v2, window
        from iat.session_config import compile_session_config

        value = synthetic_v2()
        value["weekdays"]["thu"] = {
            "quotes": [window("23:00:00", "00:00:00", 1)],
            "phases": [
                window("00:00:00", "23:00:00", 0, "CLOSED"),
                window("23:00:00", "23:02:00", 0, "CLOSE_ONLY"),
                window("23:02:00", "00:00:00", 1, "FULL_TRADING"),
            ],
        }
        cal = compile_session_config(value)
        for hour, minute, phase, opened in [
            (21, 58, "CLOSED", False),
            (23, 0, "CLOSE_ONLY", False),
            (23, 2, "FULL_TRADING", True),
        ]:
            at = NOW.replace(hour=hour, minute=minute, second=0)
            q = observed_tick(
                dict(
                    time=int(at.timestamp()),
                    time_msc=int(at.timestamp() * 1000),
                    bid=100.0,
                    ask=100.1,
                ),
                at,
            )
            r = session_diagnostics(cal, at, quote=q)
            self.assertEqual(r["phase"], phase)
            self.assertEqual(r["new_positions"], opened)
        expired = NOW + timedelta(days=5)
        self.assertIn(
            "CALENDAR_EXPIRED", session_diagnostics(cal, expired)["reason_codes"]
        )

    def test_dst_ambiguity_is_rejected_by_unchanged_calendar_loader(self):
        from test_session_v2 import synthetic_v2, window
        from iat.session_config import compile_session_config

        value = synthetic_v2()
        value["timezone"] = "America/New_York"
        value["coverage"] = {"start": "2026-10-31", "end": "2026-11-03"}
        value["verification"]["provenance"][0]["captured_at"] = "2026-10-30T00:00:00Z"
        value["verification"]["expires_at"] = "2026-11-03T23:59:00Z"
        value["weekdays"]["sun"]["quotes"] = [window("01:30:00", "02:30:00", 0)]
        with self.assertRaises(ValueError):
            compile_session_config(value)

    def test_overnight_baseline_and_rollover_unknown_are_unresolved(self):
        s, _ = self.enter()
        p = s["position"]
        future = NOW.replace(hour=0, minute=0, second=1) + timedelta(days=1)
        q = observed_tick(
            dict(
                time=int(future.timestamp()),
                time_msc=int(future.timestamp() * 1000),
                bid=100.0,
                ask=100.1,
            ),
            future,
        )
        s, _ = engine.quote_event(s, q, self.config, session(), symbol())
        self.assertEqual(s["position"]["state"], "UNRESOLVED")
        self.assertIn("UTC_OPENING_EQUITY_MARK_UNAVAILABLE", s["rejections"])

    def test_bad_capture_batch_cannot_partially_close_a_trade(self):
        s = initial_state()
        s["engine"], _ = self.enter()
        p = raw_packet(2)
        winner = tick(1.5, 102.0, 102.1)
        bad = tick(1.5, 98.0, 98.1)
        p["capture"]["ticks"] = [winner, bad, p["quote"]]
        p["capture"]["start"] = (NOW + timedelta(seconds=1)).isoformat()
        s, e = reduce_packet(s, p, self.config, None)
        self.assertFalse(any(v["kind"] == "EXIT" for v in e))
        self.assertEqual(s["engine"]["position"]["state"], "UNRESOLVED")

    def test_missing_identity_cannot_simulate(self):
        s = initial_state()
        s["engine"], _ = self.enter()
        p = raw_packet(2)
        p["identity"] = None
        s, e = reduce_packet(s, p, self.config, None)
        self.assertEqual(s["engine"]["position"]["state"], "UNRESOLVED")

    def test_metrics_have_denominators_and_never_qualified_results(self):
        s, _ = self.enter()
        self.assertGreater(Decimal(engine.summary(s)["maximum_drawdown"]), 0)
        s, _ = engine.quote_event(
            s, tick(2, 102.0, 102.1), self.config, session(), symbol()
        )
        r = engine.summary(s)
        self.assertEqual(r["closed_trades"], 1)
        self.assertEqual(r["signal_denominator"], 1)
        self.assertIsNone(r["qualified_performance_metrics"])
        self.assertIsNone(r["profit_factor"])
        self.assertEqual(r["segments"][0]["qualified_count"], 0)

    def test_record_only_runtime_actual_quote_is_available_and_orders_zero(self):
        m = TickMT5()
        j = self.journal(configuration())
        r = ShadowRuntime(ShadowFeed(m), j, clock=lambda: NOW).step()
        self.assertEqual(r["status"], "RECORDING")
        self.assertEqual(r["quote"]["ask"], "100.1")
        self.assertEqual(m.orders, 0)
        self.assertEqual(j.verify(replay=True)["status"], "MATCH")

    def test_resume_gap_and_stale_ui_withhold_unrealized_pnl(self):
        j = self.journal()
        r = ShadowRuntime(ShadowFeed(TickMT5()), j, clock=lambda: NOW)
        r.step()
        r.clock = lambda: NOW + timedelta(seconds=10)
        snapshot = r.shadow_latest()
        self.assertEqual(snapshot["status"], "STALE_OR_UNAVAILABLE")
        self.assertIsNone(snapshot["performance"]["unrealized_pnl"])

    def test_raw_secret_or_unsupported_fields_are_rejected_not_redacted(self):
        j = self.journal()
        p = raw_packet()
        p["raw_candles"] = {
            "M1": {"position": 1, "requested_count": 1, "rates": [{"server": "SECRET"}]}
        }
        with self.assertRaises(ValueError):
            j.record(p)
        self.assertNotIn(b"SECRET", j.path.read_bytes())

    def test_m1_m5_mismatch_blocks_before_fill(self):
        p = raw_packet()
        p["candles"]["M5"][-1]["high"] = 102.0
        s, e = reduce_packet(initial_state(), p, self.config, None)
        self.assertIn("M1_M5_OHLC_MISMATCH", s["engine"]["rejections"])
        self.assertFalse(any(v["kind"] == "FILL" for v in e))

    def test_read_only_dashboard_attachment(self):
        from iat.live_shadow.runtime import ReadOnlyJournalView

        j = self.journal()
        j.record(raw_packet())
        view = ReadOnlyJournalView(j, clock=lambda: NOW)
        self.assertEqual(view.shadow_latest()["quote_age_seconds"], 0)
        self.assertEqual(view.shadow_latest()["feed_status"], "CONNECTED")
        self.assertFalse(hasattr(view, "record"))
        view.clock = lambda: NOW + timedelta(seconds=3)
        self.assertEqual(view.shadow_latest()["status"], "STALE_OR_UNAVAILABLE")

    def test_quote_tick_timestamp_not_silently_truncated(self):
        m = TickMT5()
        m.copy_ticks_range = lambda *a: [
            dict(
                time=int(NOW.timestamp()),
                time_msc=NOW.timestamp() * 1000 + 0.5,
                bid=100.0,
                ask=100.1,
            )
        ]
        r = ShadowFeed(m).capture(NOW - timedelta(seconds=1), NOW)
        self.assertEqual(r["status"], "UNAVAILABLE")

    def test_unsupported_profit_currency_or_calculation_mode_blocks(self):
        for change in (
            dict(currency_profit=None),
            dict(trade_calc_mode=2),
            dict(point=-0.01),
            dict(volume_min=-1),
        ):
            s, _ = engine.decision_event(engine.initial(), decision())
            s, e = engine.quote_event(
                s, tick(1), self.config, session(), dict(symbol(), **change)
            )
            self.assertIsNone(s["position"])

    def test_typed_rule_contract_through_sqlite_fills_replay_and_prefix(self):
        """Synthetic typed observations exercise original predicates, not an OHLC edge claim."""
        from dataclasses import replace, is_dataclass, fields
        from datetime import datetime
        from test_research_strategies import observation_fixture
        from iat.intelligence.context_models import ContextConfig
        from iat.intelligence.models import IntelligenceConfig

        for strategy in specifications():
            for direction in ("BULLISH", "BEARISH"):
                report = observation_fixture(direction)
                delta = NOW.replace(second=0) - datetime.fromisoformat(
                    report.analysis_at
                )

                def shift(v):
                    if is_dataclass(v):
                        return replace(
                            v, **{f.name: shift(getattr(v, f.name)) for f in fields(v)}
                        )
                    if isinstance(v, dict):
                        return {k: shift(x) for k, x in v.items()}
                    if isinstance(v, tuple):
                        return tuple(shift(x) for x in v)
                    if isinstance(v, list):
                        return [shift(x) for x in v]
                    if isinstance(v, str):
                        try:
                            t = datetime.fromisoformat(v)
                            if t.utcoffset() is not None:
                                return (t + delta).isoformat()
                        except ValueError:
                            pass
                    return v

                report = shift(report)
                cutoff = datetime.fromisoformat(report.analysis_at)
                sources = deepcopy(report.interpretations["source_registry"])
                for name, tf, kind, price in [
                    ("SYNTHETIC:m5", "M5", "LOW", 100),
                    (
                        "SYNTHETIC:stop",
                        "M1",
                        "LOW" if direction == "BULLISH" else "HIGH",
                        99.01 if direction == "BULLISH" else 100.99,
                    ),
                ]:
                    sources[name] = dict(
                        kind="CONFIRMED_PIVOT",
                        timeframe=tf,
                        available_at=(cutoff - timedelta(minutes=1)).isoformat(),
                        observed_at=(cutoff - timedelta(minutes=2)).isoformat(),
                        pivot_kind=kind,
                        price=price,
                    )
                sources["SYNTHETIC:sweep"] = dict(
                    kind="LIQUIDITY_EVENT",
                    timeframe="M1",
                    available_at=(cutoff - timedelta(minutes=2)).isoformat(),
                    observed_at=(cutoff - timedelta(minutes=3)).isoformat(),
                )
                evidence = tuple(
                    (
                        replace(e, references=("SYNTHETIC:m5",))
                        if e.category == "STRUCTURE" and e.timeframe == "M5"
                        else e
                    )
                    for e in report.evidence
                )
                frames_ = deepcopy(report.interpretations["frames"])
                frames_["M1"]["volatility"] = {
                    "relative_volatility": 1,
                    "regime": "NORMAL_VOLATILITY",
                }
                report = replace(
                    report,
                    symbol="XAUUSD",
                    provenance="HISTORICAL_RESEARCH",
                    configuration_sha256=ContextConfig().digest,
                    intelligence_configuration_sha256=IntelligenceConfig().digest,
                    configuration=asdict(ContextConfig()),
                    interpretations={"frames": frames_, "source_registry": sources},
                    evidence=evidence,
                )
                config = deepcopy(self.config)
                config["strategy_id"] = strategy.strategy_id
                j = Journal(
                    self.root / (strategy.strategy_id + direction),
                    config,
                    create=True,
                    source_kind="SYNTHETIC_FIXTURE",
                )
                with patch("iat.live_shadow.research.context_at", return_value=report):
                    j.record(raw_packet())
                    frozen = deepcopy(j.state()["last_decision"])
                    self.assertEqual(
                        frozen["candidate"],
                        "BUY_CANDIDATE" if direction == "BULLISH" else "SELL_CANDIDATE",
                    )
                    j.record(raw_packet(1))
                    self.assertIsNotNone(j.state()["engine"]["position"])
                    target = float(j.state()["engine"]["position"]["target"])
                    before = j.verify(replay=True)
                    p = raw_packet(2)
                    p["quote"] = (
                        tick(2, target, float(Decimal(str(target)) + Decimal(".1")))
                        if direction == "BULLISH"
                        else tick(
                            2, float(Decimal(str(target)) - Decimal(".1")), target
                        )
                    )
                    p["capture"]["ticks"] = [p["quote"]]
                    j.record(p)
                    self.assertEqual(j.state()["last_decision"], frozen)
                    self.assertEqual(
                        j.snapshot()["performance"]["closed_trades"],
                        1,
                        j.snapshot()["performance"],
                    )
                    self.assertEqual(j.verify(replay=True)["status"], "MATCH")
                    self.assertEqual(
                        j.snapshot()["performance"]["segments"][0]["qualified_count"], 0
                    )

    def test_offline_cli_and_synthetic_example_repeatable_source_hashes(self):
        from diagnostics.shadow_synthetic_example import run
        from diagnostics.run_live_shadow import main

        a = run(self.root / "example-a")
        b = run(self.root / "example-b")
        self.assertEqual(a, b)
        database = self.root / "example-a/journal/shadow.sqlite3"
        before = database.read_bytes()
        with redirect_stdout(StringIO()) as output:
            code = main(
                [
                    "--journal-directory",
                    str(database.parent),
                    "--offline-verify",
                    "--synthetic-replay",
                ]
            )
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(before, database.read_bytes())
        self.assertEqual(a["journal_replay"]["event_count"], 3)
        self.assertTrue(
            all(
                e["exit"]["qualified_performance_eligible"] is False
                for e in a["engine_contracts"]
            )
        )

    def test_unverified_and_synthetic_calendar_closure_never_claims_actual_closure(
        self,
    ):
        from test_session_v2 import synthetic_v2, window
        from iat.session_config import compile_session_config

        value = synthetic_v2()
        value["weekdays"]["thu"] = {"quotes": [], "phases": [window(state="CLOSED")]}
        cal = compile_session_config(value)
        r = session_diagnostics(cal, NOW, quote=tick())
        self.assertIn("UNVERIFIED_DECLARED_CLOSURE", r["reason_codes"])
        self.assertNotIn("ACTUAL_MARKET_CLOSURE", r["reason_codes"])
        self.assertIn("SYNTHETIC_CALENDAR_NOT_REAL_EVIDENCE", r["reason_codes"])
        self.assertFalse(r["operational_eligible"])
        value["verification"]["quote_schedule_verified"] = False
        value["verification"]["trade_schedule_verified"] = False
        r = session_diagnostics(compile_session_config(value), NOW, quote=tick())
        self.assertNotIn("ACTUAL_MARKET_CLOSURE", r["reason_codes"])
        # A verified calendar declaration is still distinct from real-terminal proof.
        state = dict(
            verification="VERIFIED_DECLARATIONS",
            provenance_kinds=["PUBLISHED"],
            reason_codes=[],
            permissions=dict(
                phase="CLOSED",
                market_data_expected=False,
                broker_open_positions=False,
                broker_close_positions=False,
            ),
        )
        declared = SimpleNamespace(
            configuration_sha256="a" * 64,
            public_state=lambda at: state,
            validate_request=lambda *a: None,
        )
        r = session_diagnostics(declared, NOW, quote=tick())
        self.assertIn("ACTUAL_MARKET_CLOSURE", r["reason_codes"])
        self.assertFalse(r["operational_eligible"])

    def test_whole_second_api_query_preserves_exact_logical_tick_boundaries(self):
        module = TickMT5()
        calls = []
        times = [
            NOW - timedelta(seconds=0.9),
            NOW - timedelta(seconds=0.5),
            NOW + timedelta(seconds=0.5),
            NOW + timedelta(seconds=0.9),
        ]

        def query(symbol_, start, end, flags):
            calls.append((start, end))
            return [
                dict(
                    time=int(t.timestamp()),
                    time_msc=round(t.timestamp() * 1000),
                    bid=100.0,
                    ask=100.1,
                )
                for t in times
            ]

        module.copy_ticks_range = query
        result = ShadowFeed(module).capture(
            NOW - timedelta(seconds=0.75), NOW + timedelta(seconds=0.75)
        )
        self.assertEqual(result["status"], "OBSERVED_RANGE")
        self.assertEqual(len(result["ticks"]), 2)
        self.assertEqual(result["excluded_outside_window"], 2)
        self.assertEqual(
            calls, [(NOW - timedelta(seconds=1), NOW + timedelta(seconds=1))]
        )
        self.assertEqual(
            [q["timestamp"] for q in result["ticks"]],
            [times[1].isoformat(), times[2].isoformat()],
        )
