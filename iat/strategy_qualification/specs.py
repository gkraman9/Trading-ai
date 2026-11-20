"""Ex-ante IAT research choices, separate from unchanged experimental predicates."""

from dataclasses import dataclass, asdict, replace
from decimal import Decimal
from iat.intelligence.strategy_registry import registry
from iat.intelligence.strategy_replay import digest


@dataclass(frozen=True)
class Specification:
    strategy_id: str
    version: str = "stage-b-research-1.0.0"
    reward_risk: str = "2"
    stop_buffer_ticks: int = 1
    max_hold_minutes: int = 15
    minimum_relative_volatility: str = "0.67"
    maximum_relative_volatility: str = "1.5"

    def __post_init__(self):
        if (
            self.strategy_id not in {s["strategy_id"] for s in registry()["strategies"]}
            or self.version != "stage-b-research-1.0.0"
        ):
            raise ValueError("Unknown executable research specification")
        if (
            type(self.stop_buffer_ticks) is not int
            or not 1 <= self.stop_buffer_ticks <= 10
            or type(self.max_hold_minutes) is not int
            or not 1 <= self.max_hold_minutes <= 60
        ):
            raise ValueError("Invalid research limits")
        for key in (
            "reward_risk",
            "minimum_relative_volatility",
            "maximum_relative_volatility",
        ):
            if (
                not isinstance(getattr(self, key), str)
                or not Decimal(getattr(self, key)).is_finite()
            ):
                raise ValueError("Finite declared parameters required")
        if not Decimal("1") <= Decimal(self.reward_risk) <= Decimal(
            "4"
        ) or not 0 < Decimal(self.minimum_relative_volatility) < Decimal(
            self.maximum_relative_volatility
        ):
            raise ValueError("Conflicting research limits")

    @property
    def sha256(self):
        return digest(asdict(self))

    def description(self):
        return dict(
            specification=asdict(self),
            specification_sha256=self.sha256,
            status="EXPERIMENTAL",
            author="Original IAT research-policy composition",
            source_predicate_rule_version="1.0.0",
            source_registry_sha256=registry()["sha256"],
            entry="Unchanged original candidate predicates, eligible closed M1/M5 evidence; next executable quote strictly AFTER decision, within two seconds.",
            regime="Continuation: M1/M5 direction aligned. Sweep: established M5 structure, original post-sweep CLOSE CHoCH; opposite M5 allowed as in original research.",
            stop="Last available confirmed M1 LOW for BUY / HIGH for SELL; sweep also includes swept level; one tick beyond the adverse extreme, adverse tick-grid rounding. Reject invalid geometry.",
            target="2R from actual simulated bid/ask entry with declared adverse slippage; tick-rounded away from entry.",
            exit="Broker-side SL/TP quote crossings; next close-permitted quote after original anchor invalidation/retirement or 15-minute holding horizon.",
            invalidation="Original anchored INVALIDATED event; continuation loses M5 trend; blocked evidence makes outcome inconclusive, not a fabricated exit.",
            volatility="Existing relative volatility in [0.67,1.5], available ATR/momentum observations; no new indicator or confluence tuning.",
            session="Verified quote and new-position permissions; close-only permits exits only; UNKNOWN blocks.",
            constraints="0.01 lot, one position, five openings per UTC day, 1% daily admission/latch; qualified costs and opening marks required.",
            identity="Existing canonical setup anchor plus new specification version/hash; same setup cannot rearm after close.",
            missing_data="Abstain; no imputation, no unconfirmed pivot, no forming M5, no caller/model approval.",
            iat_choices=[
                "ONE_TICK_STOP_BUFFER",
                "TWO_R_TARGET",
                "FIFTEEN_MINUTE_MAX_HOLD",
                "NORMAL_RELATIVE_VOLATILITY_ONLY",
            ],
            limitations=[
                "UNVALIDATED_POLICY_CHOICES_NOT_PROFITABILITY_EVIDENCE",
                "OHLC_ALONE_CANNOT_ESTABLISH_FILL_ORDER",
                "NO_EXECUTION_AUTHORIZATION",
            ],
        )


def specifications():
    return [Specification(s["strategy_id"]) for s in registry()["strategies"]]


# Fixed before any qualified performance run in this milestone. Not empirical optima.
PROTOCOL = dict(
    version=1,
    min_closed_trades=300,
    min_oos_trades=100,
    min_distinct_utc_days=60,
    min_oos_days=30,
    minimum_profit_factor="1.2",
    maximum_drawdown_fraction="0.10",
    minimum_day_bootstrap_expectancy_lower_bound="0",
    bootstrap_day_blocks=1000,
    bootstrap_seed=1729,
    min_walk_forward_folds=3,
    min_trades_per_fold=30,
    robustness_cost_multipliers=["1", "1.5", "2"],
    spread_stress_multipliers=["1", "1.5", "2"],
    reward_risk_sensitivity=["1.5", "2", "2.5"],
    hold_minutes_sensitivity=[10, 15, 20],
    independent_reproduction_required=True,
    registration="FROZEN_CODE_HASH_BEFORE_QUALIFIED_OOS_ANALYSIS_NOT_AN_EXTERNAL_TIMESTAMP_AUTHORITY",
)
PROTOCOL_SHA256 = digest(PROTOCOL)
