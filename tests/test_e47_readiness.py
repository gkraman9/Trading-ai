"""Synthetic schema fixtures and mocked gate responses, never historical approval."""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from iat.paper_readiness import (
    historical_paper_preflight,
    audit_quote_events,
    performance_readiness,
    validate_performance_readiness,
    ARTIFACTS,
    EVIDENCE,
    QUOTE_COLUMNS,
)
from iat.intelligence.strategy_replay import digest
from iat.intelligence.paper_account import PaperAccount, PaperExitPolicy
from iat.intelligence.paper_contracts import FillPolicy
from paper_fixtures import specification, costs, policy
from protection_fixtures import (
    setup,
    open_position,
    quote,
    observe,
    stop_policy,
    liquidation_policy,
)
from risk_fixtures import START


def quote_bytes(changes=None):
    lines = [",".join(QUOTE_COLUMNS)]
    for i in range(16):
        stamp = (START + timedelta(seconds=i)).isoformat()
        item = dict(
            zip(QUOTE_COLUMNS, [str(i), stamp, stamp, "2100", "2100.2", "0", "FINAL"])
        )
        if changes:
            changes(i, item)
        lines.append(",".join(item[k] for k in QUOTE_COLUMNS))
    return ("\n".join(lines) + "\n").encode()


def schema_bundle(root):
    """Only exercise new schema after a MOCKED gate; never invokes real qualification success."""
    ts = lambda n: (START + timedelta(seconds=n)).isoformat()
    window = lambda a, b: dict(start=ts(a), end=ts(b))
    metadata = dict(
        dataset_kind="INDEPENDENT_HISTORICAL",
        checksums={"M1": "mock", "M5": "mock"},
        lineage={"feed_id": "SYNTHETIC_SCHEMA_FIXTURE"},
        source={"retrieved_at_utc": ts(20)},
        evaluation=window(5, 10),
        warmup={"M1": window(0, 5), "M5": window(0, 5)},
    )
    bundle = dict(
        version=1,
        symbol="XAUUSD",
        feed_id="SYNTHETIC_SCHEMA_FIXTURE",
        dataset_id=digest(metadata),
        preparer_code="synthetic-preparer",
        reviewer_code="synthetic-reviewer",
        independently_reviewed=True,
        reviewed_at_utc=ts(21),
        windows=dict(
            warmup=metadata["warmup"],
            evaluation=metadata["evaluation"],
            outcome=window(10, 15),
        ),
        artifacts={},
        evidence={},
    )

    def save(name, raw):
        (root / name).write_bytes(raw)
        return dict(file=name, sha256=sha256(raw).hexdigest())

    spec = asdict(specification("XAUUSD"))
    for k in (
        "symbol",
        "feed",
        "source",
        "effective_at_utc",
        "expires_at_utc",
        "verification",
        "version",
        "session_eligible",
    ):
        del spec[k]
    c = asdict(costs())
    del c["version"]
    del c["provenance"]

    def dated(kind, values):
        return dict(
            version=1,
            kind=kind,
            symbol="XAUUSD",
            feed_id=bundle["feed_id"],
            available_at_utc=ts(-1),
            effective_from_utc=ts(-1),
            effective_until_utc=ts(60),
            values=values,
        )

    policies = dict(
        version=1,
        starting_capital="50",
        baseline="UNCHANGED_M1_M5",
        fill=asdict(FillPolicy(0, 1000, 1000, 1000)),
        capital=asdict(policy()),
        exit=asdict(PaperExitPolicy(True, True, True)),
        stop=asdict(stop_policy()),
        liquidation=asdict(liquidation_policy()),
    )
    for k in ARTIFACTS:
        data = quote_bytes() if k == "quote_events" else b"SYNTHETIC raw schema fixture"
        if k in ("specification", "costs", "policies"):
            obj = (
                dated("INSTRUMENT_SPECIFICATION", spec)
                if k == "specification"
                else dated("TRADING_COSTS", c) if k == "costs" else policies
            )
            data = json.dumps(obj).encode()
        bundle["artifacts"][k] = save(k + ".fixture", data)
    for k in EVIDENCE:
        ref = save(
            k + ".txt", b"SYNTHETIC evidence fixture: not actual provider documentation"
        )
        bundle["evidence"][k] = dict(
            **ref,
            status="VERIFIED",
            scope=window(0, 15),
            reference="synthetic:mock-only",
            explanation="Invented schema test only"
        )
    return bundle, metadata


