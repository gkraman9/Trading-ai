"""E4 prerequisite: adversarial review of E3, not external human approval."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, localcontext, ROUND_UP
import json
import unittest
from risk_fixtures import sources, snapshot, START
from iat.intelligence.risk_intelligence import (
    assess_risk,
    validate_risk_report,
    reference_geometry,
    RiskPolicy,
)
from iat.intelligence.strategy_replay import digest


class IndependentE3Review(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s, o, e, oe, a, b = sources()
        v, c, i = snapshot(36, one=a, five=b)
        current = e.record(v, c, view_inputs=i)
        cls.inputs = dict(
            original_e1=o,
            original_e2=oe,
            current_e2=current,
            entry_source=s,
            exit_source=e,
            as_of=c.analysis_at,
        )
        cls.report = assess_risk(**cls.inputs)
        cls.assert_valid = cls.report["source_eligibility"] == "VALID"

    def test_authentication_requires_producers_not_rehashed_geometry(self):
        self.assertTrue(self.assert_valid)
        r = deepcopy(self.report)
        r["reference_geometry"]["risk_distance"] = "0.001"
        r["sha256"] = digest({k: v for k, v in r.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_risk_report(r, **self.inputs)
        with self.assertRaises(ValueError):
            validate_risk_report(self.report)

    def test_blocked_report_cannot_carry_geometry(self):
        r = assess_risk(None, None, None)
        self.assertTrue(validate_risk_report(r))
        r["reference_geometry"] = deepcopy(self.report["reference_geometry"])
        r["sha256"] = digest({k: v for k, v in r.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_risk_report(r)

    def test_frozen_original_and_current_bindings_cannot_be_replaced(self):
        for field in ("original_e1", "original_e2", "current_e2"):
            k = dict(self.inputs)
            k[field] = deepcopy(k[field])
            k[field]["symbol" if field == "original_e1" else "frozen_target"] = "forged"
            k[field]["sha256"] = digest(
                {a: b for a, b in k[field].items() if a != "sha256"}
            )
            self.assertEqual(assess_risk(**k)["source_eligibility"], "BLOCKED")

    def test_future_cutoff_and_naive_cutoff_fail_closed(self):
        for cutoff in (
            (START + timedelta(minutes=37)).isoformat(),
            "2026-11-12T15:36:00",
        ):
            self.assertEqual(
                assess_risk(**dict(self.inputs, as_of=cutoff))["source_eligibility"],
                "BLOCKED",
            )

    def test_different_session_history_is_rejected(self):
        other, _, exit, _, _, _ = sources(mirror=True)
        for field, value in (("entry_source", other), ("exit_source", exit)):
            self.assertEqual(
                assess_risk(**dict(self.inputs, **{field: value}))[
                    "source_eligibility"
                ],
                "BLOCKED",
            )

    def test_live_label_cannot_be_self_approved(self):
        k = dict(self.inputs)
        k["original_e1"] = deepcopy(k["original_e1"])
        k["original_e1"]["provenance"] = "LIVE_MT5"
        k["original_e1"]["sha256"] = digest(
            {a: b for a, b in k["original_e1"].items() if a != "sha256"}
        )
        self.assertEqual(assess_risk(**k)["source_eligibility"], "BLOCKED")

    def test_original_float_threshold_is_preserved_under_adversarial_context(self):
        with localcontext() as ctx:
            ctx.prec = 2
            ctx.rounding = ROUND_UP
            g = reference_geometry(
                "BULLISH", 2100, 2097.7999999999997, 2098, 0.01, 2106
            )
        self.assertEqual(g["invalidation_threshold"], str(2097.7999999999997 - 0.01))
        self.assertEqual(
            g["risk_distance"],
            str(Decimal("2100") - Decimal(g["invalidation_threshold"])),
        )

    def test_partial_cost_declaration_never_proves_cost_model(self):
        costs = dict(
            version=1,
            symbol=self.report["symbol"],
            e2_sha256=self.inputs["current_e2"]["sha256"],
            provenance="SYNTHETIC_RESEARCH_DECLARATION",
            commission=0,
        )
        r = assess_risk(**dict(self.inputs, costs=costs))
        self.assertIs(r["costs"]["qualified_model_available"], False)
        self.assertIsNone(r["net_risk_reward"])
        self.assertIsNone(r["costs"]["fields"]["slippage"]["value"])

    def test_future_cost_quote_does_not_erase_reference_but_is_unavailable(self):
        costs = dict(
            version=1,
            symbol=self.report["symbol"],
            e2_sha256=self.inputs["current_e2"]["sha256"],
            provenance="SYNTHETIC_RESEARCH_DECLARATION",
            bid=2100,
            ask=2101,
            price_basis="BID_ASK",
            quote_at_utc=(START + timedelta(minutes=37)).isoformat(),
            quote_available_at_utc=(START + timedelta(minutes=37)).isoformat(),
        )
        r = assess_risk(**dict(self.inputs, costs=costs))
        self.assertEqual(r["costs"]["status"], "INVALID_DECLARATION")
        self.assertEqual(r["source_eligibility"], "VALID")

    def test_tampered_safety_and_fill_fields_rejected_after_checksum(self):
        for field, value in (
            ("execution_allowed", True),
            ("entry_fill", 2100),
            ("position_size", 0.01),
            ("signal", "BUY"),
        ):
            r = deepcopy(self.report)
            r[field] = value
            r["sha256"] = digest({k: v for k, v in r.items() if k != "sha256"})
            with self.assertRaises(ValueError):
                validate_risk_report(r, **self.inputs)

    def test_prior_report_immutable_and_repeated_evaluation_identical(self):
        before = json.dumps(self.report, sort_keys=True)
        r = assess_risk(**self.inputs)
        self.assertEqual(r, self.report)
        r["frozen_invalidation"].clear()
        self.assertEqual(before, json.dumps(self.report, sort_keys=True))

    def test_unsupported_atr_policy_and_missing_pair_block(self):
        with self.assertRaises(ValueError):
            RiskPolicy(atr_timeframe="H1")
        self.assertEqual(
            assess_risk(**dict(self.inputs, view={}))["source_eligibility"], "BLOCKED"
        )
