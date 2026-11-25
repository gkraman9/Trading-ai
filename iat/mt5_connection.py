"""Serialized local read-only attachment. No account selection or execution capability."""

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from importlib import import_module
from threading import get_ident, Lock
from time import monotonic
import contextlib
import os
import re
import struct
import sys
from pathlib import Path
from iat.live_data import ReadOnlyMarketData
from iat.mt5_data import MarketDataError

CONNECTION_CODES = frozenset(
    {
        "INITIALIZATION_FAILED",
        "INITIALIZATION_EXCEPTION",
        "PROVIDER_UNAVAILABLE",
        "TERMINAL_INFO_UNAVAILABLE",
        "PROVIDER_DISCONNECTED",
        "IPC_COMMUNICATION_FAILURE",
        "CONNECTION_OPERATION_EXCEPTION",
    }
)
IPC_CODES = frozenset({-10000, -10001, -10002, -10003, -10004, -10005})


def package_label(value):
    return (
        value
        if type(value) is str and re.fullmatch(r"\d{1,5}(?:\.\d{1,5}){1,3}", value)
        else None
    )


class MT5Connection:
    timestamp_basis = "MT5_API_UTC_EPOCH"
    quote_max_age_seconds = 30  # Existing policy, never widened by recovery.

    def __init__(
        self,
        loader=None,
        *,
        clock=None,
        terminal_path=None,
        initial_delay=2,
        max_delay=60
    ):
        if (
            type(initial_delay) is not int
            or type(max_delay) is not int
            or not 2 <= initial_delay <= max_delay <= 60
        ):
            raise ValueError("Retry delays must be 2..60 seconds")
        self._loader = loader or (lambda: import_module("MetaTrader5"))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._path = terminal_path
        self._initial = initial_delay
        self._cap = max_delay
        self._operation_started = None
        self._owner = None
        self._claim_lock = Lock()
        self._reader = None
        self._initialize = None
        self._shutdown = None
        self._last_error = None
        self._attached = False
        self._failures = 0
        self._retry = None
        self.raw = {}
        self.diagnostics = {}
        self._point = None
        self._state = dict(
            connection_version=1,
            state="INITIALIZING",
            status_reason_code="OBSERVER_STARTING",
            owner_state="NOT_STARTED",
            connected=None,
            last_successful_connection_utc=None,
            last_successful_acquisition_utc=None,
            last_connection_failure_reason=None,
            mt5_error_code=None,
            shutdown_status="NOT_ATTEMPTED",
            shutdown_error_code=None,
            reconnection_attempt_count=0,
            next_retry_utc=None,
            connection_generation=0,
            terminal_selection=(
                "EXPLICIT_PATH" if terminal_path else "DEFAULT_UNVERIFIED"
            ),
            terminal_attachment_verified=None,
            demo_verified=None,
            terminal_trading_disabled=None,
            python_api_trading_disabled=None,
            symbol_visible=None,
            runtime=dict(
                python=".".join(map(str, sys.version_info[:3])),
                architecture_bits=struct.calcsize("P") * 8,
                mt5_package=None,
            ),
            signal="WAIT",
            execution_allowed=False,
            exness="BLOCKED",
            qualification="DATA_NOT_QUALIFIED",
            historical_validation="PENDING",
            historical_comparisons="NOT_RUN",
            mode="READ_ONLY_SHADOW",
        )
        self._state_lock = Lock()

    def snapshot(self):
        with self._state_lock:
            value = deepcopy(self._state)
            started = self._operation_started
        if started is not None and monotonic() - started > 10:
            value.update(
                state="DISCONNECTED",
                connected=None,
                owner_state="NATIVE_CALL_OVERDUE",
                status_reason_code="MT5_NATIVE_CALL_OVERDUE",
                demo_verified=None,
                terminal_trading_disabled=None,
                python_api_trading_disabled=None,
            )
        return value

    def _update(self, **values):
        with self._state_lock:
            self._state.update(values)

    def _claim(self):
        with self._claim_lock:
            if self._owner is None:
                self._owner = get_ident()
                self._update(owner_state="SERIALIZED_OWNER")
            if self._owner != get_ident():
                raise MarketDataError("Owner required", "CONNECTION_OWNER_MISMATCH")

    def _error(self):
        try:
            with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(
                quiet
            ), contextlib.redirect_stderr(quiet):
                value = self._last_error() if self._last_error else None
            code = value[0] if type(value) in (tuple, list) and value else None
            return code if type(code) is int and -(2**31) <= code < 2**31 else None
        except Exception:
            return None

    def _quiet(self, fn, *args, **kw):
        # Python cannot cancel a blocked native SDK call. Keep ownership, expose
        # overdue status, and never start a competing native call or shutdown.
        with self._state_lock:
            self._operation_started = monotonic()
            self._state["owner_state"] = "NATIVE_CALL_IN_PROGRESS"
        try:
            with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(
                quiet
            ), contextlib.redirect_stderr(quiet):
                return fn(*args, **kw)
        finally:
            with self._state_lock:
                self._operation_started = None
                self._state["owner_state"] = "SERIALIZED_OWNER"

    def _detach(self):
        if self._shutdown is not None:
            try:
                self._quiet(self._shutdown)
            except Exception:
                self._update(
                    shutdown_status="FAILED", shutdown_error_code=self._error()
                )
            else:
                self._update(shutdown_status="COMPLETED", shutdown_error_code=None)
        self._attached = False
        self._reader = None
        self.raw = {}
        self.diagnostics = {}
        self._point = None

    def _failure(self, code, error=None):
        # Callers capture last_error BEFORE cleanup can overwrite the native error.
        self._failures = min(9, self._failures + 1)
        delay = min(self._cap, self._initial * (2 ** min(self._failures - 1, 8)))
        self._retry = self._clock() + timedelta(seconds=delay)
        self._update(
            state=(
                "INITIALIZATION_FAILED"
                if code.startswith("INITIALIZATION")
                else "DISCONNECTED"
            ),
            connected=False,
            last_connection_failure_reason=code,
            status_reason_code=code,
            mt5_error_code=error,
            next_retry_utc=self._retry.isoformat(),
            demo_verified=None,
            terminal_trading_disabled=None,
            python_api_trading_disabled=None,
            symbol_visible=None,
            terminal_attachment_verified=None,
        )
        self._detach()
        raise MarketDataError("Read-only connection unavailable", code)

    def _load(self):
        if self._initialize is not None:
            return
        try:
            module = self._quiet(self._loader)
            reader = ReadOnlyMarketData(module)
            initialize, shutdown = module.initialize, module.shutdown
            if not all(
                callable(x)
                for x in (
                    initialize,
                    shutdown,
                    reader._terminal,
                    reader._account,
                    reader._symbol,
                    reader._tick,
                    reader._rates,
                )
            ):
                raise TypeError("Unsupported SDK capabilities")
            self._initialize, self._shutdown = initialize, shutdown
            self._last_error = getattr(module, "last_error", None)
            self._template = reader
            self._update(
                runtime=dict(
                    self.snapshot()["runtime"],
                    mt5_package=package_label(getattr(module, "__version__", None)),
                )
            )
        except ImportError:
            self._failure("PROVIDER_UNAVAILABLE")
        except Exception:
            self._failure("MT5_PACKAGE_CAPABILITY_MISMATCH")

    def preflight(self):
        self._claim()
        now = self._clock()
        if not self._attached:
            if self._retry is not None and now < self._retry:
                self._update(
                    state="RECONNECTING", status_reason_code="CONNECTION_RETRY_PENDING"
                )
                raise MarketDataError("Retry scheduled", "CONNECTION_RETRY_PENDING")
            self._load()
            self._update(
                state=(
                    "RECONNECTING"
                    if self.snapshot()["reconnection_attempt_count"]
                    else "INITIALIZING"
                ),
                reconnection_attempt_count=min(
                    2147483647, self.snapshot()["reconnection_attempt_count"] + 1
                ),
            )
            try:
                args = (self._path,) if self._path else ()
                ok = self._quiet(self._initialize, *args, timeout=10000)
            except Exception:
                self._failure("INITIALIZATION_EXCEPTION", self._error())
            if ok is not True:
                self._failure("INITIALIZATION_FAILED", self._error())
            self._reader = self._template
            self._attached = True
            self._retry = None
            self._update(
                connection_generation=self.snapshot()["connection_generation"] + 1,
                next_retry_utc=None,
                mt5_error_code=None,
            )
        try:
            self._quiet(self._reader.preflight)
            if self._path:
                info = self._call(self._reader._terminal)
                supplied = Path(self._path).resolve()
                actual = getattr(info, "path", None)
                expected = (
                    supplied.parent if supplied.suffix.lower() == ".exe" else supplied
                )
                verified = (
                    None
                    if type(actual) is not str
                    else str(Path(actual).resolve()).casefold()
                    == str(expected).casefold()
                )
                self._update(terminal_attachment_verified=verified)
                if verified is not True:
                    raise MarketDataError(
                        "Attachment not verified", "TERMINAL_ATTACHMENT_UNVERIFIED"
                    )
        except MarketDataError as exc:
            error = self._error()
            if (
                exc.code in ("PROVIDER_DISCONNECTED", "TERMINAL_INFO_UNAVAILABLE")
                or error in IPC_CODES
            ):
                self._failure(
                    "IPC_COMMUNICATION_FAILURE" if error in IPC_CODES else exc.code,
                    error,
                )
            self._sync()
            self._update(
                status_reason_code=exc.code,
                state=(
                    "SAFETY_BLOCKED"
                    if exc.code
                    in (
                        "TRADING_PERMISSIONS_NOT_DISABLED",
                        "DEMO_ACCOUNT_REQUIRED",
                        "TERMINAL_ATTACHMENT_UNVERIFIED",
                        "SAFETY_INFORMATION_UNAVAILABLE",
                    )
                    else "MARKET_DATA_UNAVAILABLE"
                ),
            )
            raise
        except Exception:
            self._failure("CONNECTION_OPERATION_EXCEPTION", self._error())
        self._sync()
        values = dict(connected=True, state="CONNECTED", status_reason_code=None)
        if self.snapshot()["last_successful_connection_utc"] is None or self.snapshot()[
            "state"
        ] in ("INITIALIZING", "RECONNECTING"):
            values["last_successful_connection_utc"] = now.isoformat()
        self._update(**values)

    def _sync(self):
        self.raw = self._reader.raw
        self.diagnostics = deepcopy(self._reader.diagnostics)
        self._point = self._reader._point
        self._update(
            **{
                k: v
                for k, v in self.diagnostics.items()
                if k
                in (
                    "connected",
                    "demo_verified",
                    "terminal_trading_disabled",
                    "python_api_trading_disabled",
                    "symbol_visible",
                )
            }
        )

    def _call(self, fn, *args):
        self._claim()
        if not self._attached:
            raise MarketDataError("Attachment unavailable", "PROVIDER_DISCONNECTED")
        try:
            value = self._quiet(fn, *args)
        except Exception:
            self._failure("CONNECTION_OPERATION_EXCEPTION", self._error())
        if value is None:
            error = self._error()
            self._update(mt5_error_code=error)
            if error in IPC_CODES:
                self._failure("IPC_COMMUNICATION_FAILURE", error)
        return value

    @property
    def TIMEFRAME_M1(self):
        return self._reader.TIMEFRAME_M1

    @property
    def TIMEFRAME_M5(self):
        return self._reader.TIMEFRAME_M5

    def terminal_info(self):
        value = self._call(self._reader._terminal)
        if value is None:
            self._failure("TERMINAL_INFO_UNAVAILABLE", self._error())
        if getattr(value, "connected", None) is not True:
            self._failure("PROVIDER_DISCONNECTED", self._error())
        from types import SimpleNamespace

        return SimpleNamespace(connected=True)

    def quote(self, now):
        self._claim()
        try:
            return self._quiet(self._reader.quote, now)
        except MarketDataError:
            error = self._error()
            self._update(mt5_error_code=error)
            if error in IPC_CODES:
                self._failure("IPC_COMMUNICATION_FAILURE", error)
            raise
        except Exception:
            self._failure("CONNECTION_OPERATION_EXCEPTION", self._error())

    def copy_rates_from_pos(self, *args):
        self._claim()
        try:
            value = self._quiet(self._reader.copy_rates_from_pos, *args)
            self._sync()
            if value is None:
                error = self._error()
                self._update(mt5_error_code=error)
                if error in IPC_CODES:
                    self._failure("IPC_COMMUNICATION_FAILURE", error)
            return value
        except MarketDataError:
            raise
        except Exception:
            self._failure("CONNECTION_OPERATION_EXCEPTION", self._error())

    def acquisition_complete(self, code=None, *, started_at=None, quote_at=None):
        self._claim()
        if code is None:
            # Safety and attachment can change while history is being fetched.
            captured = self.raw
            self.preflight()
            self.raw = self._reader.raw = captured
            finished = self._clock()
            if started_at is not None:
                if finished < started_at:
                    raise MarketDataError("Clock changed", "CLOCK_MOVED_BACKWARD")
                if (finished - started_at).total_seconds() > 10:
                    raise MarketDataError(
                        "Acquisition too slow", "ACQUISITION_LATENCY_EXCEEDED"
                    )
            if (
                quote_at is not None
                and (finished - datetime.fromisoformat(quote_at)).total_seconds() > 30
            ):
                raise MarketDataError("Stale quote", "TICK_STALE")
            self._failures = 0
            self._retry = None
            self._update(
                state="CONNECTED",
                last_successful_acquisition_utc=self._clock().isoformat(),
            )
        elif self._attached:
            self._update(
                status_reason_code=code,
                state=(
                    "SAFETY_BLOCKED"
                    if code
                    in (
                        "DEMO_ACCOUNT_REQUIRED",
                        "TRADING_PERMISSIONS_NOT_DISABLED",
                        "SAFETY_INFORMATION_UNAVAILABLE",
                        "TERMINAL_ATTACHMENT_UNVERIFIED",
                    )
                    else (
                        "MARKET_DATA_UNAVAILABLE"
                        if code
                        in (
                            "TICK_UNAVAILABLE",
                            "HISTORY_INCOMPLETE",
                            "SYMBOL_NOT_VISIBLE",
                        )
                        else "DATA_QUALITY_BLOCKED"
                    )
                ),
            )

    def retry_delay(self, interval):
        if self._retry is None:
            return interval
        return max(0.05, min(interval, (self._retry - self._clock()).total_seconds()))

    def close_owner(self):
        self._claim()
        self._detach()
        self._update(
            state="DISCONNECTED",
            connected=False,
            owner_state="STOPPED",
            next_retry_utc=None,
        )
        self._owner = None
        self._retry = None
