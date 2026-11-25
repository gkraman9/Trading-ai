"""Further independent synthetic E4.6 account protection/replay adversarial cases."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import unittest
from protection_fixtures import (
    setup,
    open_position,
    quote,
    observe,
    stop_policy,
    liquidation_policy,
)
from paper_fixtures import later, policy, shifted_snapshot
from risk_fixtures import START
from iat.intelligence.protection_contracts import (
    assess_protection_plan,
    validate_protection_plan,
    margin_assessment,
)
from iat.intelligence.protected_paper import ProtectedPaperAccount, replay_protected
from iat.intelligence.paper_account import PaperExitPolicy
from iat.intelligence.paper_contracts import SyntheticQuote
from iat.intelligence.risk_intelligence import assess_risk
from iat.intelligence.strategy_replay import digest


class ProtectionScenarios(unittest.TestCase):
    def test_authenticated_plan_cannot_be_rehashed_to_move_stop(self):
        k, _, _ = setup()
        p = assess_protection_plan(**k)
        self.assertTrue(validate_protection_plan(p, **k))
        p["stop"]["threshold"] = "2099"
        p["sha256"] = digest({a: b for a, b in p.items() if a != "sha256"})
        with self.assertRaises(ValueError):
            validate_protection_plan(p, **k)

    def test_freezing_plan_and_output_mutation_cannot_change_protective_level(self):
        k, _, _ = setup()
        r = open_position(k)
        threshold = r["position"]["proposed_protective_stop"]
        r["position"]["protection"]["stop"]["threshold"] = "9999"
        self.assertEqual(
            k["account"].snapshot()["open_positions"][0]["proposed_protective_stop"],
            threshold,
        )
        result = observe(k, quote(k, bid="2097.74", ask="2097.94"))
        self.assertEqual(result["position"]["exit_fill"]["price"], threshold)

    def test_repeated_losses_enforce_consecutive_and_daily_limits(self):
        account = None
        for i in range(2):
            k, _, _ = setup(offset=timedelta(minutes=10 * i))
            k["policy"] = policy(max_consecutive_losses=2)
            if account is not None:
                k["account"] = account
            self.assertEqual(open_position(k)["status"], "HYPOTHETICALLY_OPEN")
            observe(k, quote(k, bid="2097.74", ask="2097.94"))
            account = k["account"]
        third, _, _ = setup(offset=timedelta(minutes=20))
        third["account"] = account
        third["policy"] = policy(max_consecutive_losses=2)
        rejected = open_position(third)
        self.assertEqual(rejected["status"], "ENTRY_REJECTED")
        self.assertIn("CONSECUTIVE_LOSS_LIMIT", rejected["reason_codes"])
        self.assertEqual(len(account.snapshot()["closed_positions"]), 2)
        # Same observed loss history, independently selected daily cap, no reset.
        fourth, _, _ = setup(offset=timedelta(minutes=30))
        fourth["account"] = account
        fourth["policy"] = policy(daily_loss_fraction="0.01")
        self.assertIn("DAILY_LOSS_LIMIT", open_position(fourth)["reason_codes"])

    def test_profit_recovery_does_not_erase_drawdown_or_losses(self):
        k, _, _ = setup()
        open_position(k)
        observe(k, quote(k, bid="2097.74", ask="2097.94"))
        old = k["account"].snapshot()
        k2, a, b = setup(offset=timedelta(minutes=10))
        k2["account"] = k["account"]
        open_position(k2)
        r = k2["account"].observe(
            **later(
                k2,
                a,
                b,
                bid="2106.2",
                ask="2106.4",
                mutate=dict(open=2100, high=2106.3, low=2099.8, close=2106.2),
            )
        )
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED", r)
        new = k2["account"].snapshot()
        metrics = k2["account"].metrics()
        self.assertGreater(Decimal(new["balance"]), Decimal(old["balance"]))
        self.assertGreaterEqual(
            Decimal(new["max_drawdown"]), Decimal(old["max_drawdown"])
        )
        self.assertEqual(
            (metrics["winning_positions"], metrics["losing_positions"]), (1, 1)
        )
        self.assertEqual(metrics["protective_stop_exit_count"], 1)
        self.assertEqual(metrics["structural_exit_count"], 1)

    def test_ambiguous_e2_stop_conflict_never_selects_favorable_exit(self):
        k, a, b = setup()
        open_position(k)
        a[36].update(open=2100, high=2100.2, low=2097, close=2097.1)
        v, c, i = shifted_snapshot(37, a, b, timedelta(0))
        current = k["risk_inputs"]["exit_source"].record(v, c, view_inputs=i)
        inputs = dict(k["risk_inputs"], current_e2=current, as_of=c.analysis_at)
        risk = assess_risk(**inputs)
        row = quote(k, 60, bid="2097.7", ask="2097.9")
        r = observe(k, row, risk=risk, risk_inputs=inputs)
        self.assertEqual(r["status"], "UNRESOLVED", r)
        self.assertIsNone(r["position"]["exit_fill"])
        self.assertIsNone(k["account"].metrics()["net_return"])

    def test_new_exit_during_liquidation_latency_is_unresolved(self):
        k, _, _ = setup()
        k["specification"] = replace(
            k["specification"],
            leverage="10",
            margin_call_equity_ratio="1.132",
            stop_out_equity_ratio="1.13",
        )
        k["liquidation_policy"] = liquidation_policy(5000, False)
        open_position(k)
        self.assertEqual(
            observe(k, quote(k, bid="2099.2", ask="2099.4"))["status"], "EXIT_PENDING"
        )
        r = observe(k, quote(k, 3, bid="2097.7", ask="2097.9"))
        self.assertEqual(r["status"], "UNRESOLVED")
        self.assertIn("COMPETING_EXIT_DURING_PENDING_FILL", r["reason_codes"])

    def test_margin_warning_recovery_retains_historical_warning_and_drawdown(self):
        k, _, _ = setup()
        k["specification"] = replace(
            k["specification"],
            leverage="10",
            margin_call_equity_ratio="1.132",
            stop_out_equity_ratio="1.13",
        )
        open_position(k)
        observe(k, quote(k, bid="2099.7", ask="2099.9"))
        old = k["account"].snapshot()
        observe(k, quote(k, 3, bid="2100", ask="2100.2"))
        new = k["account"].snapshot()
        self.assertFalse(new["new_positions_restricted"])
        self.assertEqual(k["account"].metrics()["margin_warning_count"], 1)
        self.assertGreaterEqual(
            Decimal(new["max_drawdown"]), Decimal(old["max_drawdown"])
        )

    def test_costs_financing_and_slippage_are_accounted_once(self):
        k, _, _ = setup()
        k["costs"] = replace(
            k["costs"],
            commission_per_lot_side="0.1",
            other_per_lot_side="0.05",
            slippage_price_per_fill="0.1",
            financing_per_lot_day="86.4",
        )
        p = open_position(k)["position"]
        v = Decimal(p["volume"])
        r = observe(k, quote(k, bid="2097.74", ask="2097.94"))
        p = r["position"]
        gross = (Decimal("2097.64") - Decimal("2100.2")) * v
        fees = Decimal("0.3") * v
        financing = Decimal("0.001") * v
        self.assertEqual(Decimal(p["gross_hypothetical_pnl"]), gross)
        self.assertEqual(Decimal(p["net_hypothetical_pnl"]), gross - fees - financing)
        self.assertEqual(
            Decimal(k["account"].snapshot()["transaction_costs"]), fees + financing
        )

    def test_full_prefix_equivalence_with_actual_rolling_quote_replay(self):
        def run(cut):
            k, _, _ = setup()
            k["stop_policy"] = stop_policy(2000, False)
            rows = [
                quote(k, 2, bid="2100", ask="2100.2"),
                quote(k, 3, bid="2097.7", ask="2097.9"),
                quote(k, 4, bid="2097.6", ask="2097.8"),
                quote(k, 5, bid="2097.5", ask="2097.7"),
            ]
            entry = {n: v for n, v in k.items() if n != "account"}
            entry["exit_policy"] = PaperExitPolicy(True, True, True)
            observations = [
                dict(
                    risk=k["risk"],
                    risk_inputs=k["risk_inputs"],
                    tape=k["tape"],
                    quote=q,
                    as_of=q["quote"]["available_at_utc"],
                )
                for q in rows
            ]
            return replay_protected(
                account=k["account"],
                entry=entry,
                observations=observations,
                cutoff=k["as_of"] + timedelta(seconds=cut - 1),
            )

        prefix = run(3)
        full = run(5)
        self.assertEqual(prefix, run(3))
        self.assertEqual(full, run(5))
        n = len(prefix["journal"]["events"])
        self.assertEqual(prefix["journal"]["events"], full["journal"]["events"][:n])
        self.assertEqual(prefix["cutoff_review"]["status"], "UNRESOLVED")
        self.assertEqual(full["journal"]["metrics"]["positions_closed"], 1)

    def test_replay_rejects_retrospective_or_nonfresh_account(self):
        k, _, _ = setup()
        open_position(k)
        with self.assertRaises(ValueError):
            replay_protected(
                account=k["account"], entry={}, observations=[], cutoff=k["as_of"]
            )

    def test_source_analysis_freshness_is_not_silently_widened_for_protection(self):
        k, _, _ = setup()
        open_position(k)
        r = observe(k, quote(k, 32, bid="2097.7", ask="2097.9"))
        self.assertEqual(r["status"], "UNRESOLVED")
        self.assertIn("STRUCTURAL_ANALYSIS_STALE", r["reason_codes"])

    def test_future_risk_snapshot_does_not_inform_earlier_quote(self):
        k, a, b = setup()
        open_position(k)
        old = k["account"].journal()
        later_risk = later(k, a, b, n=37)
        # Previous quote remains a valid frozen source; future report cannot be applied retroactively.
        row = k["tape"].rows()[0]
        with self.assertRaises(ValueError):
            observe(
                k, row, risk=later_risk["risk"], risk_inputs=later_risk["risk_inputs"]
            )
        self.assertEqual(old, k["account"].journal())

    def test_live_provenance_unsupported_currency_and_liquidation_methods_block(self):
        k, _, _ = setup()
        r = deepcopy(k["risk"])
        r["provenance"] = "LIVE_MT5"
        r["sha256"] = digest({a: b for a, b in r.items() if a != "sha256"})
        k["risk"] = r
        self.assertEqual(open_position(k)["status"], "BLOCKED")
        k, _, _ = setup()
        k["specification"] = replace(k["specification"], margin_currency="EUR")
        self.assertEqual(open_position(k)["status"], "BLOCKED")
        with self.assertRaises(ValueError):
            replace(liquidation_policy(), model="EXNESS_VERIFIED")

    def test_byte_limits_and_transient_plan_rollback(self):
        k, _, _ = setup()
        k["account"] = ProtectedPaperAccount(started_at=START, max_report_bytes=5000)
        old = k["account"].journal()
        with self.assertRaises(ValueError):
            open_position(k)
        self.assertEqual(old, k["account"].journal())
        self.assertIsNone(k["account"]._proposal)

    def test_extra_actual_fill_prices_never_become_guaranteed_stop_prices(self):
        k, _, _ = setup()
        k["stop_policy"] = stop_policy(1000, False)
        open_position(k)
        observe(k, quote(k, bid="2097.74", ask="2097.94"))
        r = observe(k, quote(k, 3, bid="2090", ask="2090.2"))
        p = r["position"]
        self.assertNotEqual(p["proposed_protective_stop"], p["exit_fill"]["price"])
        self.assertGreater(Decimal(p["risk_budget_exceedance"]), 0)

    def test_negative_equity_warning_is_not_automatic_balance_replenishment(self):
        r = margin_assessment(
            equity="-20", used_margin="5", margin_call_ratio="1", stop_out_ratio="0.5"
        )
        self.assertTrue(r["stop_out"])
        self.assertEqual(r["free_margin"], "-25")
        self.assertEqual(r["signal"], "WAIT")
        self.assertIs(r["execution_allowed"], False)

    def test_new_source_modules_have_no_live_order_credentials_or_network_dependencies(
        self,
    ):
        root = Path(__file__).resolve().parents[1] / "iat/intelligence"
        for p in ("protected_paper.py", "protection_contracts.py"):
            text = (root / p).read_text(encoding="utf-8")
            for forbidden in (
                "import MetaTrader5",
                "order_send(",
                "account_info(",
                "os.environ",
                "requests.",
                "socket.",
            ):
                self.assertNotIn(forbidden, text)

    def test_missing_data_review_never_counts_unresolved_as_zero_loss(self):
        k, _, _ = setup()
        k["stop_policy"] = stop_policy(5000, False)
        open_position(k)
        observe(k, quote(k, bid="2097.7", ask="2097.9"))
        r = k["account"].review_cutoff(
            k["as_of"] + timedelta(seconds=10), end_of_input=True
        )
        self.assertEqual(r["unresolved_exit_denominator"], 1)
        self.assertEqual(r["resolved_exit_denominator"], 0)
        self.assertIsNone(k["account"].metrics()["win_rate"])
        self.assertEqual(k["account"].metrics()["positions_closed"], 0)

    def test_source_prefix_change_cannot_hide_between_same_entry_and_last_anchors(self):
        from iat.intelligence.paper_contracts import SyntheticQuoteTape

        k, _, _ = setup()
        open_position(k)
        observe(k, quote(k, 2))
        observe(k, quote(k, 3, bid="2100.1", ask="2100.3"))
        before = k["account"].journal()
        latest = quote(k, 4, bid="2100.2", ask="2100.4")
        replacement = SyntheticQuoteTape(
            k["tape"].symbol, k["tape"].feed, k["tape"].dataset_sha256
        )
        for row in k["tape"].rows():
            q = dict(row["quote"])
            if q["sequence"] == 1:
                q.update(bid="2101", ask="2101.2")
            supplied = replacement.append(SyntheticQuote(**q))
        with self.assertRaisesRegex(ValueError, "QUOTE_SOURCE_HISTORY_MISMATCH"):
            k["account"].observe(
                k["risk"],
                risk_inputs=k["risk_inputs"],
                tape=replacement,
                quote=supplied,
                as_of=supplied["quote"]["available_at_utc"],
            )
        self.assertEqual(before, k["account"].journal())

    def test_each_pending_wait_quote_is_retained_in_the_v2_event_prefix(self):
        k, _, _ = setup()
        k["stop_policy"] = stop_policy(3000, False)
        open_position(k)
        observe(k, quote(k, 2, bid="2097.7", ask="2097.9"))
        waiting = quote(k, 3, bid="2097.6", ask="2097.8")
        observe(k, waiting)
        events = k["account"].journal()["events"]
        waits = [e for e in events if e["kind"] == "PROTECTION_EXIT_WAITING"]
        self.assertEqual(len(waits), 1)
        self.assertEqual(waits[0]["quote_sha256"], waiting["sha256"])
