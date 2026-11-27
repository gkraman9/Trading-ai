"""R1 deterministic synthetic contracts; no provider approval or live MT5 access."""

from copy import deepcopy
from dataclasses import asdict, replace, FrozenInstanceError
from datetime import timedelta, datetime, timezone
import json
from pathlib import Path
import unittest
from iat.timeframes import (
    FoundationError,
    FrameName,
    FrameDefinition,
    FixedInterval,
    FIXED_SECONDS,
    EvidenceDocument,
    EvidenceStore,
    FrameBinding,
    TimeframeProfile,
    assess_closed_prefix,
    validate_foundation_report,
    event_reference,
    canonical,
    digest,
)
from timeframe_fixtures import fixture, document, phase, START, BEGIN, END


class FrameContracts(unittest.TestCase):
    def good(self, k):
        r = assess_closed_prefix(**k)
        self.assertEqual(r["status"], "ELIGIBLE_SYNTHETIC_ONLY", r)
        return r

    def blocked(self, k, code=None):
        r = assess_closed_prefix(**k)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(r["bars"], [])
        if code:
            self.assertIn(code, r["reason_codes"])
        self.assertEqual(r["signal"], "WAIT")
        self.assertIs(r["execution_allowed"], False)
        return r

    def test_all_seven_fixed_frames_are_contracts_not_live_enabling(self):
        for frame, seconds in [
            ("M1", 60),
            ("M3", 180),
            ("M5", 300),
            ("M15", 900),
            ("M30", 1800),
            ("H1", 3600),
            ("H4", 14400),
        ]:
            with self.subTest(frame=frame):
                k = fixture(frame)
                self.assertEqual(FrameDefinition(FrameName(frame)).seconds, seconds)
                self.assertEqual(self.good(k)["closed_bar_count"], 3)

    def test_calendar_frames_and_ticks_cannot_be_fixed_seconds(self):
        for frame in ("D1", "W1", "MN1", "TICK"):
            with self.subTest(frame=frame), self.assertRaises(FoundationError):
                FrameDefinition(FrameName(frame))

    def test_unknown_alias_and_untyped_frame_rejected(self):
        for frame in ("m15", "15m", "H2", "", None, True):
            k = fixture()
            k["frame"] = frame
            self.blocked(k)
        with self.assertRaises(FoundationError):
            FrameDefinition("M1")

    def test_empty_profile_enables_nothing(self):
        k = fixture()
        k["profile"] = TimeframeProfile()
        self.blocked(k, "FRAME_NOT_ENABLED")

    def test_only_explicit_frame_is_enabled(self):
        k = fixture()
        k["frame"] = "M5"
        self.blocked(k, "FRAME_NOT_ENABLED")

    def test_fixed_registry_and_definitions_are_immutable(self):
        with self.assertRaises(TypeError):
            FIXED_SECONDS[FrameName.M1] = 900
        with self.assertRaises(FrozenInstanceError):
            FrameDefinition(FrameName.M1).version = 2

    def test_versions_booleans_and_invalid_history_policies_reject(self):
        b = fixture()["profile"].bindings[0]
        for kwargs in (
            {"version": True},
            {"version": 2},
            {"required_closed_bars": True},
            {"required_closed_bars": 2},
            {"max_slots": 10001},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(FoundationError):
                replace(b, **kwargs)

    def test_strict_json_configuration_roundtrip(self):
        k = fixture()
        p = TimeframeProfile.from_json(
            canonical(asdict(k["profile"])), evidence=k["evidence"]
        )
        self.assertEqual(p, k["profile"])
        self.assertEqual(p.sha256, k["profile"].sha256)

    def test_duplicate_unknown_keys_and_nonfinite_json_reject(self):
        for raw in (
            b'{"version":1,"version":1,"bindings":[],"edges":[]}',
            b'{"version":1,"bindings":[],"edges":[],"extra":0}',
            b'{"version":NaN,"bindings":[],"edges":[]}',
        ):
            with self.assertRaises(FoundationError):
                TimeframeProfile.from_json(raw, evidence=EvidenceStore(()))

    def test_oversize_and_nonbyte_evidence_reject(self):
        for value in (b"x" * 65537, "{}", b"{bad", b"\xef\xbb\xbf{}"):
            with self.assertRaises(FoundationError):
                EvidenceDocument(value)

    def test_missing_evidence_cannot_be_replaced_by_a_label_or_hash(self):
        k = fixture()
        k["evidence"] = EvidenceStore(())
        self.blocked(k, "EVIDENCE_BYTES_UNAVAILABLE")

    def test_evidence_kind_and_cross_source_bindings_are_checked(self):
        k = fixture()
        b = k["profile"].bindings[0]
        k["profile"] = TimeframeProfile((replace(b, finality_sha256=b.source_sha256),))
        self.blocked(k, "EVIDENCE_KIND_MISMATCH")
        k = fixture(interval={"source_sha256": "0" * 64})
        self.blocked(k, "SOURCE_BINDING_CONFLICT")

    def test_unsupported_native_mapping_duration_or_partial_policy_reject(self):
        for changes in (
            {"provider_frame": "M5"},
            {"mapping": "MT5_AUTO"},
            {"duration_seconds": 300},
            {"duration_seconds": True},
            {"bar_policy": "ASSUME_PARTIAL_FINAL"},
        ):
            with self.subTest(changes=changes), self.assertRaises(FoundationError):
                fixture(interval=changes)

    def test_anchor_required_aware_utc_and_whole_seconds(self):
        for anchor in (
            None,
            "2026-11-01T00:00:00",
            "2026-11-01T00:00:00+01:00",
            "2026-11-01T00:00:00.000001Z",
        ):
            with self.subTest(anchor=anchor), self.assertRaises(FoundationError):
                fixture(interval={"anchor_utc": anchor})

    def test_missing_finality_or_correction_policy_reject(self):
        for changes in (
            {"policy": "UNKNOWN"},
            {"correction_policy": "ASSUME_NO_CORRECTIONS"},
        ):
            with self.assertRaises(FoundationError):
                fixture(finality=changes)
        k = fixture()
        b = k["profile"].bindings[0]
        k["evidence"] = EvidenceStore(k["evidence"].documents[:-1])
        self.blocked(k, "EVIDENCE_BYTES_UNAVAILABLE")

    def test_contradictory_phase_or_undocumented_coverage_reject(self):
        for phases in (
            [phase(quotes="CLOSED")],
            [phase(end="2026-11-20T00:00:00Z")],
            [phase(quotes="UNKNOWN", positions="DISALLOWED")],
        ):
            with self.assertRaises(FoundationError):
                fixture(phases=phases)

    def test_evidence_bytes_are_not_silently_normalized(self):
        k = fixture()
        d = k["evidence"].documents[0]
        pretty = json.dumps(d.data(), indent=2).replace("\n", "\r\n").encode()
        other = EvidenceDocument(pretty)
        self.assertNotEqual(d.sha256, other.sha256)
        k["evidence"] = EvidenceStore((other,) + k["evidence"].documents[1:])
        self.blocked(k, "EVIDENCE_BYTES_UNAVAILABLE")

    def test_evidence_decoded_mutation_does_not_change_store(self):
        k = fixture()
        d = k["evidence"].documents[0]
        data = d.data()
        data["claims"]["feed"] = "CHANGED"
        self.good(k)
        self.assertNotEqual(data, d.data())

    def test_duplicate_evidence_and_duplicate_frame_rejected(self):
        k = fixture()
        d = k["evidence"].documents[0]
        with self.assertRaises(FoundationError):
            EvidenceStore((d, d))
        b = k["profile"].bindings[0]
        with self.assertRaises(FoundationError):
            TimeframeProfile((b, b))

    def test_role_edges_require_configured_frames_and_acyclic_graph(self):
        k = fixture()
        b = k["profile"].bindings[0]
        with self.assertRaises(FoundationError):
            TimeframeProfile((b,), ((FrameName.M15, FrameName.M1),))
        with self.assertRaises(FoundationError):
            TimeframeProfile((b,), ((FrameName.M15, FrameName.M15),))
        other = fixture("M5")["profile"].bindings[0]
        with self.assertRaises(FoundationError):
            TimeframeProfile(
                (b, other),
                ((FrameName.M15, FrameName.M5), (FrameName.M5, FrameName.M15)),
            )

    def test_nominal_interval_is_typed_and_has_no_analysis_authority(self):
        k = fixture()
        i = k["profile"].bindings[0].interval(k["window_start_utc"], k["evidence"])
        self.assertIs(type(i), FixedInterval)
        self.assertEqual(i.closed_at_utc - i.opened_at_utc, timedelta(minutes=15))
        with self.assertRaises(FoundationError):
            replace(i, closed_at_utc=i.opened_at_utc + timedelta(days=1))

    def test_verified_close_cannot_be_changed_to_early_session_boundary(self):
        k = fixture()
        k["rows"][1]["closed_at_utc"] = k["rows"][1]["opened_at_utc"]
        self.blocked(k, "CLOSE_CONFLICT")

    def test_availability_cannot_precede_verified_close(self):
        k = fixture()
        k["rows"][0]["available_at_utc"] = k["rows"][0]["opened_at_utc"]
        self.blocked(k, "AVAILABILITY_PRECEDES_CLOSE")

    def test_late_publication_is_unavailable_until_actual_availability(self):
        k = fixture()
        late = datetime.fromisoformat(k["as_of_utc"]) + timedelta(seconds=2)
        k["rows"][-1]["available_at_utc"] = late.isoformat()
        self.blocked(k, "SOURCE_NOT_AVAILABLE_AS_OF")
        k["as_of_utc"] = late.isoformat()
        self.good(k)

    def test_unknown_and_missing_row_finality_are_blocked(self):
        k = fixture()
        k["rows"][0]["finality"] = "UNKNOWN"
        self.blocked(k, "FINALITY_UNESTABLISHED")
        k = fixture()
        del k["rows"][0]["finality"]
        self.blocked(k, "SCHEMA_INVALID")

    def test_forming_future_payloads_are_not_inspected(self):
        k = fixture()
        r = self.good(k)
        k["rows"].append(
            {
                "opened_at_utc": k["as_of_utc"],
                "open": object(),
                "PRIVATE_FUTURE_PAYLOAD": object(),
            }
        )
        self.assertEqual(r, self.good(k))

    def test_future_candle_cannot_satisfy_warmup(self):
        k = fixture(n=2)
        k["rows"].append({"opened_at_utc": k["as_of_utc"]})
        self.blocked(k, "HISTORY_INCOMPLETE")

    def test_future_configuration_evidence_is_not_known_yet(self):
        k = fixture(available="2026-11-13T00:00:00Z")
        self.blocked(k, "CONFIGURATION_NOT_AVAILABLE_AS_OF")

    def test_missing_leading_middle_and_trailing_bars_fail(self):
        for index in (0, 1, 3):
            k = fixture(n=4)
            del k["rows"][index]
            self.blocked(k, "MISSING_OR_OUTSIDE_SESSION_BARS")

    def test_duplicate_out_of_order_and_off_grid_bars_fail(self):
        k = fixture(n=4)
        k["rows"][2] = deepcopy(k["rows"][1])
        self.blocked(k, "BAR_CHRONOLOGY_INVALID")
        k = fixture()
        k["rows"][0], k["rows"][1] = k["rows"][1], k["rows"][0]
        self.blocked(k, "BAR_CHRONOLOGY_INVALID")
        k = fixture()
        k["rows"][0]["opened_at_utc"] = (START + timedelta(seconds=1)).isoformat()
        self.blocked(k, "TIMEFRAME_MISALIGNED")

    def test_source_frame_feed_basis_and_revision_conflicts_fail(self):
        for field, value in [
            ("provider", "OTHER"),
            ("feed", "OTHER"),
            ("price_basis", "ASK"),
            ("frame", "M5"),
            ("revision", True),
            ("source_sha256", "0" * 64),
        ]:
            k = fixture()
            k["rows"][1][field] = value
            self.blocked(k)

    def test_nonfinite_malformed_ohlc_and_unknown_fields_fail(self):
        for field, value in [
            ("high", 1),
            ("low", float("nan")),
            ("open", True),
            ("close", "private-data"),
        ]:
            k = fixture()
            k["rows"][1][field] = value
            r = self.blocked(k, "OHLC_INVALID")
            self.assertNotIn("private-data", json.dumps(r))
        k = fixture()
        k["rows"][0]["extra"] = 1
        self.blocked(k, "SCHEMA_INVALID")

    def test_calendar_expiry_and_unknown_phase_fail_closed(self):
        k = fixture()
        k["as_of_utc"] = END
        self.blocked(k, "INTERVAL_COVERAGE_UNKNOWN")
        k = fixture(phases=[phase(quotes="UNKNOWN", positions="UNKNOWN")])
        self.blocked(k, "SESSION_COVERAGE_UNKNOWN")

    def test_overnight_known_closure_is_not_missing_data(self):
        a = "2026-11-12T00:30:00+00:00"
        b = "2026-11-12T02:00:00+00:00"
        k = fixture(
            n=9, phases=[phase(end=a), phase(a, b, "CLOSED", "DISALLOWED"), phase(b)]
        )
        k["rows"] = [r for r in k["rows"] if not a <= r["opened_at_utc"] < b]
        r = self.good(k)
        self.assertEqual(r["scheduled_closed_slots"], 6)
        self.assertEqual(r["closed_bar_count"], 3)

    def test_partial_session_slot_fails_without_moving_boundaries(self):
        boundary = "2026-11-12T00:43:00+00:00"
        resume = "2026-11-12T02:00:00+00:00"
        k = fixture(
            phases=[
                phase(end=boundary),
                phase(boundary, resume, "CLOSED", "DISALLOWED"),
                phase(resume),
            ]
        )
        self.blocked(k, "PARTIAL_SESSION_INTERVAL_UNSUPPORTED")

    def test_close_only_quotes_do_not_grant_trade_permission(self):
        k = fixture(phases=[phase(positions="DISALLOWED")])
        r = self.good(k)
        self.assertEqual(r["new_position_permission"], "DISALLOWED")
        self.assertFalse(r["execution_allowed"])

    def test_cutoff_in_closed_session_remains_blocked(self):
        a = "2026-11-12T00:45:00+00:00"
        b = "2026-11-12T02:00:00+00:00"
        k = fixture(
            phases=[phase(end=a), phase(a, b, "CLOSED", "DISALLOWED"), phase(b)]
        )
        self.blocked(k, "SESSION_CLOSED")

    def test_rows_in_closed_slots_are_not_accepted(self):
        a = "2026-11-12T00:15:00+00:00"
        b = "2026-11-12T00:30:00+00:00"
        k = fixture(
            phases=[phase(end=a), phase(a, b, "CLOSED", "DISALLOWED"), phase(b)]
        )
        self.blocked(k, "MISSING_OR_OUTSIDE_SESSION_BARS")

    def test_local_dst_anchor_is_not_silently_converted(self):
        for zone in ("America/New_York", "Europe/London"):
            with self.assertRaises(FoundationError):
                fixture("H4", interval={"grid_timezone": zone})
        k = fixture()
        k["rows"][0]["opened_at_utc"] = "2026-11-01T01:30:00-04:00"
        self.blocked(k, "EXPLICIT_UTC_REQUIRED")

    def test_dated_utc_h4_anchor_contracts_around_dst(self):
        before = fixture("H4", window=datetime(2026, 11, 1, 0, tzinfo=timezone.utc))
        self.good(before)
        after = fixture(
            "H4",
            window=datetime(2026, 11, 2, 1, tzinfo=timezone.utc),
            interval={
                "anchor_utc": "2026-11-02T01:00:00Z",
                "valid_from_utc": "2026-11-02T01:00:00Z",
            },
        )
        self.good(after)
        after["window_start_utc"] = "2026-11-01T00:00:00Z"
        self.blocked(after, "INTERVAL_COVERAGE_UNKNOWN")

    def test_declared_real_source_is_not_self_qualified(self):
        k = fixture(source={"provenance": "DECLARED_OFFLINE"})
        self.blocked(k, "INDEPENDENT_QUALIFICATION_REQUIRED")

    def test_resource_limits_are_checked(self):
        k = fixture()
        k["rows"] *= 1667
        self.blocked(k, "HISTORY_LIMIT")
        k = fixture(n=4, max_slots=3)
        self.blocked(k, "INTERVAL_RESOURCE_LIMIT")

    def test_repeatability_prefix_hash_and_future_append_invariance(self):
        k = fixture()
        a = self.good(k)
        self.assertEqual(a, self.good(deepcopy(k)))
        k["rows"].append({"opened_at_utc": "2026-11-20T00:00:00Z"})
        self.assertEqual(a, self.good(k))
        self.assertEqual(
            a["sha256"],
            digest({key: value for key, value in a.items() if key != "sha256"}),
        )

    def test_outputs_and_input_proofs_are_independent(self):
        k = fixture()
        old = deepcopy(k["rows"])
        a = self.good(k)
        a["bars"][0]["close"] = 999
        self.assertEqual(k["rows"], old)
        self.assertEqual(self.good(k)["bars"][0]["close"], 100.0)

    def test_rehashed_forged_report_fails_recomputation(self):
        k = fixture()
        r = self.good(k)
        self.assertTrue(validate_foundation_report(r, **k))
        r["execution_allowed"] = True
        r["sha256"] = digest({a: b for a, b in r.items() if a != "sha256"})
        with self.assertRaises(FoundationError):
            validate_foundation_report(r, **k)

    def test_interval_identity_and_observation_revision_are_separate(self):
        k = fixture()
        a = self.good(k)
        k["rows"][1].update(revision=1, close=100.5)
        b = self.good(k)
        self.assertEqual(
            a["intervals"][1]["interval_id"], b["intervals"][1]["interval_id"]
        )
        self.assertNotEqual(
            a["intervals"][1]["observation_id"], b["intervals"][1]["observation_id"]
        )

    def test_legacy_event_identity_is_never_replaced_by_sidecar(self):
        old = "M1:CHOCH_EVENT:" + digest("underlying-event")
        a = event_reference(
            original_event_id=old,
            original_source_sha256=digest("original"),
            configuration_sha256=digest("config-A"),
        )
        b = event_reference(
            original_event_id=old,
            original_source_sha256=digest("original"),
            configuration_sha256=digest("config-B"),
        )
        self.assertEqual({a["original_event_id"], b["original_event_id"]}, {old})
        self.assertNotEqual(a["sidecar_id"], b["sidecar_id"])
        self.assertTrue(a["reference_only"])
        self.assertFalse(a["execution_allowed"])

    def test_legacy_durations_and_provider_allowlists_are_unchanged(self):
        from iat.intelligence.models import DURATIONS
        from iat.mt5_data import TIMEFRAMES

        self.assertEqual(DURATIONS, {"M1": 60, "M5": 300})
        self.assertEqual(TIMEFRAMES, {"M1": 60, "M5": 300})
        from iat.quality import assess_candles

        self.assertFalse(assess_candles([], "M15", START).valid)

    def test_report_boolean_cannot_be_replaced_by_numeric_zero(self):
        k = fixture()
        r = self.good(k)
        r["execution_allowed"] = 0
        with self.assertRaises(FoundationError):
            validate_foundation_report(r, **k)

    def test_untrusted_payload_objects_are_rejected_without_execution(self):
        class Forbidden:
            def __eq__(self, other):
                raise AssertionError("PRIVATE_CALLBACK")

            def __float__(self):
                raise AssertionError("PRIVATE_CALLBACK")

        for key in ("finality", "feed", "price_basis", "open"):
            k = fixture()
            k["rows"][0][key] = Forbidden()
            r = self.blocked(k)
            self.assertNotIn("PRIVATE", json.dumps(r))

    def test_mixed_feed_or_basis_profile_cannot_be_silently_combined(self):
        for changed in ({"feed": "OTHER_FEED"}, {"price_basis": "ASK"}):
            k = fixture("M1")
            other = fixture("M15", source=changed)
            docs = {
                d.sha256: d
                for d in k["evidence"].documents + other["evidence"].documents
            }
            k["evidence"] = EvidenceStore(tuple(docs.values()))
            k["profile"] = TimeframeProfile(
                k["profile"].bindings + other["profile"].bindings
            )
            self.blocked(k, "PROFILE_SOURCE_CONFLICT")
            with self.assertRaises(FoundationError):
                TimeframeProfile.from_json(
                    canonical(asdict(k["profile"])), evidence=k["evidence"]
                )

    def test_explicit_compatible_multi_frame_profile_is_supported_without_automatic_acquisition(
        self,
    ):
        k = fixture("M1")
        other = fixture("M15")
        docs = {
            d.sha256: d for d in k["evidence"].documents + other["evidence"].documents
        }
        k["evidence"] = EvidenceStore(tuple(docs.values()))
        k["profile"] = TimeframeProfile(
            k["profile"].bindings + other["profile"].bindings,
            ((FrameName.M15, FrameName.M1),),
        )
        p = TimeframeProfile.from_json(
            canonical(asdict(k["profile"])), evidence=k["evidence"]
        )
        self.assertEqual(p, k["profile"])
        self.good(k)