class E47Readiness(unittest.TestCase):
    def run_bundle(self, change=None, file_change=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, metadata = schema_bundle(root)
            if change:
                change(bundle)
            if file_change:
                key, transform = file_change
                path = root / bundle["artifacts"][key]["file"]
                path.write_bytes(transform(path.read_bytes()))
                bundle["artifacts"][key]["sha256"] = sha256(
                    path.read_bytes()
                ).hexdigest()
            path = root / "paper.json"
            path.write_text(json.dumps(bundle))
            gate = dict(
                status="HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED",
                reason_codes=[],
                dataset_id=digest(metadata),
            )
            with patch(
                "iat.paper_readiness.qualify_historical", return_value=gate
            ), patch(
                "iat.paper_readiness.load_dataset",
                return_value=SimpleNamespace(metadata=metadata),
            ):
                return historical_paper_preflight("mock-only", "mock-only", path)

    def test_missing_all_inputs_returns_specific_blockers_and_no_metrics(self):
        r = historical_paper_preflight()
        self.assertIn("DATASET_UNAVAILABLE", r["reason_codes"])
        self.assertIn("PAPER_BID_ASK_AVAILABILITY_REQUIRED", r["reason_codes"])
        self.assertIsNone(r["historical_metrics"])
        self.assertEqual(r["replay_status"], "NOT_RUN")

    def test_real_loader_synthetic_manifest_cannot_pass_source_gate(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "config/examples/replay.synthetic/manifest.json"
        )
        r = historical_paper_preflight(path, bundle_path="must-not-be-read.json")
        self.assertIn("REAL_HISTORICAL_DATA_REQUIRED", r["reason_codes"])
        self.assertIsNone(r["bundle_sha256"])

    def test_complete_mocked_schema_does_not_authorize_replay_or_qualify_data(self):
        r = self.run_bundle()
        self.assertEqual(
            r["input_checks_status"], "DOCUMENT_AND_MECHANICAL_CHECKS_PASSED", r
        )
        self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(r["qualification"], "DATA_NOT_QUALIFIED")
        self.assertIn(
            "E5_REVIEWED_RECEIPT_AND_SESSION_ADAPTER_REQUIRED", r["reason_codes"]
        )
        self.assertIs(r["execution_allowed"], False)
        self.assertEqual(r["historical_comparisons"], "NOT_RUN")
        self.assertEqual(r, self.run_bundle())

    def test_no_self_review_and_no_numeric_boolean_approval(self):
        for change in (
            lambda b: b.update(reviewer_code=b["preparer_code"]),
            lambda b: b.update(independently_reviewed=1),
        ):
            self.assertIn(
                "PAPER_INDEPENDENT_REVIEW_REQUIRED",
                self.run_bundle(change)["reason_codes"],
            )

    def test_missing_independent_evidence_and_wrong_coverage_reject(self):
        self.assertIn(
            "PAPER_EVIDENCE_DATED_COSTS_REQUIRED",
            self.run_bundle(
                lambda b: b["evidence"]["dated_costs"].update(status="PENDING")
            )["reason_codes"],
        )
        self.assertIn(
            "PAPER_EVIDENCE_COVERAGE_INCOMPLETE",
            self.run_bundle(
                lambda b: b["evidence"]["usage"]["scope"].update(
                    end=(START + timedelta(seconds=5)).isoformat()
                )
            )["reason_codes"],
        )

    def test_tampered_raw_bytes_are_not_normalized_to_match(self):
        self.assertIn(
            "PAPER_CHECKSUM_MISMATCH",
            self.run_bundle(lambda b: b["artifacts"]["raw_m1"].update(sha256="0" * 64))[
                "reason_codes"
            ],
        )

    def test_window_mismatch_and_dataset_substitution_reject(self):
        self.assertIn(
            "PAPER_WINDOW_BINDING_MISMATCH",
            self.run_bundle(
                lambda b: b["windows"].update(
                    evaluation=dict(start=START.isoformat(), end=START.isoformat())
                )
            )["reason_codes"],
        )
        self.assertIn(
            "PAPER_BUNDLE_LINEAGE_MISMATCH",
            self.run_bundle(lambda b: b.update(dataset_id="0" * 64))["reason_codes"],
        )

    def test_dated_spec_and_costs_cannot_be_future_known_or_expired(self):
        for key, field in (
            ("specification", "available_at_utc"),
            ("costs", "effective_from_utc"),
            ("costs", "effective_until_utc"),
        ):

            def transform(raw):
                obj = json.loads(raw)
                obj[field] = (START + timedelta(seconds=1)).isoformat()
                return json.dumps(obj).encode()

            self.assertIn(
                "PAPER_DOCUMENT_NOT_EFFECTIVE",
                self.run_bundle(file_change=(key, transform))["reason_codes"],
            )

    def test_no_capital_change_to_make_fixtures_qualify(self):
        def transform(raw):
            obj = json.loads(raw)
            obj["starting_capital"] = "5000"
            return json.dumps(obj).encode()

        self.assertIn(
            "PAPER_USD50_BASELINE_REQUIRED",
            self.run_bundle(file_change=("policies", transform))["reason_codes"],
        )

    def audit(self, raw, **kw):
        return audit_quote_events(
            raw,
            start=START.isoformat(),
            end=(START + timedelta(seconds=15)).isoformat(),
            **kw
        )

    def test_quote_unchanged_prices_new_receipts_valid_and_repeatable(self):
        self.assertEqual(self.audit(quote_bytes()), self.audit(quote_bytes()))
        self.assertEqual(self.audit(quote_bytes())["count"], 16)
        self.assertIn(
            "NOT_ESTABLISHED", self.audit(quote_bytes())["capture_completeness"]
        )

    def test_missing_availability_is_not_inferred_from_occurrence(self):
        with self.assertRaisesRegex(
            ValueError, "PAPER_OCCURRENCE_AND_AVAILABILITY_REQUIRED"
        ):
            self.audit(b"timestamp,bid,ask\n2026-11-12T08:00:00Z,1,2\n")

    def test_future_clock_delayed_receipt_and_partial_finality_reject(self):
        for field, value, code in [
            (
                "occurred_at_utc",
                (START + timedelta(days=1)).isoformat(),
                "PAPER_QUOTE_FUTURE",
            ),
            ("available_at_utc", START.isoformat(), "PAPER_QUOTE_FUTURE"),
            ("finality", "FORMING", "PAPER_CORRECTION_OR_FINALITY_ADAPTER_REQUIRED"),
            ("revision", "1", "PAPER_CORRECTION_OR_FINALITY_ADAPTER_REQUIRED"),
        ]:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, code):
                self.audit(
                    quote_bytes(
                        lambda i, x: x.update({field: value}) if i == 1 else None
                    )
                )

    def test_sequence_gaps_duplicates_and_crossed_quotes_reject(self):
        for field, value, code in [
            ("sequence", "2", "PAPER_SEQUENCE_GAP_OR_DUPLICATE"),
            ("sequence", "0", "PAPER_SEQUENCE_GAP_OR_DUPLICATE"),
            ("ask", "1", "PAPER_QUOTE_CROSSED"),
        ]:
            with self.assertRaisesRegex(ValueError, code):
                self.audit(
                    quote_bytes(
                        lambda i, x: x.update({field: value}) if i == 1 else None
                    )
                )

    def test_row_budget_and_missing_end_coverage_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "PAPER_QUOTE_ROW_LIMIT"):
            self.audit(quote_bytes(), max_rows=2)
        with self.assertRaisesRegex(ValueError, "PAPER_QUOTE_WINDOW_NOT_COVERED"):
            self.audit(b"\n".join(quote_bytes().splitlines()[:-1]) + b"\n")

    def test_unknown_quote_gaps_are_explicit_not_approved_closures(self):
        def transform(raw):
            lines = raw.splitlines()
            # Keep a declared sequence but remove received observations; renumbering
            # cannot establish capture completeness or legitimize the time gap.
            data = [lines[0], lines[1], b"1," + b",".join(lines[-1].split(b",")[1:])]
            return b"\n".join(data) + b"\n"

        r = self.run_bundle(file_change=("quote_events", transform))
        self.assertIn("PAPER_QUOTE_GAPS_UNRESOLVED", r["reason_codes"])
        self.assertEqual(r["status"], "BLOCKED")

    def test_delayed_publication_is_recorded_without_rewriting_occurrence(self):
        raw = quote_bytes(
            lambda i, x: x.update(occurred_at_utc=START.isoformat()) if i == 1 else None
        )
        result = self.audit(raw)
        self.assertEqual(result["rows"][1]["occurred_at_utc"], START.isoformat())
        self.assertNotEqual(result["rows"][1]["available_at_utc"], START.isoformat())

    def test_non_utc_and_ambiguous_quote_timestamps_reject(self):
        for value in ("2026-11-12T08:00:00", "2026-11-12T08:00:00+01:00"):
            with self.assertRaises(ValueError):
                self.audit(
                    quote_bytes(
                        lambda i, x: x.update(occurred_at_utc=value) if i == 1 else None
                    )
                )

    def test_unknown_and_duplicate_bundle_fields_reject(self):
        self.assertIn(
            "PAPER_SCHEMA_INVALID",
            self.run_bundle(lambda b: b.update(approved=True))["reason_codes"],
        )

    def test_cli_missing_inputs_and_nonoverwriting_output(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "diagnostics/paper_replay_readiness.py"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "readiness.json"
            args = [sys.executable, str(script), "--report-path", str(path)]
            r = subprocess.run(args, capture_output=True)
            self.assertEqual(r.returncode, 3, r.stderr)
            before = path.read_bytes()
            obj = json.loads(before)
            self.assertEqual(obj["status"], "BLOCKED")
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 1)
            self.assertEqual(before, path.read_bytes())


