"""Serialized synthetic E4 reports require recomputation, not checksum-only approval."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import unittest
from paper_fixtures import setup, open_position
from paper_examples import examples
from risk_fixtures import START, fixture, sources, snapshot
from iat.intelligence.paper_contracts import (
    quote_fill,
    validate_fill_report,
    specification_collection_plan,
)
from iat.intelligence.capital_intelligence import (
    assess_capital,
    validate_capital_report,
)
from iat.intelligence.paper_account import validate_paper_journal
from iat.intelligence.risk_intelligence import assess_risk
from iat.intelligence.strategy_replay import digest


class PaperReportContracts(unittest.TestCase):
    def test_capital_rehash_does_not_authorize_changed_size(self):
        k, _, _ = setup()
        r = assess_capital(**k)
        self.assertTrue(validate_capital_report(json.loads(json.dumps(r)), **k))
        r["assessment"]["step_adjusted_position_size"] = "1"
        r["sha256"] = digest({a: b for a, b in r.items() if a != "sha256"})
        with self.assertRaises(ValueError):
            validate_capital_report(r, **k)

    def test_fill_rehash_does_not_authorize_changed_side(self):
        k, _, _ = setup()
        kw = dict(
            tape=k["tape"],
            direction="BULLISH",
            phase="ENTRY",
            decision_at=k["risk"]["evaluation_at_utc"],
            as_of=k["as_of"],
            policy=k["fill_policy"],
            costs=k["costs"],
        )
        f = quote_fill(k["quote"], **kw)
        self.assertTrue(validate_fill_report(f, k["quote"], **kw))
        f["side"] = "BID"
        f["sha256"] = digest({a: b for a, b in f.items() if a != "sha256"})
        with self.assertRaises(ValueError):
            validate_fill_report(f, k["quote"], **kw)

    def test_journal_requires_current_producer_or_same_prefix_replay(self):
        k, _, _ = setup()
        open_position(k)
        j = k["account"].journal()
        self.assertTrue(
            validate_paper_journal(json.loads(json.dumps(j)), source=k["account"])
        )
        j["account"]["balance"] = "10000"
        j["sha256"] = digest({a: b for a, b in j.items() if a != "sha256"})
        with self.assertRaises(ValueError):
            validate_paper_journal(j, source=k["account"])
        with self.assertRaises(ValueError):
            validate_paper_journal(j, source=None)

    def test_collection_plan_never_approves_or_reads_account_metadata(self):
        r = specification_collection_plan("XAUUSD")
        self.assertEqual(r["status"], "NOT_RUN")
        self.assertEqual(r["verification"], "UNVERIFIED")
        self.assertNotIn("account_info", json.dumps(r))
        self.assertEqual(r["signal"], "WAIT")
        self.assertIs(r["execution_allowed"], False)

    def test_source_bound_missing_target_never_fabricates_tp2_or_tp3(self):
        one, five = fixture()
        one[34].update(close=2107, high=2107.2)
        s, o, e, oe, one, five = sources(one=one, five=five)
        v, c, i = snapshot(36, one=one, five=five)
        current = e.record(v, c, view_inputs=i)
        inputs = dict(
            original_e1=o,
            original_e2=oe,
            current_e2=current,
            entry_source=s,
            exit_source=e,
            as_of=c.analysis_at,
        )
        r = assess_risk(**inputs)
        self.assertIsNone(r["frozen_target"])
        k, _, _ = setup()
        k.update(risk=r, risk_inputs=inputs)
        result = open_position(k)
        if result["position"] is not None:
            self.assertIsNone(result["position"]["target"])
            self.assertEqual(
                result["position"]["additional_targets"], "NOT_IMPLEMENTED"
            )
        else:
            self.assertIn(result["status"], ("BLOCKED", "ENTRY_REJECTED"))

    def test_synthetic_examples_match_committed_golden_and_repeat_hash(self):
        p = (
            Path(__file__).resolve().parents[1]
            / "docs/research_audits/paper-capital.synthetic.json"
        )
        a = examples()
        self.assertEqual(a, json.loads(p.read_text(encoding="utf-8")))
        self.assertEqual(
            a["examples"]["C_source_bound_gap_loss"]["updated_balance"], "48"
        )
        self.assertEqual(a, examples())

    def test_e4_source_modules_have_no_broker_or_live_dependencies(self):
        root = Path(__file__).resolve().parents[1] / "iat/intelligence"
        for filename in (
            "paper_contracts.py",
            "capital_intelligence.py",
            "paper_account.py",
        ):
            text = (root / filename).read_text(encoding="utf-8")
            for forbidden in (
                "import MetaTrader5",
                "order_send(",
                "account_info(",
                "requests.",
                "socket.",
                "os.environ",
            ):
                self.assertNotIn(forbidden, text)

    def test_missing_risk_policies_never_default_to_a_size(self):
        k, _, _ = setup()
        for field in ("fill_policy", "policy", "costs", "specification"):
            r = assess_capital(**dict(k, **{field: None}))
            self.assertEqual(r["status"], "CAPITAL_ASSESSMENT_UNAVAILABLE")
            self.assertIsNone(r["assessment"])
