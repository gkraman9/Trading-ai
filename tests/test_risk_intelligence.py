"""Independent synthetic E3 geometry and adversarial source/availability tests."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
import json, unittest
from unittest.mock import patch
from risk_fixtures import sources, snapshot, START, CONFIG
from iat.intelligence.risk_intelligence import (
    assess_risk,
    validate_risk_report,
    reference_geometry,
    RiskPolicy,
    LIMITS,
    NULL_FIELDS,
    cost_availability,
)
from iat.intelligence.entry_intelligence import EntryResearchSession
from iat.intelligence.exit_intelligence import ExitResearchSession, ExitPolicy
from iat.intelligence.strategy_replay import digest


class RiskIntelligenceTests(unittest.TestCase):
    def inputs(self, mirror=False, one=None, five=None, exit_policy=None):
        s, o, e, oe, a, b = sources(
            mirror=mirror, one=one, five=five, policy=exit_policy
        )
        v, c, i = snapshot(36, one=a, five=b)
        current = e.record(v, c, view_inputs=i)
        self.assertEqual(current["source_eligibility"], "VALID")
        return (
            dict(
                original_e1=o,
                original_e2=oe,
                current_e2=current,
                entry_source=s,
                exit_source=e,
                as_of=c.analysis_at,
                context=c,
                view=v,
                view_inputs=i,
                policy=RiskPolicy(atr_timeframe="M1"),
            ),
            a,
            b,
        )

    def assess(self, k):
        r = assess_risk(**k)
        self.assertTrue(validate_risk_report(json.loads(json.dumps(r)), **k))
        self.safe(r)
        return r

    def safe(self, r):
        self.assertEqual(r["signal"], "WAIT")
        self.assertIs(r["execution_allowed"], False)
        self.assertEqual(r["qualification"], "DATA_NOT_QUALIFIED")
        self.assertEqual(r["exness"], "BLOCKED")
        self.assertEqual(r["historical_validation"], "PENDING")
        self.assertEqual(r["historical_comparisons"], "NOT_RUN")
        for f in NULL_FIELDS:
            self.assertIsNone(r[f])
        self.assertNotIn("TRADE_APPROVED", r["states"])
        self.assertNotIn("confidence", r)

    def test_bullish_reference_geometry_is_not_fill_risk(self):
        k, a, b = self.inputs()
        r = self.assess(k)
        g = r["reference_geometry"]
        z = r["frozen_invalidation"]
        self.assertEqual(r["source_eligibility"], "VALID")
        self.assertEqual(g["basis"], "REFERENCE_RR_ONLY")
        self.assertEqual(
            g["invalidation_threshold"], str(z["lower"] - z["break_tolerance"])
        )
        self.assertEqual(g["risk_distance"], "2.26")
        self.assertEqual(g["units"], "INSTRUMENT_PRICE_UNITS")

    def test_bearish_reference_geometry(self):
        k, a, b = self.inputs(mirror=True)
        r = self.assess(k)
        g = r["reference_geometry"]
        z = r["frozen_invalidation"]
        self.assertEqual(
            g["invalidation_threshold"], str(z["upper"] + z["break_tolerance"])
        )
        self.assertGreater(Decimal(g["reward_distance"]), 0)
        self.assertEqual(r["research_direction"], "BEARISH")

    def test_isolated_illustrative_bullish_arithmetic_2_6_3(self):
        g = reference_geometry("BULLISH", 2100, 2098.01, 2098.11, 0.01, 2106)
        self.assertEqual(
            (g["risk_distance"], g["reward_distance"], g["reward_to_risk"]),
            ("2", "6", "3"),
        )
        self.assertEqual(g["authentication"], "NOT_ESTABLISHED_BY_ARITHMETIC")

    def test_isolated_illustrative_bearish_arithmetic_2_6_3(self):
        g = reference_geometry("BEARISH", 2100, 2101.89, 2101.99, 0.01, 2094)
        self.assertEqual(
            (g["risk_distance"], g["reward_distance"], g["reward_to_risk"]),
            ("2", "6", "3"),
        )

    def test_strict_original_float_threshold_not_rationalized(self):
        low = 2097.7999999999997
        g = reference_geometry("BULLISH", 2100, low, low + 0.1, 0.01, 2106)
        self.assertEqual(g["invalidation_threshold"], str(low - 0.01))
        self.assertEqual(g["breach_semantics"], "STRICT_ELIGIBLE_CLOSE_BELOW_THRESHOLD")

    def test_invalid_direction_zero_negative_and_nonfinite_geometry(self):
        cases = [
            ("BULLISH", 2098, 2098, 2098.1, 0, 2106),
            ("BULLISH", 2097, 2098, 2098.1, 0, 2106),
            ("BULLISH", 2100, 2098, 2098.1, 0, 2099),
            ("BEARISH", 2100, 2098, 2098.1, 0, 2094),
            ("UP", 2100, 2098, 2098.1, 0, 2106),
            ("BULLISH", 2100, None, 2098.1, 0.01, 2106),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                reference_geometry(*args)
        for value in (
            float("nan"),
            float("inf"),
            float("-inf"),
            True,
            "1e999999999",
            Decimal("NaN"),
        ):
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                reference_geometry("BULLISH", value, 2098, 2098.1, 0.01, 2106)

    def test_deterministic_arithmetic_ignores_ambient_decimal_precision(self):
        expected = reference_geometry("BULLISH", 2100, 2098, 2098.1, 0.01, 2106)
        with localcontext() as ctx:
            ctx.prec = 2
            actual = reference_geometry("BULLISH", 2100, 2098, 2098.1, 0.01, 2106)
        self.assertEqual(actual, expected)

    def test_missing_target_retains_risk_but_no_reward_or_ratio(self):
        from risk_fixtures import fixture

        a, b = fixture()
        a[34].update(close=2107, high=2107.2)
        k, a, b = self.inputs(one=a, five=b)
        r = self.assess(k)
        self.assertIn("TARGET_UNAVAILABLE", r["states"])
        self.assertIsNone(r["reference_geometry"]["reward_to_risk"])
        self.assertGreater(Decimal(r["reference_geometry"]["risk_distance"]), 0)

    def test_near_boundary_geometry_keeps_far_boundary_and_exit_policy(self):
        for mode in ("WICK_CONTACT", "CLOSE_BEYOND_REFERENCE"):
            k, a, b = self.inputs(exit_policy=ExitPolicy(target_observation=mode))
            r = self.assess(k)
            self.assertEqual(r["frozen_target"], k["original_e2"]["frozen_target"])
            near = Decimal(str(r["frozen_target"]["lower"]))
            c = Decimal(str(r["confirmation_reference"]["value"]))
            self.assertEqual(
                Decimal(r["reference_geometry"]["reward_distance"]), near - c
            )
            self.assertEqual(
                r["bindings"]["exit_policy"], digest(k["original_e2"]["exit_policy"])
            )

    def test_no_rr_threshold_approval_or_ranking(self):
        k, a, b = self.inputs()
        r = self.assess(k)
        self.assertEqual(
            r["research_eligibility"], "REFERENCE_RESEARCH_ONLY_NOT_TRADE_SUITABILITY"
        )
        self.assertNotIn("selected_opportunity", r)
        self.assertIn("COST_MODEL_UNAVAILABLE", r["states"])

    def test_selected_source_bound_m1_atr(self):
        k, a, b = self.inputs()
        r = self.assess(k)
        v = r["volatility"]
        self.assertEqual(v["timeframe"], "M1")
        self.assertEqual(v["atr_period"], CONFIG.atr_period)
        self.assertEqual(
            v["atr_value"],
            str(k["context"].interpretations["frames"]["M1"]["volatility"]["atr"]),
        )
        self.assertEqual(
            v["available_at_utc"], k["context"].observed_facts["M1"]["data_as_of"]
        )
        self.assertIn(v["evidence_id"], r["supporting_evidence"])

    def test_m5_atr_is_explicitly_separate_not_mixed(self):
        k, a, b = self.inputs()
        k["policy"] = RiskPolicy(atr_timeframe="M5")
        r = self.assess(k)
        self.assertEqual(r["volatility"]["timeframe"], "M5")
        self.assertEqual(
            r["volatility"]["available_at_utc"],
            k["context"].observed_facts["M5"]["data_as_of"],
        )

    def test_missing_atr_or_unselected_timeframe_stays_unavailable(self):
        k, a, b = self.inputs()
        for change in ("no_source", "no_selection"):
            q = dict(k)
            if change == "no_source":
                q["context"] = q["view"] = None
            else:
                q["policy"] = RiskPolicy()
            r = self.assess(q)
            self.assertEqual(r["volatility"]["status"], "VOLATILITY_UNAVAILABLE")

    def test_unsupported_atr_timeframe_and_future_evidence_rejected(self):
        with self.assertRaises(ValueError):
            RiskPolicy(atr_timeframe="H1")
        k, a, b = self.inputs()
        c = k["context"]
        evidence = list(c.evidence)
        idx = next(
            i
            for i, e in enumerate(evidence)
            if e.category == "VOLATILITY" and e.timeframe == "M1"
        )
        evidence[idx] = replace(
            evidence[idx], available_at=(START + timedelta(minutes=100)).isoformat()
        )
        k["context"] = replace(c, evidence=tuple(evidence))
        self.assertEqual(self.assess(k)["source_eligibility"], "BLOCKED")

    def test_edited_atr_values_and_symbol_are_not_source_authentic(self):
        k, a, b = self.inputs()
        c = k["context"]
        frames = deepcopy(c.interpretations)
        frames["frames"]["M1"]["volatility"]["atr"] = 999
        k["context"] = replace(c, interpretations=frames)
        self.assertEqual(self.assess(k)["source_eligibility"], "BLOCKED")
        k, a, b = self.inputs()
        k["context"] = replace(k["context"], symbol="OTHER")
        self.assertEqual(self.assess(k)["source_eligibility"], "BLOCKED")

    def test_supplied_unused_context_is_still_authenticated(self):
        k, a, b = self.inputs()
        k["policy"] = RiskPolicy()
        k["context"] = replace(k["context"], symbol="OTHER")
        self.assertEqual(self.assess(k)["source_eligibility"], "BLOCKED")

    def test_default_costs_never_become_implicit_zero(self):
        k, a, b = self.inputs()
        r = self.assess(k)
        for key in (
            "spread",
            "commission",
            "slippage",
            "contract_size",
            "tick_value",
            "currency_conversion",
            "swap",
        ):
            self.assertIsNone(r["costs"]["fields"][key]["value"])
        self.assertFalse(r["costs"]["qualified_model_available"])

    def declaration(self, k):
        return dict(
            version=1,
            provenance="SYNTHETIC_RESEARCH_DECLARATION",
            symbol=k["original_e1"]["symbol"],
            e2_sha256=k["current_e2"]["sha256"],
            quote_at_utc=k["as_of"],
            quote_available_at_utc=k["as_of"],
            price_basis="BID_ASK",
            bid="2100.1",
            ask="2100.3",
            spread="0.2",
            commission="0",
            slippage=None,
            contract_size=None,
            units=dict(
                bid="INSTRUMENT_PRICE_UNITS",
                ask="INSTRUMENT_PRICE_UNITS",
                spread="INSTRUMENT_PRICE_UNITS",
                commission="ACCOUNT_CURRENCY",
            ),
        )

    def test_mechanically_valid_synthetic_costs_still_not_qualified_model(self):
        k, a, b = self.inputs()
        k["costs"] = self.declaration(k)
        r = self.assess(k)
        cost = r["costs"]
        self.assertEqual(cost["status"], "DECLARED_SYNTHETIC_NOT_QUALIFIED")
        self.assertFalse(cost["qualified_model_available"])
        self.assertEqual(cost["fields"]["commission"]["value"], "0")
        self.assertIsNone(cost["fields"]["slippage"]["value"])
        self.assertIsNone(r["net_risk_reward"])
        self.assertIsNone(r["position_size"])

    def test_bad_spread_or_unknown_units_are_not_validated_costs(self):
        k, a, b = self.inputs()
        for changes in (
            dict(spread="0.1"),
            dict(commission="NaN"),
            dict(bid=True),
            dict(price_basis="BID"),
            dict(units={"spread": "BOGUS"}),
        ):
            q = dict(k)
            q["costs"] = dict(self.declaration(k), **changes)
            self.assertEqual(self.assess(q)["costs"]["status"], "INVALID_DECLARATION")

    def test_cost_unknown_contract_and_currency_remain_unavailable(self):
        k, a, b = self.inputs()
        k["costs"] = self.declaration(k)
        r = self.assess(k)
        self.assertIsNone(r["costs"]["fields"]["account_currency"]["value"])
        self.assertIsNone(r["costs"]["fields"]["contract_size"]["value"])
        self.assertIn("DO_NOT_ADD_AGAIN", r["costs"]["spread_application"])

    def test_future_cost_quote_is_invalid_not_geometry_input(self):
        k, a, b = self.inputs()
        k["costs"] = self.declaration(k)
        k["costs"]["quote_available_at_utc"] = (
            START + timedelta(minutes=99)
        ).isoformat()
        r = self.assess(k)
        self.assertEqual(r["costs"]["status"], "INVALID_DECLARATION")
        self.assertEqual(r["source_eligibility"], "VALID")

    def test_cost_symbol_or_e2_binding_mismatch_blocks_projection(self):
        k, a, b = self.inputs()
        for changes in (dict(symbol="OTHER"), dict(e2_sha256="0" * 64)):
            q = dict(k)
            q["costs"] = dict(self.declaration(k), **changes)
            r = self.assess(q)
            self.assertIn("SOURCE_MISMATCH", r["states"])
            self.assertIsNone(r["reference_geometry"])

    def test_forged_e1_and_e2_reports_with_recomputed_hashes_block(self):
        k, a, b = self.inputs()
        for field in ("original_e1", "original_e2", "current_e2"):
            q = dict(k)
            q[field] = deepcopy(q[field])
            q[field]["confidence"] = 0.99
            q[field]["sha256"] = digest(
                {a: b for a, b in q[field].items() if a != "sha256"}
            )
            self.assertEqual(self.assess(q)["source_eligibility"], "BLOCKED")

    def test_wrong_producers_and_missing_sources_block(self):
        k, a, b = self.inputs()
        for change in (
            dict(entry_source=EntryResearchSession()),
            dict(exit_source=ExitResearchSession()),
            dict(entry_source=None),
            dict(exit_source=None),
        ):
            self.assertEqual(
                self.assess(dict(k, **change))["source_eligibility"], "BLOCKED"
            )

    def test_mismatched_setup_id_direction_and_configuration_block(self):
        k, a, b = self.inputs()
        self.assertEqual(
            self.assess(dict(k, setup_id="OTHER"))["source_eligibility"], "BLOCKED"
        )
        for field, mutator in (
            ("original_e1", lambda r: r.update(symbol="OTHER")),
            (
                "original_e2",
                lambda r: r["original"].update(research_direction="BEARISH"),
            ),
            (
                "current_e2",
                lambda r: r["bindings"]["configurations"].update(context="0" * 64),
            ),
        ):
            q = dict(k)
            r = deepcopy(q[field])
            mutator(r)
            r["sha256"] = digest({a: b for a, b in r.items() if a != "sha256"})
            q[field] = r
            self.assertEqual(self.assess(q)["source_eligibility"], "BLOCKED")

    def test_wrong_exit_policy_session_cannot_supply_current(self):
        k, a, b = self.inputs()
        other = ExitResearchSession(
            k["original_e1"],
            k["original_e2"]["original"]["setup_id"],
            entry_source=k["entry_source"],
            policy=ExitPolicy(target_observation="CLOSE_BEYOND_REFERENCE"),
        )
        v, c, i = snapshot(36, one=a, five=b)
        k["current_e2"] = other.record(v, c, view_inputs=i)
        self.assertEqual(self.assess(k)["source_eligibility"], "BLOCKED")

    def test_later_e2_report_cannot_replace_original_cutoff(self):
        k, a, b = self.inputs()
        k["original_e2"] = k["current_e2"]
        self.assertEqual(self.assess(k)["source_eligibility"], "BLOCKED")

    def test_invalidated_hypothesis_keeps_historical_geometry_not_trade_suitability(
        self,
    ):
        k, a, b = self.inputs()
        a[36].update(close=2097, low=2096.9)
        v, c, i = snapshot(37, one=a, five=b)
        k.update(
            current_e2=k["exit_source"].record(v, c, view_inputs=i),
            as_of=c.analysis_at,
            context=c,
            view=v,
            view_inputs=i,
        )
        r = self.assess(k)
        self.assertIn("HYPOTHESIS_INVALIDATED", r["states"])
        self.assertIsNotNone(r["reference_geometry"])

    def test_expired_hypothesis_is_visible_without_fill(self):
        k, a, b = self.inputs()
        for n in range(37, 41):
            v, c, i = snapshot(n, one=a, five=b)
            current = k["exit_source"].record(v, c, view_inputs=i)
        k.update(
            current_e2=current, as_of=c.analysis_at, context=c, view=v, view_inputs=i
        )
        self.assertIn("HYPOTHESIS_EXPIRED", self.assess(k)["states"])

    def test_ambiguous_exit_is_preserved_without_pnl(self):
        s, o, e, oe, a, b = sources()
        a[35].update(high=2106.5, low=2097, close=2097.1)
        v, c, i = snapshot(36, one=a, five=b)
        current = e.record(v, c, view_inputs=i)
        k = dict(
            original_e1=o,
            original_e2=oe,
            current_e2=current,
            entry_source=s,
            exit_source=e,
            as_of=c.analysis_at,
        )
        r = self.assess(k)
        self.assertIn("OBSERVATION_ORDER_UNRESOLVED", r["states"])
        self.assertEqual(r["ambiguity"], current["ambiguity"])

    def test_blocked_current_source_does_not_reuse_old_geometry(self):
        k, a, b = self.inputs()
        bad = a[:10] + a[11:]
        v, c, i = snapshot(37, one=bad, five=b)
        k["current_e2"] = k["exit_source"].record(v, c, view_inputs=i)
        r = self.assess(k)
        self.assertEqual(r["source_eligibility"], "BLOCKED")
        self.assertIsNone(r["reference_geometry"])

    def test_current_cutoff_is_required_and_must_match(self):
        k, a, b = self.inputs()
        for cutoff in (
            None,
            START + timedelta(minutes=35),
            START + timedelta(minutes=37),
        ):
            self.assertEqual(
                self.assess(dict(k, as_of=cutoff))["source_eligibility"], "BLOCKED"
            )

    def test_provenance_labels_cannot_create_authenticated_original(self):
        k, a, b = self.inputs()
        for provenance in ("VALIDATED_LIVE", "HISTORICAL_RESEARCH"):
            q = dict(k)
            o = deepcopy(k["original_e1"])
            o["provenance"] = provenance
            o["sha256"] = digest({a: b for a, b in o.items() if a != "sha256"})
            q["original_e1"] = o
            self.assertEqual(self.assess(q)["source_eligibility"], "BLOCKED")

    def test_repeatability_and_reverification_need_actual_sources(self):
        k, a, b = self.inputs()
        r = self.assess(k)
        self.assertEqual(r, self.assess(k))
        with self.assertRaises(ValueError):
            validate_risk_report(r)
        bad = dict(r, position_size="0.1")
        bad["sha256"] = digest({a: b for a, b in bad.items() if a != "sha256"})
        with self.assertRaises(ValueError):
            validate_risk_report(bad, **k)

    def test_no_mutation_or_duplicate_lifecycle_storage(self):
        k, a, b = self.inputs()
        before = (
            k["entry_source"].sr_log(),
            k["exit_source"].report(),
            deepcopy(k["original_e1"]),
        )
        r = self.assess(k)
        r["target_candidates"].clear()
        self.assertEqual(
            before,
            (k["entry_source"].sr_log(), k["exit_source"].report(), k["original_e1"]),
        )

    def test_previous_projection_verifies_after_future_append(self):
        k, a, b = self.inputs()
        r = self.assess(k)
        frozen = deepcopy(r)
        v, c, i = snapshot(37, one=a, five=b)
        k["exit_source"].record(v, c, view_inputs=i)
        self.assertEqual(r, frozen)
        self.assertTrue(validate_risk_report(r, **k))

    def test_full_prefix_future_append_invariance(self):
        k, a, b = self.inputs()
        r = self.assess(k)
        short_a = [
            x for x in a if x["timestamp"] < (START + timedelta(minutes=36)).isoformat()
        ]
        short_b = [
            x for x in b if x["timestamp"] < (START + timedelta(minutes=35)).isoformat()
        ]
        q, a2, b2 = self.inputs(one=short_a, five=short_b)
        self.assertEqual(r, self.assess(q))

    def test_resource_limits_are_explicit_stateless_failures(self):
        k, a, b = self.inputs()
        before = k["exit_source"].report()
        for change in (
            dict(max_candidates=0),
            dict(max_report_bytes=1),
            dict(max_sources=0),
        ):
            with patch.dict(LIMITS, **change):
                self.assertEqual(self.assess(k)["source_eligibility"], "BLOCKED")
        self.assertEqual(before, k["exit_source"].report())
        self.assertEqual(self.assess(k)["source_eligibility"], "VALID")

    def test_injected_calculation_failure_never_mutates_sources(self):
        k, a, b = self.inputs()
        before = k["exit_source"].report()
        with patch(
            "iat.intelligence.risk_intelligence.reference_geometry",
            side_effect=ValueError("secret"),
        ):
            r = self.assess(k)
        self.assertEqual(r["source_eligibility"], "BLOCKED")
        self.assertNotIn("secret", str(r))
        self.assertEqual(before, k["exit_source"].report())

    def test_frozen_synthetic_examples_are_repeatable(self):
        from risk_examples import examples
        from pathlib import Path

        self.assertEqual(
            examples(),
            json.loads(
                Path("docs/research_audits/risk-intelligence.synthetic.json").read_text(
                    encoding="utf-8"
                )
            ),
        )

    def test_zero_or_insufficient_current_atr_stays_unavailable(self):
        k, a, b = self.inputs()
        for row in a[36:]:
            row.update(open=2100, high=2100, low=2100, close=2100)
        v, c, i = snapshot(52, one=a, five=b)
        current = k["exit_source"].record(v, c, view_inputs=i)
        k.update(
            current_e2=current, as_of=c.analysis_at, context=c, view=v, view_inputs=i
        )
        r = self.assess(k)
        self.assertEqual(r["volatility"]["status"], "VOLATILITY_UNAVAILABLE")

    def test_unknown_cost_units_do_not_become_qualified_units(self):
        k, a, b = self.inputs()
        k["costs"] = self.declaration(k)
        k["costs"].pop("units")
        r = self.assess(k)
        self.assertEqual(
            r["costs"]["fields"]["spread"]["status"], "DECLARED_UNITS_UNAVAILABLE"
        )
        self.assertFalse(r["costs"]["qualified_model_available"])

    def test_target_replacement_is_not_authenticated_by_a_new_checksum(self):
        k, a, b = self.inputs()
        r = deepcopy(k["original_e2"])
        r["frozen_target"]["lower"] -= 1
        r["sha256"] = digest({a: b for a, b in r.items() if a != "sha256"})
        k["original_e2"] = r
        self.assertEqual(self.assess(k)["source_eligibility"], "BLOCKED")

    def test_session_restrictions_are_preserved_and_never_approved(self):
        from iat.session_config import load_session_config

        k, a, b = self.inputs()
        calendar = load_session_config(
            "config/profiles/exness-xauusd-v2.candidate.json"
        )
        v, c, i = snapshot(37, one=a, five=b, calendar=calendar, observed_finality=True)
        k.update(
            current_e2=k["exit_source"].record(v, c, view_inputs=i),
            as_of=c.analysis_at,
            context=c,
            view=v,
            view_inputs=i,
        )
        self.assertEqual(self.assess(k)["source_eligibility"], "BLOCKED")

    def test_exact_canonical_output_byte_budget(self):
        k, a, b = self.inputs()
        r = self.assess(k)
        size = len(
            json.dumps(
                r, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        )
        with patch.dict(LIMITS, max_report_bytes=size):
            self.assertEqual(r, self.assess(k))
        with patch.dict(LIMITS, max_report_bytes=size - 1):
            self.assertEqual(self.assess(k)["source_eligibility"], "BLOCKED")

    def test_no_broker_execution_ai_or_account_access(self):
        import ast
        from pathlib import Path

        tree = ast.parse(Path("iat/intelligence/risk_intelligence.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(
                    node.attr,
                    (
                        "order_send",
                        "order_check",
                        "initialize",
                        "login",
                        "account_info",
                    ),
                )
            if isinstance(node, ast.Import):
                self.assertFalse(
                    any(
                        x.name in ("MetaTrader5", "requests", "socket", "openai")
                        for x in node.names
                    )
                )


if __name__ == "__main__":
    unittest.main()
