"""Independent E4.6 contracts; all data invented. Not external human approval."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
import unittest
from paper_fixtures import setup, later, open_position, shifted_snapshot, policy
from risk_fixtures import START
from iat.intelligence.paper_contracts import SyntheticQuote, SyntheticQuoteTape
from iat.intelligence.capital_intelligence import assess_capital
from iat.intelligence.paper_account import PaperAccount, validate_paper_journal
from iat.intelligence.risk_intelligence import assess_risk
from iat.intelligence.strategy_replay import digest


class IndependentPaperReview(unittest.TestCase):
    def test_specification_not_effective_at_decision_cannot_authorize_past_fill(self):
        k, _, _ = setup()
        for extra in (0.5, 1.5):
            spec = replace(
                k["specification"],
                effective_at_utc=(
                    START + timedelta(minutes=36, seconds=extra)
                ).isoformat(),
            )
            r = assess_capital(
                **dict(
                    k,
                    specification=spec,
                    as_of=START + timedelta(minutes=36, seconds=2),
                )
            )
            self.assertEqual(r["status"], "CAPITAL_ASSESSMENT_UNAVAILABLE")

    def test_daily_loss_uses_actual_fill_day_not_later_processing_cutoff(self):
        offset = timedelta(hours=8, minutes=20)
        k, a, b = setup(offset=offset)
        k["fill_policy"] = replace(
            k["fill_policy"], max_analysis_age_ms=120000, max_gap_ms=300000
        )
        open_position(k)
        for n in (37, 38):
            v, c, i = shifted_snapshot(n, a, b, offset)
            k["risk_inputs"]["exit_source"].record(v, c, view_inputs=i)
        a[38].update(open=2100, high=2100.2, low=2096, close=2097)
        v, c, i = shifted_snapshot(39, a, b, offset)
        current = k["risk_inputs"]["exit_source"].record(v, c, view_inputs=i)
        inputs = dict(k["risk_inputs"], current_e2=current, as_of=c.analysis_at)
        risk = assess_risk(**inputs)
        quote_time = (
            START + offset + timedelta(minutes=39, seconds=59, milliseconds=900)
        )
        processing = quote_time + timedelta(milliseconds=200)
        q = k["tape"].append(
            SyntheticQuote(
                k["tape"].symbol,
                k["tape"].feed,
                1,
                quote_time.isoformat(),
                quote_time.isoformat(),
                "2097",
                "2097.2",
                True,
                True,
            )
        )
        r = k["account"].observe(
            risk, risk_inputs=inputs, tape=k["tape"], quote=q, as_of=processing
        )
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED")
        self.assertEqual(
            set(k["account"].snapshot()["daily_losses"]),
            {quote_time.date().isoformat()},
        )

    def test_forged_quote_and_journal_do_not_authenticate_after_rehash(self):
        k, _, _ = setup()
        r = deepcopy(k["quote"])
        r["quote"]["bid"] = "1"
        r["sha256"] = digest({a: b for a, b in r.items() if a != "sha256"})
        self.assertEqual(
            assess_capital(**dict(k, quote=r))["status"],
            "CAPITAL_ASSESSMENT_UNAVAILABLE",
        )
        journal = k["account"].journal()
        journal["account"]["balance"] = "999"
        journal["sha256"] = digest({a: b for a, b in journal.items() if a != "sha256"})
        with self.assertRaises(ValueError):
            validate_paper_journal(journal, source=k["account"])

    def test_input_policies_do_not_admit_unknown_costs_or_mapping(self):
        k, _, _ = setup()
        for change in (
            dict(costs=replace(k["costs"], financing_per_lot_day=None)),
            dict(policy=replace(k["policy"], reference_mapping=None)),
        ):
            r = assess_capital(**dict(k, **change))
            self.assertIsNone(r["assessment"])

    def test_downward_rounding_and_minimum_size_do_not_move_the_level(self):
        k, _, _ = setup()
        original = k["risk"]["reference_geometry"]["invalidation_threshold"]
        r = assess_capital(
            **dict(
                k,
                specification=replace(
                    k["specification"], contract_size="100", tick_value="1"
                ),
            )
        )
        self.assertIn("MINIMUM_LOT_EXCEEDS_RISK_BUDGET", r["reason_codes"])
        self.assertEqual(r["assessment"]["structural_stop_reference"], original)
        self.assertLessEqual(
            Decimal(r["assessment"]["step_adjusted_position_size"]),
            Decimal(r["assessment"]["theoretical_position_size"]),
        )

    def test_profit_does_not_erase_previously_observed_drawdown(self):
        k, a, b = setup()
        open_position(k)
        k["account"].observe(**later(k, a, b, bid="2099", ask="2099.2"))
        old = k["account"].snapshot()
        r = k["account"].observe(
            **later(
                k,
                a,
                b,
                n=38,
                bid="2106.2",
                ask="2106.4",
                mutate=dict(open=2100, high=2106.3, low=2099.8, close=2106.2),
            )
        )
        self.assertEqual(r["status"], "HYPOTHETICALLY_CLOSED")
        self.assertGreaterEqual(
            Decimal(k["account"].snapshot()["max_drawdown"]),
            Decimal(old["max_drawdown"]),
        )

    def test_existing_v1_margin_warning_never_fakes_liquidation(self):
        k, a, b = setup()
        open_position(k)
        r = k["account"].observe(**later(k, a, b, bid="1800", ask="1800.2"))
        self.assertEqual(r["status"], "UNRESOLVED")
        self.assertIsNone(r["position"]["exit_fill"])

    def test_spread_and_fees_have_distinct_single_accounting_effects(self):
        k, a, b = setup()
        k["costs"] = replace(k["costs"], commission_per_lot_side="0.1")
        opened = open_position(k)
        volume = Decimal(opened["position"]["volume"])
        r = k["account"].observe(
            **later(
                k,
                a,
                b,
                bid="2097",
                ask="2097.2",
                mutate=dict(open=2100, high=2100.2, low=2096, close=2097),
            )
        )
        p = r["position"]
        gross = (Decimal("2097") - Decimal("2100.1")) * volume
        self.assertEqual(Decimal(p["gross_hypothetical_pnl"]), gross)
        self.assertEqual(
            Decimal(p["net_hypothetical_pnl"]), gross - volume * Decimal("0.2")
        )

    def test_failed_clock_and_source_checks_roll_back_every_ledger_field(self):
        k, a, b = setup()
        open_position(k)
        old = k["account"].journal()
        m = later(k, a, b)
        m["risk"] = deepcopy(m["risk"])
        m["risk"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            k["account"].observe(**m)
        self.assertEqual(old, k["account"].journal())
        with self.assertRaises(ValueError):
            k["account"].block_observation("BACKWARD", as_of=START)
        self.assertEqual(old, k["account"].journal())

    def test_exhausted_account_retains_negative_balance_and_no_cash_events(self):
        k, a, b = setup()
        open_position(k)
        k["account"].observe(
            **later(
                k,
                a,
                b,
                bid="1000",
                ask="1000.2",
                mutate=dict(open=2100, high=2100.2, low=2096, close=2097),
            )
        )
        s = k["account"].snapshot()
        self.assertLess(Decimal(s["balance"]), 0)
        self.assertEqual(s["account_lifecycle"], "EXHAUSTED")
        self.assertEqual(s["cash_events"], [])

    def test_future_append_cannot_rewrite_prior_entry_or_account_report(self):
        k, a, b = setup()
        opened = open_position(k)
        old = k["account"].journal()
        later(k, a, b)
        self.assertEqual(old, k["account"].journal())
        self.assertEqual(json.loads(json.dumps(opened)), opened)

    def test_live_label_or_future_quote_never_authorizes_entry(self):
        k, _, _ = setup()
        r = deepcopy(k["risk"])
        r["provenance"] = "LIVE_MT5"
        r["sha256"] = digest({a: b for a, b in r.items() if a != "sha256"})
        self.assertEqual(
            assess_capital(**dict(k, risk=r))["status"],
            "CAPITAL_ASSESSMENT_UNAVAILABLE",
        )
        self.assertEqual(
            assess_capital(**dict(k, as_of=k["as_of"] - timedelta(seconds=1)))[
                "status"
            ],
            "CAPITAL_ASSESSMENT_UNAVAILABLE",
        )
        for key, val in [
            ("signal", "WAIT"),
            ("execution_allowed", False),
            ("exness", "BLOCKED"),
            ("historical_comparisons", "NOT_RUN"),
        ]:
            self.assertEqual(k["account"].snapshot()[key], val)

    def test_same_feed_label_with_missing_producer_history_is_not_continuity(self):
        k, a, b = setup()
        open_position(k)
        before = k["account"].journal()
        current = later(k, a, b)
        replacement = SyntheticQuoteTape(
            k["tape"].symbol, k["tape"].feed, k["tape"].dataset_sha256
        )
        row = replacement.append(SyntheticQuote(**current["quote"]["quote"]))
        with self.assertRaisesRegex(ValueError, "QUOTE_SOURCE_HISTORY_MISMATCH"):
            k["account"].observe(**dict(current, tape=replacement, quote=row))
        self.assertEqual(before, k["account"].journal())
        replayed = SyntheticQuoteTape(k["tape"].symbol,k["tape"].feed,k["tape"].dataset_sha256)
        for prior in k["tape"].rows():
            actual = replayed.append(SyntheticQuote(**prior["quote"]))
        self.assertEqual(k["account"].observe(**dict(current,tape=replayed,quote=actual))["status"],"MONITORING")
