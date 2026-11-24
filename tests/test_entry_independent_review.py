"""Automated adversarial contract review, not external human approval."""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import unittest
from unittest.mock import patch
from exit_fixtures import fixture, snapshot, START
from iat.intelligence.entry_intelligence import (
    EntryResearchSession,
    validate_entry_report,
    POLICY,
)
from iat.intelligence.strategy_replay import digest


class E1IndependentReview(unittest.TestCase):
    def record(self, s, n=23, **kw):
        v, c, i = snapshot(n, **kw)
        return s.record(v, c, view_inputs=i)

    def test_new_fixture_has_multiple_qualified_anchors_both_directions(self):
        for mirror in (False, True):
            r = self.record(EntryResearchSession(), mirror=mirror)
            self.assertEqual(r["research_states"], ["RESEARCH_QUALIFIED"])
            self.assertEqual(len(r["plans"]), 2)

    def test_rechecksummed_zone_and_confidence_injection_rejected(self):
        s = EntryResearchSession()
        r = self.record(s)
        for field, value in (
            ("confidence", 0.99),
            ("execution_allowed", True),
            ("provenance", "HISTORICAL_RESEARCH"),
        ):
            bad = dict(deepcopy(r), **{field: value})
            bad["sha256"] = digest({k: v for k, v in bad.items() if k != "sha256"})
            with self.assertRaises(ValueError):
                validate_entry_report(bad, source=s)
        bad = deepcopy(r)
        bad["plans"][0]["entry_location"]["upper"] += 100
        bad["sha256"] = digest({k: v for k, v in bad.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_entry_report(bad, source=s)

    def test_original_producer_required(self):
        r = self.record(EntryResearchSession())
        for s in (None, EntryResearchSession(), {}):
            with self.assertRaises(ValueError):
                validate_entry_report(r, source=s)

    def test_provenance_fails_before_synthetic_evaluator(self):
        for provenance in ("VALIDATED_LIVE", "HISTORICAL_RESEARCH"):
            with patch(
                "iat.intelligence.entry_intelligence.SRRejectionLedger.record",
                side_effect=AssertionError("forbidden"),
            ):
                r = self.record(EntryResearchSession(), provenance=provenance)
            self.assertEqual(r["status"], "BLOCKED")

    def test_future_append_has_no_effect_at_original_cutoff(self):
        a, b = fixture()
        first = self.record(EntryResearchSession(), one=a, five=b)
        a[-1].update(open=1, low=0.1, high=99999, close=99998)
        self.assertEqual(first, self.record(EntryResearchSession(), one=a, five=b))

    def test_same_cutoff_revised_source_is_transactional(self):
        a, b = fixture()
        s = EntryResearchSession()
        first = self.record(s, one=a, five=b)
        before = s.sr_log()
        a[22]["close"] = 5750.05
        self.assertEqual(self.record(s, one=a, five=b)["status"], "BLOCKED")
        self.assertEqual(s.sr_log(), before)
        self.assertTrue(validate_entry_report(first, source=s))

    def test_bad_checksum_is_not_an_eligible_observation(self):
        s = EntryResearchSession()
        self.record(s)
        before = s.sr_log()
        v, c, i = snapshot(24)
        v["sha256"] = "0" * 64
        self.assertEqual(s.record(v, c, view_inputs=i)["status"], "BLOCKED")
        self.assertEqual(before, s.sr_log())

    def test_future_and_stale_explicit_cutoffs(self):
        v, c, i = snapshot()
        for n in (22, 24):
            self.assertEqual(
                EntryResearchSession().record(v, c, as_of=START + timedelta(minutes=n))[
                    "status"
                ],
                "BLOCKED",
            )

    def test_duplicate_does_not_rearm_or_advance_age(self):
        s = EntryResearchSession()
        r = self.record(s)
        for i in range(3):
            self.assertEqual(r, self.record(s))
        self.assertEqual(len(s.sr_log()["entries"]), 1)

    def test_report_remains_frozen_after_future_source(self):
        s = EntryResearchSession()
        r = self.record(s)
        copy = deepcopy(r)
        self.record(s, 24)
        self.assertEqual(r, copy)
        self.assertTrue(validate_entry_report(r, source=s))

    def test_resource_failures_leave_no_partial_state(self):
        for limits in (dict(max_sources=1), dict(max_setups=1)):
            s = EntryResearchSession()
            before = s.sr_log()
            with patch.dict(POLICY, **limits):
                r = self.record(s)
            self.assertEqual(r["status"], "BLOCKED")
            self.assertEqual(before, s.sr_log())
            self.assertFalse(s._produced)

    def test_projection_failure_does_not_commit_candidate(self):
        s = EntryResearchSession()
        self.record(s, 22)
        before = s.sr_log()
        with patch(
            "iat.intelligence.entry_intelligence._project",
            side_effect=ValueError("private detail"),
        ):
            r = self.record(s)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(before, s.sr_log())
        self.assertNotIn("private detail", str(r))

    def test_missing_immediate_confirmation_never_backfills_old_anchor(self):
        a, b = fixture()
        s = EntryResearchSession()
        first = self.record(s, 22, one=a, five=b)
        a[22].update(open=5747, high=5747.1, low=5746.9, close=5747)
        self.record(s, 23, one=a, five=b)
        later = self.record(s, 24, one=a, five=b)
        ids = {p["setup_id"] for p in first["plans"]}
        self.assertTrue(
            all(
                p["research_state"] != "RESEARCH_QUALIFIED"
                for p in later["plans"]
                if p["setup_id"] in ids
            )
        )

    def test_five_distinct_eligible_closes_not_duplicate_calls_drive_expiry(self):
        s = EntryResearchSession()
        self.record(s)
        for n in range(24, 28):
            self.record(s, n)
            self.record(s, n)
        self.assertNotIn("EXPIRED", s.report()["research_states"])
        self.assertIn("EXPIRED", self.record(s, 28)["research_states"])

    def test_overlapping_directions_keep_distinct_canonical_anchors(self):
        a, b = fixture()
        s = EntryResearchSession()
        self.record(s, one=a, five=b)
        a[24].update(open=5753.1, high=5753.4, low=5753, close=5753.2)
        a[25].update(open=5752.8, high=5752.9, low=5749.9, close=5750)
        for n in (24, 25, 26):
            r = self.record(s, n, one=a, five=b)
        qualified = [
            p for p in r["plans"] if p["research_state"] == "RESEARCH_QUALIFIED"
        ]
        self.assertEqual(
            {p["research_direction"] for p in qualified}, {"BULLISH", "BEARISH"}
        )
        self.assertEqual(len({p["setup_id"] for p in qualified}), len(qualified))

    def test_blocked_source_does_not_advance_qualified_age(self):
        a, b = fixture()
        s = EntryResearchSession()
        self.record(s, one=a, five=b)
        bad = a[:10] + a[11:]
        r = self.record(s, 24, one=bad, five=b)
        self.assertEqual(r["status"], "BLOCKED")
        qualified = [p for p in s.sr_log()["setups"] if p["qualified_at_utc"]]
        self.assertTrue(all(p["eligible_closes_after_C"] == 0 for p in qualified))
        self.record(s, 25, one=a, five=b)
        self.assertTrue(
            all(
                p["eligible_closes_after_C"] == 1
                for p in s.sr_log()["setups"]
                if p["qualified_at_utc"]
            )
        )

    def test_startup_root_resolution_is_in_body_and_file_regression_retained(self):
        code = Path("diagnostics/Start-IATLiveMarketView.ps1").read_text()
        self.assertNotIn("$ProjectRoot = (Split-Path", code)
        self.assertIn("[IO.Path]::GetDirectoryName($PSScriptRoot)", code)
        self.assertIn(
            "powershell.exe -NoProfile -NonInteractive -File",
            Path("diagnostics/Test-IATLiveStartup.ps1").read_text(),
        )

    def test_report_and_logs_expose_no_mutable_alias(self):
        s = EntryResearchSession()
        r = self.record(s)
        r["plans"][0]["entry_location"]["lower"] = 1
        log = s.sr_log()
        log["entries"].clear()
        self.assertNotEqual(s.report()["plans"][0]["entry_location"]["lower"], 1)
        self.assertTrue(s.sr_log()["entries"])


if __name__ == "__main__":
    unittest.main()
