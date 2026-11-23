"""Synthetic boundary probes only; no private export is reconstructed or qualified."""

from copy import deepcopy
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from diagnostics.historical_session_boundaries import main
from iat.historical_session_boundaries import boundary_research
from iat.session_config import compile_session_config

PROFILE = Path("config/profiles/exness-xauusd-v2.candidate.json")
REVIEW = Path("config/profiles/exness-xauusd-v2.review.json")
REFERENCE = Path("config/reference/exness-2026-11-11-13.relayed.json")


def at(day, clock):
    return datetime.fromisoformat("2026-11-" + str(day) + "T" + clock + "+00:00")


def fake_bar(t):
    return dict(timestamp=t.isoformat(), open=100.0, high=101.0, low=99.0, close=100.0)


class SessionEvidenceInvestigationTests(unittest.TestCase):
    def setUp(self):
        self.original = {p: p.read_bytes() for p in (PROFILE, REVIEW, REFERENCE)}
        self.config = json.loads(self.original[PROFILE])
        self.calendar = compile_session_config(self.config)
        self.assertEqual(
            sha256(self.original[PROFILE]).hexdigest(),
            json.loads(self.original[REVIEW])["config_sha256"],
        )
        self.assertTrue(
            all(
                self.config["verification"][k] is False
                for k in (
                    "quote_schedule_verified",
                    "trade_schedule_verified",
                    "holidays_verified",
                    "maintenance_verified",
                )
            )
        )
        self.assertFalse(self.config["candle_finality"]["verified"])

    def tearDown(self):
        for path, raw in self.original.items():
            self.assertEqual(path.read_bytes(), raw, str(path))

    def test_three_actual_candidate_partial_close_geometries_never_compare_or_finalize(
        self,
    ):
        # Nine invented M1 bars and three invented M5 bars, NOT the 4,074/816 export.
        rows = dict(
            M1=[
                fake_bar(at(d, "21:55:00") + timedelta(minutes=i))
                for d in (11, 12, 13)
                for i in range(3)
            ],
            M5=[fake_bar(at(d, "21:55:00")) for d in (11, 12, 13)],
        )
        r = boundary_research(
            rows,
            self.calendar,
            "2026-11-11T00:00:00Z",
            "2026-11-14T00:00:00Z",
            observation_origin="SYNTHETIC_ONLY",
        )
        self.assertEqual(
            r["comparison_counts"], {"NOT_COMPARED_PARTIAL_OR_UNKNOWN_SESSION": 3}
        )
        self.assertEqual(
            r["m1_slot_absence_counts"]["MISSING_UNESTABLISHED_UNVERIFIED_CALENDAR"], 6
        )
        self.assertEqual(r["qualification"], "DATA_NOT_QUALIFIED")
        self.assertEqual(r["historical_comparisons"], "NOT_RUN")
        for item in r["m5_intervals"]:
            self.assertEqual(
                item["geometry"]["classification"], "PARTIAL_SESSION_CLOSE"
            )
            self.assertEqual(item["geometry"]["market_open_seconds"], 180)
            self.assertEqual(item["geometry"]["scheduled_end_utc"][11:16], "22:00")
            self.assertEqual(item["partial_finality"], "UNESTABLISHED")
            self.assertFalse(item["ordinary_eligible"])
            self.assertFalse(item["geometry"]["schedule_verified"])

    def test_five_synthetic_rows_do_not_turn_partial_geometry_into_a_full_match(self):
        rows = dict(
            M1=[fake_bar(at(12, "21:55:00") + timedelta(minutes=i)) for i in range(5)],
            M5=[
                fake_bar(at(12, "21:55:00") - timedelta(minutes=i)) for i in (10, 5, 0)
            ],
        )
        r = boundary_research(
            rows,
            self.calendar,
            "2026-11-12T21:40:00Z",
            "2026-11-12T22:01:00Z",
            observation_origin="SYNTHETIC_ONLY",
        )
        bar = next(
            x
            for x in r["m5_intervals"]
            if x["geometry"]["classification"] == "PARTIAL_SESSION_CLOSE"
        )
        self.assertTrue(all(s["assessment"] == "PRESENT" for s in bar["m1_slots"]))
        self.assertEqual(
            bar["five_m1_comparison"], "NOT_COMPARED_PARTIAL_OR_UNKNOWN_SESSION"
        )
        self.assertIsNone(bar["ohlc_differences"])
        self.assertIn("BAR_OUTSIDE_SESSION", r["reason_codes"])
        self.assertFalse(r["ordinary_inputs_emitted"])

    def test_same_m1_opening_cannot_distinguish_quote_resume_at_00_from_30_seconds(
        self,
    ):
        # Counterfactual configuration held only in memory; no broker/calendar approval.
        alternative = deepcopy(self.config)
        for day in ("mon", "tue", "wed", "thu"):
            alternative["weekdays"][day]["quotes"][1]["open"] = "23:00:30"
            alternative["weekdays"][day]["phases"][2]["state"] = "CLOSED"
        other = compile_session_config(alternative)
        opening = at(12, "23:00:00")
        for calendar, seconds in ((self.calendar, 60), (other, 30)):
            self.assertEqual(
                list(
                    calendar.expected_intervals(
                        opening, opening + timedelta(minutes=1), timedelta(minutes=1)
                    )
                ),
                [opening],
            )
            geometry = calendar.classify_bar(
                opening,
                "M1",
                research=True,
                observed_finalized=True,
                as_of=at(12, "23:10:00"),
            )
            self.assertEqual(geometry["market_open_seconds"], seconds)
            self.assertFalse(geometry["eligible_for_strategy"])
            self.assertFalse(geometry["iat_execution_allowed"])

    def test_quote_geometry_and_unknown_close_only_full_phases_remain_separate(self):
        for clock, phase in (
            ("23:00:00", "UNKNOWN"),
            ("23:00:29", "UNKNOWN"),
            ("23:00:30", "CLOSE_ONLY"),
            ("23:01:59", "CLOSE_ONLY"),
            ("23:02:00", "FULL_TRADING"),
        ):
            t = at(12, clock)
            self.assertTrue(any(a <= t < b for a, b in self.calendar.windows))
            self.assertEqual(self.calendar.phase_at(t), phase)
            permissions = self.calendar.public_state(t)["permissions"]
            self.assertIsNone(permissions["market_data_expected"])
            self.assertIsNone(permissions["broker_open_positions"])
            self.assertFalse(permissions["broker_permissions_verified"])
            self.assertFalse(permissions["iat_execution_allowed"])
        geometry = self.calendar.classify_bar(at(12, "23:00:00"), "M5", research=True)
        self.assertEqual(geometry["classification"], "FULL_SESSION_BAR")
        self.assertEqual(
            geometry["phase_states"], ["CLOSE_ONLY", "FULL_TRADING", "UNKNOWN"]
        )
        self.assertEqual(geometry["broker_finality"], "UNESTABLISHED")

    def test_friday_weekend_is_not_overridden_by_a_generic_daily_break_reply(self):
        friday = at(13, "23:00:00")
        self.assertFalse(any(a <= friday < b for a, b in self.calendar.windows))
        self.assertEqual(self.calendar.phase_at(friday), "CLOSED")
        self.assertEqual(
            self.calendar.classify_bar(friday, "M1", research=True)["classification"],
            "OUTSIDE_SESSION",
        )
        reference = json.loads(self.original[REFERENCE])
        self.assertIn(
            "FRIDAY_2026_11_13_2300_REOPEN_VS_REGULAR_WEEKEND_CLOSE",
            reference["unresolved"],
        )
        self.assertEqual(reference["independent_authentication"], "PENDING")

    def test_historical_geometry_does_not_renew_expired_or_future_captured_evidence(
        self,
    ):
        current = self.calendar.public_state(
            datetime(2026, 11, 23, tzinfo=timezone.utc)
        )
        self.assertEqual(current["verification"], "BLOCKED")
        self.assertIn("CALENDAR_EXPIRED", current["reason_codes"])
        earlier = self.calendar.public_state(at(11, "23:02:00"))
        self.assertIn("CALENDAR_COVERAGE_UNVERIFIED", earlier["reason_codes"])
        self.assertEqual(earlier["permissions"]["phase"], "UNKNOWN")
        geometry = self.calendar.classify_bar(
            at(11, "21:55:00"),
            "M5",
            research=True,
            observed_finalized=True,
            as_of=datetime(2026, 11, 23, tzinfo=timezone.utc),
        )
        self.assertEqual(geometry["classification"], "PARTIAL_SESSION_CLOSE")
        self.assertFalse(geometry["eligible_for_strategy"])
        self.assertEqual(geometry["broker_finality"], "UNESTABLISHED")

    def test_closed_phase_cannot_overlap_quotes_even_with_all_assurance_flags_false(
        self,
    ):
        inconsistent = deepcopy(self.config)
        inconsistent["weekdays"]["thu"]["phases"][2]["state"] = "CLOSED"
        with self.assertRaises(ValueError) as caught:
            compile_session_config(inconsistent)
        self.assertEqual(caught.exception.code, "PHASE_CONFLICT")

    def test_missing_local_csv_does_not_manufacture_comparison_counts(self):
        with TemporaryDirectory(prefix="iat boundary unavailable ") as folder:
            root = Path(folder)
            args = [
                "--m1",
                str(root / "missing-M1.csv"),
                "--m5",
                str(root / "missing-M5.csv"),
                "--calendar",
                str(PROFILE),
                "--timestamp-column",
                "timestamp_utc",
                "--start-utc",
                "2026-11-11T00:00:00Z",
                "--end-utc",
                "2026-11-14T00:00:00Z",
                "--report-path",
                str(root / "unavailable.json"),
            ]
            with redirect_stdout(StringIO()):
                self.assertEqual(main(args), 3)
            r = json.loads((root / "unavailable.json").read_text())
            self.assertEqual(r["status"], "UNAVAILABLE")
            self.assertNotIn("comparison_counts", r)
            self.assertEqual(r["qualification"], "DATA_NOT_QUALIFIED")
            self.assertFalse(r["safety"]["execution_allowed"])
            self.assertEqual(r["safety"]["signal"], "WAIT")
