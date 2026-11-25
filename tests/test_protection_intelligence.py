"""Synthetic E4.6 protection and liquidation contracts, no terminal dependency."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
import json
import unittest
from protection_fixtures import (
    setup,
    open_position,
    quote,
    observe,
    stop_policy,
    liquidation_policy,
)
from paper_fixtures import later, policy
from risk_fixtures import START
from iat.intelligence.protection_contracts import (
    margin_assessment,
    stop_gap_arithmetic,
    ProtectiveStopPolicy,
    LiquidationPolicy,
    assess_protection_plan,
    validate_protection_plan,
)
from iat.intelligence.protected_paper import (
    ProtectedPaperAccount,
    validate_protected_journal,
)
from iat.intelligence.paper_account import validate_paper_journal
from iat.intelligence.strategy_replay import digest


class ProtectionContracts(unittest.TestCase):
    def test_before_open_plan_and_new_journal_version(self):
        k, _, _ = setup()
        r = open_position(k)
        self.assertEqual(r["status"], "HYPOTHETICALLY_OPEN", r)
        p = r["position"]
        self.assertEqual(
            p["proposed_protective_stop"],
            k["risk"]["reference_geometry"]["invalidation_threshold"],
        )
        j = k["account"].journal()
        self.assertEqual(j["report_version"], 2)
        kinds = [x["kind"] for x in j["events"]]
        self.assertLess(
            kinds.index("PROTECTIVE_STOP_ESTABLISHED"),
            kinds.index("HYPOTHETICALLY_OPEN"),
        )
        self.assertTrue(
            validate_protected_journal(json.loads(json.dumps(j)), source=k["account"])
        )
        with self.assertRaises(ValueError):
            validate_paper_journal(j, source=k["account"])

    def test_long_exact_bid_contact_fills_declared_trigger_quote(self):
        k, _, _ = setup()
        open_position(k)
        r = observe(k, quote(k, bid="2097.74", ask="2097.94"))
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED", r)
        self.assertEqual(r["position"]["exit_fill"]["price"], "2097.74")
        self.assertEqual(r["position"]["exit_fill"]["side"], "BID")
        self.assertEqual(k["account"].metrics()["protective_stop_exit_count"], 1)

    def test_short_exact_ask_contact_uses_ask_not_bid(self):
        k, _, _ = setup(True)
        open_position(k)
        r = observe(k, quote(k, bid="2102.06", ask="2102.26"))
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED", r)
        self.assertEqual(r["position"]["exit_fill"]["side"], "ASK")
        self.assertEqual(r["position"]["exit_fill"]["price"], "2102.26")

    def test_wrong_quote_side_does_not_activate(self):
        k, _, _ = setup()
        open_position(k)
        r = observe(k, quote(k, bid="2097.75", ask="2097.95"))
        self.assertEqual(r["status"], "MONITORING")
        self.assertFalse(r["position"]["protection"]["stop_triggered"])

    def test_trigger_quote_excluded_requires_next_eligible_quote(self):
        k, _, _ = setup()
        k["stop_policy"] = stop_policy(0, False)
        open_position(k)
        r = observe(k, quote(k, bid="2097.74", ask="2097.94"))
        self.assertEqual(r["status"], "EXIT_PENDING", r)
        r = observe(k, quote(k, 3, bid="2097.5", ask="2097.7"))
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED", r)
        self.assertEqual(r["position"]["exit_fill"]["price"], "2097.5")

    def test_latency_never_selects_better_before_deadline_or_later_quote(self):
        k, _, _ = setup()
        k["stop_policy"] = stop_policy(2000, False)
        open_position(k)
        self.assertEqual(
            observe(k, quote(k, bid="2097.7", ask="2097.9"))["status"], "EXIT_PENDING"
        )
        self.assertEqual(
            observe(k, quote(k, 3, bid="2098", ask="2098.2"))["status"], "EXIT_PENDING"
        )
        eligible = quote(k, 4, bid="2097.4", ask="2097.6")
        quote(
            k, 5, bid="2105", ask="2105.2"
        )  # future at4-second cutoff must not influence fill
        r = observe(k, eligible)
        self.assertEqual(r["position"]["exit_fill"]["price"], "2097.4")
        self.assertEqual(r["position"]["exit_fill"]["modeled_exit_latency_ms"], 2000)

    def test_gap_through_exceeds_estimated_risk_without_replenishment(self):
        k, _, _ = setup()
        p = open_position(k)["position"]
        r = observe(k, quote(k, bid="2090.1", ask="2090.3"))
        p = r["position"]
        self.assertGreater(
            Decimal(p["realized_hypothetical_loss"]), Decimal(p["estimated_risk"])
        )
        self.assertGreater(Decimal(p["risk_budget_exceedance"]), 0)
        self.assertEqual(k["account"].snapshot()["cash_events"], [])

    def test_requested_3500_example_is_isolated_arithmetic(self):
        r = stop_gap_arithmetic(
            entry="3500.15",
            stop="3499.65",
            exit_price="3498.90",
            volume="0.01",
            contract_size="100",
            direction="BULLISH",
            additional_costs="0",
        )
        self.assertEqual(r["estimated_price_risk"], "0.5")
        self.assertEqual(r["gross_hypothetical_loss"], "1.25")
        self.assertEqual(r["gap_through_component"], "0.75")
        self.assertFalse(r["execution_allowed"])

    def test_missing_costs_are_not_zero_in_arithmetic(self):
        r = stop_gap_arithmetic(
            entry="3500.15",
            stop="3499.65",
            exit_price="3498.90",
            volume="0.01",
            contract_size="100",
            direction="BULLISH",
            additional_costs=None,
        )
        self.assertIsNone(r["net_hypothetical_loss"])

    def test_invalid_mapping_trigger_side_or_implicit_latency_block(self):
        sp = stop_policy()
        for field, value in [
            ("mapping", None),
            ("trigger_basis", "LONG_ASK_SHORT_BID"),
            ("latency_ms", None),
            ("trigger_quote_can_fill", None),
            ("version", 2),
        ]:
            with self.assertRaises(ValueError):
                replace(sp, **{field: value})
        with self.assertRaises(ValueError):
            stop_policy(1, True)

    def test_stop_grid_and_minimum_distance_are_not_rounded_or_tightened(self):
        k, _, _ = setup()
        before = k["account"].journal()
        k["specification"] = replace(
            k["specification"], tick_size="0.1", tick_value="0.1"
        )
        r = open_position(k)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("STOP_OFF_TICK_GRID", r["reason_codes"])
        self.assertEqual(before, k["account"].journal())
        k, _, _ = setup()
        k["specification"] = replace(k["specification"], min_stop_distance="2.2")
        r = open_position(k)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("STOP_MINIMUM_DISTANCE", r["reason_codes"])

    def test_minimum_lot_usd50_rejection_remains_financial(self):
        k, _, _ = setup()
        k["specification"] = replace(
            k["specification"], contract_size="100", tick_value="1"
        )
        r = open_position(k)
        self.assertEqual(r["status"], "ENTRY_REJECTED", r)
        self.assertIn("MINIMUM_LOT_EXCEEDS_RISK_BUDGET", r["reason_codes"])
        self.assertEqual(k["account"].snapshot()["balance"], "50")

    def test_equity_over_margin_zero_and_exact_thresholds(self):
        zero = margin_assessment(
            equity="-1", used_margin="0", margin_call_ratio="1.2", stop_out_ratio="1.1"
        )
        self.assertIsNone(zero["margin_level_percent"])
        self.assertFalse(zero["stop_out"])
        r = margin_assessment(
            equity="110",
            used_margin="100",
            margin_call_ratio="1.2",
            stop_out_ratio="1.1",
        )
        self.assertEqual(r["margin_level_percent"], "110")
        self.assertTrue(r["stop_out"])
        r = margin_assessment(
            equity="-10", used_margin="5", margin_call_ratio="1.2", stop_out_ratio="1.1"
        )
        self.assertEqual(r["margin_level_percent"], "-200")
        self.assertTrue(r["stop_out"])

    def margin_setup(self):
        k, a, b = setup()
        k["specification"] = replace(
            k["specification"],
            leverage="10",
            margin_call_equity_ratio="1.132",
            stop_out_equity_ratio="1.13",
        )
        opened = open_position(k)
        self.assertEqual(opened["status"], "HYPOTHETICALLY_OPEN", opened)
        return k, a, b

    def test_margin_call_warning_does_not_liquidate(self):
        k, _, _ = self.margin_setup()
        r = observe(k, quote(k, bid="2099.7", ask="2099.9"))
        self.assertEqual(r["status"], "MONITORING", r)
        self.assertTrue(k["account"].snapshot()["new_positions_restricted"])
        self.assertIsNone(r["position"]["exit_fill"])
        self.assertEqual(k["account"].metrics()["margin_warning_count"], 1)

    def test_stop_out_liquidates_on_declared_quote_and_releases_margin(self):
        k, _, _ = self.margin_setup()
        r = observe(k, quote(k, bid="2099.2", ask="2099.4"))
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED", r)
        self.assertEqual(
            r["position"]["protection"]["liquidation_status"],
            "HYPOTHETICALLY_LIQUIDATED",
        )
        self.assertEqual(k["account"].metrics()["liquidation_count"], 1)
        self.assertEqual(k["account"].snapshot()["used_margin"], "0")
        self.assertEqual(k["account"].snapshot()["margin"]["status"], "NO_USED_MARGIN")

    def test_liquidation_latency_waits_for_first_causal_quote(self):
        k, _, _ = self.margin_setup()
        # Frozen policy must be supplied before opening, not moved retrospectively.
        k, _, _ = setup()
        k["specification"] = replace(
            k["specification"],
            leverage="10",
            margin_call_equity_ratio="1.132",
            stop_out_equity_ratio="1.13",
        )
        k["liquidation_policy"] = liquidation_policy(2000, False)
        open_position(k)
        self.assertEqual(
            observe(k, quote(k, bid="2099.2", ask="2099.4"))["status"], "EXIT_PENDING"
        )
        self.assertEqual(
            observe(k, quote(k, 3, bid="2099.3", ask="2099.5"))["status"],
            "EXIT_PENDING",
        )
        r = observe(k, quote(k, 4, bid="2099", ask="2099.2"))
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED", r)

    def test_stop_and_liquidation_with_different_latency_stay_unresolved(self):
        k, _, _ = setup()
        k["liquidation_policy"] = liquidation_policy(1000, False)
        open_position(k)
        r = observe(k, quote(k, bid="1000", ask="1000.2"))
        self.assertEqual(r["status"], "UNRESOLVED", r)
        self.assertIsNone(r["position"]["exit_fill"])
        self.assertIsNone(k["account"].snapshot()["equity"])

    def test_identical_coincident_policies_share_one_fill_and_retain_negative_balance(
        self,
    ):
        k, _, _ = setup()
        open_position(k)
        r = observe(k, quote(k, bid="1000", ask="1000.2"))
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED", r)
        state = k["account"].snapshot()
        self.assertLess(Decimal(state["balance"]), 0)
        self.assertEqual(state["account_lifecycle"], "EXHAUSTED")
        self.assertEqual(state["cash_events"], [])
        metrics = k["account"].metrics()
        self.assertEqual(metrics["positions_closed"], 1)
        self.assertEqual(metrics["liquidation_count"], 1)
        self.assertEqual(metrics["protective_stop_exit_count"], 1)

    def test_no_fill_at_missing_end_of_capture_and_old_review_is_immutable(self):
        k, _, _ = setup()
        k["stop_policy"] = stop_policy(3000, False)
        open_position(k)
        observe(k, quote(k, bid="2097.7", ask="2097.9"))
        prefix = k["account"].journal()
        review = k["account"].review_cutoff(
            k["as_of"] + timedelta(seconds=9), end_of_input=True
        )
        self.assertEqual(review["status"], "UNRESOLVED")
        self.assertIsNone(review["current_equity_at_cutoff"])
        self.assertEqual(prefix, k["account"].journal())
        observe(k, quote(k, 5, bid="2097.5", ask="2097.7"))
        self.assertEqual(review["status"], "UNRESOLVED")
        self.assertEqual(
            prefix["account"]["open_positions"][0]["state"], "EXIT_PENDING"
        )

    def test_known_skipped_quote_and_unknown_gap_never_silently_fill(self):
        k, _, _ = setup()
        open_position(k)
        quote(k, bid="2097.7", ask="2097.9")
        row = quote(k, 3, bid="2100", ask="2100.2")
        self.assertEqual(observe(k, row)["status"], "UNRESOLVED")
        k, _, _ = setup()
        k["fill_policy"] = replace(k["fill_policy"], max_gap_ms=1000)
        open_position(k)
        self.assertEqual(
            observe(k, quote(k, 4, bid="2097.7", ask="2097.9"))["status"], "UNRESOLVED"
        )

    def test_closed_quotations_unknown_future_and_stale_quotes(self):
        k, _, _ = setup()
        open_position(k)
        self.assertEqual(
            observe(k, quote(k, quotation=False, opening=False))["status"], "UNRESOLVED"
        )
        k, _, _ = setup()
        open_position(k)
        before = k["account"].journal()
        row = quote(k, 5, occurred=k["as_of"])
        with self.assertRaises(ValueError):
            observe(k, row)
        self.assertEqual(before, k["account"].journal())

    def test_close_only_quote_can_fill_protection_without_open_permission(self):
        k, _, _ = setup()
        open_position(k)
        r = observe(k, quote(k, bid="2097.7", ask="2097.9", opening=False))
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED", r)

    def test_forged_quote_risk_or_journal_rejects_without_mutation(self):
        k, _, _ = setup()
        open_position(k)
        before = k["account"].journal()
        row = quote(k)
        forged = deepcopy(row)
        forged["quote"]["bid"] = "1000"
        forged["sha256"] = digest({a: b for a, b in forged.items() if a != "sha256"})
        with self.assertRaises(ValueError):
            observe(k, forged)
        risk = deepcopy(k["risk"])
        risk["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            observe(k, row, risk=risk)
        self.assertEqual(before, k["account"].journal())
        j = deepcopy(before)
        j["account"]["balance"] = "1000"
        j["sha256"] = digest({a: b for a, b in j.items() if a != "sha256"})
        with self.assertRaises(ValueError):
            validate_protected_journal(j, source=k["account"])

    def test_duplicate_activation_and_fill_do_not_double_count(self):
        k, _, _ = setup()
        k["stop_policy"] = stop_policy(2000, False)
        open_position(k)
        row = quote(k, bid="2097.7", ask="2097.9")
        observe(k, row)
        old = k["account"].journal()
        self.assertEqual(observe(k, row)["status"], "DUPLICATE")
        self.assertEqual(old, k["account"].journal())
        observe(k, quote(k, 3, bid="2097.6", ask="2097.8"))
        observe(k, quote(k, 4, bid="2097.5", ask="2097.7"))
        kinds = [e["kind"] for e in k["account"].journal()["events"]]
        self.assertEqual(kinds.count("PROTECTIVE_STOP_ACTIVATED"), 1)
        self.assertEqual(kinds.count("HYPOTHETICALLY_CLOSED"), 1)
        with self.assertRaises(ValueError):
            observe(k, row)

    def test_expired_specification_and_resource_failure_rollback(self):
        k, _, _ = setup()
        k["specification"] = replace(
            k["specification"],
            expires_at_utc=(k["as_of"] + timedelta(seconds=1)).isoformat(),
        )
        open_position(k)
        old = k["account"].journal()
        with self.assertRaises(ValueError):
            observe(k, quote(k, 3))
        self.assertEqual(old, k["account"].journal())
        k, _, _ = setup()
        k["account"] = ProtectedPaperAccount(started_at=START, max_events=4)
        open_position(k)
        old = k["account"].journal()
        with self.assertRaises(ValueError):
            observe(k, quote(k, bid="2097.7", ask="2097.9"))
        self.assertEqual(old, k["account"].journal())

    def test_repeatability_prefix_future_append_and_decimal_context(self):
        results = []
        for _ in range(2):
            k, _, _ = setup()
            open_position(k)
            prefix = k["account"].journal()
            row = quote(k, bid="2097.74", ask="2097.94")
            quote(k, 3, bid="2200", ask="2200.2")
            observe(k, row)
            results.append(k["account"].journal())
            self.assertEqual(
                prefix["account"]["open_positions"][0]["protection"]["stop_status"],
                "ESTABLISHED",
            )
        self.assertEqual(results[0], results[1])
        with localcontext() as c:
            c.prec = 2
            k, _, _ = setup()
            open_position(k)
            observe(k, quote(k, bid="2097.74", ask="2097.94"))
        self.assertEqual(k["account"].journal(), results[0])
