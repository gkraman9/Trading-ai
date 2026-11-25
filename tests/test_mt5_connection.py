"""Controlled SDK doubles only. No actual Windows MT5 attachment is established."""

from datetime import timedelta
from pathlib import Path
from threading import Event, Thread, get_ident
from types import SimpleNamespace
from unittest.mock import patch
from time import monotonic, sleep
import json
import tempfile
import unittest
from test_live_observer import MockMT5, NOW
from iat.mt5_connection import MT5Connection
from iat.live_observer import LiveObserver, ShadowLog
from iat.live_dashboard import create_dashboard


class SDK(MockMT5):
    __version__ = "5.0.6231"

    def __init__(self):
        super().__init__()
        self.ok = True
        self.error = (1, "Success")
        self.operations = []
        self.boom = False

    def initialize(self, *args, **kw):
        self.initialization_path = args[0] if args else None
        self.operations.append(("initialize", get_ident(), kw))
        if self.boom:
            raise RuntimeError("PRIVATE_PASSWORD_SERVER_PATH")
        return self.ok

    def shutdown(self):
        self.operations.append(("shutdown", get_ident(), {}))
        self.error = (1, "cleanup overwrote error")

    def last_error(self):
        return self.error

    def terminal_info(self):
        self.operations.append(("terminal", get_ident(), {}))
        return super().terminal_info()

    def copy_rates_from_pos(self, *args):
        self.operations.append(("rates", get_ident(), {}))
        return super().copy_rates_from_pos(*args)


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.sdk = SDK()
        self.now = NOW
        self.p = MT5Connection(lambda: self.sdk, clock=lambda: self.now)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.o = LiveObserver(
            self.p, ShadowLog(Path(self.tmp.name) / "journal"), clock=lambda: self.now
        )

    def failed(self, code):
        r = self.o.step()
        self.assertIn(code, r["reason_codes"])
        self.assertIsNone(r["quote"])
        self.assertFalse(r["execution_allowed"])
        self.assertEqual(r["signal"], "WAIT")
        return r

    def good(self):
        r = self.o.step()
        self.assertEqual(r["feed_status"], "CONNECTED", r["reason_codes"])
        return r

    def recover_time(self):
        self.now += timedelta(seconds=2)

    def test_initialization_false_captures_error_before_shutdown(self):
        self.sdk.ok = False
        self.sdk.error = (-10003, "PRIVATE_PASSWORD_SERVER_PATH")
        r = self.failed("INITIALIZATION_FAILED")
        self.assertEqual(r["connection"]["mt5_error_code"], -10003)
        self.assertEqual(self.o.analysis_computations, 0)

    def test_initialization_exception_is_sanitized(self):
        self.sdk.boom = True
        r = self.failed("INITIALIZATION_EXCEPTION")
        self.assertNotIn("PRIVATE", json.dumps(r))

    def test_module_unavailable(self):
        self.p._loader = lambda: (_ for _ in ()).throw(ImportError("PRIVATE"))
        self.failed("PROVIDER_UNAVAILABLE")

    def test_terminal_none_is_distinct_from_disconnected(self):
        self.sdk.terminal_info = lambda: None
        r = self.failed("TERMINAL_INFO_UNAVAILABLE")
        self.assertIsNone(r["connection"]["demo_verified"])

    def test_terminal_disconnected(self):
        self.sdk.connected = False
        self.failed("PROVIDER_DISCONNECTED")

    def test_missing_permissions_unknown_not_confirmed_violation(self):
        self.sdk.allowed = None
        r = self.failed("SAFETY_INFORMATION_UNAVAILABLE")
        self.assertIsNone(r["connection"]["terminal_trading_disabled"])

    def test_missing_demo_information_is_unknown(self):
        self.sdk.account_info = lambda: None
        r = self.failed("SAFETY_INFORMATION_UNAVAILABLE")
        self.assertIsNone(r["connection"]["demo_verified"])

    def test_initial_failure_recovers_fresh_acquisition(self):
        self.sdk.ok = False
        self.failed("INITIALIZATION_FAILED")
        self.sdk.ok = True
        self.failed("CONNECTION_RETRY_PENDING")
        self.recover_time()
        r = self.good()
        self.assertEqual(r["connection"]["connection_generation"], 1)
        self.assertIsNotNone(r["connection"]["last_successful_acquisition_utc"])

    def test_established_loss_invalidates_cache_then_recovers(self):
        self.good()
        self.sdk.connected = False
        self.failed("PROVIDER_DISCONNECTED")
        self.assertIsNone(self.o._closed_cache)
        self.assertIsNone(self.o.previous)
        self.sdk.connected = True
        self.recover_time()
        r = self.good()
        self.assertEqual(r["connection"]["connection_generation"], 2)
        self.assertFalse(self.o._live_publication["runtime"]["cache_hit"])

    def test_terminal_restart_is_new_generation(self):
        self.good()
        self.sdk.connected = False
        self.failed("PROVIDER_DISCONNECTED")
        self.sdk.connected = True
        self.recover_time()
        r = self.good()
        self.assertEqual(r["connection"]["connection_generation"], 2)

    def test_loss_during_acquisition_with_ipc_error(self):
        original = self.sdk.copy_rates_from_pos

        def lost(*args):
            self.sdk.connected = False
            self.sdk.error = (-10002, "PRIVATE")
            return None

        self.sdk.copy_rates_from_pos = (
            lost  # binding must be installed before initialization
        )
        self.failed("IPC_COMMUNICATION_FAILURE")
        self.assertIsNone(self.o._closed_cache)

    def test_final_safety_recheck_rejects_permission_change_during_read(self):
        original = self.sdk.copy_rates_from_pos

        def read(*args):
            result = original(*args)
            self.sdk.allowed = True
            return result

        self.sdk.copy_rates_from_pos = read
        self.failed("TRADING_PERMISSIONS_NOT_DISABLED")

    def test_bounded_exponential_retry_and_no_busy_initialization(self):
        self.sdk.ok = False
        delays = []
        for _ in range(8):
            self.failed("INITIALIZATION_FAILED")
            s = self.p.snapshot()
            retry = __import__("datetime").datetime.fromisoformat(s["next_retry_utc"])
            delays.append((retry - self.now).total_seconds())
            n = len(self.sdk.operations)
            self.failed("CONNECTION_RETRY_PENDING")
            self.assertEqual(n, len(self.sdk.operations))
            self.now = retry
        self.assertEqual(delays, [2, 4, 8, 16, 32, 60, 60, 60])

    def test_reconnect_demo_failure_blocks_without_quote(self):
        self.good()
        self.sdk.connected = False
        self.failed("PROVIDER_DISCONNECTED")
        self.recover_time()
        self.sdk.connected = True
        self.sdk.mode = 2
        r = self.failed("DEMO_ACCOUNT_REQUIRED")
        self.assertEqual(r["connection"]["state"], "SAFETY_BLOCKED")

    def test_reconnect_permissions_failure(self):
        self.good()
        self.sdk.connected = False
        self.failed("PROVIDER_DISCONNECTED")
        self.recover_time()
        self.sdk.connected = True
        self.sdk.api_disabled = False
        self.failed("TRADING_PERMISSIONS_NOT_DISABLED")

    def test_reconnect_missing_symbol(self):
        self.good()
        self.sdk.connected = False
        self.failed("PROVIDER_DISCONNECTED")
        self.recover_time()
        self.sdk.connected = True
        self.sdk.visible = False
        self.failed("SYMBOL_NOT_VISIBLE")

    def test_reconnect_missing_quote_never_publishes_old_analysis(self):
        self.good()
        self.sdk.connected = False
        self.failed("PROVIDER_DISCONNECTED")
        self.recover_time()
        self.sdk.connected = True
        self.p._template._tick = lambda name: None
        r = self.failed("TICK_UNAVAILABLE")
        self.assertEqual(r["connection"]["state"], "MARKET_DATA_UNAVAILABLE")

    def test_stale_quote_remains_blocked_after_reconnect(self):
        self.good()
        self.sdk.connected = False
        self.failed("PROVIDER_DISCONNECTED")
        self.recover_time()
        self.sdk.connected = True
        self.sdk.tick_age = 100
        self.failed("TICK_STALE")

    def test_acquisition_success_requires_both_closed_frames(self):
        self.sdk.mutate = lambda data, tf: data[:-1] if tf == 5 else data
        r = self.failed("HISTORY_INCOMPLETE")
        self.assertIsNone(r["connection"]["last_successful_acquisition_utc"])

    def test_unknown_gaps_not_filled_or_approved(self):
        def gap(data, tf):
            if tf == 1:
                for row in data[:250]:
                    row["time"] -= 3600
            return data

        self.sdk.mutate = gap
        r = self.o.step()
        self.assertEqual(r["feed_status"], "DATA_UNAVAILABLE")
        self.assertIsNone(r["quote"])
        self.assertEqual(r["connection"]["state"], "DATA_QUALITY_BLOCKED")
        self.assertIn("GAP_UNVERIFIED", r["reason_codes"])

    def test_http_reads_never_touch_sdk(self):
        self.good()
        n = len(self.sdk.operations)
        c = create_dashboard(self.o).test_client()
        for endpoint in (
            "/live/v1/snapshot",
            "/live/intelligence/v3/snapshot",
            "/live/v3/snapshot",
        ):
            self.assertEqual(c.get(endpoint).status_code, 200)
        self.assertEqual(n, len(self.sdk.operations))

    def test_other_thread_is_rejected_before_native_call(self):
        self.good()
        n = len(self.sdk.operations)
        errors = []

        def read():
            try:
                self.p.terminal_info()
            except Exception as e:
                errors.append(e.code)

        t = Thread(target=read)
        t.start()
        t.join()
        self.assertEqual(errors, ["CONNECTION_OWNER_MISMATCH"])
        self.assertEqual(n, len(self.sdk.operations))

    def test_owner_initialization_reads_shutdown_same_thread(self):
        self.o.start()
        deadline = monotonic() + 3
        while self.o.latest()["feed_status"] != "CONNECTED" and monotonic() < deadline:
            sleep(0.01)
        self.o.close()
        self.assertFalse(self.o.thread.is_alive())
        ids = {x[1] for x in self.sdk.operations}
        self.assertEqual(len(ids), 1)
        self.assertNotIn(get_ident(), ids)
        self.assertEqual(self.sdk.operations[-1][0], "shutdown")

    def test_stop_during_backoff_is_interruptible(self):
        self.sdk.ok = False
        self.o.start()
        deadline = monotonic() + 2
        while not self.sdk.operations and monotonic() < deadline:
            sleep(0.01)
        began = monotonic()
        self.o.close()
        self.assertLess(monotonic() - began, 1)
        self.assertFalse(self.o.thread.is_alive())

    def test_repeated_start_stop_no_orphan_or_overlap(self):
        for _ in range(3):
            self.o.start()
            with self.assertRaises(ValueError):
                self.o.start()
            self.o.close()
            self.assertFalse(self.o.thread.is_alive())
        self.assertEqual(self.p.snapshot()["owner_state"], "STOPPED")

    def test_stop_during_native_init_never_concurrently_shutdowns(self):
        entered = Event()
        release = Event()
        original = self.sdk.initialize

        def slow(**kw):
            entered.set()
            release.wait(3)
            return original(**kw)

        self.sdk.initialize = slow
        self.o.start()
        self.assertTrue(entered.wait(1))
        # Signal stop without waiting for an uninterruptible native call.
        self.o.stop.set()
        with self.assertRaises(ValueError):
            self.o.start()
        self.assertFalse(any(x[0] == "shutdown" for x in self.sdk.operations))
        release.set()
        self.o.close()
        self.assertFalse(self.o.thread.is_alive())

    def test_safe_facts_and_no_order_capability(self):
        r = self.good()
        self.assertEqual(r["qualification"], "DATA_NOT_QUALIFIED")
        self.assertEqual(r["exness"], "BLOCKED")
        for name in (
            "order_send",
            "order_check",
            "login",
            "symbol_select",
            "initialize",
            "shutdown",
        ):
            self.assertFalse(hasattr(self.p, name))
        for kind in ("entry", "risk", "paper"):
            self.assertNotIn(kind.upper() + "_AUTHORIZED", json.dumps(r))

    def test_raw_history_is_retained_after_final_safety_recheck(self):
        self.good()
        self.assertEqual(set(self.p.raw), {"M1", "M5"})

    def test_explicit_wrong_attachment_is_blocked_and_path_not_printed(self):
        self.p._path = "PRIVATE_TERMINAL_PATH"
        self.sdk.terminal_info = lambda: SimpleNamespace(
            connected=True,
            trade_allowed=False,
            tradeapi_disabled=True,
            path="OTHER_PRIVATE_PATH",
        )
        r = self.failed("TERMINAL_ATTACHMENT_UNVERIFIED")
        self.assertEqual(self.sdk.initialization_path, "PRIVATE_TERMINAL_PATH")
        self.assertNotIn("PRIVATE", json.dumps(r))
        self.assertEqual(r["connection"]["state"], "SAFETY_BLOCKED")

    def test_no_automatic_ai_paper_strategy_or_orders(self):
        r = self.good()
        view = self.o.market_intelligence()
        self.assertEqual(view["strategy"]["live_status"], "NOT_RUN")
        self.assertFalse(r["execution_allowed"])
        self.assertEqual(self.sdk.orders, 0)

    def test_diagnostic_payload_bounded_even_for_hostile_errors(self):
        self.sdk.ok = False
        self.sdk.error = ("PRIVATE" * 100000, "PRIVATE" * 100000)
        self.failed("INITIALIZATION_FAILED")
        s = json.dumps(self.p.snapshot())
        self.assertLess(len(s), 3000)
        self.assertNotIn("PRIVATE", s)


