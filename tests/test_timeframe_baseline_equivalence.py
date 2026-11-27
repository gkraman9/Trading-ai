"""Unchanged M1/M5 report/strategy and committed USD50 paper comparison."""

from dataclasses import asdict
import json
from pathlib import Path
import unittest
from timeframe_fixtures import fixture
from iat.timeframes import assess_closed_prefix, TimeframeProfile
from test_scenario_assessment import context
from iat.intelligence.scenario_assessment import assess_scenarios
from iat.intelligence.strategies import evaluate_strategies
from iat.intelligence.context_evidence import ReplayLedger
from iat.intelligence.decision_log import from_replay
from iat.intelligence.strategy_replay import digest
from paper_examples import examples


def exercise_r1():
    for frame in ("M1", "M3", "M5", "M15", "M30", "H1", "H4"):
        result = assess_closed_prefix(**fixture(frame))
        if result["status"] != "ELIGIBLE_SYNTHETIC_ONLY":
            raise AssertionError(result["reason_codes"])


def baseline():
    report = context(choch=True)
    return dict(
        context=report.to_dict(),
        scenario=assess_scenarios(report),
        strategies=evaluate_strategies(report),
        decision=asdict(from_replay(ReplayLedger().record(report))),
    )


class BaselineEquivalence(unittest.TestCase):
    def test_context_hypotheses_strategies_events_and_decisionlog_unchanged(self):
        before = baseline()
        exercise_r1()
        after = baseline()
        self.assertEqual(before, after)
        self.assertEqual(digest(before), digest(after))
        self.assertEqual(
            before["context"]["confluence"]["selected_hypothesis"],
            after["context"]["confluence"]["selected_hypothesis"],
        )

    def test_unchanged_committed_usd50_paper_golden_and_hash(self):
        golden = json.loads(
            Path("docs/research_audits/paper-capital.synthetic.json").read_text(
                encoding="utf-8"
            )
        )
        before = examples()
        self.assertEqual(before, golden)
        exercise_r1()
        after = examples()
        self.assertEqual(after, golden)
        self.assertEqual(before["sha256"], after["sha256"])
        self.assertEqual(
            after["examples"]["C_source_bound_gap_loss"]["updated_balance"], "48"
        )

    def test_default_profile_does_not_change_legacy_supported_frames(self):
        self.assertEqual(TimeframeProfile().bindings, ())
        exercise_r1()
        from iat.intelligence.models import DURATIONS
        from iat.mt5_data import TIMEFRAMES

        self.assertEqual(DURATIONS, {"M1": 60, "M5": 300})
        self.assertEqual(TIMEFRAMES, DURATIONS)
