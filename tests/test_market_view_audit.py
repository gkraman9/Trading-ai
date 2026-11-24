"""Automated adversarial review: independent invented OHLC, no broker evidence."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from iat.intelligence.context import context_at, analyze_context
from iat.intelligence.engine import analyze_at
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.adaptive import assess_adaptive
from iat.intelligence.scenario_assessment import assess_scenarios
from iat.intelligence.market_view import build_market_view_v3, validate_market_view_v3
from iat.intelligence.strategy_replay import digest
from iat.session_config import compile_session_config

AT = datetime(2026, 11, 12, 13, tzinfo=timezone.utc)
SYMBOL = "SYNTHETIC_AUDIT_XAUUSD"


def fixture(count=60, sign=1, missing=None, calendar=None):
    """Independent staircase waves; no imported original implementation fixtures."""
    frames = {}
    wave = (0, 1, 3, 1, 0, -1, -3, -1, 0, 0.5)
    for tf, minutes in (("M1", 1), ("M5", 5)):
        rows = []
        for n in range(count):
            price = 1800 + sign * ((n // 10) * 1.5 + wave[n % 10])
            rows.append(
                dict(
                    timestamp=(
                        AT - timedelta(minutes=(count - n) * minutes)
                    ).isoformat(),
                    open=price - 0.1 * sign,
                    high=price + 0.4,
                    low=price - 0.4,
                    close=price,
                )
            )
        frames[tf] = rows if tf != missing else None
    options = dict(
        config=ContextConfig(),
        intelligence_config=IntelligenceConfig(),
        calendar=calendar,
        observed_finality=True if calendar else None,
    )
    c = context_at(SYMBOL, frames["M1"], frames["M5"], AT, **options)
    i = analyze_at(
        SYMBOL,
        frames["M1"],
        frames["M5"],
        AT,
        config=options["intelligence_config"],
        calendar=calendar,
        observed_finality=options["observed_finality"],
    )
    return c, i, frames, options


def calendar_fixture():
    win = dict(open="00:00:00", close="00:00:00", close_day_offset=1)
    return compile_session_config(
        dict(
            version=2,
            symbol=SYMBOL,
            timezone="UTC",
            coverage=dict(start="2026-11-10", end="2026-11-14"),
            verification=dict(
                quote_schedule_verified=True,
                trade_schedule_verified=True,
                holidays_verified=True,
                maintenance_verified=True,
                expires_at="2026-11-14T00:00:00Z",
                provenance=[
                    dict(
                        id="audit",
                        kind="SYNTHETIC_TEST",
                        reference="Invented audit calendar only",
                        captured_at="2026-11-09T00:00:00Z",
                    )
                ],
            ),
            candle_finality=dict(policy="MT5_POSITION_1_ELAPSED", verified=True),
            weekdays={
                d: dict(quotes=[win], phases=[dict(win, state="FULL_TRADING")])
                for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
            },
            holidays=[],
            exceptions={},
            maintenance=[],
            closures=[],
            assurance_holds=[],
        )
    )


def rehash(v):
    v["sha256"] = digest({k: x for k, x in v.items() if k != "sha256"})
    return v


class AutomatedAuditTests(unittest.TestCase):
    def test_unknown_nested_field_rejected_by_python_and_json_schema(self):
        c, _, _, _ = fixture()
        v = build_market_view_v3(c)
        v["price_structure"]["swings"]["approval"] = True
        rehash(v)
        with self.assertRaises(ValueError):
            validate_market_view_v3(v)

    def test_malformed_collection_item_rejected(self):
        c, _, _, _ = fixture()
        v = build_market_view_v3(c)
        v["price_structure"]["swings"]["items"] = [
            {"kind": "HIGH", "price": "not a price"}
        ]
        rehash(v)
        schema = json.loads(
            Path("config/market-intelligence-v3.schema.json").read_text()
        )
        self.assertFalse(
            Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(v)
        )
        with self.assertRaises(ValueError):
            validate_market_view_v3(v)

    def test_unsupported_market_regime_rejected(self):
        c, _, _, _ = fixture()
        v = build_market_view_v3(c)
        v["market_state"]["regime"] = "CERTAIN_PROFIT"
        rehash(v)
        with self.assertRaises(ValueError):
            validate_market_view_v3(v)

    def test_rechecksummed_rank_and_score_mismatch_rejected(self):
        c, _, _, _ = fixture()
        for field, value in (("rank", 999), ("heuristic_score", 9000)):
            v = build_market_view_v3(c)
            v["advisory"]["ranked_hypotheses"][0][field] = value
            rehash(v)
            with self.assertRaises(ValueError):
                validate_market_view_v3(v)

    def test_rechecksummed_child_hash_binding_mismatch_rejected(self):
        cal = calendar_fixture()
        c, _, _, _ = fixture(calendar=cal)
        v = build_market_view_v3(c, session_snapshot=cal.public_state(AT))
        v["bindings"]["session"] = "0" * 64
        rehash(v)
        with self.assertRaises(ValueError):
            validate_market_view_v3(v)

    def test_rechecksummed_unavailable_collection_cannot_contain_items(self):
        c, i, _, _ = fixture()
        v = build_market_view_v3(c, intelligence_report=i)
        self.assertTrue(v["price_structure"]["swings"]["items"])
        v["price_structure"]["swings"]["status"] = "UNAVAILABLE"
        rehash(v)
        with self.assertRaises(ValueError):
            validate_market_view_v3(v)

    def test_invalid_session_permission_metadata_does_not_get_presented(self):
        cal = calendar_fixture()
        c, _, _, _ = fixture(calendar=cal)
        for field, value in (("provenance_count", -5), ("provenance_kinds", 42)):
            s = cal.public_state(AT)
            s[field] = value
            v = build_market_view_v3(c, session_snapshot=s)
            self.assertEqual(v["status"], "BLOCKED")

    def test_neutral_selection_cannot_be_relabelled_assessed(self):
        cal = calendar_fixture()
        c, _, _, _ = fixture(count=4, calendar=cal)
        v = build_market_view_v3(c, session_snapshot=cal.public_state(AT))
        v["status"] = "ASSESSED"
        rehash(v)
        with self.assertRaises(ValueError):
            validate_market_view_v3(v)

    def test_session_calendar_binding_is_not_inferred_from_supplied_snapshot(self):
        cal = calendar_fixture()
        c, _, _, _ = fixture(calendar=cal)
        s = cal.public_state(AT)
        s["configuration_sha256"] = "f" * 64
        v = build_market_view_v3(c, session_snapshot=s)
        # ContextReport v1 carries no calendar digest. A declaration alone cannot
        # establish a same-calendar binding or permit ASSESSED/ABSTAINED status.
        self.assertEqual(v["status"], "UNKNOWN")
        self.assertIn(
            "SESSION_CONTEXT_BINDING_UNESTABLISHED", v["advisory"]["wait_reasons"]
        )

    def test_independent_state_matrix_and_unchanged_sources(self):
        cal = calendar_fixture()
        for missing in (None, "M1", "M5"):
            for count in (4, 60):
                c, i, _, _ = fixture(count=count, missing=missing, calendar=cal)
                before = deepcopy(c.to_dict())
                before_i = deepcopy(i.to_dict())
                snapshot = cal.public_state(AT)
                v = build_market_view_v3(
                    c, session_snapshot=snapshot, intelligence_report=i
                )
                self.assertTrue(
                    validate_market_view_v3(
                        v,
                        context_report=c,
                        session_snapshot=snapshot,
                        intelligence_report=i,
                    )
                )
                self.assertEqual(v["status"], "UNKNOWN")
                self.assertEqual(
                    v["advisory"]["selected_hypothesis"],
                    c.confluence["selected_hypothesis"],
                )
                self.assertEqual(
                    v["confluence"]["scores"], json.loads(json.dumps(c.confluence))
                )
                self.assertEqual(v["signal"], "WAIT")
                self.assertIs(v["execution_allowed"], False)
                self.assertEqual(c.to_dict(), before)
                self.assertEqual(i.to_dict(), before_i)

    def test_independent_closed_unknown_and_restricted_sessions(self):
        cal = calendar_fixture()
        c, _, _, _ = fixture(calendar=cal)
        for phase, pair in (
            ("CLOSED", (False, False)),
            ("QUOTE_ONLY", (False, False)),
            ("CLOSE_ONLY", (False, True)),
            ("UNKNOWN", (None, None)),
        ):
            s = cal.public_state(AT)
            s["permissions"].update(
                phase=phase,
                broker_open_positions=pair[0],
                broker_close_positions=pair[1],
                broker_permissions_verified=phase != "UNKNOWN",
            )
            v = build_market_view_v3(c, session_snapshot=s)
            self.assertEqual(
                v["status"], "UNKNOWN" if phase == "UNKNOWN" else "BLOCKED"
            )
            self.assertTrue(validate_market_view_v3(v))
        s = cal.public_state(AT)
        s.update(verification="BLOCKED", reason_codes=["CALENDAR_COVERAGE_UNVERIFIED"])
        self.assertEqual(
            build_market_view_v3(c, session_snapshot=s)["status"], "BLOCKED"
        )

    def test_independent_stale_unfinished_and_malformed_history_fail_closed(self):
        c, _, rows, options = fixture()
        for at, one, five in (
            (AT + timedelta(hours=1), rows["M1"], rows["M5"]),
            (
                AT,
                rows["M1"],
                rows["M5"]
                + [
                    dict(
                        timestamp=AT.isoformat(),
                        open=1800,
                        high=1801,
                        low=1799,
                        close=1800,
                    )
                ],
            ),
        ):
            invalid = analyze_context(SYMBOL, one, five, at, **options)
            v = build_market_view_v3(invalid)
            self.assertEqual(v["status"], "BLOCKED")
            self.assertFalse(v["confluence"]["evidence_index"])
            self.assertTrue(validate_market_view_v3(v))
        for bad in (None, {}, replace(c, analysis_at="1999-01-01T00:00:00Z")):
            self.assertEqual(build_market_view_v3(bad)["status"], "BLOCKED")

    def test_independent_opposing_structure_and_fresh_change_remain_visible(self):
        _, _, one, opt = fixture(sign=1)
        _, _, other, _ = fixture(sign=-1)
        c = context_at(SYMBOL, one["M1"], other["M5"], AT, **opt)
        v = build_market_view_v3(c)
        self.assertIn(
            "CONFLICTING_TIMEFRAME_STRUCTURE", v["advisory"]["abstention_reasons"]
        )
        self.assertTrue(v["confluence"]["conflicts"])
        # Add one newly closed opposing break after the old bullish prefix.
        one["M1"].append(
            dict(timestamp=AT.isoformat(), open=1800, high=1801, low=1750, close=1751)
        )
        c = context_at(SYMBOL, one["M1"], one["M5"], AT + timedelta(minutes=1), **opt)
        v = build_market_view_v3(c)
        self.assertIn("FRESH_OPPOSING_M1_CHOCH", v["advisory"]["wait_reasons"])
        self.assertTrue(validate_market_view_v3(v, context_report=c))

    def test_independent_mixed_reports_and_configuration_hashes_reject(self):
        c, i, _, _ = fixture()
        other, _, _, _ = fixture(sign=-1)
        for inputs in (
            {"scenario_report": assess_scenarios(other)},
            {"adaptive_report": assess_adaptive(other)},
            {"intelligence_report": replace(i, configuration_sha256="a" * 64)},
            {"intelligence_report": replace(i, symbol="OTHER")},
        ):
            self.assertEqual(build_market_view_v3(c, **inputs)["status"], "BLOCKED")
        v = build_market_view_v3(c)
        v["bindings"]["configuration_hashes"]["context"] = "b" * 64
        rehash(v)
        with self.assertRaises(ValueError):
            validate_market_view_v3(v, context_report=c)

    def test_independent_duplicate_and_conflicting_evidence(self):
        c, _, _, _ = fixture()
        same = replace(c, evidence=c.evidence + c.evidence)
        self.assertEqual(build_market_view_v3(c), build_market_view_v3(same))
        changed = replace(
            c.evidence[0],
            direction="BEARISH" if c.evidence[0].direction != "BEARISH" else "BULLISH",
        )
        self.assertEqual(
            build_market_view_v3(replace(c, evidence=c.evidence + (changed,)))[
                "status"
            ],
            "BLOCKED",
        )

    def test_independent_replay_repeat_prefix_and_future_invariance(self):
        _, _, rows, opt = fixture(count=30)

        def view(one, five, at):
            return build_market_view_v3(context_at(SYMBOL, one, five, at, **opt))

        cutoff = AT - timedelta(minutes=2)
        prefix_one = [
            r
            for r in rows["M1"]
            if datetime.fromisoformat(r["timestamp"]) + timedelta(minutes=1) <= cutoff
        ]
        prefix_five = [
            r
            for r in rows["M5"]
            if datetime.fromisoformat(r["timestamp"]) + timedelta(minutes=5) <= cutoff
        ]
        snapshots = [
            cutoff - timedelta(minutes=2),
            cutoff - timedelta(minutes=1),
            cutoff,
        ]
        full = [view(rows["M1"], rows["M5"], t) for t in snapshots]
        self.assertEqual(full, [view(prefix_one, prefix_five, t) for t in snapshots])
        self.assertEqual(
            digest(full), digest([view(rows["M1"], rows["M5"], t) for t in snapshots])
        )
        rows["M1"].append(
            dict(timestamp=AT.isoformat(), open=999, high=1000, low=1, close=2)
        )
        self.assertEqual(full[-1], view(rows["M1"], rows["M5"], cutoff))

    def test_report_scoped_event_key_cannot_be_forged_into_canonical_occurrence(self):
        c, i, _, _ = fixture()
        v = build_market_view_v3(c, intelligence_report=i)
        events = v["price_structure"]["structural_events"]["items"]
        self.assertTrue(events)
        for e in events:
            self.assertEqual(e["source_report_sha256"], v["bindings"]["intelligence"])
            if not e["event_type"].endswith("_CHOCH"):
                self.assertIsNone(e["event_id"])
        events[0]["source_report_sha256"] = "a" * 64
        rehash(v)
        with self.assertRaises(ValueError):
            validate_market_view_v3(v)

    def test_negative_nested_fuzz_parity(self):
        c, _, _, _ = fixture()
        original = build_market_view_v3(c)
        schema = json.loads(
            Path("config/market-intelligence-v3.schema.json").read_text()
        )
        schema_validator = Draft202012Validator(schema, format_checker=FormatChecker())
        changes = [
            ("restrictions", "data_quality", []),
            ("market_state", "momentum", {"M1": "bullish"}),
            ("advisory", "ranked_hypotheses", [{}]),
            ("confluence", "sources", {"arbitrary": {}}),
            (
                "liquidity",
                "events",
                {"status": "AVAILABLE", "items": [{}], "reason_codes": []},
            ),
            ("restrictions", "session", {"version": 2}),
            ("advisory", "confidence", 0.99),
        ]
        for section, key, value in changes:
            v = deepcopy(original)
            v[section][key] = value
            rehash(v)
            self.assertFalse(schema_validator.is_valid(v), (section, key))
            with self.assertRaises(ValueError):
                validate_market_view_v3(v)
