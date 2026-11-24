"""Independent synthetic E1 regressions; no actual XAUUSD validation or fills."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import ast, json, unittest
from pathlib import Path
from unittest.mock import patch

from entry_fixtures import START, CONFIG, INTELLIGENCE, fixture, snapshot
from iat.intelligence.entry_intelligence import (
    EntryResearchSession,
    assess_entry,
    validate_entry_report,
    blocked_entry,
    POLICY,
)
from iat.intelligence.sr_rejection import evaluate_sr_rejection, validate_sr_log
from iat.intelligence.strategy_replay import digest


def rehash(r):
    r["sha256"] = digest({k: v for k, v in r.items() if k != "sha256"})
    return r


class EntryIntelligenceTests(unittest.TestCase):
    def record(self, s, n=23, **options):
        v, c, k = snapshot(n, **options)
        r = s.record(v, c, view_inputs=k)
        self.assertTrue(validate_entry_report(json.loads(json.dumps(r)), source=s))
        self.safe(r)
        return r

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

        def scan(x):
            if isinstance(x, dict):
                self.assertFalse(
                    set(x)
                    & {
                        "entry_price",
                        "stop_loss",
                        "take_profit",
                        "position_size",
                        "confidence",
                        "probability",
                        "pnl",
                        "profit",
                        "win_rate",
                    }
                )
                for v in x.values():
                    scan(v)
            elif isinstance(x, list):
                for v in x:
                    scan(v)

        scan(r)

    def test_bullish_source_bound_qualification_and_exact_zone(self):
        v, c, k = snapshot()
        upstream = evaluate_sr_rejection(v, c, view_inputs=k)
        s = EntryResearchSession()
        r = s.record(v, c, view_inputs=k)
        self.safe(r)
        self.assertEqual(r["status"], "EVALUATED")
        for p in r["plans"]:
            original = next(
                x for x in upstream["evaluations"] if x["setup_id"] == p["setup_id"]
            )
            self.assertEqual(p["research_state"], "RESEARCH_QUALIFIED")
            self.assertEqual(p["research_direction"], "BULLISH")
            self.assertEqual(
                {k: v for k, v in p["entry_location"].items() if k != "reference_type"},
                original["zone"],
            )
            self.assertEqual(p["confirmation"]["predicates"], original["conditions"])
            self.assertEqual(
                p["confirmation"]["earliest_research_qualification_at_utc"],
                c.analysis_at,
            )
            self.assertIsNone(p["timing_research"]["fill"])
        self.assertEqual(len(r["plans"]), 2)

    def test_bearish_source_bound_qualification(self):
        r = self.record(EntryResearchSession(), mirror=True)
        self.assertEqual(len(r["plans"]), 2)
        self.assertTrue(
            all(
                p["research_direction"] == "BEARISH"
                and p["research_state"] == "RESEARCH_QUALIFIED"
                for p in r["plans"]
            )
        )

    def test_missing_confirmation_awaits_closed_c(self):
        r = self.record(EntryResearchSession(), 22)
        self.assertEqual(r["research_states"], ["AWAITING_CONFIRMATION"])
        self.assertTrue(
            all(
                p["confirmation"]["missing_evidence"]
                and p["confirmation"]["earliest_research_qualification_at_utc"] is None
                for p in r["plans"]
            )
        )

    def test_no_upstream_location_produces_no_setup(self):
        r = self.record(EntryResearchSession(), 24)
        self.assertEqual(r["research_states"], ["NO_SETUP"])
        self.assertEqual(r["plans"], [])

    def test_duplicate_snapshot_does_not_duplicate_identity_or_age(self):
        s = EntryResearchSession()
        a = self.record(s, 22)
        b = self.record(s, 23)
        c = self.record(s, 23)
        self.assertEqual(b, c)
        self.assertEqual(len(s.sr_log()["entries"]), 2)
        self.assertEqual(
            {p["setup_id"] for p in a["plans"]}, {p["setup_id"] for p in b["plans"]}
        )
        self.assertTrue(
            all(
                p["setup_age"]["eligible_closes_after_confirmation"] == 0
                for p in c["plans"]
            )
        )

    def test_expiry_uses_existing_five_eligible_close_lifecycle(self):
        for mirror in (False, True):
            s = EntryResearchSession()
            for n in range(22, 29):
                r = self.record(s, n, mirror=mirror)
            self.assertEqual(r["research_states"], ["EXPIRED"])
            self.assertTrue(
                all(
                    p["setup_age"]["eligible_closes_after_confirmation"] == 5
                    for p in r["plans"]
                )
            )
            validate_sr_log(s.sr_log())

    def test_frozen_zone_loss_invalidates_qualified_setup(self):
        a, b = fixture()
        s = EntryResearchSession()
        self.record(s, 22, one=a, five=b)
        before = self.record(s, 23, one=a, five=b)
        a[23].update(open=2098, high=2098.1, low=2096.5, close=2097)
        r = self.record(s, 24, one=a, five=b)
        qualified_ids = {p["setup_id"] for p in before["plans"]}
        invalid = [p for p in r["plans"] if p["setup_id"] in qualified_ids]
        self.assertTrue(all(p["research_state"] == "INVALIDATED" for p in invalid))
        self.assertEqual(
            [p["entry_location"] for p in invalid],
            [p["entry_location"] for p in before["plans"]],
        )

    def test_future_append_does_not_mutate_prior_assessments_or_hashes(self):
        s = EntryResearchSession()
        first = self.record(s, 23)
        frozen = json.dumps(first, sort_keys=True)
        self.record(s, 24)
        self.assertEqual(json.dumps(first, sort_keys=True), frozen)
        self.assertTrue(validate_entry_report(first, source=s))

    def test_full_prefix_repeatability(self):
        one, five = fixture()
        full = EntryResearchSession()
        reports = []
        for n in (22, 23, 24):
            reports.append(self.record(full, n, one=one, five=five))
        prefix = EntryResearchSession()
        cutoff = START + timedelta(minutes=23)
        one_short = [
            r
            for r in one
            if __import__("datetime").datetime.fromisoformat(r["timestamp"])
            + timedelta(minutes=1)
            <= cutoff
        ]
        five_short = [
            r
            for r in five
            if __import__("datetime").datetime.fromisoformat(r["timestamp"])
            + timedelta(minutes=5)
            <= cutoff
        ]
        small = [
            self.record(prefix, n, one=one_short, five=five_short) for n in (22, 23)
        ]
        self.assertEqual(reports[:2], small)
        repeat = EntryResearchSession()
        again = [self.record(repeat, n, one=one, five=five) for n in (22, 23, 24)]
        self.assertEqual(reports, again)

    def test_exact_cutoff_rejects_future_and_stale_source(self):
        v, c, k = snapshot()
        for offset, code in (
            (-1, "ENTRY_FUTURE_SOURCE"),
            (1, "ENTRY_SOURCE_NOT_CURRENT"),
        ):
            r = assess_entry(
                v, c, view_inputs=k, as_of=START + timedelta(minutes=23, seconds=offset)
            )
            self.safe(r)
            self.assertIn(code, r["reason_codes"])
            self.assertFalse(r["plans"])

    def test_live_provenance_blocked_before_sr_evaluation(self):
        v, c, k = snapshot(provenance="VALIDATED_LIVE")
        with patch(
            "iat.intelligence.sr_rejection.evaluate_sr_rejection",
            side_effect=AssertionError("Live evaluation forbidden"),
        ):
            r = assess_entry(v, c, view_inputs=k)
        self.safe(r)
        self.assertIn("ENTRY_SYNTHETIC_ONLY", r["reason_codes"])

    def test_historical_label_does_not_bypass_manifest_or_grant_entry(self):
        v, c, k = snapshot(provenance="HISTORICAL_RESEARCH")
        r = assess_entry(v, c, view_inputs=k)
        self.safe(r)
        self.assertEqual(r["status"], "BLOCKED")

    def test_missing_typed_input_and_serialized_context_blocked(self):
        v, c, k = snapshot()
        for value in (None, {}, c.to_dict()):
            r = assess_entry(v, value)
            self.safe(r)
            self.assertEqual(r["status"], "BLOCKED")

    def test_source_binding_mismatch_blocks_without_lifecycle_progress(self):
        s = EntryResearchSession()
        self.record(s, 22)
        before = s.sr_log()
        v, c, k = snapshot()
        v["bindings"]["context"] = "0" * 64
        rehash(v)
        r = s.record(v, c, view_inputs=k)
        self.safe(r)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(before, s.sr_log())

    def test_blocked_quality_withholds_old_plans_without_advancing_expiry(self):
        s = EntryResearchSession()
        self.record(s, 23)
        v, c, k = snapshot(24)
        c = replace(c, data_quality=dict(valid=False, diagnostics=[]))
        from iat.intelligence.market_view import build_market_view_v3

        v = build_market_view_v3(c)
        r = s.record(v, c, view_inputs=k)
        self.safe(r)
        self.assertEqual(r["research_states"], ["BLOCKED"])
        self.assertFalse(r["plans"])
        self.assertTrue(
            all(x["eligible_closes_after_C"] == 0 for x in s.sr_log()["setups"])
        )
        self.record(s, 25)
        self.assertTrue(
            all(x["eligible_closes_after_C"] == 1 for x in s.sr_log()["setups"])
        )

    def test_unfinished_m5_is_excluded_and_cannot_change_same_cutoff(self):
        a, b = fixture()
        v, c, k = snapshot(one=a, five=b)
        unclosed = next(
            r
            for r in b
            if r["timestamp"] == (START + timedelta(minutes=20)).isoformat()
        )
        unclosed.update(open=1, high=9999, low=0.5, close=9998)
        v2, c2, k2 = snapshot(one=a, five=b)
        self.assertEqual(
            assess_entry(v, c, view_inputs=k), assess_entry(v2, c2, view_inputs=k2)
        )

    def test_m1_gap_or_incomplete_history_is_blocked(self):
        a, b = fixture()
        del a[18]
        r = self.record(EntryResearchSession(), one=a, five=b)
        self.assertEqual(r["status"], "BLOCKED")

    def test_unverified_session_remains_blocked(self):
        from iat.session_config import load_session_config

        calendar = load_session_config(
            "config/profiles/exness-xauusd-v2.candidate.json"
        )
        r = self.record(
            EntryResearchSession(), calendar=calendar, observed_finality=True
        )
        self.assertEqual(r["status"], "BLOCKED")

    def test_opposing_choch_with_raw_ohlc_invalidates_without_qualification(self):
        # Independent staircase and wick break, not a hand-authored strategy outcome.
        a, b = fixture()
        prices = [
            2100,
            2102,
            2099,
            2097.6,
            2100,
            2103,
            2101,
            2099,
            2101,
            2104,
            2102,
            2100,
            2102,
            2105,
            2103,
            2101,
            2103,
            2106,
            2104,
            2102,
        ]
        for row, p in zip(a, prices):
            row.update(open=p, high=p + 0.15, low=p - 0.15, close=p)
        a[22]["low"] = 2097
        from iat.intelligence.context import context_at
        from iat.intelligence.market_view import build_market_view_v3

        policy = replace(INTELLIGENCE, break_policy="WICK")
        s = EntryResearchSession()
        for n in (22, 23):
            c = context_at(
                "SYNTHETIC_E1_XAUUSD",
                a,
                b,
                START + timedelta(minutes=n),
                config=CONFIG,
                intelligence_config=policy,
            )
            v = build_market_view_v3(c)
            r = s.record(v, c)
        self.safe(r)
        self.assertTrue(any(p["contradictory_evidence"] for p in r["plans"]))
        self.assertNotIn("RESEARCH_QUALIFIED", r["research_states"])
        invalid = [p for p in r["plans"] if p["research_state"] == "INVALIDATED"]
        self.assertTrue(invalid)
        self.assertTrue(
            all(
                p["confirmation"]["earliest_research_qualification_at_utc"] is None
                for p in invalid
            )
        )

    def test_conflicting_m5_is_not_inferred_to_be_a_reversal(self):
        a, b = fixture()
        # A falling M5 staircase is incompatible with bullish SR continuation.
        for i, row in enumerate(b):
            p = 2150 - i * 0.7 + (1 if i % 4 == 1 else -1 if i % 4 == 3 else 0)
            row.update(open=p, high=p + 0.15, low=p - 0.15, close=p)
        r = self.record(EntryResearchSession(), one=a, five=b)
        self.assertNotIn("RESEARCH_QUALIFIED", r["research_states"])
        self.assertIn("ABSTAINED", r["research_states"])
        self.assertTrue(
            any("M5_STRUCTURE_INCOMPATIBLE" in p["reason_codes"] for p in r["plans"])
        )

    def test_late_confirmation_cannot_backfill_original_candidate(self):
        a, b = fixture()
        a[22].update(open=2098.05, high=2098.06, low=2097.95, close=2098)
        s = EntryResearchSession()
        first = self.record(s, 22, one=a, five=b)
        self.record(s, 23, one=a, five=b)
        a[23].update(open=2098.2, high=2101, low=2098.1, close=2100.5)
        r = self.record(s, 24, one=a, five=b)
        original = {p["setup_id"] for p in first["plans"]}
        self.assertTrue(
            all(
                p["research_state"] != "RESEARCH_QUALIFIED"
                for p in r["plans"]
                if p["setup_id"] in original
            )
        )

    def test_rechecksummed_forgery_requires_producing_session(self):
        s = EntryResearchSession()
        r = self.record(s)
        with self.assertRaises(ValueError):
            validate_entry_report(r)
        for change in (
            {"signal": "BUY"},
            {"execution_allowed": True},
            {"confidence": 0.9},
            {"provenance": "HISTORICAL_RESEARCH"},
        ):
            bad = rehash(dict(deepcopy(r), **change))
            with self.assertRaises(ValueError):
                validate_entry_report(bad, source=s)
        bad = deepcopy(r)
        bad["plans"][0]["entry_location"]["lower"] += 0.1
        rehash(bad)
        with self.assertRaises(ValueError):
            validate_entry_report(bad, source=s)

    def test_blocked_reports_are_strict_and_empty(self):
        r = blocked_entry()
        self.safe(r)
        self.assertTrue(validate_entry_report(r))
        for key, value in (
            ("plans", [{}]),
            ("market_suitability", {}),
            ("validation_status", "VALIDATED"),
        ):
            bad = rehash(dict(deepcopy(r), **{key: value}))
            with self.assertRaises(ValueError):
                validate_entry_report(bad)

    def test_snapshot_limit_is_explicit_and_repeated_last_snapshot_is_allowed(self):
        with patch.dict(POLICY, max_snapshots=1):
            s = EntryResearchSession()
            a = self.record(s, 23)
            self.assertEqual(a, self.record(s, 23))
            r = self.record(s, 24)
            self.assertIn("ENTRY_RESOURCE_LIMIT", r["reason_codes"])
            self.assertEqual(len(s.sr_log()["entries"]), 1)

    def test_original_strategy_and_default_selection_are_unchanged(self):
        from iat.intelligence.strategy_registry import registry
        from iat.intelligence.adaptive import assess_adaptive

        v, c, k = snapshot()
        before = (
            registry(),
            assess_adaptive(c),
            evaluate_sr_rejection(v, c, view_inputs=k),
            c.to_dict(),
            deepcopy(v),
        )
        assess_entry(v, c, view_inputs=k)
        self.assertEqual(
            before,
            (
                registry(),
                assess_adaptive(c),
                evaluate_sr_rejection(v, c, view_inputs=k),
                c.to_dict(),
                v,
            ),
        )

    def test_parent_sr_log_contract_is_identical(self):
        from iat.intelligence.sr_rejection import SRRejectionLedger

        parent = SRRejectionLedger()
        entry = EntryResearchSession()
        for n in (22, 23, 24):
            v, c, inputs = snapshot(n)
            parent.record(v, c, view_inputs=inputs)
            entry.record(v, c, view_inputs=inputs)
        self.assertEqual(parent.to_dict(), entry.sr_log())
        self.assertTrue(validate_sr_log(entry.sr_log()))

    def test_unfinished_m1_and_future_extremes_are_not_consumed(self):
        a, b = fixture()
        before = self.record(EntryResearchSession(), one=a, five=b)
        a[23].update(open=1, high=99999, low=0.1, close=99998)
        after = self.record(EntryResearchSession(), one=a, five=b)
        self.assertEqual(before, after)

    def test_report_and_log_exports_do_not_mutate_internal_state(self):
        s = EntryResearchSession()
        r = self.record(s)
        log = s.sr_log()
        log["setups"].clear()
        r["plans"].clear()
        self.assertEqual(len(s.sr_log()["setups"]), 2)
        self.assertEqual(len(s.report()["plans"]), 2)

    def test_wrong_producing_session_and_bad_checksum_are_rejected(self):
        s = EntryResearchSession()
        r = self.record(s)
        with self.assertRaises(ValueError):
            validate_entry_report(r, source=EntryResearchSession())
        r["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_entry_report(r, source=s)

    def test_frozen_synthetic_examples_match_generated_reports(self):
        from entry_examples import examples

        actual = examples()
        frozen = json.loads(
            Path("docs/research_audits/entry-intelligence.synthetic.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(actual, frozen)
        self.assertEqual(actual["cases"]["bullish"]["setup_count"], 2)
        self.assertEqual(actual["cases"]["bearish"]["setup_count"], 2)

    def test_stale_m1_source_is_blocked_by_existing_quality_gates(self):
        a, b = fixture()
        r = self.record(EntryResearchSession(), 28, one=a[:23], five=b)
        self.assertEqual(r["research_states"], ["BLOCKED"])
        self.assertFalse(r["plans"])

    def test_no_execution_or_acquisition_imports(self):
        tree = ast.parse(Path("iat/intelligence/entry_intelligence.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(
                    node.attr, ("order_send", "order_check", "initialize", "login")
                )
            if isinstance(node, ast.Import):
                self.assertFalse(
                    any(
                        x.name in ("MetaTrader5", "requests", "socket")
                        for x in node.names
                    )
                )

    def test_live_dashboard_remains_presentation_only(self):
        from test_live_market_view import SyntheticTerminal, NOW
        from iat.live_data import ReadOnlyMarketData
        from iat.live_observer import LiveObserver, ShadowLog
        from iat.live_dashboard import create_dashboard
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            o = LiveObserver(
                ReadOnlyMarketData(SyntheticTerminal(lambda: NOW)),
                ShadowLog(Path(folder) / "private"),
                clock=lambda: NOW,
            )
            with patch.object(
                EntryResearchSession,
                "record",
                side_effect=AssertionError("Live entry forbidden"),
            ):
                before = o.step()
                client = create_dashboard(o).test_client()
                self.assertEqual(client.get("/live/v1/snapshot").get_json(), before)
                self.assertEqual(
                    client.get("/live/intelligence/v3/snapshot").status_code, 200
                )
                with client.get("/") as response:
                    html = response.get_data(as_text=True)
            self.assertIn("entry-research-panel", html)
            self.assertIn("SYNTHETIC_ONLY", html)
            self.assertIn("NOT_IMPLEMENTED", html)
            self.assertIn("live.js", html)
            self.assertIn("market-view.js", html)


if __name__ == "__main__":
    unittest.main()
