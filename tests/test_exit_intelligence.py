"""Independent raw synthetic E2 and source-binding adversarial regressions."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import json, unittest
from unittest.mock import patch
from exit_fixtures import fixture, snapshot, START, INTELLIGENCE
from iat.intelligence.entry_intelligence import (
    EntryResearchSession,
    validate_entry_report,
)
from iat.intelligence.exit_intelligence import (
    ExitResearchSession,
    ExitPolicy,
    validate_exit_report,
    LIMITS,
)
from iat.intelligence.strategy_replay import digest


class ExitIntelligenceTests(unittest.TestCase):
    def make(
        self, mirror=False, one=None, five=None, policy=None, intelligence=INTELLIGENCE
    ):
        if one is None:
            one, five = fixture(mirror)
        source = EntryResearchSession()
        v, c, i = snapshot(one=one, five=five, intelligence=intelligence)
        original = source.record(v, c, view_inputs=i)
        self.assertIn("RESEARCH_QUALIFIED", original["research_states"])
        sid = next(
            p["setup_id"]
            for p in original["plans"]
            if p["research_state"] == "RESEARCH_QUALIFIED"
        )
        session = ExitResearchSession(original, sid, entry_source=source, policy=policy)
        self.assertEqual(session.report()["source_eligibility"], "VALID")
        return session, source, original, one, five

    def record(self, e, n, a, b, **kw):
        options = {k: kw.pop(k) for k in list(kw) if k in ("as_of",)}
        v, c, i = snapshot(n, one=a, five=b, **kw)
        r = e.record(v, c, view_inputs=i, **options)
        self.assertTrue(validate_exit_report(json.loads(json.dumps(r)), source=e))
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
        for k in (
            "entry_fill",
            "exit_fill",
            "realized_pnl",
            "hypothetical_pnl",
            "holding_duration",
            "performance_metrics",
        ):
            self.assertIsNone(r[k])
        self.assertEqual(r["timer_exit"], "NOT_IMPLEMENTED")
        self.assertEqual(
            r["sha256"], digest({k: v for k, v in r.items() if k != "sha256"})
        )

    def events(self, r, kind):
        return [e for e in r["observations"] if e["kind"] == kind]

    def test_bullish_structural_invalidation_uses_original_close_rule(self):
        e, s, o, a, b = self.make()
        frozen = e.report()["frozen_invalidation"]
        a[23].update(open=5750, high=5750.2, low=5745.8, close=5746)
        r = self.record(e, 24, a, b)
        self.assertTrue(self.events(r, "STRUCTURAL_INVALIDATION_OBSERVED"))
        self.assertEqual(r["frozen_invalidation"], frozen)
        self.assertEqual(r["original_hypothesis_lifecycle"]["state"], "INVALIDATED")
        self.assertEqual(
            self.events(r, "STRUCTURAL_INVALIDATION_OBSERVED")[0]["occurred_at_utc"],
            (START + timedelta(minutes=24)).isoformat(),
        )

    def test_bearish_structural_invalidation(self):
        e, s, o, a, b = self.make(mirror=True)
        a[23].update(open=5750, low=5749.8, high=5754.2, close=5754)
        self.assertTrue(
            self.events(self.record(e, 24, a, b), "STRUCTURAL_INVALIDATION_OBSERVED")
        )

    def test_bullish_wick_target_is_not_close_confirmation_or_fill(self):
        e, s, o, a, b = self.make()
        a[23]["high"] = 5753.3
        r = self.record(e, 24, a, b)
        hit = self.events(r, "STRUCTURAL_TARGET_OBSERVED")[0]
        self.assertTrue(hit["details"]["wick_contact"])
        self.assertFalse(hit["details"]["closed_beyond_reference"])
        self.assertIsNone(hit["occurred_at_utc"])
        self.assertTrue(hit["occurred_interval_utc"])
        self.assertIsNone(r["exit_fill"])

    def test_bearish_wick_target(self):
        e, s, o, a, b = self.make(mirror=True)
        a[23]["low"] = 5746.7
        self.assertTrue(
            self.events(self.record(e, 24, a, b), "STRUCTURAL_TARGET_OBSERVED")
        )

    def test_close_policy_does_not_promote_wick_contact(self):
        e, s, o, a, b = self.make(
            policy=ExitPolicy(target_observation="CLOSE_BEYOND_REFERENCE")
        )
        a[23]["high"] = 5753.3
        self.assertFalse(
            self.events(self.record(e, 24, a, b), "STRUCTURAL_TARGET_OBSERVED")
        )
        a[24].update(open=5750, low=5749.8, high=5753.8, close=5753.6)
        hit = self.events(self.record(e, 25, a, b), "STRUCTURAL_TARGET_OBSERVED")[0]
        self.assertEqual(hit["occurred_at_utc"], hit["available_at_utc"])

    def test_targets_preserve_all_candidates_and_canonical_tie_break(self):
        e, *_ = self.make()
        r = e.report()
        self.assertGreaterEqual(len(r["target_candidates"]), 2)
        self.assertEqual(r["frozen_target"], r["target_candidates"][0])
        self.assertEqual(
            [z["id"] for z in r["target_candidates"]],
            sorted(z["id"] for z in r["target_candidates"]),
        )

    def test_no_eligible_original_target(self):
        a, b = fixture()
        a[22].update(close=5754, high=5754.1)
        e, s, o, a, b = self.make(one=a, five=b)
        self.assertEqual(e.report()["target_status"], "TARGET_UNAVAILABLE")
        self.assertIsNone(e.report()["frozen_target"])
        self.assertIn("NO_EXIT_REFERENCE", e.report()["analytical_states"])

    def test_late_source_producer_cannot_import_future_state_or_targets(self):
        e, s, o, a, b = self.make()
        original = e.report()
        for n in (24, 25, 26):
            v, c, i = snapshot(n, one=a, five=b)
            s.record(v, c, view_inputs=i)
        late = ExitResearchSession(o, o["plans"][0]["setup_id"], entry_source=s)
        self.assertEqual(late.report(), original)
        self.assertEqual(self.record(late, 24, a, b), self.record(e, 24, a, b))

    def test_later_entry_report_cannot_select_targets_retrospectively(self):
        e, s, o, a, b = self.make()
        v, c, i = snapshot(24, one=a, five=b)
        late = s.record(v, c, view_inputs=i)
        blocked = ExitResearchSession(
            late, o["plans"][0]["setup_id"], entry_source=s
        ).report()
        self.assertEqual(blocked["source_eligibility"], "BLOCKED")
        self.assertIn(
            "E2_ORIGINAL_QUALIFICATION_CUTOFF_REQUIRED", blocked["reason_codes"]
        )

    def test_forged_original_targets_rejected(self):
        e, s, o, a, b = self.make()
        bad = deepcopy(o)
        bad["plans"][0]["structural_invalidation"]["lower"] = 1
        bad["sha256"] = digest({k: v for k, v in bad.items() if k != "sha256"})
        self.assertEqual(
            ExitResearchSession(
                bad, o["plans"][0]["setup_id"], entry_source=s
            ).report()["source_eligibility"],
            "BLOCKED",
        )

    def test_no_source_or_wrong_source_is_not_authentication(self):
        e, s, o, a, b = self.make()
        for source in (None, {}, EntryResearchSession()):
            r = ExitResearchSession(
                o, o["plans"][0]["setup_id"], entry_source=source
            ).report()
            self.assertEqual(r["source_eligibility"], "BLOCKED")
            self.assertTrue(validate_exit_report(r))

    def test_awaiting_or_invalidated_original_is_not_a_qualified_setup(self):
        a, b = fixture()
        s = EntryResearchSession()
        v, c, i = snapshot(22, one=a, five=b)
        o = s.record(v, c)
        self.assertEqual(
            ExitResearchSession(o, o["plans"][0]["setup_id"], entry_source=s).report()[
                "source_eligibility"
            ],
            "BLOCKED",
        )

    def test_constructor_never_observes_qualification_candle_as_subsequent_exit(self):
        e, s, o, a, b = self.make()
        r = e.report()
        self.assertFalse(r["observations"])
        self.assertEqual(self.record(e, 23, a, b), r)

    def test_setup_expiry_preserves_five_distinct_closes(self):
        e, s, o, a, b = self.make()
        for n in range(24, 29):
            r = self.record(e, n, a, b)
            self.record(e, n, a, b)
        self.assertEqual(len(self.events(r, "HYPOTHESIS_EXPIRED")), 1)
        self.assertEqual(
            r["original_hypothesis_lifecycle"]["eligible_closes_after_confirmation"], 5
        )

    def test_same_bar_target_invalidation_has_no_invented_order(self):
        e, s, o, a, b = self.make()
        a[23].update(high=5753.6, low=5745.8, close=5746)
        r = self.record(e, 24, a, b)
        self.assertTrue(self.events(r, "STRUCTURAL_TARGET_OBSERVED"))
        self.assertTrue(self.events(r, "STRUCTURAL_INVALIDATION_OBSERVED"))
        self.assertEqual(r["ambiguity"]["status"], "UNRESOLVED_EVENT_ORDER")
        self.assertEqual(
            r["ambiguity"]["groups"][0]["timing_basis"], "UNKNOWN_INTRABAR_ORDER"
        )

    def test_simultaneous_close_target_and_expiry_are_distinguished(self):
        e, s, o, a, b = self.make(
            policy=ExitPolicy(target_observation="CLOSE_BEYOND_REFERENCE")
        )
        for n in range(24, 28):
            self.record(e, n, a, b)
        a[27].update(high=5753.8, close=5753.6)
        r = self.record(e, 28, a, b)
        self.assertEqual(
            r["ambiguity"]["groups"][0]["timing_basis"],
            "SIMULTANEOUS_CLOSE_AVAILABILITY",
        )

    def test_repetition_deduplicates_exit_evidence(self):
        e, s, o, a, b = self.make()
        a[23]["high"] = 5753.3
        r = self.record(e, 24, a, b)
        self.assertEqual(r, self.record(e, 24, a, b))
        self.assertEqual(len(self.events(r, "STRUCTURAL_TARGET_OBSERVED")), 1)

    def test_returned_reports_remain_frozen_and_verifiable(self):
        e, s, o, a, b = self.make()
        r = self.record(e, 24, a, b)
        copy = deepcopy(r)
        self.record(e, 25, a, b)
        self.assertEqual(r, copy)
        self.assertTrue(validate_exit_report(r, source=e))
        r["target_candidates"].clear()
        self.assertTrue(e.report()["target_candidates"])

    def test_multiple_original_anchors_are_scoped_independently(self):
        e, s, o, a, b = self.make()
        other = ExitResearchSession(o, o["plans"][1]["setup_id"], entry_source=s)
        self.assertNotEqual(
            e.report()["original"]["setup_id"], other.report()["original"]["setup_id"]
        )
        self.assertFalse(e.report()["observations"])
        self.assertFalse(other.report()["observations"])

    def test_stale_cutoff_and_backward_observation_fail_closed(self):
        e, s, o, a, b = self.make()
        self.record(e, 24, a, b)
        before = e._entry.sr_log()
        r = self.record(e, 25, a, b, as_of=START + timedelta(minutes=26))
        self.assertEqual(r["source_eligibility"], "BLOCKED")
        self.assertEqual(e._entry.sr_log(), before)
        self.assertEqual(self.record(e, 23, a, b)["source_eligibility"], "BLOCKED")

    def test_corrected_prefix_is_blocked_without_partial_state(self):
        e, s, o, a, b = self.make()
        self.record(e, 24, a, b)
        before = e._entry.sr_log()
        a[0]["close"] += 0.01
        r = self.record(e, 25, a, b)
        self.assertEqual(r["source_eligibility"], "BLOCKED")
        self.assertEqual(before, e._entry.sr_log())

    def test_forged_current_view_and_recovery(self):
        e, s, o, a, b = self.make()
        v, c, i = snapshot(24, one=a, five=b)
        v["sha256"] = "0" * 64
        self.assertEqual(e.record(v, c)["source_eligibility"], "BLOCKED")
        self.assertEqual(self.record(e, 24, a, b)["source_eligibility"], "VALID")

    def test_blocked_observation_does_not_advance_expiry_or_backfill_exits(self):
        e, s, o, a, b = self.make()
        bad = a[:10] + a[11:]
        r = self.record(e, 24, bad, b)
        self.assertEqual(r["source_eligibility"], "BLOCKED")
        self.assertFalse(r["observations"])
        r = self.record(e, 25, a, b)
        self.assertEqual(
            r["original_hypothesis_lifecycle"]["eligible_closes_after_confirmation"], 1
        )
        self.assertIn(
            "INTERVENING_EXIT_OBSERVATIONS_NOT_EVALUATED", r["missing_evidence"]
        )

    def test_unfinished_bar_future_append_has_no_effect(self):
        e, s, o, a, b = self.make()
        r = self.record(e, 24, a, b)
        a[24].update(open=1, low=0.1, high=99999, close=99998)
        self.assertEqual(r, self.record(e, 24, a, b))

    def test_full_run_prefix_equivalence(self):
        e, s, o, a, b = self.make()
        reports = [self.record(e, n, a, b) for n in (24, 25)]
        a2 = [
            r
            for r in a
            if datetime.fromisoformat(r["timestamp"]) < START + timedelta(minutes=25)
        ]
        b2 = [
            r
            for r in b
            if datetime.fromisoformat(r["timestamp"]) + timedelta(minutes=5)
            <= START + timedelta(minutes=25)
        ]
        other, _, _, _, _ = self.make(one=a2, five=b2)
        self.assertEqual(reports, [self.record(other, n, a2, b2) for n in (24, 25)])

    def test_live_and_historical_never_reach_synthetic_evaluator(self):
        e, s, o, a, b = self.make()
        for provenance in ("VALIDATED_LIVE", "HISTORICAL_RESEARCH"):
            v, c, i = snapshot(24, one=a, five=b, provenance=provenance)
            with patch.object(
                EntryResearchSession, "record", side_effect=AssertionError("forbidden")
            ):
                r = e.record(v, c, view_inputs=i)
            self.assertEqual(r["source_eligibility"], "BLOCKED")

    def test_unqualified_calendar_remains_blocked(self):
        from iat.session_config import load_session_config

        e, s, o, a, b = self.make()
        r = self.record(
            e,
            24,
            a,
            b,
            calendar=load_session_config(
                "config/profiles/exness-xauusd-v2.candidate.json"
            ),
            observed_finality=True,
        )
        self.assertEqual(r["source_eligibility"], "BLOCKED")

    def test_event_resource_failure_is_transactional(self):
        e, s, o, a, b = self.make()
        before = e._entry.sr_log()
        a[23]["high"] = 5753.3
        with patch.dict(LIMITS, max_events=0):
            r = self.record(e, 24, a, b)
        self.assertEqual(r["source_eligibility"], "BLOCKED")
        self.assertEqual(e._entry.sr_log(), before)
        self.assertFalse(e._events)
        self.assertTrue(
            self.events(self.record(e, 24, a, b), "STRUCTURAL_TARGET_OBSERVED")
        )

    def test_report_limit_preserves_state_and_duplicate_is_allowed(self):
        e, s, o, a, b = self.make()
        original = e.report()
        with patch.dict(LIMITS, max_reports=1):
            self.assertEqual(original, self.record(e, 23, a, b))
            self.assertEqual(self.record(e, 24, a, b)["source_eligibility"], "BLOCKED")
        self.assertEqual(len(e._produced), 1)

    def test_unexpected_projection_failure_rolls_back(self):
        e, s, o, a, b = self.make()
        before = e._entry.sr_log()
        with patch.object(e, "_report", side_effect=ValueError("private secret")):
            r = self.record(e, 24, a, b)
        self.assertEqual(r["source_eligibility"], "BLOCKED")
        self.assertEqual(before, e._entry.sr_log())
        self.assertNotIn("secret", str(r))

    def test_termination_prevents_late_target_success_after_expiry(self):
        e, s, o, a, b = self.make()
        for n in range(24, 29):
            self.record(e, n, a, b)
        a[28]["high"] = 5753.9
        self.assertFalse(
            self.events(self.record(e, 29, a, b), "STRUCTURAL_TARGET_OBSERVED")
        )

    def test_checksum_only_and_rechecksummed_results_never_authorize(self):
        e, s, o, a, b = self.make()
        r = self.record(e, 24, a, b)
        with self.assertRaises(ValueError):
            validate_exit_report(r)
        for field, value in (
            ("execution_allowed", True),
            ("confidence", 0.9),
            ("entry_fill", 5750),
        ):
            bad = dict(deepcopy(r), **{field: value})
            bad["sha256"] = digest({k: v for k, v in bad.items() if k != "sha256"})
            with self.assertRaises(ValueError):
                validate_exit_report(bad, source=e)

    def test_policy_dict_and_unimplemented_timer_policy_are_rejected(self):
        with self.assertRaises(ValueError):
            ExitPolicy(target_observation="50_SECONDS")
        e, s, o, a, b = self.make()
        self.assertEqual(
            ExitResearchSession(
                o, o["plans"][0]["setup_id"], entry_source=s, policy={}
            ).report()["source_eligibility"],
            "BLOCKED",
        )

    def test_e1_fork_excludes_future_prefix_and_rejects_serialized_approval(self):
        e, s, o, a, b = self.make()
        v, c, i = snapshot(24, one=a, five=b)
        s.record(v, c)
        fork = s.fork_at(o)
        self.assertEqual(len(fork.sr_log()["entries"]), 1)
        self.assertEqual(fork.report(), o)
        bad = deepcopy(o)
        bad["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            s.fork_at(bad)

    def test_frozen_synthetic_examples_are_repeatable(self):
        from exit_examples import examples
        from pathlib import Path

        self.assertEqual(
            examples(),
            json.loads(
                Path("docs/research_audits/exit-intelligence.synthetic.json").read_text(
                    encoding="utf-8"
                )
            ),
        )

    def test_before_qualification_observation_does_not_create_an_exit(self):
        e, s, o, a, b = self.make()
        r = self.record(e, 22, a, b)
        self.assertEqual(r["source_eligibility"], "BLOCKED")
        self.assertFalse(r["observations"])
        self.assertFalse(e._events)

    def test_no_acquisition_execution_or_ai_capabilities(self):
        import ast
        from pathlib import Path

        tree = ast.parse(Path("iat/intelligence/exit_intelligence.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(
                    node.attr, ("order_send", "order_check", "initialize", "login")
                )
            if isinstance(node, ast.Import):
                self.assertFalse(
                    any(
                        x.name in ("MetaTrader5", "requests", "socket", "openai")
                        for x in node.names
                    )
                )

    def test_confirmed_opposing_choch_uses_canonical_occurrence_id(self):
        a, b = fixture()
        prices = [
            5750,
            5753,
            5748,
            5746.6,
            5750,
            5754,
            5751,
            5749,
            5752,
            5755,
            5753,
            5750,
            5753,
            5756,
            5754,
            5751,
            5754,
            5757,
            5755,
            5752,
        ]
        for row, p in zip(a, prices):
            row.update(open=p, high=p + 0.2, low=p - 0.2, close=p)
        a[22]["low"] = 5746.5
        policy = replace(INTELLIGENCE, break_policy="WICK")
        e, s, o, a, b = self.make(one=a, five=b, intelligence=policy)
        a[23]["low"] = 5746
        r = self.record(e, 24, a, b, intelligence=policy)
        events = self.events(r, "OPPOSING_STRUCTURE_OBSERVED")
        self.assertTrue(events)
        self.assertTrue(
            all(x["canonical_event_id"].startswith("M1:CHOCH_EVENT:") for x in events)
        )
        self.assertEqual(r["original_hypothesis_lifecycle"]["state"], "INVALIDATED")

    def test_unconfirmed_wick_under_close_policy_is_not_opposing_choch(self):
        e, s, o, a, b = self.make()
        a[23]["low"] = 5746.5
        r = self.record(e, 24, a, b)
        self.assertFalse(self.events(r, "OPPOSING_STRUCTURE_OBSERVED"))
        self.assertFalse(self.events(r, "STRUCTURAL_INVALIDATION_OBSERVED"))


if __name__ == "__main__":
    unittest.main()
