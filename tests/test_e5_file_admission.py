"""Real parsing of synthetic file graphs; upstream human verdicts are explicitly mocked."""

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from e5_package import package
from iat.e5_source import load_source, AdmissionError
from iat.e5_replay import run_historical
from iat.paper_source_scope import source_scope
from iat.intelligence.paper_contracts import SyntheticQuote


class E5FileAdmission(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.plan, self.review, self.ready, self.gate = package(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    @contextmanager
    def mock_human_gates(self):
        with patch(
            "iat.e5_source.historical_paper_preflight", return_value=self.ready
        ), patch("iat.e5_source.qualify_historical", return_value=self.gate):
            yield

    def test_synthetic_package_is_rejected_by_actual_qualification_gate(self):
        r = run_historical(self.plan, self.review)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIsNone(r["historical_metrics"])
        self.assertEqual(r["comparisons"]["full_full"], "NOT_RUN")

    def test_mechanics_pass_only_with_explicit_mock_of_human_verdicts(self):
        with self.mock_human_gates():
            s, a = load_source(self.plan, self.review)
        self.assertEqual(a["quote_bar_audit"]["ohlc_mismatches"], 0)
        self.assertEqual(s.provenance, "HISTORICAL_RESEARCH")
        q = s.quote_rows()[0]
        with source_scope(s):
            r = SyntheticQuote(
                "XAUUSD",
                s.specification.feed,
                int(q["sequence"]),
                q["occurred_at_utc"],
                q["available_at_utc"],
                q["bid"],
                q["ask"],
                True,
                True,
                provenance=s.provenance,
            )
            self.assertEqual(r.provenance, "HISTORICAL_RESEARCH")
            with self.assertRaises(ValueError):
                SyntheticQuote(
                    "XAUUSD",
                    s.specification.feed,
                    int(q["sequence"]),
                    q["occurred_at_utc"],
                    q["available_at_utc"],
                    q["bid"],
                    q["ask"],
                    True,
                    True,
                )
        with self.assertRaises(ValueError):
            s.costs.validate()

    def test_actual_raw_byte_change_is_rejected_without_normalization(self):
        (self.root / "m1.csv").write_bytes(
            (self.root / "m1.csv").read_bytes() + b"\r\n"
        )
        with self.mock_human_gates(), self.assertRaises(ValueError):
            load_source(self.plan, self.review)

    def test_rehashed_but_inconsistent_availability_fails_mechanical_gate(self):
        plan = json.loads(self.plan.read_text())
        path = self.root / "availability.csv"
        path.write_bytes(path.read_bytes().replace(b",0,FINAL", b",1,FINAL", 1))
        plan["inputs"]["bar_availability"]["sha256"] = sha256(
            path.read_bytes()
        ).hexdigest()
        self.plan.write_text(json.dumps(plan))
        review = json.loads(self.review.read_text())
        review["plan_sha256"] = sha256(self.plan.read_bytes()).hexdigest()
        self.review.write_text(json.dumps(review))
        with self.mock_human_gates(), self.assertRaisesRegex(
            ValueError, "E5_BAR_CORRECTION_OR_FINALITY_UNSUPPORTED"
        ):
            load_source(self.plan, self.review)

    def test_bundle_or_financial_artifact_changed_during_qualification_rejects(self):
        self.ready["bundle_sha256"] = "0" * 64
        with self.mock_human_gates(), self.assertRaisesRegex(
            ValueError, "E5_BUNDLE_CHANGED_DURING_QUALIFICATION"
        ):
            load_source(self.plan, self.review)
        self.ready["bundle_sha256"] = sha256(
            (self.root / "paper-bundle.json").read_bytes()
        ).hexdigest()
        self.ready["artifacts"]["costs"] = "0" * 64
        with self.mock_human_gates(), self.assertRaisesRegex(
            ValueError, "E5_ARTIFACT_CHANGED_DURING_QUALIFICATION"
        ):
            load_source(self.plan, self.review)

    def test_independent_review_changing_mid_admission_never_registers_capability(self):
        from iat.replay_dataset import read_bytes

        calls = 0

        def read(path):
            nonlocal calls
            raw = read_bytes(path)
            if Path(path) == self.review:
                calls += 1
                if calls > 1:
                    return raw + b" "
            return raw

        with self.mock_human_gates(), patch(
            "iat.e5_source.read_bytes", side_effect=read
        ), patch("iat.e5_source._register_source") as register:
            with self.assertRaisesRegex(
                ValueError, "E5_REVIEW_OR_PLAN_CHANGED_DURING_ADMISSION"
            ):
                load_source(self.plan, self.review)
            register.assert_not_called()

    def test_underlying_source_review_cannot_be_self_approval_under_another_bundle(
        self,
    ):
        hpath = self.root / "human-review.mock.json"
        h = json.loads(hpath.read_bytes())
        bundle = json.loads((self.root / "paper-bundle.json").read_bytes())
        h["reviewer_code"] = bundle["preparer_code"]
        hpath.write_bytes(json.dumps(h).encode())
        self.ready["source_qualification"]["human_review_sha256"] = sha256(
            hpath.read_bytes()
        ).hexdigest()
        self.gate["human_review_sha256"] = sha256(hpath.read_bytes()).hexdigest()
        plan = json.loads(self.plan.read_bytes())
        for k in ("review", "outcome_review"):
            plan["inputs"][k]["sha256"] = sha256(hpath.read_bytes()).hexdigest()
        self.plan.write_bytes(json.dumps(plan).encode())
        review = json.loads(self.review.read_bytes())
        review["plan_sha256"] = sha256(self.plan.read_bytes()).hexdigest()
        self.review.write_bytes(json.dumps(review).encode())
        with self.mock_human_gates(), self.assertRaisesRegex(
            ValueError, "E5_INDEPENDENT_PROVIDER_REVIEW_MISMATCH"
        ):
            load_source(self.plan, self.review)

    def test_unapproved_adapter_review_cannot_admit_mechanically_valid_files(self):
        r = json.loads(self.review.read_text())
        r["decision"] = "PENDING"
        self.review.write_text(json.dumps(r))
        with self.mock_human_gates(), self.assertRaisesRegex(
            ValueError, "E5_INDEPENDENT_ADAPTER_REVIEW_REQUIRED"
        ):
            load_source(self.plan, self.review)

    def test_qualified_labels_do_not_bypass_wrong_raw_mapping(self):
        path = self.root / "import.json"
        m = json.loads(path.read_text())
        m["frames"]["M1"]["columns"]["close"] = "high"
        path.write_text(json.dumps(m))
        p = json.loads(self.plan.read_text())
        p["inputs"]["import_spec"]["sha256"] = sha256(path.read_bytes()).hexdigest()
        self.plan.write_text(json.dumps(p))
        with self.mock_human_gates(), self.assertRaises(ValueError):
            load_source(self.plan, self.review)


if __name__ == "__main__":
    unittest.main()
