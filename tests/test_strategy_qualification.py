"""Stage-B SYNTHETIC software fixtures; no historical validation or broker calls."""

from copy import deepcopy
from dataclasses import replace, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from hashlib import sha256
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
import csv, json, tempfile, unittest
from decimal import Decimal
from iat.strategy_qualification.specs import specifications, PROTOCOL, PROTOCOL_SHA256
from iat.strategy_qualification.quotes import Quote, read_quotes, qualify_quotes, ITEMS
from iat.strategy_qualification.backtest import (
    Costs,
    Decision,
    simulate,
    ambiguous_ohlc_exit,
)
from iat.strategy_qualification.metrics import metrics, qualification_status
from iat.strategy_qualification.validation import validate_plan, validation_runs
from iat.strategy_qualification.dataset import (
    run_study,
    validate_study,
    quote_bar_audit,
)
from iat.strategy_qualification.decisions import decisions_from_candles
from iat.intelligence.strategy_replay import digest
from iat.replay_dataset import load_dataset
from diagnostics.strategy_qualification import main
from test_strategy_dataset_replay import scoped_fixture
from test_context_components import CONFIG
from test_context_engine import P7

T = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


def stamp(seconds=0):
    return (T + timedelta(seconds=seconds)).isoformat()


def costs(**kw):
    return Costs(
        **(
            dict(
                initial_equity="10000",
                currency="USD",
                contract_size="100",
                tick_size=".01",
                minimum_stop_distance=".01",
                volume_min=".01",
                volume_step=".01",
                max_spread=".20",
                slippage_ticks=0,
                commission_per_side_per_lot="0",
                fee_per_side_per_lot="0",
                rollovers=(),
                evidence_sha256="a" * 64,
                known_at=stamp(-3600),
                currency_quantum=".01",
                money_rounding="ROUND_HALF_EVEN",
            )
            | kw
        )
    )


def q(seconds, bid, ask):
    return Quote(stamp(seconds), str(bid), str(ask))


def d(seconds=0, side="BUY", key="SYNTHETIC:setup", stop="99"):
    return Decision(
        stamp(seconds),
        key,
        side,
        stop,
        False,
        True,
        "TREND_UP" if side == "BUY" else "TREND_DOWN",
        "NORMAL_VOLATILITY",
    )


def permit(at):
    return dict(quotes=True, open=True, close=True)


class StageBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="iat Stage B SYNTHETIC ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = specifications()[0]

    def run_(self, quotes, decisions=None, **kw):
        return simulate(
            kw.pop("spec", self.spec),
            kw.pop("costs", costs()),
            quotes,
            decisions or [d()],
            permissions=kw.pop("permissions", permit),
            cutoff=kw.pop("cutoff", quotes[-1].timestamp),
            **kw
        )

    def test_specifications_complete_versioned_and_no_registry_promotion(self):
        from iat.intelligence.strategy_registry import registry

        for s in specifications():
            v = s.description()
            self.assertEqual(v["status"], "EXPERIMENTAL")
            self.assertEqual(v["specification_sha256"], s.sha256)
            for field in (
                "entry",
                "stop",
                "target",
                "exit",
                "invalidation",
                "volatility",
                "session",
                "constraints",
                "identity",
                "missing_data",
            ):
                self.assertTrue(v[field])
        self.assertTrue(
            all(
                s["validation_status"] == "EXPERIMENTAL_SYNTHETIC_ONLY"
                for s in registry()["strategies"]
            )
        )

    def test_first_executable_quote_after_close_not_same_timestamp(self):
        r = self.run_([q(0, "99", "99.1"), q(1, "99.9", "100"), q(2, "102", "102.1")])
        trade = r["trade_log"][0]
        self.assertEqual(trade["entry_at"], stamp(1))
        self.assertEqual(Decimal(trade["entry"]), Decimal("100"))
        self.assertEqual(Decimal(trade["exit"]), Decimal("102.00"))
        self.assertEqual(r["orders_requested"], 0)
        self.assertFalse(r["execution_allowed"])
        self.assertEqual(r["signal"], "WAIT")

    def test_buy_ask_sell_bid_and_exit_correct_sides(self):
        buy = self.run_([q(1, "99.9", "100"), q(2, "102", "102.1")])
        self.assertEqual(Decimal(buy["trade_log"][0]["gross_pnl"]), Decimal("2.00"))
        sell = self.run_(
            [q(1, "100", "100.1"), q(2, "97.9", "98")], [d(side="SELL", stop="101")]
        )
        self.assertEqual(Decimal(sell["trade_log"][0]["entry"]), Decimal("100"))
        self.assertEqual(Decimal(sell["trade_log"][0]["exit"]), Decimal("98.00"))

    def test_stop_gap_uses_observed_worse_price_target_no_gap_bonus(self):
        stop = self.run_([q(1, "99.9", "100"), q(2, "97", "97.1")])
        self.assertEqual(stop["trade_log"][0]["exit"], "97.00")
        target = self.run_([q(1, "99.9", "100"), q(2, "110", "110.1")])
        self.assertEqual(target["trade_log"][0]["exit"], "102.00")

    def test_commission_fees_spread_and_adverse_slippage_not_double_counted(self):
        c = costs(
            commission_per_side_per_lot="1", fee_per_side_per_lot="1", slippage_ticks=1
        )
        r = self.run_([q(1, "99.9", "100"), q(2, "97", "97.1")], costs=c)
        t = r["trade_log"][0]
        self.assertEqual(t["entry"], "100.01")
        self.assertEqual(t["exit"], "96.99")
        self.assertEqual(t["costs"], "0.04")
        self.assertEqual(Decimal(t["net_pnl"]), Decimal("-3.06"))

    def test_late_entry_quote_and_spread_filter_abstain(self):
        r = self.run_([q(3, "99.9", "100")])
        self.assertEqual(r["trade_log"], [])
        self.assertIn(
            "ENTRY_QUOTE_UNAVAILABLE_WITHIN_TWO_SECONDS", r["blocked_reasons"]
        )
        r = self.run_([q(1, "99", "100")])
        self.assertIn("SPREAD_FILTER", r["blocked_reasons"])

    def test_stop_precision_and_wrong_side_rejected(self):
        for stop in ("100.01", "99.001", "99.95"):
            r = self.run_([q(1, "99.9", "100")], [d(stop=stop)])
            self.assertIsNone(r["open_position"])
            self.assertTrue(r["blocked_reasons"])

    def test_open_position_and_incomplete_entry_not_fabricated_at_end(self):
        r = self.run_([q(1, "99.9", "100")])
        self.assertIn("OPEN_POSITION_AT_OBSERVATION_CUTOFF", r["unresolved_reasons"])
        self.assertEqual(r["trade_log"], [])
        r = self.run_([q(0, "99.9", "100")])
        self.assertIn("ENTRY_HORIZON_INCOMPLETE", r["unresolved_reasons"])

    def test_intrabar_both_hits_inconclusive(self):
        bar = {"low": "98", "high": "103"}
        self.assertEqual(
            ambiguous_ohlc_exit("BUY", "99", "102", bar, bar),
            "UNRESOLVED_INTRABAR_ORDER",
        )

    def test_duplicate_setup_never_rearms_and_one_position_only(self):
        qs = [
            q(1, "99.9", "100"),
            q(2, "102", "102.1"),
            q(61, "99.9", "100"),
            q(62, "102", "102.1"),
        ]
        r = self.run_(qs, [d(), d(60)])
        self.assertEqual(len(r["trade_log"]), 1)
        r = self.run_(
            [q(1, "99.9", "100"), q(61, "100", "100.1")], [d(), d(60, key="other")]
        )
        self.assertIsNotNone(r["open_position"])
        self.assertEqual(sum(e["kind"] == "ENTRY" for e in r["events"]), 1)

    def test_five_openings_daily_cap(self):
        qs = []
        ds = []
        for i in range(6):
            qs.extend([q(i * 60 + 1, "99.9", "100"), q(i * 60 + 2, "102", "102.1")])
            ds.append(d(i * 60, key="setup" + str(i)))
        r = self.run_(qs, ds)
        self.assertEqual(len(r["trade_log"]), 5)
        self.assertEqual(r["blocked_reasons"]["DAILY_TRADE_CAP"], 1)

    def test_daily_loss_latch_no_reset_on_recovery(self):
        # The planned risk is below 1% only with a larger baseline; use a stop-gap to cross it.
        r = self.run_(
            [q(1, "99.9", "100"), q(2, "1", "1.1"), q(61, "99.9", "100")],
            [d(), d(60, key="next")],
            costs=costs(initial_equity="1000"),
        )
        self.assertEqual(len(r["trade_log"]), 1)
        self.assertTrue(r["daily"][T.date().isoformat()]["latched"])

    def test_projected_daily_budget_blocks_before_entry(self):
        r = self.run_([q(1, "99.9", "100")], costs=costs(initial_equity="100"))
        self.assertIn("PROJECTED_DAILY_LOSS_CAP", r["blocked_reasons"])

    def test_close_only_quote_permission_is_not_new_trade_permission(self):
        r = self.run_(
            [q(1, "99.9", "100")],
            permissions=lambda at: dict(quotes=True, open=False, close=True),
        )
        self.assertIn("NEW_POSITION_SESSION_BLOCKED", r["blocked_reasons"])
        r = self.run_(
            [q(1, "99.9", "100"), q(2, "102", "102.1")],
            permissions=lambda at: dict(
                quotes=True, open=at < T + timedelta(seconds=2), close=True
            ),
        )
        self.assertEqual(r["trade_log"][0]["exit_session_phase"], "CLOSE_ONLY")

    def test_unknown_session_and_blocked_data_remain_visible(self):
        r = self.run_(
            [q(1, "99.9", "100")],
            permissions=lambda at: dict(quotes=None, open=None, close=None),
        )
        self.assertEqual(r["trade_log"], [])
        r = self.run_(
            [q(1, "99.9", "100"), q(61, "100", "100.1")],
            [d(), replace(d(60), valid=False)],
        )
        self.assertIn("OPEN_POSITION_DURING_BLOCKED_EVIDENCE", r["unresolved_reasons"])

    def test_invalidation_next_quote_and_timeout(self):
        invalid = Decision(
            stamp(60), None, "WAIT", None, True, True, "TRANSITION", "NORMAL_VOLATILITY"
        )
        r = self.run_(
            [q(1, "99.9", "100"), q(60, "100", "100.1"), q(61, "100", "100.1")],
            [d(), invalid],
        )
        self.assertEqual(r["trade_log"][0]["exit_at"], stamp(61))
        self.assertEqual(r["trade_log"][0]["reason"], "INVALIDATED")
        r = self.run_([q(1, "99.9", "100"), q(901, "100", "100.1")])
        self.assertEqual(r["trade_log"][0]["reason"], "TIME")

    def test_rollover_costs_and_future_cost_knowledge(self):
        schedule = (
            {
                "timestamp": stamp(2),
                "announced_at": stamp(-100),
                "long_per_lot": "-3",
                "short_per_lot": "1",
            },
        )
        r = self.run_(
            [q(1, "99.9", "100"), q(3, "102", "102.1")], costs=costs(rollovers=schedule)
        )
        self.assertEqual(r["trade_log"][0]["costs"], "0.03")
        future = (
            {
                "timestamp": stamp(2),
                "announced_at": stamp(2),
                "long_per_lot": "-3",
                "short_per_lot": "1",
            },
        )
        r = self.run_([q(1, "99.9", "100")], costs=costs(rollovers=future))
        self.assertIn("ROLLOVER_COST_NOT_KNOWN_AT_ENTRY", r["blocked_reasons"])
        r = self.run_([q(1, "99.9", "100")], costs=costs(known_at=stamp(2)))
        self.assertIn("COST_MODEL_NOT_KNOWN_AT_DECISION", r["blocked_reasons"])

    def test_overnight_missing_opening_mark_inconclusive(self):
        base = T.replace(hour=23, minute=59)
        ds = [
            Decision(
                base.isoformat(),
                "overnight",
                "BUY",
                "90",
                False,
                True,
                "TREND_UP",
                "NORMAL",
            )
        ]
        qs = [
            Quote((base + timedelta(seconds=1)).isoformat(), "99.9", "100"),
            Quote((base + timedelta(minutes=1, seconds=1)).isoformat(), "100", "100.1"),
        ]
        r = simulate(
            self.spec,
            costs(initial_equity="10000"),
            qs,
            ds,
            permissions=permit,
            cutoff=qs[-1].timestamp,
        )
        self.assertIn("UTC_OPENING_EQUITY_MARK_UNAVAILABLE", r["unresolved_reasons"])

    def test_replay_repeat_prefix_and_future_append_are_causal(self):
        qs = [q(1, "99.9", "100"), q(2, "100", "100.1"), q(3, "102", "102.1")]
        full = self.run_(qs)
        again = self.run_(qs)
        prefix = self.run_(qs, cutoff=stamp(2))
        self.assertEqual(full, again)
        self.assertEqual(
            prefix["events"], [e for e in full["events"] if e["timestamp"] <= stamp(2)]
        )
        frozen = deepcopy(prefix)
        self.run_(qs + [q(4, "100", "100.1")])
        self.assertEqual(prefix, frozen)

    def test_quote_order_duplicates_and_utc_ambiguity_fail(self):
        for rows in (
            [q(1, "99", "99.1"), q(1, "99", "99.1")],
            [q(2, "99", "99.1"), q(1, "99", "99.1")],
        ):
            with self.assertRaises(ValueError):
                self.run_(rows)
        with self.assertRaises(ValueError):
            Quote("2026-11-20T12:00:00", "99", "100")
        with self.assertRaises(ValueError):
            Quote(stamp(1), "100", "99")

    def test_metrics_denominators_and_small_sample_no_confidence(self):
        r = self.run_([q(1, "99.9", "100"), q(2, "102", "102.1")])
        m = metrics(r)
        self.assertEqual(m["closed_trades"], 1)
        self.assertEqual(m["win_rate"], "1")
        self.assertIsNone(m["profit_factor"])
        self.assertIsNone(m["confidence_interval"])
        empty = self.run_([q(0, "99.9", "100")])
        m = metrics(empty)
        self.assertIsNone(m["net_pnl"])
        self.assertIsNone(m["expectancy"])

    def test_synthetic_and_provenance_labels_cannot_qualify(self):
        r = self.run_([q(1, "99.9", "100"), q(2, "102", "102.1")])
        self.assertEqual(
            qualification_status("HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED", r)[0],
            "EXPERIMENTAL",
        )
        with self.assertRaises(ValueError):
            self.run_([q(1, "99.9", "100")], scope="INDEPENDENT_HISTORICAL")

    def test_disjoint_plan_protocol_and_walk_forward(self):
        p = dict(
            version=1,
            registered_protocol_sha256=PROTOCOL_SHA256,
            in_sample={"start": stamp(0), "end": stamp(60)},
            out_of_sample={"start": stamp(60), "end": stamp(120)},
            walk_forward=[],
        )
        validate_plan(p)
        p["out_of_sample"]["start"] = stamp(59)
        with self.assertRaisesRegex(ValueError, "LEAKAGE"):
            validate_plan(p)
        p["out_of_sample"]["start"] = stamp(60)
        p["registered_protocol_sha256"] = "changed"
        with self.assertRaises(ValueError):
            validate_plan(p)

    def test_cost_and_parameter_sensitivity_is_not_selection(self):
        p = dict(
            version=1,
            registered_protocol_sha256=PROTOCOL_SHA256,
            in_sample={"start": stamp(-60), "end": stamp(0)},
            out_of_sample={"start": stamp(0), "end": stamp(120)},
            walk_forward=[],
        )
        report = validation_runs(
            self.spec,
            costs(),
            [q(1, "99.9", "100"), q(2, "102", "102.1")],
            [d()],
            permit,
            p,
        )
        self.assertEqual(len(report["sensitivity"]), 12)
        self.assertNotIn("best", report)
        self.assertEqual(
            report["sha256"], digest({k: v for k, v in report.items() if k != "sha256"})
        )

    def test_missing_data_study_never_reports_zero_historical_trades(self):
        r = run_study()
        validate_study(r)
        self.assertTrue(
            all(
                c["qualification"] == "DATA_NOT_QUALIFIED"
                and c["historical_metrics"] is None
                for c in r["candidates"]
            )
        )
        self.assertEqual(r["comparisons"], "NOT_RUN")
        self.assertEqual(r["later_stages"]["C"]["status"], "BLOCKED_NOT_STARTED")

    def test_manual_qualification_edit_and_checksum_recompute_rejected(self):
        r = run_study()
        r["candidates"][0]["qualification"] = "BACKTEST_QUALIFIED"
        r["recommendation"] = "PROCEED_TO_STAGE_C_REVIEW_ONLY"
        r["sha256"] = digest({k: v for k, v in r.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_study(r)

    def test_synthetic_manifest_uses_existing_qualification_gate(self):
        manifest = scoped_fixture(self.root)
        r = run_study(manifest)
        validate_study(r)
        self.assertIn("REAL_HISTORICAL_DATA_REQUIRED", r["reason_codes"])
        self.assertIsNone(r["candidates"][0]["backtest"])

    def test_existing_causal_ohlc_to_decision_integration(self):
        path = scoped_fixture(self.root, total_minutes=35)
        dataset = load_dataset(path)
        c = costs(tick_size=".00001", minimum_stop_distance=".00001")
        for spec in specifications():
            rows, hashes = decisions_from_candles(
                spec,
                c,
                dataset.rows["M1"],
                dataset.rows["M5"],
                evaluation=dataset.metadata["evaluation"],
                context_config=CONFIG,
                intelligence_config=P7,
            )
            self.assertTrue(rows)
            self.assertTrue(
                all(e.timestamp <= dataset.metadata["evaluation"]["end"] for e in rows)
            )
            self.assertGreater(hashes["warmup_decisions"], 0)

    def test_stream_quote_import_source_invariance_hash_and_duplicates(self):
        path = self.root / "quotes.csv"
        path.write_text(
            "timestamp,bid,ask\n" + stamp(0) + ",99,100\n" + stamp(1) + ",100,101\n"
        )
        raw = path.read_bytes()
        rows, meta = read_quotes(path, sha256(raw).hexdigest())
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(meta["count"], 2)
        with self.assertRaises(ValueError):
            read_quotes(path, "a" * 64)
        path.write_text(
            "timestamp,bid,ask\n" + stamp(0) + ",99,100\n" + stamp(0) + ",99,100\n"
        )
        with self.assertRaises(ValueError):
            read_quotes(path, sha256(path.read_bytes()).hexdigest())

    def test_quote_review_missing_does_not_self_approve(self):
        ds = load_dataset(scoped_fixture(self.root))
        r = qualify_quotes(None, ds)
        self.assertEqual(r["status"], "DATA_NOT_QUALIFIED")

    def test_cli_fail_closed_atomic_new_private_report(self):
        path = self.root / "report.json"
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["--report-path", str(path)]), 3)
        r = json.loads(path.read_text())
        validate_study(r)
        raw = path.read_bytes()
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["--report-path", str(path)]), 1)
        self.assertEqual(path.read_bytes(), raw)

    def test_no_order_provider_or_terminal_capabilities_added(self):
        import ast

        root = Path(__file__).resolve().parents[1] / "iat/strategy_qualification"
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text())
            imports = [
                n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
            ]
            self.assertFalse(
                any(
                    v.startswith(("MetaTrader5", "google", "openai", "iat.live_ai_"))
                    for v in imports
                )
            )
            self.assertFalse(
                {"order_send", "order_check", "login", "initialize"}
                & {
                    n.func.attr
                    for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                }
            )

    def test_money_rounding_is_explicit_per_fee_component(self):
        qs = [q(1, "99.9", "100"), q(2, "102", "102.1")]
        even = self.run_(
            qs,
            costs=costs(
                commission_per_side_per_lot=".5",
                fee_per_side_per_lot=".5",
                money_rounding="ROUND_HALF_EVEN",
            ),
        )
        up = self.run_(
            qs,
            costs=costs(
                commission_per_side_per_lot=".5",
                fee_per_side_per_lot=".5",
                money_rounding="ROUND_HALF_UP",
            ),
        )
        self.assertEqual(Decimal(even["trade_log"][0]["costs"]), Decimal("0"))
        self.assertEqual(Decimal(up["trade_log"][0]["costs"]), Decimal(".04"))

    def test_exit_session_unknown_does_not_invent_a_fill(self):
        r = self.run_(
            [q(1, "99.9", "100"), q(2, "102", "102.1")],
            permissions=lambda at: dict(
                quotes=True,
                open=True,
                close=None if at == T + timedelta(seconds=2) else True,
            ),
        )
        self.assertEqual(r["trade_log"], [])
        self.assertIn("OPEN_POSITION_AT_OBSERVATION_CUTOFF", r["unresolved_reasons"])

    def test_known_hold_exit_session_required(self):
        def permissions(at):
            return dict(
                quotes=True,
                open=True,
                close=False if at >= T + timedelta(minutes=15) else True,
            )

        r = self.run_([q(1, "99.9", "100")], permissions=permissions)
        self.assertIn("HOLD_EXIT_SESSION_UNVERIFIED", r["blocked_reasons"])

    def test_final_stale_mark_is_unresolved(self):
        r = self.run_([q(1, "99.9", "100")], cutoff=stamp(10))
        self.assertIsNone(r["final_equity"])
        self.assertIn("FINAL_EQUITY_MARK_UNAVAILABLE", r["unresolved_reasons"])

    def test_day_block_interval_repeatable_and_labels_limits(self):
        r = self.run_([q(1, "99.9", "100"), q(2, "102", "102.1")])
        trade = r["trade_log"][0]
        r["trade_log"] = [
            dict(trade, exit_at=(T + timedelta(days=i)).isoformat()) for i in range(30)
        ]
        a = metrics(r)
        b = metrics(r)
        self.assertEqual(a, b)
        self.assertEqual(a["confidence_interval"]["days"], 30)
        self.assertIn("NOT_IID_PROOF", a["confidence_interval"]["method"])

    def test_registry_all_states_are_named_no_status_input(self):
        from iat.strategy_qualification.metrics import QUALIFICATION_STATES

        self.assertEqual(
            set(QUALIFICATION_STATES),
            {
                "EXPERIMENTAL",
                "DATA_NOT_QUALIFIED",
                "BACKTEST_INCONCLUSIVE",
                "BACKTEST_FAILED",
                "BACKTEST_QUALIFIED",
            },
        )
        self.assertEqual(
            qualification_status("DATA_NOT_QUALIFIED")[0], "DATA_NOT_QUALIFIED"
        )
        self.assertEqual(
            qualification_status("HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED")[0],
            "BACKTEST_INCONCLUSIVE",
        )

    def test_quote_review_binds_evidence_and_rejects_self_review(self):
        from types import SimpleNamespace

        path = self.root / "q.csv"
        path.write_text(
            "timestamp,bid,ask\n" + stamp(0) + ",99,100\n" + stamp(2) + ",100,101\n"
        )
        doc = self.root / "evidence.txt"
        doc.write_text("SYNTHETIC evidence, not actual authorization")
        interval = {"start": stamp(0), "end": stamp(2)}
        sha = sha256(doc.read_bytes()).hexdigest()
        m = dict(
            version=1,
            symbol="XAUUSD",
            feed_id="SYNTHETIC_FEED",
            timestamp_convention="OBSERVATION_UTC",
            price_basis="BID_ASK",
            interval=interval,
            file=path.name,
            sha256=sha256(path.read_bytes()).hexdigest(),
            preparer_code="synthetic_preparer",
            reviewer_code="synthetic_reviewer",
            reviewed_at_utc=stamp(10),
            costs_config_sha256="b" * 64,
            evidence={
                k: dict(
                    status="VERIFIED",
                    file=doc.name,
                    sha256=sha,
                    reference="synthetic:contract-test-only",
                    interval=interval,
                )
                for k in ITEMS
            },
        )
        manifest = self.root / "quotes.json"
        manifest.write_text(json.dumps(m))
        ds = SimpleNamespace(
            metadata={"lineage": {"feed_id": "SYNTHETIC_FEED"}, "utc_range": interval}
        )
        self.assertEqual(
            qualify_quotes(manifest, ds)["status"], "QUOTE_PRECHECKS_PASSED"
        )
        m["reviewer_code"] = m["preparer_code"]
        manifest.write_text(json.dumps(m))
        self.assertIn(
            "INDEPENDENT_QUOTE_REVIEW_REQUIRED",
            qualify_quotes(manifest, ds)["reason_codes"],
        )
        m["reviewer_code"] = "synthetic_reviewer"
        m["evidence"]["capture_completeness"]["status"] = "PENDING"
        manifest.write_text(json.dumps(m))
        self.assertEqual(qualify_quotes(manifest, ds)["status"], "DATA_NOT_QUALIFIED")

    def test_quote_ohlc_alignment_is_diagnostic_not_native_m5_proof(self):
        from types import SimpleNamespace

        dataset = SimpleNamespace(
            metadata={
                "lineage": {"price_basis": "BID", "m5_origin": "AGGREGATED_FROM_M1"}
            },
            rows={
                "M1": [
                    dict(
                        timestamp=stamp(0), open=99.0, high=100.0, low=99.0, close=100.0
                    )
                ]
            },
        )
        a = quote_bar_audit(dataset, [q(0, "99", "99.1"), q(1, "100", "100.1")])
        self.assertEqual(a["ohlc_mismatches"], 0)
        self.assertEqual(a["m5_consistency"], "INTERNAL_AGGREGATION_ONLY")
        a = quote_bar_audit(dataset, [q(0, "98", "98.1")])
        self.assertEqual(a["ohlc_mismatches"], 1)

    def test_walk_forward_overlap_is_rejected(self):
        p = dict(
            version=1,
            registered_protocol_sha256=PROTOCOL_SHA256,
            in_sample={"start": stamp(0), "end": stamp(60)},
            out_of_sample={"start": stamp(60), "end": stamp(600)},
            walk_forward=[
                {
                    "train": {"start": stamp(0), "end": stamp(60)},
                    "test": {"start": stamp(60), "end": stamp(180)},
                },
                {
                    "train": {"start": stamp(0), "end": stamp(120)},
                    "test": {"start": stamp(120), "end": stamp(300)},
                },
            ],
        )
        with self.assertRaisesRegex(ValueError, "LEAKAGE"):
            validate_plan(p)

    def test_derived_decisions_hide_unfinished_m5_and_future_candles(self):
        dataset = load_dataset(scoped_fixture(self.root, total_minutes=35))
        c = costs(tick_size=".00001", minimum_stop_distance=".00001")
        kwargs = dict(
            evaluation=dataset.metadata["evaluation"],
            context_config=CONFIG,
            intelligence_config=P7,
        )
        a, _ = decisions_from_candles(
            self.spec, c, dataset.rows["M1"], dataset.rows["M5"], **kwargs
        )
        extra = dict(dataset.rows["M5"][-1])
        extra["timestamp"] = dataset.metadata["utc_range"]["end"]
        extra.update(open=999, high=1000, low=998, close=999)
        b, _ = decisions_from_candles(
            self.spec, c, dataset.rows["M1"], dataset.rows["M5"] + [extra], **kwargs
        )
        self.assertEqual(a, b)

    def test_typed_synthetic_observations_exercise_both_candidates_and_directions(self):
        from test_research_strategies import observation_fixture
        from dataclasses import replace

        for side in ("BULLISH", "BEARISH"):
            for spec in specifications():
                report = observation_fixture(side)
                at = datetime.fromisoformat(report.analysis_at)
                sources = deepcopy(report.interpretations["source_registry"])
                pivot = "SYNTHETIC:confirmed-stop"
                m5p = "SYNTHETIC:m5pivot"
                sources[pivot] = dict(
                    kind="CONFIRMED_PIVOT",
                    timeframe="M1",
                    observed_at=(at - timedelta(minutes=3)).isoformat(),
                    available_at=(at - timedelta(minutes=1)).isoformat(),
                    price=90 if side == "BULLISH" else 120,
                    pivot_kind="LOW" if side == "BULLISH" else "HIGH",
                )
                sources[m5p] = dict(
                    kind="CONFIRMED_PIVOT",
                    timeframe="M5",
                    observed_at=(at - timedelta(minutes=5)).isoformat(),
                    available_at=(at - timedelta(minutes=1)).isoformat(),
                    price=100,
                    pivot_kind="LOW",
                )
                sources["SYNTHETIC:sweep"] = dict(
                    kind="LIQUIDITY_EVENT",
                    timeframe="M1",
                    observed_at=(at - timedelta(minutes=3)).isoformat(),
                    available_at=(at - timedelta(minutes=2)).isoformat(),
                )
                evidence = tuple(
                    (
                        replace(e, references=(m5p,))
                        if e.category == "STRUCTURE" and e.timeframe == "M5"
                        else e
                    )
                    for e in report.evidence
                )
                frames = deepcopy(report.interpretations["frames"])
                frames["M1"]["volatility"] = {
                    "relative_volatility": 1,
                    "regime": "NORMAL_VOLATILITY",
                }
                report = replace(
                    report,
                    symbol="XAUUSD",
                    interpretations={"frames": frames, "source_registry": sources},
                    evidence=evidence,
                )
                m1 = [
                    dict(
                        timestamp=(at - timedelta(minutes=1)).isoformat(),
                        open=100,
                        high=101,
                        low=99,
                        close=100,
                    )
                ]
                with patch(
                    "iat.strategy_qualification.decisions.context_at",
                    return_value=report,
                ):
                    decisions, _ = decisions_from_candles(
                        spec,
                        costs(),
                        m1,
                        [],
                        evaluation={
                            "start": (at - timedelta(minutes=1)).isoformat(),
                            "end": at.isoformat(),
                        },
                        context_config=CONFIG,
                        intelligence_config=P7,
                    )
                self.assertEqual(
                    decisions[0].side, "BUY" if side == "BULLISH" else "SELL"
                )

    def test_quote_source_rows_limit_does_not_truncate_silently(self):
        path = self.root / "q.csv"
        path.write_text(
            "timestamp,bid,ask\n" + stamp(0) + ",99,100\n" + stamp(1) + ",100,101\n"
        )
        with self.assertRaisesRegex(ValueError, "ROW_LIMIT"):
            read_quotes(path, sha256(path.read_bytes()).hexdigest(), max_rows=1)

    def test_publication_failure_leaves_incomplete_not_success(self):
        path = self.root / "report.json"
        with patch(
            "diagnostics.strategy_qualification.run_study",
            side_effect=RuntimeError("PRIVATE"),
        ), redirect_stdout(StringIO()):
            self.assertEqual(main(["--report-path", str(path)]), 1)
        result = json.loads(path.read_text())
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason_codes"], ["RUN_INCOMPLETE"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_invalidated_signal_cannot_open_a_position(self):
        r = self.run_([q(1, "99.9", "100")], [replace(d(), invalidated=True)])
        self.assertIsNone(r["open_position"])
        self.assertEqual(r["trade_log"], [])

    def test_unknown_exit_permission_persists_as_uncertainty_after_later_fill(self):
        def allowed(at):
            return dict(
                quotes=True,
                open=True,
                close=None if at == T + timedelta(seconds=2) else True,
            )

        r = self.run_(
            [q(1, "99.9", "100"), q(2, "98", "98.1"), q(3, "102", "102.1")],
            permissions=allowed,
        )
        self.assertIn("POSITION_EXIT_PERMISSION_UNVERIFIED", r["unresolved_reasons"])

    def test_rollover_and_barrier_same_timestamp_inconclusive(self):
        schedule = (
            {
                "timestamp": stamp(2),
                "announced_at": stamp(-100),
                "long_per_lot": "-3",
                "short_per_lot": "1",
            },
        )
        r = self.run_(
            [q(1, "99.9", "100"), q(2, "102", "102.1")], costs=costs(rollovers=schedule)
        )
        self.assertIn("ROLLOVER_QUOTE_ORDER_UNRESOLVED", r["unresolved_reasons"])

    def test_spread_stress_is_labeled_cost_assumption_preserves_quote_identity(self):
        rows = [q(1, "99.9", "100"), q(2, "97", "97.1")]
        saved = deepcopy(rows)
        base = self.run_(rows)
        stress = self.run_(rows, costs=costs(spread_stress_multiplier="2"))
        self.assertEqual(rows, saved)
        self.assertEqual(stress["trade_log"][0]["observed_spread"], "0.1")
        self.assertEqual(
            Decimal(stress["trade_log"][0]["modeled_spread"]), Decimal(".20")
        )
        self.assertLess(
            Decimal(stress["trade_log"][0]["net_pnl"]),
            Decimal(base["trade_log"][0]["net_pnl"]),
        )
        self.assertEqual(
            [e["data"]["quote_id"] for e in base["events"] if e["kind"] == "MARK"],
            [e["data"]["quote_id"] for e in stress["events"] if e["kind"] == "MARK"],
        )

    def test_session_permission_integer_does_not_authorize(self):
        with self.assertRaises(ValueError):
            self.run_(
                [q(1, "99.9", "100")],
                permissions=lambda at: dict(quotes=1, open=True, close=True),
            )

    def test_anchor_retirement_cannot_invalidate_different_open_setup(self):
        unrelated = replace(
            d(60),
            side="WAIT",
            setup_id=None,
            stop=None,
            invalidated=True,
            invalidated_setup_ids=("another-setup",),
        )
        run = self.run_(
            [q(1, "99.9", "100"), q(61, "100", "100.1"), q(62, "102", "102.1")],
            [d(), unrelated],
        )
        self.assertEqual(run["trade_log"][0]["reason"], "TP")
        matching = replace(unrelated, invalidated_setup_ids=(d().setup_id,))
        run = self.run_([q(1, "99.9", "100"), q(61, "100", "100.1")], [d(), matching])
        self.assertEqual(run["trade_log"][0]["reason"], "INVALIDATED")

    def test_committed_protocol_matches_runtime_without_status_promotion(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "config/research/stage-b-protocol-v1.json"
        )
        doc = json.loads(path.read_text())
        self.assertEqual(doc["protocol"], PROTOCOL)
        self.assertEqual(doc["protocol_sha256"], PROTOCOL_SHA256)
        self.assertEqual(
            doc["specifications"],
            json.loads(json.dumps([s.description() for s in specifications()])),
        )

    def test_rechecksummed_success_without_run_is_rejected(self):
        report = run_study()
        report["status"] = "PASS"
        report["sha256"] = digest({k: v for k, v in report.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_study(report)
