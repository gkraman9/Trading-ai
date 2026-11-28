"""Frozen E4.7 comparison policies; no data, costs or broker defaults are invented."""

from dataclasses import asdict
from iat.intelligence.paper_contracts import FillPolicy
from iat.intelligence.capital_intelligence import CapitalPolicy
from iat.intelligence.paper_account import PaperExitPolicy
from iat.intelligence.protection_contracts import (
    ProtectiveStopPolicy,
    LiquidationPolicy,
)
from iat.intelligence.exit_intelligence import ExitPolicy
from iat.intelligence.risk_intelligence import RiskPolicy
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.sr_rejection import STRATEGY, RULE, POLICY
from iat.intelligence.strategy_replay import digest


def baseline():
    """Same explicit policy values as E4.7 comparison fixtures, never broker certification."""
    return dict(
        version=1,
        starting_capital="50",
        baseline="UNCHANGED_M1_M5",
        fill=asdict(FillPolicy(0, 2000, 120000, 30000)),
        capital=asdict(
            CapitalPolicy(
                "0.01",
                "0.1",
                "0.1",
                "0.2",
                "1",
                1,
                3,
                "0.5",
                120,
                "0",
                None,
                "DECLARED_SYNTHETIC_ABSTRACT_REFERENCE_TO_QUOTE_UNITS",
            )
        ),
        exit=asdict(PaperExitPolicy(True, True, True)),
        stop=asdict(
            ProtectiveStopPolicy(
                "DECLARED_SYNTHETIC_STRUCTURE_TO_QUOTE_STOP",
                "LONG_BID_SHORT_ASK",
                0,
                True,
                "AT_ENTRY_QUOTE_RECEIPT_BEFORE_OPEN",
            )
        ),
        liquidation=asdict(
            LiquidationPolicy(
                "SYNTHETIC_EQUITY_OVER_FROZEN_ENTRY_MARGIN",
                "NET_LIQUIDATION_EQUITY_WITH_DECLARED_COSTS",
                "SYNTHETIC_EXIT_ON_STOP_OUT_ONLY",
                0,
                True,
            )
        ),
    )


def protocol():
    p = dict(
        protocol_version=1,
        parent="2ff62c3b59b4dbb4b341f3934ec192c276eca092",
        strategy=STRATEGY,
        rule=RULE,
        sr_policy_sha256=digest(POLICY),
        policies=baseline(),
        context_sha256=ContextConfig().digest,
        intelligence_sha256=IntelligenceConfig().digest,
        risk_policy=asdict(RiskPolicy()),
        exit_observation_policy=asdict(ExitPolicy()),
        priority="ONE_POSITION_NO_REENTRY_SAME_SETUP_NO_CASH_EVENTS",
        scheduling="M1_CLOSE_BEFORE_COINCIDENT_QUOTE_RECEIPT_FIRST_CAUSAL_QUOTE_ONLY",
        opportunity="FIRST_QUALIFICATION_IN_EVALUATION_WARMUP_IS_STATE_ONLY",
        outcome="NO_NEW_ENTRIES_AFTER_EVALUATION_END_NO_FORCED_CLOSE",
        fill="NATIVE_RECEIPT_SIDE_PRICE_PLUS_INDEPENDENTLY_REVIEWED_DECLARED_SLIPPAGE",
        costs="REQUIRE_DATED_DOCUMENTS_NO_ZERO_COST_DEFAULT",
        correction="REJECT_REVISIONS_UNTIL_SEPARATELY_REVIEWED_AS_OF_ADAPTER",
        resources=dict(
            max_m1_snapshots=256,
            max_quotes=100000,
            max_events=10000,
            max_report_bytes=10000000,
        ),
    )
    return dict(p, sha256=digest(p))
