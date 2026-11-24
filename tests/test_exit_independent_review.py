"""Contract-derived automated E2 review; not external human approval."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import unittest
from unittest.mock import patch
from risk_fixtures import sources, snapshot, START, CONFIG
from iat.intelligence.entry_intelligence import EntryResearchSession
from iat.intelligence.exit_intelligence import (
    ExitResearchSession,
    ExitPolicy,
    validate_exit_report,
    LIMITS,
)
from iat.intelligence.strategy_replay import digest


class E2IndependentReview(unittest.TestCase):
    def make(self, **kw):
        return sources(**kw)

    def record(self, e, n, a, b, **kw):
        v, c, i = snapshot(n, one=a, five=b, **kw)
        r = e.record(v, c, view_inputs=i)
        validate_exit_report(r, source=e)
        return r

    def test_independent_fixture_and_target_ties(self):
        s, o, e, initial, a, b = self.make()
        self.assertEqual(initial["source_eligibility"], "VALID")
        self.assertEqual(
            initial["target_candidates"],
            sorted(initial["target_candidates"], key=lambda z: z["id"]),
        )
        self.assertEqual(initial["frozen_target"], initial["target_candidates"][0])

    def test_source_future_prefix_cannot_select_target_or_age(self):
        s, o, e, initial, a, b = self.make()
        for n in (36, 37, 38):
            v, c, i = snapshot(n, one=a, five=b)
            s.record(v, c, view_inputs=i)
        later = ExitResearchSession(o, initial["original"]["setup_id"], entry_source=s)
        self.assertEqual(initial, later.report())
        self.assertEqual(self.record(e, 36, a, b), self.record(later, 36, a, b))

    def test_retrospective_original_rejected(self):
        s, o, e, initial, a, b = self.make()
        v, c, i = snapshot(36, one=a, five=b)
        later = s.record(v, c, view_inputs=i)
        r = ExitResearchSession(
            later, initial["original"]["setup_id"], entry_source=s
        ).report()
        self.assertEqual(r["source_eligibility"], "BLOCKED")

    def test_forged_original_and_recomputed_hash_rejected(self):
        s, o, e, initial, a, b = self.make()
        bad = deepcopy(o)
        bad["plans"][0]["structural_invalidation"]["lower"] = 1
        bad["sha256"] = digest({k: v for k, v in bad.items() if k != "sha256"})
        self.assertEqual(
            ExitResearchSession(
                bad, initial["original"]["setup_id"], entry_source=s
            ).report()["source_eligibility"],
            "BLOCKED",
        )

    def test_fake_e2_hash_and_wrong_producer_rejected(self):
        s, o, e, r, a, b = self.make()
        for field, value in (
            ("confidence", 0.99),
            ("entry_fill", 2100),
            ("execution_allowed", True),
        ):
            bad = dict(deepcopy(r), **{field: value})
            bad["sha256"] = digest({k: v for k, v in bad.items() if k != "sha256"})
            with self.assertRaises(ValueError):
                validate_exit_report(bad, source=e)
        with self.assertRaises(ValueError):
            validate_exit_report(r, source=ExitResearchSession())

    def test_same_cutoff_conflict_is_not_another_exit(self):
        s, o, e, r, a, b = self.make()
        self.record(e, 36, a, b)
        before = e._entry.sr_log()
        a[35]["close"] += 0.01
        self.assertEqual(self.record(e, 36, a, b)["source_eligibility"], "BLOCKED")
        self.assertEqual(before, e._entry.sr_log())

    def test_configuration_mismatch_is_not_compatible_source(self):
        s, o, e, r, a, b = self.make()
        before = e._entry.sr_log()
        self.assertEqual(
            self.record(e, 36, a, b, config=replace(CONFIG, atr_period=13))[
                "source_eligibility"
            ],
            "BLOCKED",
        )
        self.assertEqual(before, e._entry.sr_log())

    def test_exact_original_tolerance_and_strict_breach(self):
        for mirror in (False, True):
            s, o, e, r, a, b = self.make(mirror=mirror)
            z = r["frozen_invalidation"]
            threshold = (
                z["upper"] + z["break_tolerance"]
                if mirror
                else z["lower"] - z["break_tolerance"]
            )
            a[35].update(
                close=threshold, low=min(threshold, 2097), high=max(threshold, 2103)
            )
            at = self.record(e, 36, a, b)
            self.assertFalse(
                any(
                    x["kind"] == "STRUCTURAL_INVALIDATION_OBSERVED"
                    for x in at["observations"]
                )
            )

    def test_wick_and_close_policies_remain_different(self):
        for mode in ("WICK_CONTACT", "CLOSE_BEYOND_REFERENCE"):
            s, o, e, r, a, b = self.make(policy=ExitPolicy(target_observation=mode))
            a[35]["high"] = 2106.4
            r = self.record(e, 36, a, b)
            self.assertEqual(
                any(
                    x["kind"] == "STRUCTURAL_TARGET_OBSERVED" for x in r["observations"]
                ),
                mode == "WICK_CONTACT",
            )

    def test_same_bar_ambiguity_preserves_both_observations(self):
        s, o, e, r, a, b = self.make()
        a[35].update(high=2106.4, low=2097, close=2097.1)
        r = self.record(e, 36, a, b)
        self.assertEqual(r["ambiguity"]["status"], "UNRESOLVED_EVENT_ORDER")
        self.assertTrue(
            {"STRUCTURAL_TARGET_OBSERVED", "STRUCTURAL_INVALIDATION_OBSERVED"}
            <= set(r["analytical_states"])
        )

    def test_simultaneous_close_availability_not_invented_tick_order(self):
        s, o, e, r, a, b = self.make(
            policy=ExitPolicy(target_observation="CLOSE_BEYOND_REFERENCE")
        )
        for n in range(36, 40):
            self.record(e, n, a, b)
        a[39].update(close=2106.5, high=2106.6)
        r = self.record(e, 40, a, b)
        self.assertEqual(
            r["ambiguity"]["groups"][0]["timing_basis"],
            "SIMULTANEOUS_CLOSE_AVAILABILITY",
        )

    def test_repeated_snapshots_do_not_duplicate_events(self):
        s, o, e, r, a, b = self.make()
        a[35]["high"] = 2106.4
        r = self.record(e, 36, a, b)
        self.assertEqual(r, self.record(e, 36, a, b))
        self.assertEqual(len(r["observations"]), 1)

    def test_terminal_hypothesis_never_records_late_target_success(self):
        s, o, e, r, a, b = self.make()
        for n in range(36, 41):
            self.record(e, n, a, b)
        a[40]["high"] = 2106.5
        r = self.record(e, 41, a, b)
        self.assertFalse(
            any(x["kind"] == "STRUCTURAL_TARGET_OBSERVED" for x in r["observations"])
        )

    def test_skipped_observations_are_not_retrospectively_evaluated(self):
        s, o, e, r, a, b = self.make()
        a[35]["high"] = 2106.5
        r = self.record(e, 37, a, b)
        self.assertIn("ABSTAINED", r["analytical_states"])
        self.assertFalse(r["observations"])
        self.assertIn(
            "INTERVENING_EXIT_OBSERVATIONS_NOT_EVALUATED", r["missing_evidence"]
        )

    def test_prior_reports_and_first_observed_are_frozen(self):
        s, o, e, r, a, b = self.make()
        a[35]["high"] = 2106.4
        r = self.record(e, 36, a, b)
        frozen = deepcopy(r)
        self.record(e, 37, a, b)
        self.assertEqual(r, frozen)
        validate_exit_report(r, source=e)
        event = r["observations"][0]
        self.assertIsNone(event["occurred_at_utc"])
        self.assertEqual(
            event["first_observed_at_utc"], (START + timedelta(minutes=36)).isoformat()
        )

    def test_resource_limit_and_projection_failure_roll_back(self):
        for kind in ("limit", "projection"):
            s, o, e, r, a, b = self.make()
            a[35]["high"] = 2106.5
            before = e._entry.sr_log()
            manager = (
                patch.dict(LIMITS, max_events=0)
                if kind == "limit"
                else patch.object(e, "_report", side_effect=ValueError("secret"))
            )
            with manager:
                r = self.record(e, 36, a, b)
            self.assertEqual(r["source_eligibility"], "BLOCKED")
            self.assertEqual(before, e._entry.sr_log())
            self.assertFalse(e._events)
            self.assertEqual(self.record(e, 36, a, b)["source_eligibility"], "VALID")

    def test_real_provenance_never_calls_synthetic_entry(self):
        s, o, e, r, a, b = self.make()
        for provenance in ("VALIDATED_LIVE", "HISTORICAL_RESEARCH"):
            with patch.object(
                EntryResearchSession, "record", side_effect=AssertionError("forbidden")
            ):
                self.assertEqual(
                    self.record(e, 36, a, b, provenance=provenance)[
                        "source_eligibility"
                    ],
                    "BLOCKED",
                )

    def test_unconfirmed_wick_does_not_create_opposing_structure(self):
        s, o, e, r, a, b = self.make()
        a[35]["low"] = 2097.6
        r = self.record(e, 36, a, b)
        self.assertFalse(
            any(x["kind"] == "OPPOSING_STRUCTURE_OBSERVED" for x in r["observations"])
        )

    def test_blocked_source_does_not_advance_expiry(self):
        s, o, e, r, a, b = self.make()
        bad = a[:10] + a[11:]
        self.assertEqual(self.record(e, 36, bad, b)["source_eligibility"], "BLOCKED")
        self.assertTrue(
            all(
                x["eligible_closes_after_C"] == 0
                for x in e._entry.sr_log()["setups"]
                if x["qualified_at_utc"]
            )
        )
        recovered = self.record(e, 37, a, b)
        self.assertEqual(
            recovered["original_hypothesis_lifecycle"][
                "eligible_closes_after_confirmation"
            ],
            1,
        )

    def test_declared_cutoff_mismatch_does_not_commit_source(self):
        s, o, e, r, a, b = self.make()
        v, c, i = snapshot(36, one=a, five=b)
        before = e._entry.sr_log()
        self.assertEqual(
            e.record(v, c, view_inputs=i, as_of=START + timedelta(minutes=37))[
                "source_eligibility"
            ],
            "BLOCKED",
        )
        self.assertEqual(before, e._entry.sr_log())

    def test_no_fill_probability_pnl_or_permission_after_observation(self):
        s, o, e, r, a, b = self.make()
        a[35]["high"] = 2106.4
        r = self.record(e, 36, a, b)
        self.assertEqual(r["signal"], "WAIT")
        self.assertIs(r["execution_allowed"], False)
        for k in (
            "entry_fill",
            "exit_fill",
            "hypothetical_pnl",
            "realized_pnl",
            "holding_duration",
            "performance_metrics",
        ):
            self.assertIsNone(r[k])


if __name__ == "__main__":
    unittest.main()
