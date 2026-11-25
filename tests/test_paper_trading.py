"""Independent synthetic E4 contract, affordability and lifecycle regressions."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
import json
import unittest
from paper_fixtures import setup, later, open_position, specification, costs, policy
from risk_fixtures import START
from iat.intelligence.paper_contracts import (
    SyntheticQuote,
    SyntheticQuoteTape,
    FillPolicy,
    SyntheticCosts,
    quote_fill,
    PaperError,
)
from iat.intelligence.capital_intelligence import assess_capital, capital_arithmetic
from iat.intelligence.paper_account import PaperAccount, PaperExitPolicy
from iat.intelligence.strategy_replay import digest


class QuoteContracts(unittest.TestCase):
    def setUp(self):
        self.t = SyntheticQuoteTape("SYNTHETIC_XAUUSD", "TOY", digest("invented"))
        self.d = START
        self.when = START + timedelta(seconds=1)
        self.q = SyntheticQuote(
            "SYNTHETIC_XAUUSD",
            "TOY",
            0,
            self.when.isoformat(),
            self.when.isoformat(),
            "2100",
            "2100.2",
            True,
            True,
        )
        self.row = self.t.append(self.q)
        self.p = FillPolicy(0, 2000, 120000, 30000)

    def fill(self, direction="BULLISH", phase="ENTRY", **kw):
        k = dict(
            tape=self.t,
            direction=direction,
            phase=phase,
            decision_at=self.d,
            as_of=self.when,
            policy=self.p,
            costs=costs(),
        )
        k.update(kw)
        return quote_fill(self.row, **k)

    def test_long_and_short_side_specific_fills(self):
        for direction, phase, side, price in [
            ("BULLISH", "ENTRY", "ASK", "2100.2"),
            ("BULLISH", "EXIT", "BID", "2100"),
            ("BEARISH", "ENTRY", "BID", "2100"),
            ("BEARISH", "EXIT", "ASK", "2100.2"),
        ]:
            r = self.fill(direction, phase)
            self.assertEqual((r["side"], r["price"]), (side, price))
            self.assertIs(r["execution_allowed"], False)

    def test_explicit_adverse_slippage_not_double_spread(self):
        c = replace(costs(), slippage_price_per_fill="0.1")
        self.assertEqual(self.fill(costs=c)["price"], "2100.3")
        self.assertEqual(self.fill(phase="EXIT", costs=c)["price"], "2099.9")

    def test_future_availability_and_fill_before_decision(self):
        for changes in (
            dict(as_of=self.d),
            dict(decision_at=self.when),
            dict(policy=FillPolicy(2000, 2000, 120000, 30000)),
        ):
            with self.assertRaises(ValueError):
                self.fill(**changes)

    def test_stale_quote_not_refreshed_by_new_receipt(self):
        old = replace(
            self.q,
            sequence=1,
            available_at_utc=(self.when + timedelta(seconds=4)).isoformat(),
        )
        row = self.t.append(old)
        with self.assertRaisesRegex(ValueError, "QUOTE_STALE"):
            self.t.authenticate(
                row, as_of=self.when + timedelta(seconds=4), policy=self.p
            )

    def test_unchanged_prices_with_new_occurrence_are_new_observation(self):
        new = replace(
            self.q,
            sequence=1,
            occurred_at_utc=(self.when + timedelta(seconds=1)).isoformat(),
            available_at_utc=(self.when + timedelta(seconds=1)).isoformat(),
        )
        row = self.t.append(new)
        self.assertEqual(
            self.t.authenticate(row, as_of=new.available_at_utc, policy=self.p)[
                "sequence"
            ],
            1,
        )

    def test_forged_checksum_does_not_authenticate_quote(self):
        forged = deepcopy(self.row)
        forged["quote"]["ask"] = "2101"
        forged["sha256"] = digest({k: v for k, v in forged.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            self.t.authenticate(forged, as_of=self.when, policy=self.p)

    def test_clock_sequence_corrections_and_feed_fail_closed(self):
        for q in (
            replace(self.q, ask="2101"),
            replace(self.q, sequence=2),
            replace(self.q, sequence=1),
            replace(self.q, feed="OTHER"),
            replace(
                self.q,
                sequence=1,
                available_at_utc=self.d.isoformat(),
                occurred_at_utc=self.d.isoformat(),
            ),
        ):
            with self.assertRaises(ValueError):
                self.t.append(q)
        self.assertEqual(len(self.t.rows()), 1)

    def test_close_only_allows_exit_but_not_entry(self):
        t = SyntheticQuoteTape(self.q.symbol, self.q.feed, digest("close_only"))
        row = t.append(replace(self.q, new_position_eligible=False))
        k = dict(
            tape=t,
            direction="BULLISH",
            decision_at=self.d,
            as_of=self.when,
            policy=self.p,
            costs=costs(),
        )
        with self.assertRaises(ValueError):
            quote_fill(row, phase="ENTRY", **k)
        self.assertEqual(quote_fill(row, phase="EXIT", **k)["side"], "BID")

    def test_live_provenance_and_invalid_prices_rejected(self):
        for changes in (
            dict(provenance="LIVE_MT5"),
            dict(bid="NaN"),
            dict(bid=True),
            dict(bid="2101"),
            dict(new_position_eligible=None),
        ):
            with self.assertRaises(ValueError):
                replace(self.q, **changes)

    def test_first_causal_quote_not_retrospectively_best(self):
        row = self.t.append(
            replace(
                self.q,
                sequence=1,
                occurred_at_utc=(self.when + timedelta(seconds=1)).isoformat(),
                available_at_utc=(self.when + timedelta(seconds=1)).isoformat(),
                ask="2100.1",
            )
        )
        with self.assertRaisesRegex(ValueError, "NOT_FIRST_CAUSAL_QUOTE"):
            quote_fill(
                row,
                tape=self.t,
                direction="BULLISH",
                phase="ENTRY",
                decision_at=self.d,
                as_of=self.when + timedelta(seconds=1),
                policy=self.p,
                costs=costs(),
            )

    def test_future_append_does_not_change_earlier_fill_or_hash(self):
        old = self.fill()
        self.t.append(
            replace(
                self.q,
                sequence=1,
                occurred_at_utc=(self.when + timedelta(seconds=10)).isoformat(),
                available_at_utc=(self.when + timedelta(seconds=10)).isoformat(),
            )
        )
        self.assertEqual(self.fill(), old)

    def test_resource_bounds_and_duplicate_are_transactional(self):
        t = SyntheticQuoteTape(
            self.q.symbol, self.q.feed, digest("bounded"), max_quotes=1
        )
        r = t.append(self.q)
        self.assertEqual(t.append(self.q), r)
        with self.assertRaises(ValueError):
            t.append(
                replace(
                    self.q,
                    sequence=1,
                    occurred_at_utc=(self.when + timedelta(seconds=1)).isoformat(),
                    available_at_utc=(self.when + timedelta(seconds=1)).isoformat(),
                )
            )
        self.assertEqual(t.rows(), [r])


class CapitalAndLedger(unittest.TestCase):
    def assess(self, k):
        return assess_capital(**k)

    def test_fifty_dollar_account_is_synthetic_and_not_connected(self):
        a = PaperAccount(started_at=START).snapshot()
        self.assertEqual(
            (a["balance"], a["equity"], a["free_margin"]), ("50", "50", "50")
        )
        self.assertIsNone(a["connected_account_balance"])
        self.assertIs(a["execution_allowed"], False)

    def test_example_a_minimum_lot_is_unaffordable(self):
        r = capital_arithmetic(
            balance="50",
            equity="50",
            fill_price="2100",
            stop_reference="2098",
            direction="BULLISH",
            specification=specification("SYNTHETIC_XAUUSD"),
            costs=costs(),
            policy=policy(),
        )
        self.assertEqual(r["risk_budget"], "0.5")
        self.assertEqual(r["theoretical_position_size"], "0.0025")
        self.assertEqual(r["step_adjusted_position_size"], "0")
        self.assertFalse(r["minimum_lot_affordable"])

    def test_example_b_costs_consume_two_percent_budget(self):
        spec = specification("SYNTHETIC_XAUUSD")
        args = dict(
            balance="50",
            equity="50",
            fill_price="2100",
            stop_reference="2099",
            direction="BULLISH",
            specification=spec,
            policy=policy("0.02"),
        )
        self.assertEqual(
            capital_arithmetic(**args, costs=costs())["step_adjusted_position_size"],
            "0.01",
        )
        r = capital_arithmetic(
            **args, costs=replace(costs(), commission_per_lot_side="1")
        )
        self.assertFalse(r["minimum_lot_affordable"])

    def test_research_budgets_005_01_02_are_explicit(self):
        spec = specification("SYNTHETIC_XAUUSD")
        for frac, budget in [("0.005", "0.25"), ("0.01", "0.5"), ("0.02", "1")]:
            r = capital_arithmetic(
                balance="50",
                equity="50",
                fill_price="2100",
                stop_reference="2098",
                direction="BULLISH",
                specification=spec,
                costs=costs(),
                policy=policy(frac),
            )
            self.assertEqual(r["risk_budget"], budget)

    def test_authenticated_eligible_setup_both_directions(self):
        for mirror in (False, True):
            k, _, _ = setup(mirror)
            r = self.assess(k)
            self.assertEqual(r["status"], "HYPOTHETICAL_POSITION_ELIGIBLE", r)
            self.assertIs(r["execution_allowed"], False)
            self.assertEqual(
                r["assessment"]["structural_stop_reference"],
                k["risk"]["reference_geometry"]["invalidation_threshold"],
            )

    def test_volume_rounds_down_and_loss_does_not_exceed_budget(self):
        k, _, _ = setup()
        r = self.assess(k)["assessment"]
        self.assertLessEqual(
            Decimal(r["step_adjusted_position_size"]),
            Decimal(r["theoretical_position_size"]),
        )
        self.assertLessEqual(Decimal(r["estimated_loss"]), Decimal(r["risk_budget"]))
        self.assertEqual(Decimal(r["step_adjusted_position_size"]) % Decimal("0.01"), 0)

    def test_source_forgeries_and_live_labels_do_not_authorize_capital(self):
        k, _, _ = setup()
        for field, value in [
            ("reference_geometry", {}),
            ("execution_allowed", True),
            ("provenance", "LIVE_MT5"),
        ]:
            forged = deepcopy(k["risk"])
            forged[field] = value
            forged["sha256"] = digest(
                {a: b for a, b in forged.items() if a != "sha256"}
            )
            self.assertEqual(
                self.assess(dict(k, risk=forged))["status"],
                "CAPITAL_ASSESSMENT_UNAVAILABLE",
            )

    def test_missing_spec_and_costs_block_calculations(self):
        k, _, _ = setup()
        for changes in (
            dict(specification=None),
            dict(costs=None),
            dict(policy=None),
            dict(specification=replace(k["specification"], tick_value=None)),
            dict(costs=replace(k["costs"], commission_per_lot_side=None)),
        ):
            r = self.assess(dict(k, **changes))
            self.assertEqual(r["status"], "CAPITAL_ASSESSMENT_UNAVAILABLE")
            self.assertIsNone(r["assessment"])

    def test_unsupported_specs_and_wrong_feed_currency_or_expiry_block(self):
        k, _, _ = setup()
        for field, value in [
            ("margin_method", "UNKNOWN"),
            ("profit_currency", "EUR"),
            ("feed", "OTHER"),
            ("leverage", None),
            ("session_eligible", None),
            ("tick_value", "100"),
            ("verification", "BROKER_APPROVED"),
            ("expires_at_utc", START.isoformat()),
        ]:
            r = self.assess(
                dict(k, specification=replace(k["specification"], **{field: value}))
            )
            self.assertEqual(r["status"], "CAPITAL_ASSESSMENT_UNAVAILABLE", r)

    def test_insufficient_margin_and_cost_limit_reject_without_changing_stop(self):
        k, _, _ = setup()
        r = self.assess(
            dict(k, specification=replace(k["specification"], leverage="1"))
        )
        self.assertIn("INSUFFICIENT_FREE_MARGIN", r["reason_codes"])
        r = self.assess(
            dict(
                k,
                costs=replace(k["costs"], commission_per_lot_side="2"),
                policy=policy(max_cost_fraction_of_budget="0.01"),
            )
        )
        self.assertIn("TRANSACTION_COST_LIMIT", r["reason_codes"])
        self.assertEqual(
            r["assessment"]["structural_stop_reference"],
            k["risk"]["reference_geometry"]["invalidation_threshold"],
        )

    def test_account_snapshot_cannot_replace_producing_ledger(self):
        k, _, _ = setup()
        self.assertEqual(
            self.assess(dict(k, account=k["account"].snapshot()))["status"],
            "CAPITAL_ASSESSMENT_UNAVAILABLE",
        )

    def test_stale_analysis_and_future_account_state_block(self):
        k, _, _ = setup()
        self.assertEqual(
            self.assess(dict(k, as_of=k["as_of"] + timedelta(minutes=2)))["status"],
            "CAPITAL_ASSESSMENT_UNAVAILABLE",
        )
        a = PaperAccount(started_at=k["as_of"] + timedelta(seconds=1))
        self.assertEqual(
            self.assess(dict(k, account=a))["status"], "CAPITAL_ASSESSMENT_UNAVAILABLE"
        )

    def test_open_monitor_and_target_close_causal_net_accounting(self):
        k, a, b = setup()
        opened = open_position(k)
        self.assertEqual(opened["status"], "HYPOTHETICALLY_OPEN", opened)
        old = k["account"].snapshot()
        m = later(
            k,
            a,
            b,
            n=37,
            bid="2106.2",
            ask="2106.4",
            mutate=dict(open=2100, high=2106.3, low=2099.8, close=2106.2),
        )
        result = k["account"].observe(**m)
        self.assertEqual(result["status"], "HYPOTHETICALLY_CLOSED", result)
        state = k["account"].snapshot()
        p = state["closed_positions"][0]
        self.assertEqual(p["exit_fill"]["side"], "BID")
        self.assertEqual(
            state["balance"], str(Decimal("50") + Decimal(p["net_hypothetical_pnl"]))
        )
        self.assertEqual(old["closed_positions"], [])
        self.assertEqual(k["account"].metrics()["positions_closed"], 1)

    def test_short_entry_and_exit_sides(self):
        k, a, b = setup(True)
        self.assertEqual(open_position(k)["position"]["entry_fill"]["side"], "BID")
        m = later(
            k,
            a,
            b,
            n=37,
            bid="2093.6",
            ask="2093.8",
            mutate=dict(open=2100, high=2100.2, low=2093.7, close=2093.8),
        )
        r = k["account"].observe(**m)
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED", r)
        self.assertEqual(r["position"]["exit_fill"]["side"], "ASK")

    def test_gap_through_loss_can_exceed_estimate_no_account_replenishment(self):
        k, a, b = setup()
        r = open_position(k)
        estimate = Decimal(r["position"]["estimated_risk"])
        m = later(
            k,
            a,
            b,
            n=37,
            bid="2080",
            ask="2080.2",
            mutate=dict(open=2100, high=2100.2, low=2096, close=2097),
        )
        r = k["account"].observe(**m)
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED", r)
        loss = -Decimal(r["position"]["net_hypothetical_pnl"])
        self.assertGreater(loss, estimate)
        state = k["account"].snapshot()
        self.assertLess(Decimal(state["balance"]), Decimal("50"))
        self.assertEqual(state["consecutive_losses"], 1)
        self.assertGreater(Decimal(state["max_drawdown"]), 0)
        self.assertEqual(len(state["cash_events"]), 0)

    def test_duplicate_positions_fills_terminal_reopen_rejected(self):
        k, _, _ = setup()
        open_position(k)
        before = k["account"].journal()
        # Existing position makes capital unsuitable/unavailable; it never creates a second fill.
        r = open_position(k)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(before, k["account"].journal())
        with self.assertRaises(ValueError):
            k["account"].partial_exit("0.001")

    def test_missing_quote_interval_becomes_unresolved_not_success(self):
        k, a, b = setup()
        k["fill_policy"] = replace(k["fill_policy"], max_gap_ms=10000)
        open_position(k)
        m = later(k, a, b)
        r = k["account"].observe(**m)
        self.assertEqual(r["status"], "UNRESOLVED")
        self.assertIsNone(k["account"].snapshot()["equity"])
        with self.assertRaises(ValueError):
            k["account"].observe(**m)

    def test_source_failure_and_resource_limit_rollback(self):
        k, a, b = setup()
        open_position(k)
        before = k["account"].journal()
        m = later(k, a, b)
        forged = deepcopy(m["risk"])
        forged["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            k["account"].observe(**dict(m, risk=forged))
        self.assertEqual(before, k["account"].journal())
        bounded, a, b = setup()
        bounded["account"] = PaperAccount(started_at=START, max_events=3)
        open_position(bounded)
        before = bounded["account"].journal()
        m = later(bounded, a, b)
        with self.assertRaises(ValueError):
            bounded["account"].observe(**m)
        self.assertEqual(before, bounded["account"].journal())

    def test_blocked_interval_is_visible_without_manufactured_fill(self):
        k, _, _ = setup()
        open_position(k)
        r = k["account"].block_observation(
            "DATA_QUALITY_FAILED", as_of=k["as_of"] + timedelta(seconds=1)
        )
        self.assertEqual(r["account_lifecycle"], "UNRESOLVED")
        self.assertEqual(r["data_quality_exclusions"], 1)
        self.assertIsNone(r["open_positions"][0]["exit_fill"])

    def test_explicit_cash_events_no_automatic_reset(self):
        a = PaperAccount(started_at=START)
        a.cash_event("WITHDRAWAL", "2", as_of=START, reference="synthetic_cash_fixture")
        self.assertEqual(a.snapshot()["balance"], "48")
        self.assertEqual(
            Decimal(a.snapshot()["balance"]) * Decimal("0.01"), Decimal("0.48")
        )
        self.assertEqual(
            a.metrics()["net_return_status"],
            "UNAVAILABLE_UNRESOLVED_OR_EXTERNAL_CASH_FLOW",
        )
        with self.assertRaises(ValueError):
            a.cash_event(
                "DEPOSIT", "50", as_of=START, reference="synthetic_cash_fixture"
            )
        with self.assertRaises(ValueError):
            a.cash_event("RESET", "50", as_of=START, reference="reset")

    def test_deterministic_replay_prefix_and_future_append(self):
        logs = []
        for _ in range(2):
            k, a, b = setup()
            open_position(k)
            prefix = k["account"].journal()
            m = later(k, a, b)
            k["account"].observe(**m)
            logs.append(k["account"].journal())
            self.assertEqual(
                prefix["account"]["open_positions"][0]["state"], "HYPOTHETICALLY_OPEN"
            )
        self.assertEqual(logs[0], logs[1])
        # Source future append leaves the frozen account prefix and its original report unchanged.
        k, a, b = setup()
        open_position(k)
        prefix = k["account"].journal()
        later(k, a, b)
        self.assertEqual(prefix, k["account"].journal())

    def test_decimal_context_and_json_are_deterministic(self):
        k, _, _ = setup()
        expected = self.assess(k)
        with localcontext() as c:
            c.prec = 2
            actual = self.assess(k)
        self.assertEqual(actual, expected)
        self.assertEqual(json.loads(json.dumps(actual)), actual)
