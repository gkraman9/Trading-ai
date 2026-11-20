"""Read-only journal follower; provider failures never block market capture or authorize orders."""

from concurrent.futures import Future
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from threading import Thread, Event, Lock
import time
from iat.replay_dataset import utc
from iat.intelligence.strategy_replay import digest
from iat.three_engine.config import PROTOCOL
from iat.three_engine.evidence import build
from iat.three_engine.contracts import validate_response, proposal
from iat.three_engine.reducer import request_packet


def utcnow():
    return datetime.now(timezone.utc)


class ComparisonRuntime:
    def __init__(self, source, journal, *, providers=None, clock=None, monotonic=None):
        self.source = source
        self.journal = journal
        self.providers = providers or {}
        self.clock = clock or utcnow
        self.monotonic = monotonic or time.monotonic
        self.jobs = {}
        self.stop = Event()
        self.thread = None
        self.lock = Lock()
        self.error = None
        self.journal.record(
            dict(kind="RECOVERY", data=dict(at=self.clock().isoformat()))
        )

    def _launch(self, key, engine, packet):
        future = Future()
        provider = self.providers[engine]
        clock = self.clock

        def run():
            try:
                raw = provider.request(deepcopy(packet))
                result = dict(raw=raw, response_at=clock().isoformat(), code=None)
            except Exception:
                result = dict(
                    raw=None, response_at=clock().isoformat(), code="PROVIDER_ERROR"
                )
            future.set_result(result)

        thread = Thread(target=run, name="iat-three-engine-" + engine, daemon=True)
        self.jobs[key] = dict(
            future=future, engine=engine, started=self.monotonic(), recorded=False
        )
        thread.start()

    def drain(self):
        for key, job in list(self.jobs.items()):
            future = job["future"]
            if job["recorded"]:
                if future.done():
                    del self.jobs[key]
                continue
            if future.done():
                result = future.result()
                state = self.journal.state()
                req = state["requests"][key]
                bundle = state["bundles"][req["bundle_id"]]
                raw = result["raw"]
                code = result["code"]
                if raw is not None:
                    try:
                        raw = validate_response(raw, bundle)
                    except Exception:
                        raw = None
                        code = "MODEL_SCHEMA_INVALID"
                # Finish common pricing/risk validation before sampling availability.
                # The journal repeats this pure validation for integrity, without new evidence.
                proposal(
                    req["engine"],
                    bundle,
                    raw,
                    self.clock().isoformat(),
                    self.journal.config,
                    model=req["model"],
                    request_at=req["at"],
                    response_at=result["response_at"],
                    blocked_reason=code,
                )
                available = self.clock().isoformat()
                # Record only validated bounded fields, never SDK errors, free text or private thoughts.
                self.journal.record(
                    dict(
                        kind="RESULT",
                        data=dict(
                            request_id=key,
                            raw=raw,
                            response_at=result["response_at"],
                            available_at=available,
                            code=code,
                        ),
                    )
                )
                job["recorded"] = True
                del self.jobs[key]
            elif (
                self.monotonic() - job["started"]
                >= PROTOCOL["provider_timeout_seconds"]
            ):
                at = self.clock().isoformat()
                self.journal.record(
                    dict(
                        kind="RESULT",
                        data=dict(
                            request_id=key,
                            raw=None,
                            response_at=at,
                            available_at=at,
                            code="PROVIDER_TIMEOUT",
                        ),
                    )
                )
                job["recorded"] = True

    def compare(self, packet):
        state = self.journal.state()
        candles = packet["candles"]["M1"]
        if not candles:
            return
        analysis = (utc(candles[-1]["timestamp"]) + timedelta(minutes=1)).isoformat()
        latest = state["bundles"].get(state["latest_bundle"])
        if latest and utc(analysis) <= utc(latest["analysis_at"]):
            return
        # Computation precedes availability. A common cutoff freezes the market inputs for all engines.
        cutoff = self.clock().isoformat()
        bundle = build(
            packet,
            self.journal.config,
            cutoff,
            calendar=self.journal.calendar,
            source_kind=self.source.source_kind,
        )
        if state["source_latched"]:
            bundle["quality"]["valid"] = False
            bundle["quality"]["reason_codes"].append("SOURCE_CORRECTION_LATCHED")
            bundle.pop("id")
            bundle["id"] = digest(bundle)
        from iat.three_engine.rules import baseline

        _, raw, _ = baseline(
            bundle, state["rules"], self.journal.config, self.journal.calendar
        )
        proposal(
            "A_RULES",
            bundle,
            raw,
            self.clock().isoformat(),
            self.journal.config,
            request_at=bundle["cutoff"],
        )
        self.journal.record(
            dict(
                kind="POINT",
                data=dict(bundle=bundle, available_at=self.clock().isoformat()),
            )
        )
        for engine in ("B_HYBRID", "C_AI_LED"):
            provider = self.providers.get(engine)
            model = (
                getattr(provider, "model_ref", provider.model)
                if provider
                else self.journal.binding["models"][engine]
            )
            key = digest([engine, bundle["id"], model, PROTOCOL["prompt_version"]])
            busy = any(
                j["engine"] == engine and not j["future"].done()
                for j in self.jobs.values()
            )
            self.journal.record(
                dict(
                    kind="REQUEST",
                    data=dict(
                        request_id=key,
                        engine=engine,
                        bundle_id=bundle["id"],
                        model=model,
                        at=self.clock().isoformat(),
                        enabled=provider is not None,
                        actual_ai=bool(getattr(provider, "actual_ai", False)),
                        blocked_reason="PROVIDER_BUSY" if busy else None,
                    ),
                )
            )
            state = self.journal.state()
            if state["requests"][key]["status"] == "PENDING":
                self._launch(key, engine, request_packet(state, bundle, engine))

    def step(self):
        try:
            self.drain()
            cursor = self.journal.state()["source_cursor"]
            for record in self.source.records(cursor, limit=20):
                record["consumed_at"] = self.clock().isoformat()
                self.journal.record(dict(kind="SOURCE", data=record))
                self.compare(record["packet"])
                self.drain()
            self.error = None
        except Exception:
            self.error = "COMPARISON_SOURCE_OR_JOURNAL_UNAVAILABLE"
        return self.latest()

    def latest(self):
        try:
            r = self.journal.snapshot()
        except Exception:
            return dict(
                status="BLOCKED",
                reason_codes=["COMPARISON_JOURNAL_UNAVAILABLE"],
                signal="WAIT",
                execution_allowed=False,
                orders_requested=0,
            )
        if self.error:
            r["status"] = "BLOCKED"
            r["reason_codes"] = [self.error]
        at = self.clock()
        watermark = r["market_watermark"]
        r["data_age_seconds"] = (
            (at - utc(watermark)).total_seconds() if watermark else None
        )
        q = r.get("current_market_quote")
        r["quote_age_seconds"] = (
            (at - utc(q["timestamp"])).total_seconds() if q else None
        )
        if (
            r["data_age_seconds"] is None
            or not 0 <= r["data_age_seconds"] <= 2
            or r["quote_age_seconds"] is None
            or not 0 <= r["quote_age_seconds"] <= 2
        ):
            r["current_data_status"] = "STALE_OR_UNAVAILABLE"
            for e in r["engines"].values():
                e["metrics"]["unrealized_pnl"] = None
                if e["position"] is not None:
                    e["metrics"]["paper_equity"] = None
        else:
            r["current_data_status"] = "OBSERVED_FRESH"
        r["provider_activity"] = {
            name: dict(
                configured=name in self.providers,
                provider=getattr(self.providers.get(name), "provider_name", "DISABLED"),
                actual_ai=bool(getattr(self.providers.get(name), "actual_ai", False)),
            )
            for name in ("B_HYBRID", "C_AI_LED")
        }
        return r

    def start(self):
        if self.thread is not None:
            raise ValueError("Comparison already started")

        def run():
            while not self.stop.is_set():
                self.step()
                self.stop.wait(0.25)

        self.thread = Thread(
            target=run, name="iat-three-engine-comparison", daemon=True
        )
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=12)
        for name, p in self.providers.items():
            if not any(
                j["engine"] == name and not j["future"].done()
                for j in self.jobs.values()
            ):
                try:
                    p.close()
                except Exception:
                    pass
