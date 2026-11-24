"""Labeled synthetic OHLC only. No broker, terminal, source approval or service."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from iat.intelligence.adaptive import assess_adaptive
from iat.intelligence.context import context_at, analyze_context
from iat.intelligence.engine import analyze_intelligence, analyze_at
from iat.intelligence.market_view import (
    build_market_view_v3,
    validate_market_view_v3,
    SAFETY,
)
from iat.intelligence.scenario_assessment import assess_scenarios
from iat.intelligence.strategy_replay import digest
from iat.session_config import compile_session_config
from test_context_engine import two_frames, CONFIG, P7
from test_scenario_assessment import context


def reports(mirror=False, choch=False, **options):
    a, b, at = two_frames(mirror, choch)
    c = context_at(
        "SYNTHETIC_XAUUSD", a, b, at, config=CONFIG, intelligence_config=P7, **options
    )
    i = analyze_at(c.symbol, a, b, at, config=P7, **options)
    return c, i


class MarketViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(
            Path("config/market-intelligence-v3.schema.json").read_text()
        )
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema, format_checker=FormatChecker())

    def safe(self, v, **inputs):
        self.assertTrue(validate_market_view_v3(v, **inputs))
        self.validator.validate(v)
        for k, value in SAFETY.items():
            self.assertEqual(v[k], value)
        self.assertIs(v["execution_allowed"], False)
        self.assertIsNone(v["advisory"]["confidence"])
        return v

    def test_normal_both_directions_with_full_original_detail(self):
        for mirror in (False, True):
            c, i = reports(mirror)
            v = self.safe(
                build_market_view_v3(c, intelligence_report=i),
                context_report=c,
                intelligence_report=i,
            )
            self.assertEqual(v["market_state"]["available_timeframes"], ["M1", "M5"])
            self.assertEqual(
                v["market_state"]["regime"], "TREND_DOWN" if mirror else "TREND_UP"
            )
            self.assertEqual(v["price_structure"]["swings"]["status"], "AVAILABLE")
            self.assertTrue(
                any(
                    p["relation"] in ("HH", "HL", "LH", "LL")
                    for p in v["price_structure"]["swings"]["items"]
                )
            )
            self.assertTrue(v["price_structure"]["structural_events"]["items"])
            self.assertEqual(v["status"], "UNKNOWN")  # No verified session invented.

    def test_score_selection_and_hypotheses_exactly_preserved(self):
        c, _ = reports()
        v = self.safe(build_market_view_v3(c))
        self.assertEqual(
            v["confluence"]["scores"], json.loads(json.dumps(c.confluence))
        )
        self.assertEqual(
            v["advisory"]["selected_hypothesis"], c.confluence["selected_hypothesis"]
        )
        self.assertEqual(
            v["advisory"]["ranked_hypotheses"], assess_scenarios(c)["ranked_hypotheses"]
        )
        self.assertEqual(v["advisory"]["upstream_signal"], "WAIT")
        self.assertEqual(
            v["price_structure"]["swings"]["reason_codes"],
            ["V1_INTELLIGENCE_NOT_SUPPLIED"],
        )

    def test_existing_canonical_ids_and_relations_resolve_without_window_keys(self):
        c, i = reports(choch=True)
        v = self.safe(build_market_view_v3(c, intelligence_report=i))
        self.assertEqual(
            [e["id"] for e in v["confluence"]["evidence_index"]],
            sorted(e.id for e in c.evidence),
        )
        sources = v["confluence"]["sources"]
        for p in v["price_structure"]["swings"]["items"]:
            self.assertIn(p["id"], sources)
            self.assertTrue(set(p["references"]) <= set(sources))
        for e in v["price_structure"]["structural_events"]["items"]:
            self.assertTrue(set(e["references"]) <= set(sources))
        self.assertEqual(
            {e["event_id"] for e in v["confluence"]["evidence_index"] if e["event_id"]},
            {e.event_id for e in c.evidence if e.event_id},
        )

    def test_missing_m1_is_not_positive_confirmation(self):
        a, b, at = two_frames()
        c = context_at(
            "SYNTHETIC_XAUUSD", None, b, at, config=CONFIG, intelligence_config=P7
        )
        v = self.safe(build_market_view_v3(c))
        self.assertEqual(v["status"], "UNKNOWN")
        self.assertEqual(v["restrictions"]["missing_timeframes"], ["M1"])
        self.assertEqual(v["confluence"]["m1_structure"], "UNKNOWN")

    def test_missing_m5_is_not_positive_confirmation(self):
        a, b, at = two_frames()
        c = context_at(
            "SYNTHETIC_XAUUSD", a, None, at, config=CONFIG, intelligence_config=P7
        )
        v = self.safe(build_market_view_v3(c))
        self.assertEqual(v["restrictions"]["missing_timeframes"], ["M5"])
        self.assertEqual(v["market_state"]["regime"], "UNKNOWN")

    def test_opposing_structures_preserve_conflicts_and_abstention(self):
        a, b, at = two_frames()
        for row in b:
            o, h, l, cl = [row[k] for k in ("open", "high", "low", "close")]
            row.update(open=200 - o, high=200 - l, low=200 - h, close=200 - cl)
        c = analyze_context(
            "SYNTHETIC_XAUUSD", a, b, at, config=CONFIG, intelligence_config=P7
        )
        v = self.safe(build_market_view_v3(c))
        self.assertTrue(v["confluence"]["conflicts"])
        self.assertIn(
            "CONFLICTING_TIMEFRAME_STRUCTURE", v["advisory"]["abstention_reasons"]
        )
        self.assertEqual(
            v["advisory"]["selected_hypothesis"], c.confluence["selected_hypothesis"]
        )

    def test_fresh_opposing_choch_not_hidden_by_directional_alignment(self):
        c, i = reports(choch=True)
        v = self.safe(build_market_view_v3(c, intelligence_report=i))
        self.assertEqual(v["confluence"]["agreement"], c.context["phase7_alignment"])
        self.assertIn("FRESH_OPPOSING_M1_CHOCH", v["advisory"]["wait_reasons"])
        self.assertTrue(
            any(
                c["reason_code"] == "FRESH_OPPOSING_M1_CHOCH"
                for c in v["confluence"]["conflicts"]
            )
        )

    def test_unknown_session_stays_unknown(self):
        c, _ = reports()
        v = self.safe(build_market_view_v3(c))
        self.assertIsNone(v["restrictions"]["session"])
        self.assertEqual(v["restrictions"]["calendar_qualification"], "UNKNOWN")
        self.assertIn("SESSION_SNAPSHOT_UNAVAILABLE", v["advisory"]["wait_reasons"])

    def test_actual_exness_calendar_stays_blocked_and_unchanged(self):
        p = Path("config/profiles/exness-xauusd-v2.candidate.json")
        before = p.read_bytes()
        calendar = compile_session_config(json.loads(before))
        c, _ = reports()
        session = calendar.public_state(
            __import__("iat.replay_dataset", fromlist=["utc"]).utc(c.analysis_at)
        )
        v = self.safe(build_market_view_v3(c, session_snapshot=session))
        self.assertEqual(v["status"], "BLOCKED")
        self.assertEqual(v["restrictions"]["session"], json.loads(json.dumps(session)))
        self.assertEqual(v["restrictions"]["calendar_qualification"], "BLOCKED")
        self.assertEqual(p.read_bytes(), before)

    def test_stale_bars_are_quarantined(self):
        a, b, at = two_frames()
        c = context_at(
            "SYNTHETIC_XAUUSD",
            a,
            b,
            at + timedelta(hours=1),
            config=CONFIG,
            intelligence_config=P7,
        )
        v = self.safe(build_market_view_v3(c))
        self.assertEqual(v["status"], "BLOCKED")
        self.assertEqual(v["confluence"]["evidence_index"], [])
        self.assertEqual(
            v["advisory"]["selected_hypothesis"], c.confluence["selected_hypothesis"]
        )
        self.assertEqual(v["advisory"]["upstream_signal"], c.signal)
        self.assertTrue(any("STALE" in r for r in v["advisory"]["wait_reasons"]))

    def test_warmup_restrictions_are_explicit(self):
        a, b, at = two_frames()
        c = context_at(
            "SYNTHETIC_XAUUSD",
            a[-3:],
            b[-3:],
            at,
            config=CONFIG,
            intelligence_config=P7,
        )
        v = self.safe(build_market_view_v3(c))
        self.assertEqual(v["market_state"]["regime"], "UNKNOWN")
        self.assertIn("INSUFFICIENT_STRUCTURAL_CONTEXT", v["restrictions"]["warmup"])

    def test_missing_liquidity_and_zones_are_unavailable_not_confirmations(self):
        a, b, at = two_frames()
        from test_intelligence_patterns import rows
        from iat.replay_dataset import utc

        sample = rows([100, 101, 102])
        c = context_at(
            "SYNTHETIC_XAUUSD",
            sample,
            None,
            utc(sample[-1]["timestamp"]) + timedelta(minutes=1),
            config=CONFIG,
            intelligence_config=P7,
        )
        v = self.safe(build_market_view_v3(c))
        self.assertEqual(v["liquidity"]["pools"]["status"], "UNAVAILABLE")
        self.assertEqual(
            v["price_structure"]["support_resistance"]["status"], "UNAVAILABLE"
        )
        self.assertEqual(v["price_structure"]["supply_demand"]["items"], [])

    def test_supplied_adaptive_and_scenario_reports_bind_exactly(self):
        c, _ = reports()
        v = self.safe(build_market_view_v3(c, assess_adaptive(c), assess_scenarios(c)))
        self.assertEqual(v, build_market_view_v3(c))
        other, _ = reports(True)
        for options in (
            {"adaptive_report": assess_adaptive(other)},
            {"scenario_report": assess_scenarios(other)},
        ):
            self.assertEqual(
                self.safe(build_market_view_v3(c, **options))["status"], "BLOCKED"
            )

    def test_wrong_v1_symbol_time_configuration_or_frames_blocks(self):
        c, i = reports()
        other, _ = reports(True)
        for bad in (
            replace(i, symbol="OTHER"),
            replace(i, analysis_at=other.analysis_at + "Z"),
            replace(i, configuration_sha256="0" * 64),
            replace(i, frames={}),
        ):
            self.assertEqual(
                self.safe(build_market_view_v3(c, intelligence_report=bad))["status"],
                "BLOCKED",
            )

    def test_bad_session_cutoff_or_execution_claim_is_blocked(self):
        c, _ = reports()
        calendar = compile_session_config(
            json.loads(
                Path("config/profiles/exness-xauusd-v2.candidate.json").read_text()
            )
        )
        from iat.replay_dataset import utc

        s = calendar.public_state(utc(c.analysis_at))
        for bad in (
            dict(s, evaluated_at_utc="2099-01-01T00:00:00Z"),
            dict(s, permissions=dict(s["permissions"], iat_execution_allowed=True)),
            {},
        ):
            self.assertEqual(
                self.safe(build_market_view_v3(c, session_snapshot=bad))["status"],
                "BLOCKED",
            )

    def test_qualification_input_cannot_self_approve(self):
        c, _ = reports()
        for q in ({"qualification": "DATA_QUALIFIED"}, dict(SAFETY, exness="APPROVED")):
            self.assertEqual(
                self.safe(build_market_view_v3(c, qualification_snapshot=q))["status"],
                "BLOCKED",
            )
        self.safe(build_market_view_v3(c, qualification_snapshot=SAFETY))

    def test_invalid_none_future_and_nonfinite_context_fail_closed(self):
        c, _ = reports()
        for bad in (
            None,
            {},
            [],
            object(),
            replace(c, analysis_at="2000-01-01T00:00:00Z"),
            replace(c, confluence=dict(c.confluence, scores={"BULLISH": float("nan")})),
        ):
            self.assertEqual(self.safe(build_market_view_v3(bad))["status"], "BLOCKED")

    def test_duplicate_evidence_does_not_inflate_scores_or_ids(self):
        c, _ = reports()
        duplicated = replace(c, evidence=c.evidence + c.evidence)
        self.assertEqual(build_market_view_v3(c), build_market_view_v3(duplicated))
        bad = replace(
            c,
            evidence=c.evidence
            + (
                replace(
                    c.evidence[0],
                    direction=(
                        "BEARISH" if c.evidence[0].direction != "BEARISH" else "BULLISH"
                    ),
                ),
            ),
        )
        self.assertEqual(self.safe(build_market_view_v3(bad))["status"], "BLOCKED")

    def test_inconsistent_liquidity_detail_is_rejected(self):
        c, _ = reports()
        raw = deepcopy(c.interpretations)
        pools = raw["frames"]["M1"]["liquidity_pools"]
        self.assertTrue(pools)
        raw["frames"]["M1"]["liquidity_pools"] = (
            replace(pools[0], level=pools[0].level + 99),
        ) + tuple(pools[1:])
        v = self.safe(build_market_view_v3(replace(c, interpretations=raw)))
        self.assertEqual(v["status"], "BLOCKED")

    def test_future_append_and_unfinished_m5_do_not_change_prior_view(self):
        a, b, at = two_frames()
        options = dict(config=CONFIG, intelligence_config=P7)
        before = build_market_view_v3(
            context_at("SYNTHETIC_XAUUSD", a, b, at, **options)
        )
        future = dict(timestamp=at.isoformat(), open=100, high=999, low=1, close=998)
        a.append(future)
        b.append(
            dict(
                future, timestamp=(at.replace(minute=(at.minute // 5) * 5)).isoformat()
            )
        )
        after = build_market_view_v3(
            context_at("SYNTHETIC_XAUUSD", a, b, at, **options)
        )
        self.assertEqual(before, after)
        direct = analyze_context("SYNTHETIC_XAUUSD", a, b, at, **options)
        self.assertEqual(self.safe(build_market_view_v3(direct))["status"], "BLOCKED")

    def test_repeatability_prefix_equivalence_and_hashes(self):
        a, b, at = two_frames()

        def replay(one, five, cutoff):
            out = []
            for row in one:
                from iat.replay_dataset import utc

                t = utc(row["timestamp"]) + timedelta(minutes=1)
                if t <= cutoff:
                    out.append(
                        build_market_view_v3(
                            context_at(
                                "SYNTHETIC_XAUUSD",
                                one,
                                five,
                                t,
                                config=CONFIG,
                                intelligence_config=P7,
                            )
                        )
                    )
            return out

        full = replay(a, b, at)
        self.assertEqual(full, replay(a, b, at))
        cutoff = at - timedelta(minutes=2)
        from iat.replay_dataset import utc

        prefix_a = [
            r for r in a if utc(r["timestamp"]) + timedelta(minutes=1) <= cutoff
        ]
        prefix_b = [
            r for r in b if utc(r["timestamp"]) + timedelta(minutes=5) <= cutoff
        ]
        prefix = replay(prefix_a, prefix_b, cutoff)
        self.assertEqual(full[: len(prefix)], prefix)
        self.assertEqual(digest(full), digest(replay(a, b, at)))

    def test_no_mutation_and_v1_compatibility(self):
        c, i = reports()
        before = (
            deepcopy(c.to_dict()),
            deepcopy(i.to_dict()),
            assess_scenarios(c),
            assess_adaptive(c),
        )
        v = build_market_view_v3(c, intelligence_report=i)
        v["confluence"]["sources"].clear()
        self.assertEqual(
            before, (c.to_dict(), i.to_dict(), assess_scenarios(c), assess_adaptive(c))
        )
        fresh_c, fresh_i = reports()
        self.assertEqual(c.to_dict(), fresh_c.to_dict())
        self.assertEqual(i.to_dict(), fresh_i.to_dict())

    def test_serialized_tampering_and_rechecksummed_safety_are_rejected(self):
        c, _ = reports()
        v = build_market_view_v3(c)
        for change in (
            {"signal": "BUY"},
            {"execution_allowed": True},
            {"qualification": "DATA_QUALIFIED"},
            {"report_version": 2},
            {"unexpected": True},
        ):
            bad = dict(v, **change)
            bad["sha256"] = digest({k: x for k, x in bad.items() if k != "sha256"})
            with self.assertRaises((ValueError, TypeError)):
                validate_market_view_v3(bad)
            with self.assertRaises(ValidationError):
                self.validator.validate(bad)
        bad = deepcopy(v)
        bad["confluence"]["scores"]["scores"]["BULLISH"] += 1
        bad["sha256"] = digest({k: x for k, x in bad.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_market_view_v3(bad, context_report=c)

    def test_bound_validation_rejects_future_source_even_after_rehash(self):
        c, _ = reports()
        v = build_market_view_v3(c)
        next(iter(v["confluence"]["sources"].values()))[
            "available_at"
        ] = "2099-01-01T00:00:00Z"
        v["sha256"] = digest({k: x for k, x in v.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_market_view_v3(v)

    def test_no_unsupported_confidence_execution_levels_or_order_dependencies(self):
        c, i = reports()
        v = self.safe(build_market_view_v3(c, intelligence_report=i))

        def visit(value):
            if isinstance(value, dict):
                self.assertFalse(
                    {
                        "entry_price",
                        "stop_loss",
                        "take_profit",
                        "probability",
                        "order_request",
                    }
                    & set(value)
                )
                for x in value.values():
                    visit(x)
            elif isinstance(value, list):
                for x in value:
                    visit(x)

        visit(v)
        code = Path("iat/intelligence/market_view.py").read_text()
        self.assertNotIn("MetaTrader5", code)
        self.assertNotIn("order_send", code)

    def test_synthetic_declared_session_preserves_upstream_but_cannot_bind_calendar(
        self,
    ):
        from test_session_v2 import synthetic_v2
        from iat.replay_dataset import utc

        raw = synthetic_v2()
        raw["symbol"] = "SYNTHETIC_XAUUSD"
        calendar = compile_session_config(raw)
        for choch, expected in ((False, "ASSESSED"), (True, "ABSTAINED")):
            c, i = reports(choch=choch, calendar=calendar, observed_finality=True)
            snapshot = calendar.public_state(utc(c.analysis_at))
            adaptive = assess_adaptive(c, session_sha256=calendar.configuration_sha256)
            v = self.safe(
                build_market_view_v3(
                    c,
                    adaptive_report=adaptive,
                    session_snapshot=snapshot,
                    intelligence_report=i,
                )
            )
            self.assertEqual(v["status"], "UNKNOWN", v["restrictions"])
            self.assertIn(
                "SESSION_CONTEXT_BINDING_UNESTABLISHED", v["advisory"]["wait_reasons"]
            )
            self.assertEqual(
                v["advisory"]["selected_hypothesis"],
                c.confluence["selected_hypothesis"],
            )
            self.assertEqual(v["qualification"], "DATA_NOT_QUALIFIED")
            self.assertEqual(v["exness"], "BLOCKED")

    def test_quote_only_and_close_only_snapshots_remain_restricted(self):
        from test_session_v2 import synthetic_v2
        from iat.replay_dataset import utc

        c, _ = reports()
        calendar = compile_session_config(synthetic_v2())
        for phase in ("QUOTE_ONLY", "CLOSE_ONLY", "CLOSED", "UNKNOWN"):
            snapshot = calendar.public_state(utc(c.analysis_at))
            snapshot["permissions"]["phase"] = phase
            pairs = {
                "QUOTE_ONLY": (False, False),
                "CLOSE_ONLY": (False, True),
                "CLOSED": (False, False),
                "UNKNOWN": (None, None),
            }
            (
                snapshot["permissions"]["broker_open_positions"],
                snapshot["permissions"]["broker_close_positions"],
            ) = pairs[phase]
            snapshot["permissions"]["broker_permissions_verified"] = phase != "UNKNOWN"
            v = self.safe(build_market_view_v3(c, session_snapshot=snapshot))
            self.assertEqual(
                v["status"], "UNKNOWN" if phase == "UNKNOWN" else "BLOCKED"
            )
            self.assertFalse(v["execution_allowed"])

    def test_serialized_future_zone_and_null_selection_rejected_after_rehash(self):
        c, _ = reports()
        for change in ("zone", "selection"):
            v = build_market_view_v3(c)
            if change == "zone":
                v["price_structure"]["support_resistance"]["items"].append(
                    {"confirmed_at": "2099-01-01T00:00:00Z"}
                )
            else:
                v["advisory"]["selected_hypothesis"] = None
                for h in v["advisory"]["ranked_hypotheses"]:
                    h["selected_by_context"] = False
            v["sha256"] = digest({k: x for k, x in v.items() if k != "sha256"})
            with self.assertRaises(ValueError):
                validate_market_view_v3(v)

    def test_frozen_synthetic_example_records_stable_full_view_hash(self):
        c, i = reports()
        v = build_market_view_v3(c, intelligence_report=i)
        example = json.loads(
            Path("docs/research_audits/market-view-v3.synthetic.json").read_text()
        )
        self.assertEqual(example["provenance"], "SYNTHETIC_RESEARCH")
        self.assertEqual(example["full_view_sha256"], v["sha256"])
        self.assertEqual(
            example["confluence_scores"], v["confluence"]["scores"]["scores"]
        )
