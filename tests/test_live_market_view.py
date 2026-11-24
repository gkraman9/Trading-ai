"""Independent synthetic OHLC and mocked MT5: no real-terminal validation."""

import ast
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from iat.live_data import ReadOnlyMarketData
from iat.live_observer import LiveObserver, ShadowLog
from iat.live_dashboard import create_dashboard
from iat.live_market_view import formal_artifact, gate_fingerprint
from iat.intelligence.strategy_replay import digest
from iat.sessions import SessionCalendar
from iat.session_config import load_session_config

NOW = datetime(2026, 11, 12, 12, 0, 10, tzinfo=timezone.utc)


class SyntheticTerminal:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, clock):
        self.clock = clock
        self.connected = True
        self.allowed = False
        self.api_disabled = True
        self.mode = 0
        self.visible = True
        self.age = 0.25
        self.ask = 100.03
        self.point = 0.01
        self.calls = []
        self.orders = 0
        self.mutate = None

    def terminal_info(self):
        return SimpleNamespace(
            connected=self.connected,
            trade_allowed=self.allowed,
            tradeapi_disabled=self.api_disabled,
        )

    def account_info(self):
        class PrivateAccount:
            def __getattr__(self, name):
                raise AssertionError("Account identifiers forbidden")

        a = PrivateAccount()
        a.trade_mode = self.mode
        return a

    def symbol_info(self, name):
        assert name == "XAUUSD"
        return SimpleNamespace(visible=self.visible, point=self.point)

    def symbol_info_tick(self, name):
        assert name == "XAUUSD"
        ms = int((self.clock() - timedelta(seconds=self.age)).timestamp() * 1000)
        return SimpleNamespace(bid=100.0, ask=self.ask, time=ms // 1000, time_msc=ms)

    def copy_rates_from_pos(self, symbol, tf, position, count):
        assert symbol == "XAUUSD" and position == 1
        self.calls.append((tf, position, count))
        period = tf * 60
        end = int(self.clock().timestamp()) // period * period
        rows = [
            dict(
                time=end - (count - i) * period,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                tick_volume=10 * tf,
                spread=3,
                real_volume=0,
            )
            for i in range(count)
        ]
        return self.mutate(rows, tf) if self.mutate else rows

    def order_send(self, *args, **kwargs):
        self.orders += 1
        raise AssertionError("Forbidden")

    def order_check(self, *args, **kwargs):
        self.orders += 1
        raise AssertionError("Forbidden")


class LiveMarketViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="iat V3 SYNTHETIC ")
        self.addCleanup(self.temp.cleanup)
        self.now = NOW
        self.mt5 = SyntheticTerminal(lambda: self.now)
        self.provider = ReadOnlyMarketData(self.mt5)
        self.observer = LiveObserver(
            self.provider,
            ShadowLog(Path(self.temp.name) / "private"),
            clock=lambda: self.now,
        )

    def view(self):
        self.observer.step()
        return self.observer.market_intelligence()

    def safe(self, r):
        for k, v in dict(
            signal="WAIT",
            execution_allowed=False,
            exness="BLOCKED",
            qualification="DATA_NOT_QUALIFIED",
            historical_validation="PENDING",
            historical_comparisons="NOT_RUN",
        ).items():
            self.assertEqual(r[k], v)
        self.assertEqual(
            r["sha256"], digest({k: v for k, v in r.items() if k != "sha256"})
        )
        self.assertEqual(self.mt5.orders, 0)
        json.dumps(r, allow_nan=False)

    def calendar(self, end=None):
        a = NOW.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)
        b = end or a + timedelta(days=4)
        return SessionCalendar(
            "XAUUSD", a, b, ((a, b),)
        )  # SYNTHETIC, never Exness approval.

    def test_real_capability_adapter_with_synthetic_demo_quote_and_broker_point(self):
        r = self.view()
        self.safe(r)
        self.assertEqual(r["status"], "DESCRIPTIVE_ONLY")
        self.assertEqual(r["quote"]["bid"], 100.0)
        self.assertEqual(r["quote"]["ask"], 100.03)
        self.assertAlmostEqual(r["quote"]["spread_points"], 3.0)
        self.assertEqual(r["quote"]["age_seconds"], 0.25)
        self.assertEqual(
            r["runtime"]["demo_checks"],
            dict(
                connected=True,
                demo_verified=True,
                terminal_trading_disabled=True,
                python_api_trading_disabled=True,
                symbol_visible=True,
            ),
        )
        self.assertTrue(r["descriptive"]["frames"]["M1"]["structure"])

    def test_missing_calendar_retains_descriptive_not_formal(self):
        r = self.view()
        self.safe(r)
        self.assertEqual(r["formal_context"]["status"], "UNAVAILABLE")
        self.assertIn("SESSION_CALENDAR_UNAVAILABLE", r["reason_codes"])
        self.assertEqual(r["adapter"]["status"], "BLOCKED")
        self.assertEqual(r["adapter"]["report"]["status"], "BLOCKED")
        self.assertTrue(r["descriptive"])

    def test_quality_valid_live_context_not_relabelled_as_offline(self):
        self.observer.calendar = self.calendar()
        r = self.view()
        self.safe(r)
        self.assertEqual(r["formal_context"]["status"], "AVAILABLE")
        self.assertEqual(r["formal_context"]["provenance"], "VALIDATED_LIVE")
        self.assertEqual(r["adapter"]["status"], "BLOCKED")
        self.assertIn("V3_LIVE_PROVENANCE_UNSUPPORTED", r["reason_codes"])

    def test_exness_candidate_stays_blocked(self):
        self.observer.calendar = load_session_config(
            "config/profiles/exness-xauusd-v2.candidate.json"
        )
        before = deepcopy(self.observer.calendar)
        r = self.view()
        self.safe(r)
        self.assertEqual(self.observer.calendar, before)
        self.assertEqual(r["formal_context"]["status"], "UNAVAILABLE")
        self.assertEqual(r["adapter"]["status"], "BLOCKED")
        self.assertTrue(r["reason_codes"])

    def test_quote_refresh_uses_exact_closed_cache_without_rebuilding(self):
        first = self.view()
        with patch(
            "iat.live_observer.frame_report", side_effect=AssertionError("must reuse")
        ), patch(
            "iat.live_observer.context_at", side_effect=AssertionError("must reuse")
        ):
            self.now += timedelta(seconds=1)
            self.mt5.ask = 100.04
            r = self.view()
        self.safe(r)
        self.assertEqual(r["status"], "DESCRIPTIVE_ONLY")
        self.assertEqual(r["runtime"]["analysis_computations"], 1)
        self.assertEqual(r["runtime"]["cache_hits"], 1)
        self.assertEqual(r["descriptive"], first["descriptive"])
        self.assertEqual(r["adapter"], first["adapter"])
        self.assertNotEqual(
            r["quote"]["observed_at_utc"], first["quote"]["observed_at_utc"]
        )
        self.assertEqual(
            len(self.mt5.calls), 4
        )  # acquisition and quality checks are NOT cached

    def test_new_closed_m1_recomputes(self):
        first = self.view()
        self.now += timedelta(minutes=1)
        r = self.view()
        self.safe(r)
        self.assertEqual(r["runtime"]["analysis_computations"], 2)
        self.assertNotEqual(r["cutoffs"]["M1"], first["cutoffs"]["M1"])

    def test_new_closed_m5_recomputes(self):
        first = self.view()
        self.now += timedelta(minutes=5)
        r = self.view()
        self.safe(r)
        self.assertEqual(r["runtime"]["analysis_computations"], 2)
        self.assertNotEqual(r["cutoffs"]["M5"], first["cutoffs"]["M5"])

    def test_failure_clears_cache_and_recovery_recomputes(self):
        self.view()
        self.mt5.connected = False
        r = self.view()
        self.safe(r)
        self.assertEqual(r["status"], "UNAVAILABLE")
        self.assertIsNone(self.observer._closed_cache)
        self.mt5.connected = True
        r = self.view()
        self.assertEqual(r["runtime"]["analysis_computations"], 2)

    def test_permission_change_invalidates_no_old_analysis(self):
        self.view()
        self.mt5.allowed = True
        r = self.view()
        self.safe(r)
        self.assertIsNone(r["quote"])
        self.assertIsNone(r["descriptive"])
        self.assertIn("TRADING_PERMISSIONS_NOT_DISABLED", r["reason_codes"])

    def test_non_demo_rejected(self):
        self.mt5.mode = 2
        r = self.view()
        self.safe(r)
        self.assertIn("DEMO_ACCOUNT_REQUIRED", r["reason_codes"])

    def test_stale_quote_invalidates(self):
        self.view()
        self.mt5.age = 31
        r = self.view()
        self.safe(r)
        self.assertIsNone(r["descriptive"])
        self.assertIn("TICK_STALE", r["reason_codes"])

    def test_future_quote_withheld_even_inside_legacy_tolerance(self):
        self.mt5.age = -0.14
        r = self.view()
        self.safe(r)
        self.assertIn("QUOTE_FUTURE", r["reason_codes"])
        self.assertIsNone(r["quote"])
        self.assertIsNone(r["descriptive"])

    def test_future_quote_outside_legacy_tolerance_rejected(self):
        self.mt5.age = -3
        r = self.view()
        self.safe(r)
        self.assertIn("TICK_FUTURE_OR_TIME_BASIS_AMBIGUOUS", r["reason_codes"])

    def test_http_rechecks_provider_freshness_without_new_tick(self):
        self.provider.quote_max_age_seconds = 2
        self.view()
        self.now += timedelta(seconds=3)
        r = self.observer.market_intelligence()
        self.safe(r)
        self.assertIn("TICK_STALE", r["reason_codes"])
        self.assertIsNone(r["quote"])

    def test_unavailable_broker_point_does_not_invent_spread(self):
        self.mt5.point = None
        r = self.view()
        self.safe(r)
        self.assertIsNone(r["quote"]["spread_points"])
        self.assertIsNone(r["quote"]["broker_point"])

    def test_clock_reversal_withholds(self):
        self.view()
        self.now -= timedelta(seconds=1)
        r = self.observer.market_intelligence()
        self.safe(r)
        self.assertEqual(r["status"], "UNAVAILABLE")
        self.assertIsNone(r["descriptive"])

    def test_unclosed_candle_never_presented(self):
        def corrupt(rows, tf):
            rows[-1]["time"] += tf * 60
            return rows

        self.mt5.mutate = corrupt
        r = self.view()
        self.safe(r)
        self.assertEqual(r["status"], "UNAVAILABLE")
        self.assertIsNone(r["descriptive"])

    def test_gap_cannot_be_hidden_by_cached_analysis(self):
        self.view()
        self.mt5.mutate = lambda rows, tf: rows[:40] + rows[41:]
        r = self.view()
        self.safe(r)
        self.assertIsNone(r["quote"])
        self.assertIsNone(self.observer._closed_cache)

    def test_corrected_ohlc_source_recomputes_and_existing_revision_guard_survives(
        self,
    ):
        self.observer.calendar = self.calendar()
        self.view()

        def change(rows, tf):
            rows[-1]["close"] = 100.5
            return rows

        self.mt5.mutate = change
        for i in range(2):
            r = self.view()
            self.safe(r)
            self.assertIn("CLOSED_CANDLE_REVISION_DETECTED", r["reason_codes"])
        self.assertEqual(self.observer.analysis_cache_hits, 0)

    def test_calendar_change_rechecked_at_http_and_next_acquisition(self):
        self.view()
        self.observer.calendar = self.calendar()
        r = self.observer.market_intelligence()
        self.safe(r)
        self.assertIn("SESSION_STATE_CHANGED", r["reason_codes"])
        r = self.view()
        self.assertEqual(r["runtime"]["analysis_computations"], 2)

    def test_calendar_expiry_between_acquisitions_withheld(self):
        self.observer.calendar = self.calendar(NOW + timedelta(seconds=1))
        self.view()
        self.now += timedelta(seconds=2)
        r = self.observer.market_intelligence()
        self.safe(r)
        self.assertIn("SESSION_STATE_CHANGED", r["reason_codes"])

    def test_http_revalidates_closed_history_even_with_fresh_quote(self):
        # High interval keeps legacy observer-stall threshold open, but M1 quality expires.
        self.observer.interval = 60
        self.view()
        self.now += timedelta(seconds=119)
        with self.observer.lock:
            self.observer.cached["quote"]["observed_at_utc"] = self.now.isoformat()
            self.observer.cached["snapshot_id"] = digest(
                {k: v for k, v in self.observer.cached.items() if k != "snapshot_id"}
            )
            self.observer._live_publication["snapshot_id"] = self.observer.cached[
                "snapshot_id"
            ]
        r = self.observer.market_intelligence()
        self.safe(r)
        self.assertEqual(r["status"], "UNAVAILABLE")
        self.assertIsNone(r["descriptive"])

    def test_config_change_invalidates(self):
        from iat.intelligence.context_models import ContextConfig

        self.view()
        with patch(
            "iat.live_observer.ContextConfig",
            return_value=replace(ContextConfig(), roc_period=6),
        ):
            r = self.view()
        self.assertEqual(self.observer.analysis_computations, 2)

    def test_invalid_context_source_binding_not_cached(self):
        import iat.live_observer as module

        original = module.context_at

        def changed(*args, **kwargs):
            return replace(original(*args, **kwargs), configuration_sha256="0" * 64)

        with patch.object(module, "context_at", side_effect=changed):
            r = self.view()
            r = self.view()
        self.safe(r)
        self.assertIn("LIVE_CONTEXT_BINDING_INVALID", r["reason_codes"])
        self.assertEqual(self.observer.analysis_computations, 2)

    def test_absent_and_wrong_provenance_typed_context_rejected(self):
        self.view()
        snapshot = self.observer.latest()
        a = formal_artifact(snapshot, None, None)
        self.assertIn(
            "LIVE_CONTEXT_BINDING_INVALID", a["formal_context"]["reason_codes"]
        )
        from iat.intelligence.context import context_at

        rows = self.observer._closed_cache["rows"]
        at = NOW.replace(second=0)
        offline = context_at("XAUUSD", rows["M1"], rows["M5"], at)
        self.assertIn(
            "LIVE_CONTEXT_BINDING_INVALID",
            formal_artifact(snapshot, offline, None)["formal_context"]["reason_codes"],
        )

    def test_http_snapshot_binding_race_withheld(self):
        self.view()
        with self.observer.lock:
            self.observer._live_publication["snapshot_id"] = "0" * 64
        r = self.observer.market_intelligence()
        self.safe(r)
        self.assertEqual(r["status"], "UNAVAILABLE")

    def test_tampered_snapshot_with_publication_id_rejected(self):
        self.view()
        with self.observer.lock:
            self.observer.cached["quote"]["bid"] = 999.0
        r = self.observer.market_intelligence()
        self.safe(r)
        self.assertIn("LIVE_SNAPSHOT_BINDING_INVALID", r["reason_codes"])

    def test_adapter_failure_withholds_formal_artifact_and_is_not_cached(self):
        self.observer.calendar = self.calendar()
        with patch(
            "iat.live_market_view.validate_market_view_v3",
            side_effect=ValueError("invalid adapter output"),
        ):
            r = self.view()
            self.assertEqual(r["formal_context"]["status"], "UNAVAILABLE")
            self.assertIsNone(r["adapter"]["report"])
            self.assertIn("LIVE_CONTEXT_BINDING_INVALID", r["reason_codes"])
            r = self.view()
        self.safe(r)
        self.assertEqual(self.observer.analysis_computations, 2)

    def test_cache_and_uncached_observation_payload_are_equivalent(self):
        self.observer.calendar = self.calendar()
        self.view()
        self.now += timedelta(seconds=1)
        cached = self.observer.step()
        self.observer._closed_cache = (
            None  # Force only analysis, not observations, to recompute.
        )
        computed = self.observer.step()
        for key in (
            "quote",
            "observations",
            "scenario",
            "cutoffs",
            "reasoning",
            "candle_quality",
            "snapshot_id",
        ):
            self.assertEqual(cached[key], computed[key], key)

    def test_unchanged_quote_timestamp_ages_out_on_refresh(self):
        fixed = self.mt5.symbol_info_tick("XAUUSD")
        with patch.object(self.mt5, "symbol_info_tick", return_value=fixed):
            # Capability wrapper retains bound read callables, so bind before construction.
            o = LiveObserver(
                ReadOnlyMarketData(self.mt5),
                ShadowLog(Path(self.temp.name) / "unchanged"),
                clock=lambda: self.now,
            )
            self.assertEqual(o.step()["feed_status"], "CONNECTED")
            self.now += timedelta(seconds=31)
            snapshot = o.step()
            self.assertIn("TICK_STALE", snapshot["reason_codes"])
            self.assertIsNone(o.market_intelligence()["quote"])

    def test_source_registry_mismatch_rejected_even_with_typed_context(self):
        import iat.live_observer as module

        original = module.context_at
        self.observer.calendar = self.calendar()

        def mismatch(*args, **kwargs):
            c = original(*args, **kwargs)
            interpretations = deepcopy(c.interpretations)
            interpretations["source_registry"] = {}
            return replace(c, interpretations=interpretations)

        with patch.object(module, "context_at", side_effect=mismatch):
            r = self.view()
        self.safe(r)
        self.assertIn("LIVE_CONTEXT_BINDING_INVALID", r["reason_codes"])
        self.assertEqual(r["adapter"]["status"], "UNAVAILABLE")

    def test_metadata_only_strategy_not_evaluated(self):
        with patch(
            "iat.intelligence.sr_rejection.evaluate_sr_rejection",
            side_effect=AssertionError("No live evaluation"),
        ):
            r = self.view()
        self.safe(r)
        self.assertEqual(r["strategy"]["live_status"], "NOT_RUN")
        self.assertEqual(r["strategy"]["validation_status"], "SYNTHETIC_ONLY")
        for name in ("iat/live_market_view.py", "iat/live_observer.py"):
            tree = ast.parse(Path(name).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(
                        node.attr,
                        ("order_send", "order_check", "login", "symbol_select"),
                    )

    def test_http_security_backcompat_and_no_acquisition(self):
        self.view()
        before = self.observer.latest()
        calls = list(self.mt5.calls)
        client = create_dashboard(self.observer).test_client()
        for route in (
            "/live/v1/snapshot",
            "/live/v2/snapshot",
            "/live/v3/snapshot",
            "/live/intelligence/v3/snapshot",
        ):
            r = client.get(route)
            self.assertEqual(r.status_code, 200)
            self.assertIn("no-store", r.headers["Cache-Control"])
            self.assertEqual(client.get(route + "?token=private").status_code, 400)
            self.assertEqual(client.post(route).status_code, 405)
            self.assertEqual(
                client.get(
                    route, environ_overrides={"REMOTE_ADDR": "10.0.0.2"}
                ).status_code,
                403,
            )
        self.assertEqual(client.get("/live/v1/snapshot").get_json(), before)
        self.assertEqual(self.observer.latest(), before)
        self.assertEqual(self.mt5.calls, calls)
        html = client.get("/").get_data(as_text=True)
        self.assertIn("market-view.js", html)
        self.assertIn("live.js", html)
        self.assertIn("market-view-panel", html)
        self.assertEqual(client.get("/market-view.js").status_code, 200)

    def test_repeatability_and_no_mutation_on_public_read(self):
        self.view()
        a = self.observer.market_intelligence()
        b = self.observer.market_intelligence()
        self.assertEqual(a, b)
        self.safe(a)
        a["adapter"]["report"]["status"] = "FAKE"
        a["descriptive"]["frames"].clear()
        self.assertEqual(b, self.observer.market_intelligence())

    def test_journal_failure_removes_presentation(self):
        self.view()
        with patch.object(
            self.observer.log,
            "append",
            side_effect=OSError("private details must not leak"),
        ):
            r = self.view()
        self.safe(r)
        self.assertIn("SHADOW_LOG_FAILED", r["reason_codes"])
        self.assertIsNone(r["quote"])
        self.assertNotIn("private details", json.dumps(r))

    def test_frontend_renders_and_clears_stale_fields_without_html_execution(self):
        if shutil.which("node") is None:
            self.skipTest("Node unavailable; CI installs Node")
        r = self.view()
        harness = r"""
const fs=require('fs'),vm=require('vm');const input=JSON.parse(fs.readFileSync(0,'utf8'));
class Element { constructor(){this.children=[];this.textContent='';} append(...v){this.children.push(...v);} replaceChildren(){this.children=[];} }
const nodes={};let scheduled=[],fail=false;
const context={document:{getElementById:id=>nodes[id]||(nodes[id]=new Element()),createElement:()=>new Element()},AbortController,console,
setTimeout:(f,ms)=>{scheduled.push([f,ms]);return scheduled.length;},clearTimeout:()=>{},
fetch:async url=>{if(fail)throw Error('offline');return {ok:true,json:async()=>url.includes('settings')?{refresh_seconds:10}:input};}};
vm.runInNewContext(fs.readFileSync('iat/live_web/market-view.js','utf8'),context);
setImmediate(async()=>{setImmediate(async()=>{
function all(n){return n.textContent+' '+n.children.map(all).join(' ');}
if(nodes['mv-status'].textContent!=='DESCRIPTIVE_ONLY'||!all(nodes['mv-runtime']).includes('100.03')||!all(nodes['mv-strategy']).includes('NOT_RUN'))throw Error('Rendering failed');
if(nodes['entry-research-state'].textContent!=='BLOCKED'||!all(nodes['entry-research-reasons']).includes('ENTRY_SYNTHETIC_ONLY'))throw Error('Live entry research was not blocked');
if(nodes['exit-research-state'].textContent!=='BLOCKED'||!all(nodes['entry-research-reasons']).includes('EXIT_SYNTHETIC_ONLY'))throw Error('Live exit research was not blocked');
if(nodes['risk-research-state'].textContent!=='BLOCKED'||!all(nodes['entry-research-reasons']).includes('RISK_SYNTHETIC_ONLY'))throw Error('Live risk research was not blocked');
fail=true;const retry=scheduled.find(x=>x[1]===10000);await retry[0]();
if(nodes['mv-status'].textContent!=='UNAVAILABLE'||all(nodes['mv-runtime']).includes('100.03')||nodes['mv-report'].textContent!=='Unavailable')throw Error('Stale fields retained');
console.log('render and unavailable state passed');
});});
"""
        result = subprocess.run(
            ["node", "-e", harness],
            input=json.dumps(r),
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("render and unavailable state passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
