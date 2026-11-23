"""One read-only polling loop; recorder failure cannot masquerade as current evidence."""

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from threading import Thread, Event, Lock
from iat.live_shadow.research import normalized, assess
from iat.live_observer import LiveObserver, base
from iat.live_shadow import LABEL


def unavailable(code="SHADOW_DISABLED"):
    return dict(
        shadow_version=1,
        status="BLOCKED",
        label=LABEL,
        reason_codes=[code],
        signal="WAIT",
        execution_allowed=False,
        orders_requested=0,
        exness="BLOCKED",
        historical_validation="PENDING",
        historical_comparisons="NOT_RUN",
        stage_b_qualification="PENDING",
        stages_c_d="BLOCKED",
        qualified_performance_metrics=None,
    )


class MemoryObserverLog:
    """Legacy observer presentation is journaled by the outer durable recorder."""

    def append(self, report, raw):
        pass


class ShadowRuntime:
    def __init__(self, feed, journal, *, calendar=None, clock=None, interval=1):
        if type(interval) is not int or not 1 <= interval <= 10:
            raise ValueError("SHADOW_INTERVAL_1_TO_10_REQUIRED")
        self.feed = feed
        self.journal = journal
        self.calendar = calendar
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.interval = interval
        self.observer = LiveObserver(
            feed,
            MemoryObserverLog(),
            calendar=calendar,
            clock=self.clock,
            interval=max(2, interval),
        )
        self.stop = Event()
        self.thread = None
        self.lock = Lock()
        self.poll_lock = Lock()
        self.cached = unavailable("SHADOW_RECOVERING")

    def step(self):
        with self.poll_lock:
            try:
                observed = self.observer.step()
                raw = deepcopy(self.feed.raw)
                errors = []
                now = self.clock()
                quote = None
                try:
                    self.feed.preflight()
                    for tf, count in (("M1", 500), ("M5", 100)):
                        self.feed.copy_rates_from_pos(
                            "XAUUSD", getattr(self.feed, "TIMEFRAME_" + tf), 1, count
                        )
                    raw = deepcopy(self.feed.raw)
                    self.feed.quote_observed(self.clock)
                    quote = deepcopy(self.feed.last_quote)
                except Exception as exc:
                    errors.append(getattr(exc, "code", "QUOTE_UNAVAILABLE"))
                # Close after acquisition, even when the read failed. A successful
                # quote must never sit beyond its own recorded capture window.
                now = self.clock()
                state = self.journal.state()
                start = (
                    datetime.fromisoformat(state["last_capture_end"])
                    if state["last_capture_end"]
                    else now - timedelta(seconds=1)
                )
                capture = self.feed.capture(start, now)
                try:
                    candles = normalized(raw)
                except Exception:
                    candles = dict(M1=[], M5=[])
                    errors.append("CANDLE_NORMALIZATION_FAILED")
                # Precompute before stamping availability. Capture closes before this knowledge timestamp.
                try:
                    assess(
                        candles,
                        now.isoformat(),
                        state["research"],
                        self.journal.config,
                        self.calendar,
                    )
                except Exception:
                    pass
                received = self.clock()
                packet = dict(
                    received_at=received.isoformat(),
                    quote=quote,
                    capture=capture,
                    candles=candles,
                    raw_candles=raw,
                    identity=deepcopy(self.feed.identity),
                    symbol_specification=deepcopy(self.feed.specification or {}),
                    errors=sorted(set(errors)),
                    observer_snapshot_id=observed["snapshot_id"],
                    observer_reason_codes=observed["reason_codes"],
                )
                self.journal.record(packet)
                result = self.journal.snapshot()
                result["quote"] = quote
                result["feed_status"] = (
                    "CONNECTED" if quote and not errors else "DATA_UNAVAILABLE"
                )
                result["original_observer_status"] = observed["feed_status"]
                result["original_observer_reason_codes"] = observed["reason_codes"]
                result["data_quality_warnings"] = sorted(
                    set(errors + capture["reason_codes"])
                )
                result["source_provenance"] = (
                    "LOCAL_MT5_DEMO_READ_ONLY_CAPTURE_NOT_QUALIFIED"
                )
            except Exception:
                result = unavailable("SHADOW_JOURNAL_OR_OBSERVATION_FAILED")
            with self.lock:
                self.cached = result
            return deepcopy(result)

    def latest(self):
        return self.observer.latest()

    def shadow_latest(self):
        with self.lock:
            r = deepcopy(self.cached)
        if r.get("last_received"):
            try:
                now = self.clock()
                age = (now - datetime.fromisoformat(r["last_received"])).total_seconds()
                r["observation_age_seconds"] = age
                q = r.get("quote")
                r["quote_age_seconds"] = (
                    (now - datetime.fromisoformat(q["timestamp"])).total_seconds()
                    if q
                    else None
                )
                if (
                    age < 0
                    or age > max(3, self.interval * 2)
                    or r["quote_age_seconds"] is None
                    or not 0 <= r["quote_age_seconds"] <= 2
                ):
                    r["status"] = "STALE_OR_UNAVAILABLE"
                    r["research_candidate"] = "BLOCKED"
                    r["data_quality_warnings"] = sorted(
                        set(
                            r.get("data_quality_warnings", [])
                            + ["CURRENT_QUOTE_OR_RECORDER_STALE"]
                        )
                    )
                    r["performance"]["unrealized_pnl"] = None
            except Exception:
                return unavailable("CLOCK_UNAVAILABLE_OR_BACKWARD")
        return r

    def start(self):
        if self.thread is not None:
            raise ValueError("Already started")

        def run():
            while not self.stop.is_set():
                self.step()
                self.stop.wait(self.interval)

        self.thread = Thread(target=run, name="iat-read-only-shadow", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=15)


class ReadOnlyJournalView:
    """Optional existing-dashboard attachment; only the snapshot read capability is retained."""

    def __init__(self, journal, clock=None):
        self._snapshot = journal.snapshot
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def shadow_latest(self):
        try:
            r = self._snapshot()
            now = self.clock()
            q = r.get("quote")
            r["quote_age_seconds"] = (
                (now - datetime.fromisoformat(q["timestamp"])).total_seconds()
                if q
                else None
            )
            if not q or not 0 <= r["quote_age_seconds"] <= 2:
                r["status"] = "STALE_OR_UNAVAILABLE"
                r["research_candidate"] = "BLOCKED"
                r["performance"]["unrealized_pnl"] = None
            return r
        except Exception:
            return unavailable("SHADOW_JOURNAL_UNAVAILABLE")
