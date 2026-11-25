"""Additional E4 adversarial contracts; automated review, not human sign-off."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest
from paper_fixtures import setup, later, open_position, policy
from risk_fixtures import START
from iat.intelligence.capital_intelligence import assess_capital
from iat.intelligence.paper_contracts import SyntheticQuoteTape, SyntheticQuote
from iat.intelligence.paper_account import PaperAccount, PaperExitPolicy
from iat.intelligence.risk_intelligence import assess_risk
from iat.intelligence.strategy_replay import digest


class PaperIndependentReview(unittest.TestCase):
    def test_loss_updates_next_budget_and_protection_limits(self):
        k, a, b = setup()
        open_position(k)
        m = later(
            k,
            a,
            b,
            bid="2080",
            ask="2080.2",
            mutate=dict(open=2100, high=2100.2, low=2096, close=2097),
        )
        k["account"].observe(**m)
        next_k, _, _ = setup(offset=timedelta(minutes=10))
        next_k["account"] = k["account"]
        normal = assess_capital(**next_k)
        self.assertEqual(normal["status"], "HYPOTHETICAL_POSITION_ELIGIBLE", normal)
        self.assertEqual(
            Decimal(normal["assessment"]["risk_budget"]),
            Decimal(k["account"].snapshot()["balance"]) * Decimal("0.01"),
        )
        for selected, reason in [
            (policy(daily_loss_fraction="0.01"), "DAILY_LOSS_LIMIT"),
            (policy(drawdown_fraction="0.01"), "DRAWDOWN_LIMIT"),
            (policy(max_consecutive_losses=1), "CONSECUTIVE_LOSS_LIMIT"),
        ]:
            r = assess_capital(**dict(next_k, policy=selected))
            self.assertIn(reason, r["reason_codes"])

    def test_hypothesis_invalidated_before_entry_is_not_suitable(self):
        k, a, b = setup()
        m = later(
            k,
            a,
            b,
            bid="2097",
            ask="2097.2",
            mutate=dict(open=2100, high=2100.2, low=2096, close=2097),
        )
        r = assess_capital(
            **dict(
                k,
                risk=m["risk"],
                risk_inputs=m["risk_inputs"],
                quote=m["quote"],
                as_of=m["as_of"],
            )
        )
        self.assertEqual(r["status"], "CAPITAL_ASSESSMENT_UNAVAILABLE")

    def test_already_observed_target_cannot_be_entered_retrospectively(self):
        k, a, b = setup()
        m = later(
            k,
            a,
            b,
            bid="2106.2",
            ask="2106.4",
            mutate=dict(open=2100, high=2106.3, low=2099.8, close=2106.2),
        )
        r = assess_capital(
            **dict(
                k,
                risk=m["risk"],
                risk_inputs=m["risk_inputs"],
                quote=m["quote"],
                as_of=m["as_of"],
            )
        )
        self.assertEqual(r["status"], "CAPITAL_ASSESSMENT_UNAVAILABLE")

    def test_ambiguous_same_candle_events_never_choose_profitable_fill(self):
        k, a, b = setup()
        open_position(k)
        m = later(
            k,
            a,
            b,
            bid="2097",
            ask="2097.2",
            mutate=dict(open=2100, high=2106.5, low=2096, close=2097),
        )
        r = k["account"].observe(**m)
        self.assertEqual(r["status"], "UNRESOLVED", r)
        self.assertIsNone(r["position"]["exit_fill"])
        self.assertIsNone(k["account"].metrics()["net_return"])

    def test_skipped_e2_interval_is_not_silent_success(self):
        k, a, b = setup()
        open_position(k)
        m = later(k, a, b, n=38)
        r = k["account"].observe(**m)
        self.assertEqual(r["status"], "UNRESOLVED", r)
        self.assertIsNone(r["position"]["net_hypothetical_pnl"])

    def test_missing_target_not_invented(self):
        k, a, b = setup()
        original = deepcopy(k["risk"])
        # Rehashed absence is not authenticated; absent native target must come from E2.
        k["risk"]["frozen_target"] = None
        k["risk"]["sha256"] = digest(
            {a: b for a, b in k["risk"].items() if a != "sha256"}
        )
        self.assertEqual(
            assess_capital(**k)["status"], "CAPITAL_ASSESSMENT_UNAVAILABLE"
        )
        self.assertIsNotNone(original["frozen_target"])

    def test_new_quote_feed_label_cannot_replace_dataset_identity(self):
        k, a, b = setup()
        open_position(k)
        m = later(k, a, b)
        other = SyntheticQuoteTape(
            k["tape"].symbol, k["tape"].feed, digest("OTHER_INVENTED_DATASET")
        )
        q = other.append(SyntheticQuote(**m["quote"]["quote"]))
        before = k["account"].journal()
        with self.assertRaisesRegex(ValueError, "DATASET_MISMATCH"):
            k["account"].observe(**dict(m, tape=other, quote=q))
        self.assertEqual(before, k["account"].journal())

    def test_failed_exit_fill_does_not_mutate_monitoring_or_costs(self):
        k, a, b = setup()
        k["fill_policy"] = replace(k["fill_policy"], latency_ms=2000)
        # Entry quote is deliberately too early: unavailable, not a fabricated fill.
        before = k["account"].journal()
        r = open_position(k)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(before, k["account"].journal())

    def test_commission_is_charged_once_per_side_and_spread_once(self):
        k, a, b = setup()
        k["costs"] = replace(
            k["costs"], commission_per_lot_side="0.1", other_per_lot_side="0.05"
        )
        opened = open_position(k)
        p = opened["position"]
        v = Decimal(p["volume"])
        self.assertEqual(
            Decimal(k["account"].snapshot()["balance"]),
            Decimal("50") - v * Decimal("0.15"),
        )
        m = later(
            k,
            a,
            b,
            bid="2106.2",
            ask="2106.4",
            mutate=dict(open=2100, high=2106.3, low=2099.8, close=2106.2),
        )
        result = k["account"].observe(**m)["position"]
        gross = (Decimal("2106.2") - Decimal("2100.1")) * v
        self.assertEqual(Decimal(result["gross_hypothetical_pnl"]), gross)
        self.assertEqual(
            Decimal(result["net_hypothetical_pnl"]), gross - v * Decimal("0.3")
        )
        self.assertEqual(
            Decimal(k["account"].snapshot()["transaction_costs"]), v * Decimal("0.3")
        )

    def test_no_replenishment_after_account_is_exhausted_by_gap(self):
        k, a, b = setup()
        open_position(k)
        m = later(
            k,
            a,
            b,
            bid="1000",
            ask="1000.2",
            mutate=dict(open=2100, high=2100.2, low=2096, close=2097),
        )
        k["account"].observe(**m)
        s = k["account"].snapshot()
        self.assertLess(Decimal(s["balance"]), 0)
        self.assertEqual(s["account_lifecycle"], "EXHAUSTED")
        self.assertEqual(s["cash_events"], [])
        self.assertGreater(Decimal(s["max_drawdown_fraction"]), 1)

    def test_report_byte_budget_rolls_back_entry_and_seen_setup(self):
        k, _, _ = setup()
        k["account"] = PaperAccount(started_at=START, max_report_bytes=5000)
        before = k["account"].journal()
        with self.assertRaisesRegex(ValueError, "ACCOUNT_RESOURCE_LIMIT"):
            open_position(k)
        self.assertEqual(before, k["account"].journal())

    def test_mutating_returned_reports_does_not_change_account(self):
        k, _, _ = setup()
        opened = open_position(k)
        before = k["account"].journal()
        opened["position"]["entry_fill"]["price"] = "1"
        detached = k["account"].snapshot()
        detached["open_positions"].clear()
        self.assertEqual(before, k["account"].journal())

    def test_no_default_timer_or_partial_exit_and_one_position_only(self):
        k, _, _ = setup()
        with self.assertRaises(ValueError):
            replace(k["policy"], max_positions=2).validate()
        with self.assertRaises(ValueError):
            PaperExitPolicy(True, False, True)
        r = open_position(k)["position"]
        self.assertNotIn("timer_seconds", r["exit_policy"])
        self.assertEqual(r["additional_targets"], "NOT_IMPLEMENTED")
        with self.assertRaises(ValueError):
            k["account"].partial_exit("0.001")

    def test_no_implicit_zero_costs_or_auto_leverage_escalation(self):
        k, _, _ = setup()
        r = assess_capital(
            **dict(k, costs=replace(k["costs"], slippage_price_per_fill=None))
        )
        self.assertEqual(r["status"], "CAPITAL_ASSESSMENT_UNAVAILABLE")
        low = replace(k["specification"], leverage="1")
        r = assess_capital(**dict(k, specification=low))
        self.assertEqual(low.leverage, "1")
        self.assertIn("INSUFFICIENT_FREE_MARGIN", r["reason_codes"])

    def test_example_c_realized_two_dollar_gap_loss_leaves_48(self):
        k, a, b = setup()
        k["specification"] = replace(
            k["specification"], min_lot="0.1", volume_step="0.1"
        )
        opened = open_position(k)
        self.assertEqual(opened["position"]["volume"], "0.2")
        m = later(
            k,
            a,
            b,
            bid="2090.1",
            ask="2090.3",
            mutate=dict(open=2100, high=2100.2, low=2096, close=2097),
        )
        r = k["account"].observe(**m)
        self.assertEqual(r["position"]["net_hypothetical_pnl"], "-2")
        self.assertEqual(k["account"].snapshot()["balance"], "48")
        self.assertEqual(k["account"].snapshot()["cash_events"], [])
        next_k, _, _ = setup(offset=timedelta(minutes=10))
        next_k["account"] = k["account"]
        self.assertEqual(assess_capital(**next_k)["assessment"]["risk_budget"], "0.48")

    def test_full_prefix_equivalence_and_future_source_append(self):
        full, a, b = setup()
        open_position(full)
        m = later(full, a, b)
        full["account"].observe(**m)
        frozen = full["account"].journal()
        m = later(full, a, b, n=38)
        full["account"].observe(**m)
        prefix, a, b = setup()
        open_position(prefix)
        m = later(prefix, a, b)
        prefix["account"].observe(**m)
        self.assertEqual(frozen, prefix["account"].journal())
        baseline, a, b = setup()
        baseline_open = open_position(baseline)
        appended, a, b = setup()
        later(appended, a, b, n=37)
        self.assertEqual(open_position(appended), baseline_open)

    def test_financing_is_explicit_and_no_fee_is_implicitly_missing(self):
        k, a, b = setup()
        k["costs"] = replace(k["costs"], financing_per_lot_day="86.4")
        opened = open_position(k)
        self.assertEqual(opened["status"], "HYPOTHETICALLY_OPEN")
        m = later(
            k,
            a,
            b,
            bid="2106.2",
            ask="2106.4",
            mutate=dict(open=2100, high=2106.3, low=2099.8, close=2106.2),
        )
        p = k["account"].observe(**m)["position"]
        v = Decimal(p["volume"])
        self.assertEqual(
            Decimal(p["gross_hypothetical_pnl"]) - Decimal(p["net_hypothetical_pnl"]),
            v * Decimal("0.06"),
        )

    def test_equity_curve_contains_values_not_inferred_strategy_results(self):
        k, _, _ = setup()
        open_position(k)
        metrics = k["account"].metrics()
        self.assertTrue(all("equity" in p for p in metrics["equity_curve"]))
        self.assertIsNone(metrics["win_rate"])
        self.assertEqual(metrics["resolved_denominator"], 0)
        self.assertEqual(metrics["historical_performance"], "UNMEASURED")

    def test_equity_marks_preserve_loss_drawdown_and_negative_balances(self):
        k, a, b = setup()
        open_position(k)
        m = later(k, a, b, bid="2099", ask="2099.2")
        k["account"].observe(**m)
        before = k["account"].snapshot()
        m = later(k, a, b, n=38, bid="2101", ask="2101.2")
        k["account"].observe(**m)
        after = k["account"].snapshot()
        self.assertGreater(Decimal(before["max_drawdown"]), 0)
        self.assertGreaterEqual(
            Decimal(after["max_drawdown"]), Decimal(before["max_drawdown"])
        )

    def test_unfinished_or_expired_hypothesis_never_creates_a_timer_fill(self):
        k, a, b = setup()
        open_position(k)
        for n in (37, 38, 39, 40):
            m = later(k, a, b, n=n)
            result = k["account"].observe(**m)
        self.assertEqual(result["status"], "UNRESOLVED", result)
        self.assertIsNone(result["position"]["exit_fill"])

    def test_capital_policy_rr_is_opt_in_and_not_a_trading_signal(self):
        k, _, _ = setup()
        r = assess_capital(**dict(k, policy=policy(min_reference_rr="100")))
        self.assertIn("REFERENCE_RR_POLICY_NOT_MET", r["reason_codes"])
        self.assertEqual(r["signal"], "WAIT")
        self.assertIs(r["execution_allowed"], False)

    def test_margin_call_cannot_fabricate_liquidation_or_allow_more_positions(self):
        k, a, b = setup()
        open_position(k)
        # A large adverse live quote without a new structural close is only an observation.
        # It is synthetic and is never interpreted as an executable guarantee.
        m = later(k, a, b, bid="1800", ask="1800.2")
        result = k["account"].observe(**m)
        self.assertEqual(result["status"], "UNRESOLVED", result)
        self.assertIsNone(result["position"]["exit_fill"])
        self.assertIsNone(k["account"].snapshot()["equity"])

    def test_exit_quote_must_match_frozen_specification_tick_grid(self):
        k, a, b = setup()
        open_position(k)
        before = k["account"].journal()
        m = later(k, a, b, bid="2100.001", ask="2100.201")
        with self.assertRaisesRegex(ValueError, "QUOTE_OFF_TICK_GRID"):
            k["account"].observe(**m)
        self.assertEqual(before, k["account"].journal())

    def test_nonpositive_modeled_exit_mark_blocks_financial_calculations(self):
        k, _, _ = setup()
        r = assess_capital(
            **dict(k, costs=replace(k["costs"], slippage_price_per_fill="2101"))
        )
        self.assertEqual(r["status"], "CAPITAL_ASSESSMENT_UNAVAILABLE")
        self.assertIn("EXIT_MARK_PRICE_INVALID", r["reason_codes"])

    def test_entry_already_beyond_frozen_target_is_financially_rejected(self):
        k, _, _ = setup()
        tape = SyntheticQuoteTape(
            k["tape"].symbol, k["tape"].feed, k["tape"].dataset_sha256
        )
        q = tape.append(
            SyntheticQuote(**dict(k["quote"]["quote"], bid="2106.9", ask="2107.1"))
        )
        r = assess_capital(**dict(k, tape=tape, quote=q))
        self.assertEqual(r["status"], "FINANCIALLY_UNSUITABLE")
        self.assertIn("FROZEN_TARGET_NOT_FAVORABLE_TO_ENTRY_FILL", r["reason_codes"])