class ProbeTests(unittest.TestCase):
    def test_inspection_does_not_load_sdk(self):
        from diagnostics.mt5_connection_probe import probe

        def forbidden():
            raise AssertionError("Must not load SDK")

        r = probe(inspect_only=True, loader=forbidden)
        self.assertFalse(r["attachment_attempted"])
        self.assertIsNone(r["connection"])
        self.assertFalse(r["execution_allowed"])

    def test_probe_is_same_owner_and_redacts_path(self):
        from diagnostics.mt5_connection_probe import probe

        sdk = SDK()
        sdk.terminal_info = lambda: SimpleNamespace(
            connected=True,
            trade_allowed=False,
            tradeapi_disabled=True,
            path="PRIVATE_ACCOUNT_PATH",
        )
        r = probe(loader=lambda: sdk, nonce="a" * 32)
        self.assertNotIn("PRIVATE", json.dumps(r))
        self.assertIsNotNone(r["attachment_token"])
        self.assertEqual(r["acquisition"], "NOT_RUN")
        self.assertEqual(len({x[1] for x in sdk.operations}), 1)

    def test_probe_failure_never_echoes_exception(self):
        from diagnostics.mt5_connection_probe import probe

        sdk = SDK()
        sdk.boom = True
        r = probe(loader=lambda: sdk)
        self.assertEqual(r["connection"]["state"], "INITIALIZATION_FAILED")
        self.assertNotIn("PRIVATE", json.dumps(r))

    def test_launcher_validate_only_precedes_any_attachment(self):
        text = Path("diagnostics/Start-IATLiveMarketView.ps1").read_text()
        self.assertLess(
            text.index("if ($ValidateOnly)"), text.index("-c 'import MetaTrader5'")
        )
        text = Path("diagnostics/Test-IATMT5Connection.ps1").read_text()
        self.assertIn("'--inspect-only'", text)
        self.assertNotIn("Start-Process", text)
        self.assertNotIn("order_send", text)