class E47PerformanceContract(unittest.TestCase):
    def test_empty_denominators_and_source_recomputation(self):
        account = PaperAccount(started_at=START)
        r = performance_readiness(account)
        self.assertEqual(r["starting_balance"], "50")
        self.assertIsNone(r["win_rate"])
        self.assertIsNone(r["net_expectancy"])
        self.assertIsNone(r["profit_factor"])
        self.assertEqual(r["resolved_trades"], 0)
        self.assertTrue(
            validate_performance_readiness(json.loads(json.dumps(r)), account=account)
        )
        r["execution_allowed"] = 0
        with self.assertRaises(ValueError):
            validate_performance_readiness(r, account=account)

    def test_gap_loss_costs_holdings_and_denominators_are_exact(self):
        k, _, _ = setup()
        open_position(k)
        observe(k, quote(k, bid="2090.1", ask="2090.3"))
        r = performance_readiness(k["account"])
        self.assertEqual(r["ending_balance"], "47.9")
        self.assertEqual(Decimal(r["closed_net_pnl"]), Decimal("-2.1"))
        self.assertEqual(r["resolved_trades"], 1)
        self.assertEqual(r["losing_trades"], 1)
        self.assertEqual(Decimal(r["average_holding_seconds"]), 1)
        self.assertEqual(r["unresolved_outcomes"], 0)
        self.assertIsNone(r["historical_metrics"])
        self.assertIsNone(r["exit_efficiency"])

    def test_missing_quote_exit_does_not_count_as_resolved_or_profitable(self):
        k, _, _ = setup()
        k["stop_policy"] = stop_policy(2000, False)
        open_position(k)
        observe(k, quote(k, bid="2097.7", ask="2097.9"))
        before = performance_readiness(k["account"])
        self.assertEqual(before["unresolved_outcomes"], 1)
        self.assertEqual(before["resolved_trades"], 0)
        self.assertIsNone(before["win_rate"])
        observe(k, quote(k, 3, bid="2097.6", ask="2097.8"))
        observe(k, quote(k, 4, bid="2097.5", ask="2097.7"))
        after = performance_readiness(k["account"])
        self.assertEqual(after["resolved_trades"], 1)
        self.assertEqual(before["resolved_trades"], 0)
        self.assertNotEqual(
            before["source_journal_sha256"], after["source_journal_sha256"]
        )

    def test_blocked_equity_unknown_and_original_journal_untouched(self):
        k, _, _ = setup()
        open_position(k)
        observe(k, quote(k, quotation=False, opening=False))
        original = k["account"].journal()
        r = performance_readiness(k["account"])
        self.assertIsNone(r["equity"])
        self.assertEqual(r["capital_survival"], "UNRESOLVED")
        self.assertEqual(original, k["account"].journal())
        self.assertEqual(r["unresolved_outcomes"], 1)


if __name__ == "__main__":
    unittest.main()
