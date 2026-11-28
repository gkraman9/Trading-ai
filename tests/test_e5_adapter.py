"""Adversarial E5 software checks. Every price/review here is synthetic or mocked."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from e5_fixtures import source
from risk_fixtures import START
from paper_fixtures import policy
from protection_fixtures import stop_policy, liquidation_policy
from iat.e5_protocol import protocol, baseline
from iat.e5_source import (
    bar_availability,
    load_source,
    _review,
    BAR_COLUMNS,
    ASSERTIONS,
    AdmissionError,
)
from iat.e5_replay import replay_source, common_prefix, run_historical
from iat.paper_source_scope import current_source, source_scope
from iat.intelligence.entry_intelligence import EntryResearchSession
from iat.intelligence.paper_contracts import SyntheticQuote, SyntheticQuoteTape
from iat.intelligence.protected_paper import ProtectedPaperAccount
from iat.intelligence.strategy_replay import digest
from iat.intelligence.market_view import build_market_view_v3


def bar_bytes(s, change=None):
    lines = [",".join(BAR_COLUMNS)]
    for i, row in enumerate(s._availability.values()):
        r = deepcopy(row)
        if change:
            change(i, r)
        lines.append(",".join(r[k] for k in BAR_COLUMNS))
    return ("\n".join(lines) + "\n").encode()


class E5ProtocolAndAdmission(unittest.TestCase):
    def test_frozen_policy_values_match_e47_without_higher_risk(self):
        self.assertEqual(baseline()["capital"], asdict(policy()))
        self.assertEqual(baseline()["stop"], asdict(stop_policy()))
        self.assertEqual(baseline()["liquidation"], asdict(liquidation_policy()))
        self.assertEqual(protocol(), protocol())
        self.assertEqual(baseline()["starting_capital"], "50")

    def test_missing_inputs_publish_exact_requirements_and_unmeasured_metrics(self):
        with patch("iat.e5_replay.ProtectedPaperAccount") as account:
            r = run_historical()
        account.assert_not_called()
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIsNone(r["historical_metrics"])
        self.assertEqual(r["performance_status"], "UNMEASURED")
        self.assertEqual(
            r["comparisons"], {"full_full": "NOT_RUN", "prefix": "NOT_RUN"}
        )
        self.assertIn("E5_PLAN_AND_INDEPENDENT_REVIEW_REQUIRED", r["reason_codes"])
        self.assertIn("bar_availability", r["evidence_requirements"]["inputs"])

    def test_caller_provenance_or_arbitrary_object_is_not_admission(self):
        with self.assertRaises(ValueError):
            with source_scope(object()):
                pass
        session = EntryResearchSession()
        s = source()
        c, v, vi = s.context((START + timedelta(minutes=36)).isoformat())
        hist = replace(c, provenance="HISTORICAL_RESEARCH")
        view = build_market_view_v3(hist, **vi)
        self.assertEqual(
            session.record(view, hist, view_inputs=vi)["status"], "BLOCKED"
        )
        self.assertIsNone(current_source())

    def test_source_context_cannot_be_mutated_after_authentication(self):
        s = source()
        at = (START + timedelta(minutes=36)).isoformat()
        with source_scope(s):
            e = EntryResearchSession()
            c, v, vi = s.context(at)
            self.assertNotEqual(e.record(v, c, view_inputs=vi)["status"], "BLOCKED")
            c.context["classification"] = "FORGED"
            v = build_market_view_v3(c, **vi)
            self.assertEqual(e.record(v, c, view_inputs=vi)["status"], "BLOCKED")

    def test_source_snapshot_public_configuration_is_detached(self):
        s = source()
        p = s.policies
        p["capital"]["risk_fraction"] = "1"
        self.assertEqual(s.policies, baseline())
        with self.assertRaises(AttributeError):
            s.binding = "0" * 64
        rows = s.quote_rows()
        rows[0]["bid"] = "1"
        self.assertNotEqual(rows, s.quote_rows())

    def test_wrong_source_scope_and_scope_cleanup(self):
        a, b = source(), source()
        with source_scope(a):
            account = ProtectedPaperAccount(started_at=START)
            before = account.journal()
        with self.assertRaises(ValueError):
            account.block_observation("FORGED", as_of=START)
        with source_scope(b):
            with self.assertRaises(ValueError):
                account.snapshot()
        with source_scope(a):
            self.assertEqual(before, account.journal())
        self.assertIsNone(current_source())

    def test_scope_cannot_change_starting_capital_or_tape_source(self):
        s = source()
        with source_scope(s):
            with self.assertRaises(ValueError):
                ProtectedPaperAccount(started_at=START, starting_balance="5000")
            with self.assertRaises(ValueError):
                SyntheticQuoteTape("XAUUSD", s.specification.feed, "0" * 64)

    def test_frozen_capital_and_protection_policies_cannot_be_changed_in_scope(self):
        from iat.intelligence.capital_intelligence import assess_capital, CapitalPolicy
        from iat.intelligence.paper_contracts import FillPolicy
        from iat.intelligence.protection_contracts import (
            assess_protection_plan,
            ProtectiveStopPolicy,
            LiquidationPolicy,
        )

        s = source()
        with source_scope(s):
            a = ProtectedPaperAccount(started_at=START)
            tape = SyntheticQuoteTape("XAUUSD", s.specification.feed, s.binding)
            result = assess_capital(
                None,
                risk_inputs={},
                account=a,
                tape=tape,
                quote=None,
                specification=s.specification,
                costs=s.costs,
                policy=policy(risk="0.02"),
                fill_policy=FillPolicy(**baseline()["fill"]),
                as_of=START,
            )
            self.assertIn(
                "E5_FROZEN_CAPITAL_OR_FILL_POLICY_MISMATCH", result["reason_codes"]
            )
            with self.assertRaisesRegex(
                ValueError, "E5_FROZEN_PROTECTION_POLICY_MISMATCH"
            ):
                assess_protection_plan(
                    None,
                    risk_inputs={},
                    account=a,
                    tape=tape,
                    quote=None,
                    specification=s.specification,
                    costs=s.costs,
                    policy=CapitalPolicy(**baseline()["capital"]),
                    fill_policy=FillPolicy(**baseline()["fill"]),
                    stop_policy=replace(
                        stop_policy(), latency_ms=1, trigger_quote_can_fill=False
                    ),
                    liquidation_policy=LiquidationPolicy(**baseline()["liquidation"]),
                    as_of=START,
                )

    def test_native_quote_mutation_and_synthetic_relabel_are_rejected(self):
        s = source()
        r = s.quote_rows()[0]
        with source_scope(s):
            args = [
                "XAUUSD",
                s.specification.feed,
                int(r["sequence"]),
                r["occurred_at_utc"],
                r["available_at_utc"],
                r["bid"],
                r["ask"],
                True,
                True,
            ]
            self.assertEqual(
                SyntheticQuote(*args, provenance=s.provenance).bid, r["bid"]
            )
            args[5] = "1"
            with self.assertRaises(ValueError):
                SyntheticQuote(*args, provenance=s.provenance)
            args[5] = r["bid"]
            with self.assertRaises(ValueError):
                SyntheticQuote(*args, provenance="HISTORICAL_RESEARCH")

    def test_no_deposits_and_no_unreviewed_specification_change(self):
        s = source()
        r = s.quote_rows()[0]
        with source_scope(s):
            a = ProtectedPaperAccount(started_at=START)
            with self.assertRaises(ValueError):
                a.cash_event("DEPOSIT", "100", as_of=START, reference="NO")
            q = dict(
                symbol="XAUUSD", feed=s.specification.feed, bid=r["bid"], ask=r["ask"]
            )
            s.specification.validate(q, r["available_at_utc"])
            with self.assertRaises(ValueError):
                replace(s.specification, leverage="9999").validate(
                    q, r["available_at_utc"]
                )
            with self.assertRaises(ValueError):
                replace(s.costs, slippage_price_per_fill="1").validate()
        with self.assertRaises(ValueError):
            s.costs.validate()

    def test_plan_hash_mismatch_does_not_create_account(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "plan.json"
            path.write_text(
                json.dumps(
                    dict(version=1, protocol_sha256=protocol()["sha256"], inputs={})
                )
            )
            r = run_historical(path, "missing-review.json")
            self.assertEqual(r["status"], "BLOCKED")
            self.assertIsNone(r["replay"])

    def test_missing_input_role_is_actionable_and_private(self):
        from iat.e5_source import PLAN_INPUTS

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "plan.json"
            path.write_text(
                json.dumps(
                    dict(
                        version=1,
                        protocol_sha256=protocol()["sha256"],
                        inputs={
                            k: dict(file=k + ".json", sha256="0" * 64)
                            for k in PLAN_INPUTS
                        },
                    )
                )
            )
            r = run_historical(path, "missing-review.json")
            self.assertIn(
                "E5_INPUT_MANIFEST_UNAVAILABLE_OR_HASH_MISMATCH", r["reason_codes"]
            )
            self.assertNotIn(d, json.dumps(r))

    def test_independent_review_is_bound_and_not_self_approval(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            evidence = b"SYNTHETIC evidence only"
            (root / "e.txt").write_bytes(evidence)
            bundle = source()._bundle
            scope = dict(
                start=min(v["start"] for v in bundle["windows"]["warmup"].values()),
                end=bundle["windows"]["outcome"]["end"],
            )
            raw = b"SYNTHETIC plan"
            r = dict(
                version=1,
                kind="E5_INDEPENDENT_ADAPTER_REVIEW",
                preparer_code=bundle["preparer_code"],
                reviewer_code="synthetic-independent",
                independently_reviewed=True,
                decision="APPROVED",
                reviewed_at_utc=(START + timedelta(days=1)).isoformat(),
                plan_sha256=sha256(raw).hexdigest(),
                protocol_sha256=protocol()["sha256"],
                assertions={
                    k: dict(
                        status="VERIFIED",
                        file="e.txt",
                        sha256=sha256(evidence).hexdigest(),
                        scope=scope,
                    )
                    for k in ASSERTIONS
                },
            )
            self.assertEqual(
                _review(json.dumps(r).encode(), raw, root, bundle)["reviewer_code"],
                "synthetic-independent",
            )
            for change in (
                dict(reviewer_code=bundle["preparer_code"]),
                dict(independently_reviewed=1),
                dict(plan_sha256="0" * 64),
                dict(decision="PENDING"),
            ):
                with self.assertRaises(ValueError):
                    _review(json.dumps(dict(r, **change)).encode(), raw, root, bundle)

    def test_cli_missing_inputs_is_atomic_and_nonoverwriting(self):
        script = (
            Path(__file__).resolve().parents[1] / "diagnostics/e5_historical_paper.py"
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "private.json"
            cmd = [sys.executable, str(script), "--report-path", str(path)]
            r = subprocess.run(cmd, capture_output=True)
            self.assertEqual(r.returncode, 3, r.stderr)
            original = path.read_bytes()
            report = json.loads(original)
            self.assertEqual(report["historical_validation"], "PENDING")
            self.assertIs(report["execution_allowed"], False)
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 1)
            self.assertEqual(original, path.read_bytes())


class E5BarChronology(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = source()

    def test_explicit_finality_and_availability_cover_every_candle(self):
        self.assertEqual(
            len(bar_availability(bar_bytes(self.source), self.source._dataset)),
            len(self.source._availability),
        )

    def test_unfinished_corrected_missing_and_duplicate_bars_reject(self):
        for field, val in (
            ("finality", "FORMING"),
            ("revision", "1"),
            ("available_at_utc", START.isoformat()),
        ):
            raw = bar_bytes(
                self.source, lambda i, r: r.update({field: val}) if i == 0 else None
            )
            with self.assertRaises(ValueError):
                bar_availability(raw, self.source._dataset)
        raw = bar_bytes(self.source)
        with self.assertRaises(ValueError):
            bar_availability(
                b"\n".join(raw.splitlines()[:-1]) + b"\n", self.source._dataset
            )
        with self.assertRaises(ValueError):
            bar_availability(raw + raw.splitlines()[1] + b"\n", self.source._dataset)

    def test_partial_m5_boundary_is_not_rounded(self):
        from test_session_v2 import synthetic_v2, bounded_day
        from iat.session_config import compile_session_config

        s = source()
        c = synthetic_v2()
        c["weekdays"]["thu"] = bounded_day("09:00:00", "15:38:00")
        data = deepcopy(s._dataset)
        data.calendar = compile_session_config(c)
        with self.assertRaisesRegex(
            ValueError, "E5_PARTIAL_OR_UNKNOWN_BAR_UNSUPPORTED"
        ):
            bar_availability(bar_bytes(s), data)

    def test_tick_duplicates_corrections_gaps_and_future_occurrence_fail_closed(self):
        from iat.paper_readiness import audit_quote_events
        from test_e47_readiness import quote_bytes

        for key, value in [
            ("sequence", "0"),
            ("sequence", "9"),
            ("revision", "1"),
            ("occurred_at_utc", (START + timedelta(days=1)).isoformat()),
        ]:
            raw = quote_bytes(lambda i, r: r.update({key: value}) if i == 1 else None)
            with self.assertRaises(ValueError):
                audit_quote_events(
                    raw,
                    start=START.isoformat(),
                    end=(START + timedelta(seconds=15)).isoformat(),
                )

    def test_verified_overnight_gap_differs_from_missing_open_session_capture(self):
        from types import SimpleNamespace
        from iat.e5_source import quote_gap_audit

        a = START
        b = a + timedelta(hours=1)
        cal = SimpleNamespace(
            windows=((a - timedelta(hours=1), a), (b, b + timedelta(hours=1)))
        )
        rows = [
            {"available_at_utc": (a - timedelta(seconds=1)).isoformat()},
            {"available_at_utc": (b + timedelta(seconds=1)).isoformat()},
        ]
        self.assertEqual(
            quote_gap_audit(rows, cal, 120000)["scheduled_closure_gaps"], 1
        )
        rows[0]["available_at_utc"] = (a - timedelta(minutes=5)).isoformat()
        self.assertEqual(
            quote_gap_audit(rows, cal, 120000)["unexpected_open_session_gaps"], 1
        )

    def test_warmup_uses_source_availability_not_just_bar_count(self):
        from iat.e5_source import warmup_audit

        s = source()
        cutoff = s.windows["evaluation"]["start"]
        result = warmup_audit(s._dataset, s._availability, cutoff)
        self.assertEqual(result["required_closed_bars_per_frame"], 15)
        availability = deepcopy(s._availability)
        for (tf, _), r in availability.items():
            if tf == "M5":
                r["available_at_utc"] = (START + timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(
            ValueError, "E5_WARMUP_UNAVAILABLE_OR_INSUFFICIENT"
        ):
            warmup_audit(s._dataset, availability, cutoff)

    def test_quote_vs_new_position_permission_is_distinct(self):
        from test_session_v2 import synthetic_v2, window
        from iat.session_config import compile_session_config

        s = source()
        config = synthetic_v2()
        config["weekdays"]["thu"]["phases"] = [window(state="CLOSE_ONLY")]
        s._dataset.calendar = compile_session_config(config)
        quotation, opening = s.permissions(
            (START + timedelta(minutes=36)).isoformat(),
            (START + timedelta(minutes=36)).isoformat(),
        )
        self.assertTrue(quotation)
        self.assertFalse(opening)

    def test_late_m5_publication_cannot_enter_earlier_context(self):
        s = source(late_bar=True)
        before, _, _ = s.context((START + timedelta(minutes=35)).isoformat())
        after, _, _ = s.context((START + timedelta(minutes=36)).isoformat())
        self.assertLess(
            utc(before.observed_facts["M5"]["data_as_of"]),
            START + timedelta(minutes=35),
        )
        self.assertEqual(
            utc(after.observed_facts["M5"]["data_as_of"]), START + timedelta(minutes=35)
        )

    def test_future_price_tail_cannot_change_earlier_context(self):
        a, b = source(), source()
        b._dataset.rows["M1"][-1]["close"] = 99999
        x, _, _ = a.context((START + timedelta(minutes=36)).isoformat())
        y, _, _ = b.context((START + timedelta(minutes=36)).isoformat())
        self.assertEqual(x, y)


class E5Replay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = source()
        cls.full = replay_source(cls.s)
        cls.again = replay_source(source())
        cls.prefix = replay_source(
            source(), cutoff=(START + timedelta(minutes=36, seconds=1)).isoformat()
        )

    def test_two_independent_full_replays_match(self):
        self.assertEqual(self.full, self.again)

    def test_common_cutoff_prefix_equivalence(self):
        self.assertTrue(common_prefix(self.full, self.prefix))

    def test_source_binding_or_event_corruption_rejects_prefix(self):
        forged = deepcopy(self.prefix)
        forged["source_binding"] = "0" * 64
        with self.assertRaises(ValueError):
            common_prefix(self.full, forged)
        forged = deepcopy(self.prefix)
        forged["journal"]["events"][0]["balance"] = "99999"
        with self.assertRaises(ValueError):
            common_prefix(self.full, forged)

    def test_unchanged_engine_records_closed_and_competing_opportunity_once(self):
        self.assertEqual(self.full["opportunity_counts"], {"CLOSED": 1, "REJECTED": 1})
        self.assertEqual(self.full["journal"]["metrics"]["positions_closed"], 1)
        self.assertEqual(
            self.full["cost_breakdown"]["total_explicit_charges"],
            self.full["journal"]["account"]["transaction_costs"],
        )
        self.assertLess(Decimal(self.full["journal"]["account"]["balance"]), 50)
        self.assertEqual(self.full["provenance"], "SYNTHETIC_RESEARCH")

    def test_incomplete_prefix_keeps_open_position_and_never_forces_fill(self):
        self.assertEqual(self.prefix["open_at_cutoff"], 1)
        self.assertEqual(self.prefix["journal"]["metrics"]["positions_closed"], 0)
        self.assertIsNone(self.prefix["performance"]["net_expectancy"])

    def test_outcome_window_has_no_new_qualifications_or_deposits(self):
        self.assertEqual(self.full["journal"]["account"]["cash_events"], [])
        self.assertTrue(
            all(
                utc(x["qualified_at_utc"]) <= START + timedelta(minutes=38)
                for x in self.full["opportunities"]
            )
        )
        self.assertEqual(self.full["window_counts"]["OUTCOME"], 2)

    def test_usd50_minimum_lot_rejection_is_not_bypassed(self):
        r = replay_source(source(minimum_contract=True))
        self.assertEqual(r["journal"]["account"]["balance"], "50")
        self.assertEqual(r["journal"]["metrics"]["positions_opened"], 0)
        self.assertIn("MINIMUM_LOT_EXCEEDS_RISK_BUDGET", r["reason_counts"])

    def test_gap_through_stop_and_exhaustion_are_not_clamped(self):
        r = replay_source(source(prices=[("2099.9", "2100.1"), ("1000", "1000.2")]))
        self.assertLess(Decimal(r["journal"]["account"]["balance"]), 0)
        self.assertEqual(r["journal"]["account"]["account_lifecycle"], "EXHAUSTED")

    def test_spread_widening_and_missing_exit_evidence_remain_visible(self):
        r = replay_source(source(prices=[("2099.9", "2100.1"), ("2099.9", "2110")]))
        self.assertGreater(r["open_at_cutoff"], 0)
        self.assertEqual(r["journal"]["metrics"]["positions_closed"], 0)
        self.assertEqual(r["performance"]["resolved_trades"], 0)

    def test_late_native_receipt_does_not_refresh_old_quote(self):
        r = replay_source(source(receipt_delay=5))
        self.assertEqual(r["journal"]["metrics"]["positions_opened"], 0)
        self.assertIn("QUOTE_STALE", r["reason_counts"])

    def test_declared_adverse_slippage_is_applied_once_per_fill(self):
        r = replay_source(source(slippage="0.1"))
        p = r["journal"]["account"]["closed_positions"][0]
        self.assertEqual(Decimal(p["entry_fill"]["price"]), Decimal("2100.2"))
        self.assertEqual(Decimal(p["exit_fill"]["price"]), Decimal("2097.6"))

    def test_historical_namespace_is_not_relabelled_synthetic_in_kernel(self):
        # Private invented capability tests producer plumbing, not real admission.
        r = replay_source(source(historical=True))
        self.assertEqual(r["provenance"], "HISTORICAL_RESEARCH")
        self.assertEqual(r["journal"]["provenance"], "HISTORICAL_RESEARCH")
        p = r["journal"]["account"]["closed_positions"][0]
        self.assertEqual(p["entry_fill"]["provenance"], "HISTORICAL_RESEARCH")
        self.assertEqual(
            p["entry_fill"]["fill_time_basis"],
            "DECLARED_HISTORICAL_RECEIPT_SIDE_PRICE_MODEL",
        )
        self.assertEqual(r["journal"]["account"]["starting_balance"], "50")

    def test_supported_readonly_safety_flags(self):
        for r in (self.full, self.prefix, run_historical()):
            self.assertEqual(r["signal"], "WAIT")
            self.assertIs(r["execution_allowed"], False)
            self.assertEqual(r["exness"], "BLOCKED")
            self.assertEqual(r["historical_validation"], "PENDING")


from iat.replay_dataset import utc

if __name__ == "__main__":
    unittest.main()