class AdditionalLifecycleTests(unittest.TestCase):
    setUp = ConnectionTests.setUp
    failed = ConnectionTests.failed
    good = ConnectionTests.good
    recover_time = ConnectionTests.recover_time

    def test_unsupported_sdk_capabilities_retry_transactionally(self):
        self.p._loader = lambda: SimpleNamespace(
            initialize=self.sdk.initialize, shutdown=self.sdk.shutdown
        )
        self.failed("MT5_PACKAGE_CAPABILITY_MISMATCH")
        self.p._loader = lambda: self.sdk
        self.recover_time()
        self.good()

    def test_unknown_permission_types_are_not_confirmed_violations(self):
        self.sdk.allowed = "PRIVATE_FALSE"
        r = self.failed("SAFETY_INFORMATION_UNAVAILABLE")
        self.assertIsNone(r["connection"]["terminal_trading_disabled"])

    def test_http_initializing_uses_only_memory_diagnostics(self):
        n = len(self.sdk.operations)
        r = self.o.market_intelligence()
        self.assertEqual(r["runtime"]["connection"]["state"], "INITIALIZING")
        self.assertEqual(n, len(self.sdk.operations))

    def test_owner_failure_blocks_http_before_observer_cache_replacement(self):
        self.good()
        self.sdk.connected = False
        with self.assertRaises(Exception):
            self.p.preflight()
        r = self.o.latest()
        self.assertIsNone(r["quote"])
        self.assertEqual(r["connection"]["state"], "DISCONNECTED")

    def test_restart_cannot_reuse_old_analysis_cache(self):
        for _ in range(2):
            self.o.start()
            deadline = monotonic() + 3
            while (
                self.o.latest()["feed_status"] != "CONNECTED" and monotonic() < deadline
            ):
                sleep(0.01)
            self.assertEqual(self.o.latest()["feed_status"], "CONNECTED")
            self.o.close()
        self.assertEqual(self.o.analysis_computations, 2)

    def test_overdue_native_call_withholds_snapshot_without_competing_shutdown(self):
        from iat.mt5_connection import monotonic as real_time

        entered = Event()
        release = Event()
        original = self.sdk.initialize

        def blocked(**kw):
            entered.set()
            release.wait(3)
            return original(**kw)

        self.sdk.initialize = blocked
        self.o.start()
        self.assertTrue(entered.wait(1))
        try:
            with patch(
                "iat.mt5_connection.monotonic", side_effect=lambda: real_time() + 11
            ):
                r = self.o.latest()
                self.assertEqual(r["connection"]["owner_state"], "NATIVE_CALL_OVERDUE")
                self.assertIsNone(r["quote"])
                self.assertIsNone(r["connection"]["connected"])
            with self.assertRaises(ValueError):
                self.o.start()
            self.assertFalse(any(v[0] == "shutdown" for v in self.sdk.operations))
        finally:
            release.set()
            self.o.close()

    def test_slow_final_safety_recheck_cannot_publish_recovery(self):
        original = self.sdk.terminal_info
        count = [0]

        def read():
            count[0] += 1
            if count[0] == 4:
                self.now += timedelta(seconds=11)
            return original()

        self.sdk.terminal_info = read
        r = self.failed("ACQUISITION_LATENCY_EXCEEDED")
        self.assertIsNone(r["connection"]["last_successful_acquisition_utc"])

    def test_shutdown_failure_is_sanitized_and_distinct_from_attachment_failure(self):
        def broken():
            self.sdk.error = (-10005, "PRIVATE_SHUTDOWN_PATH")
            raise RuntimeError("PRIVATE_SHUTDOWN_PATH")

        self.sdk.shutdown = broken
        self.sdk.ok = False
        r = self.failed("INITIALIZATION_FAILED")
        self.assertEqual(r["connection"]["shutdown_status"], "FAILED")
        self.assertEqual(r["connection"]["shutdown_error_code"], -10005)
        self.assertEqual(r["connection"]["mt5_error_code"], 1)
        self.assertNotIn("PRIVATE", json.dumps(r))
