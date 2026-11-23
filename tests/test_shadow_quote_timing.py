"""Deterministic synthetic timing; no terminal, broker credentials or network."""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from iat.live_shadow.feed import ShadowFeed, observed_tick
from iat.live_shadow.runtime import ShadowRuntime, ReadOnlyJournalView
from iat.live_shadow.store import Journal
from iat.live_shadow.policy import configuration
from iat.live_shadow import engine
from iat.mt5_data import MarketDataError
from test_live_shadow import TickMT5, NOW, session, symbol


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class UpdatingMT5(TickMT5):
    def __init__(self, clock, *, delay_ms=140, lead_ms=0):
        super().__init__()
        self.clock = clock
        self.delay_ms = delay_ms
        self.lead_ms = lead_ms
        self.tape = []
        self.fixed = None

    def symbol_info_tick(self, name):
        self.clock.now += timedelta(milliseconds=self.delay_ms)
        at = self.clock.now + timedelta(milliseconds=self.lead_ms)
        row = self.fixed or dict(
            time=int(at.timestamp()),
            time_msc=round(at.timestamp() * 1000),
            bid=100.0,
            ask=100.1,
        )
        from types import SimpleNamespace

        if row not in self.tape:
            self.tape.append(deepcopy(row))
        return SimpleNamespace(**row)

    def copy_ticks_range(self, name, start, end, flags):
        return [
            deepcopy(row)
            for row in self.tape
            if start.timestamp() * 1000 <= row["time_msc"] <= end.timestamp() * 1000
        ]


def row(at):
    return dict(
        time=int(at.timestamp()),
        time_msc=round(at.timestamp() * 1000),
        bid=100.0,
        ask=100.1,
    )


class ShadowQuoteTimingTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="iat SYNTHETIC quote timing ")
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()

    def runtime(self, module=None):
        feed = ShadowFeed(module or UpdatingMT5(self.clock))
        journal = Journal(
            Path(self.temp.name) / "new-journal",
            configuration(),
            create=True,
            source_kind="SYNTHETIC_FIXTURE",
        )
        return ShadowRuntime(feed, journal, clock=self.clock), journal

    def test_140ms_tick_during_read_is_not_future_at_actual_observation(self):
        runtime, journal = self.runtime()
        result = runtime.step()
        self.assertIsNotNone(result.get("quote"), result.get("data_quality_warnings"))
        self.assertNotIn("QUOTE_FUTURE", result["data_quality_warnings"])
        self.assertNotIn("QUOTE_FUTURE", result["original_observer_reason_codes"])
        self.assertEqual(result["original_observer_status"], "CONNECTED")
        self.assertEqual(runtime.shadow_latest()["status"], "RECORDING")
        with journal.connection(readonly=True) as db:
            from iat.replay_dataset import strict_json, utc

            packet = strict_json(
                db.execute(
                    "SELECT body FROM events ORDER BY seq DESC LIMIT 1"
                ).fetchone()[0]
            )["packet"]
        self.assertLessEqual(
            utc(packet["quote"]["timestamp"]), utc(packet["capture"]["end"])
        )
        self.assertLessEqual(utc(packet["capture"]["end"]), utc(packet["received_at"]))
        self.assertEqual(journal.verify(replay=True)["status"], "MATCH")
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(result["orders_requested"], 0)

    def test_future_relative_to_pre_read_clock_reproduces_original_race(self):
        module = UpdatingMT5(self.clock)
        before = self.clock()
        tick = module.symbol_info_tick("XAUUSD")
        with self.assertRaisesRegex(ValueError, "^QUOTE_FUTURE$"):
            observed_tick(tick, before)
        self.assertEqual(
            observed_tick(tick, self.clock())["timestamp"], self.clock().isoformat()
        )

    def test_true_post_read_clock_lead_1ms_140ms_and_seconds_remains_rejected(self):
        for lead in (1, 140, 1000, 5600):
            with self.subTest(lead_ms=lead):
                feed = ShadowFeed(UpdatingMT5(self.clock, lead_ms=lead))
                with self.assertRaises(MarketDataError) as caught:
                    feed.quote_observed(self.clock)
                self.assertEqual(caught.exception.code, "QUOTE_FUTURE")

    def test_read_crossing_second_uses_full_consistent_milliseconds(self):
        self.clock.now = NOW.replace(microsecond=950000)
        module = UpdatingMT5(self.clock, delay_ms=140)
        q = ShadowFeed(module).quote_observed(self.clock)
        self.assertEqual(
            q["observed_at_utc"],
            (NOW + timedelta(seconds=1, milliseconds=90)).isoformat(),
        )
        self.assertEqual(q["age_seconds"], 0)
        bad = row(self.clock())
        bad["time"] -= 1
        with self.assertRaisesRegex(ValueError, "^QUOTE_TIMESTAMP_INVALID$"):
            observed_tick(bad, self.clock())

    def test_stale_24_to_56_seconds_stays_blocked_and_2_seconds_is_inclusive(self):
        for age in (0, 0.14, 1.999, 2, 2.001, 2.4, 5.6):
            with self.subTest(age=age):
                module = UpdatingMT5(self.clock, delay_ms=0)
                module.fixed = row(self.clock() - timedelta(seconds=age))
                feed = ShadowFeed(module)
                if age <= 2:
                    self.assertAlmostEqual(
                        feed.quote_observed(self.clock)["age_seconds"], age
                    )
                else:
                    with self.assertRaises(MarketDataError) as caught:
                        feed.quote_observed(self.clock)
                    self.assertEqual(caught.exception.code, "QUOTE_STALE")

    def test_clock_moving_backward_during_read_fails_closed(self):
        module = UpdatingMT5(self.clock, delay_ms=-140)
        module.fixed = row(NOW - timedelta(seconds=1))
        with self.assertRaises(MarketDataError) as caught:
            ShadowFeed(module).quote_observed(self.clock)
        self.assertEqual(caught.exception.code, "CLOCK_MOVED_BACKWARD")

    def test_repeated_tick_does_not_gain_new_identity_or_reset_age(self):
        module = UpdatingMT5(self.clock, delay_ms=0)
        module.fixed = row(NOW)
        feed = ShadowFeed(module)
        feed.quote_observed(self.clock)
        original = deepcopy(feed.last_quote)
        self.clock.now += timedelta(seconds=1)
        q = feed.quote_observed(self.clock)
        self.assertEqual(feed.last_quote, original)
        self.assertEqual(q["age_seconds"], 1)
        s, effects = engine.quote_event(
            engine.initial(), original, configuration(), session(), symbol()
        )
        repeated, duplicate_effects = engine.quote_event(
            s, feed.last_quote, configuration(), session(), symbol()
        )
        self.assertEqual(repeated, s)
        self.assertEqual(duplicate_effects, [])
        self.clock.now += timedelta(seconds=1.4)
        with self.assertRaises(MarketDataError) as caught:
            feed.quote_observed(self.clock)
        self.assertEqual(caught.exception.code, "QUOTE_STALE")
        module.fixed = row(
            self.clock()
        )  # same prices, genuinely new provider timestamp
        feed.quote_observed(self.clock)
        self.assertNotEqual(feed.last_quote["id"], original["id"])

    def test_fresh_recorder_receipt_cannot_hide_old_tick_or_refresh_frozen_views(self):
        runtime, journal = self.runtime()
        runtime.step()
        original = deepcopy(runtime.shadow_latest()["quote"])
        before = journal.path.read_bytes()
        self.clock.now += timedelta(seconds=2.4)
        result = runtime.shadow_latest()
        self.assertEqual(result["status"], "STALE_OR_UNAVAILABLE")
        self.assertIn(
            "CURRENT_QUOTE_OR_RECORDER_STALE", result["data_quality_warnings"]
        )
        self.assertEqual(result["quote"], original)
        self.assertIsNone(result["performance"]["unrealized_pnl"])
        self.assertEqual(
            ReadOnlyJournalView(journal, clock=self.clock).shadow_latest()["status"],
            "STALE_OR_UNAVAILABLE",
        )
        self.assertEqual(journal.path.read_bytes(), before)

    def test_intermittent_unchanged_ticks_recover_only_on_fresh_provider_update(self):
        module = UpdatingMT5(self.clock, delay_ms=0)
        module.fixed = row(NOW)
        runtime, journal = self.runtime(module)
        first = runtime.step()
        self.assertEqual(runtime.shadow_latest()["status"], "RECORDING")
        self.clock.now += timedelta(seconds=1)
        runtime.step()
        self.assertEqual(runtime.shadow_latest()["quote"]["id"], first["quote"]["id"])
        self.clock.now += timedelta(seconds=1.4)
        runtime.step()
        self.assertIsNone(runtime.shadow_latest()["quote"])
        self.assertIn("QUOTE_STALE", runtime.shadow_latest()["data_quality_warnings"])
        self.assertEqual(runtime.shadow_latest()["status"], "STALE_OR_UNAVAILABLE")
        self.clock.now += timedelta(seconds=0.1)
        module.fixed = row(self.clock())
        runtime.step()
        result = runtime.shadow_latest()
        self.assertEqual(result["status"], "RECORDING")
        self.assertNotEqual(result["quote"]["id"], first["quote"]["id"])
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(journal.verify(replay=True)["status"], "MATCH")
        self.assertEqual(module.orders, 0)

    def test_quote_that_becomes_stale_during_read_is_rejected_at_completion(self):
        module = UpdatingMT5(self.clock, delay_ms=140)
        module.fixed = row(NOW - timedelta(seconds=1.9))
        # It was fresh when the API call began; the age at completion is 2.04 s.
        self.assertIsNotNone(observed_tick(module.fixed, NOW))
        with self.assertRaises(MarketDataError) as caught:
            ShadowFeed(module).quote_observed(self.clock)
        self.assertEqual(caught.exception.code, "QUOTE_STALE")

    def test_true_clock_skew_stays_null_and_b3_retains_quality_and_execution_gates(
        self,
    ):
        from iat.three_engine.config import configuration as comparison_configuration
        from iat.three_engine.journal import SourceReader, ComparisonJournal
        from iat.three_engine.runtime import ComparisonRuntime

        module = UpdatingMT5(self.clock, lead_ms=140)
        runtime, source = self.runtime(module)
        result = runtime.step()
        self.assertIsNone(result["quote"])
        self.assertIn("QUOTE_FUTURE", result["data_quality_warnings"])
        j = ComparisonJournal(
            Path(self.temp.name) / "new-comparison",
            comparison_configuration(),
            source.binding_sha,
            create=True,
            source_kind="SYNTHETIC_FIXTURE",
        )
        comparison = ComparisonRuntime(SourceReader(source), j, clock=self.clock)
        blocked = comparison.step()
        self.assertEqual(blocked["source_cursor"], 1)
        self.assertFalse(blocked["common_evidence"]["quality"]["valid"])
        self.assertTrue(
            all(p["decision"] == "BLOCKED" for p in blocked["proposals"].values())
        )
        self.assertEqual(blocked["signal"], "WAIT")
        self.assertFalse(blocked["execution_allowed"])
        self.assertEqual(blocked["orders_requested"], 0)
        self.assertEqual(blocked["historical_validation"], "PENDING")
        self.assertEqual(blocked["historical_comparisons"], "NOT_RUN")
        self.assertEqual(j.verify(replay=True)["status"], "MATCH")

    def test_fixed_capture_flows_to_b3_without_enabling_any_provider_or_execution(self):
        from iat.three_engine.config import configuration as comparison_configuration
        from iat.three_engine.journal import SourceReader, ComparisonJournal
        from iat.three_engine.runtime import ComparisonRuntime

        runtime, source = self.runtime()
        runtime.step()
        j = ComparisonJournal(
            Path(self.temp.name) / "new-comparison",
            comparison_configuration(),
            source.binding_sha,
            create=True,
            source_kind="SYNTHETIC_FIXTURE",
        )
        result = ComparisonRuntime(SourceReader(source), j, clock=self.clock).step()
        self.assertEqual(result["source_cursor"], 1)
        self.assertTrue(result["common_evidence"]["quality"]["valid"])
        self.assertEqual(result["proposals"]["C_AI_LED"]["decision"], "BLOCKED")
        self.assertIn(
            "PROVIDER_DISABLED", result["proposals"]["C_AI_LED"]["reason_codes"]
        )
        self.assertEqual(result["budget"]["calls"], 0)
        self.assertEqual(result["signal"], "WAIT")
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(j.verify(replay=True)["status"], "MATCH")
