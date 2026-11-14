"""Phase 8 contracts: observations, interpretations and research scenarios stay separate."""
from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json
from math import isfinite


@dataclass(frozen=True)
class ContextConfig:
    version: int = 1
    cluster_tolerance: float = 0.1
    zone_half_width: float = 0.05
    minimum_touches: int = 2
    break_tolerance: float = 0.01
    base_bars: int = 2
    base_range_ratio: float = 0.8
    base_width_ratio: float = 2.0
    departure_range_multiple: float = 1.5
    departure_atr_multiple: float = 0.0
    departure_body_ratio: float = 0.6
    roc_period: int = 5
    atr_period: int = 14
    range_period: int = 5
    momentum_threshold: float = 0.001
    acceleration_threshold: float = 0.0001
    volatility_high: float = 1.5
    volatility_low: float = 0.67
    breakout_closes: int = 2
    minimum_score: float = 3.0
    contradiction_limit: float = 3.0
    minimum_margin: float = 1.0
    structure_weight: float = 2.0
    zone_weight: float = 1.0
    liquidity_weight: float = 1.0
    momentum_weight: float = 1.0
    candle_weight: float = 0.5

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError('Unsupported context configuration version')
        windows = {'minimum_touches','base_bars','roc_period','atr_period','range_period','breakout_closes'}
        for f in fields(self):
            if f.name == 'version': continue
            v = getattr(self, f.name)
            if f.name in windows:
                if type(v) is not int or not 2 <= v <= 100:
                    raise ValueError('Context windows must be integers in [2,100]')
            elif type(v) not in (float,int) or not isfinite(v) or v < 0:
                raise ValueError('Context thresholds must be finite and nonnegative')
        if not (0 < self.base_range_ratio <= 1 and 0 < self.departure_body_ratio < 1
                and 0 < self.volatility_low < 1 < self.volatility_high
                and self.departure_range_multiple >= 1 and self.base_width_ratio >= 1
                and self.zone_half_width > 0 and self.minimum_margin > 0 and self.minimum_score > 0
                and self.contradiction_limit > 0):
            raise ValueError('Conflicting context thresholds')
        if any(getattr(self,k)>100 for k in ('structure_weight','zone_weight','liquidity_weight','momentum_weight','candle_weight')):
            raise ValueError('Evidence weights must be bounded')

    @property
    def digest(self):
        return sha256(json.dumps(asdict(self),sort_keys=True,separators=(',',':')).encode()).hexdigest()

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw,dict) or 'version' not in raw or set(raw)-{f.name for f in fields(cls)}:
            raise ValueError('Explicit version and known context fields required')
        return cls(**raw)


@dataclass(frozen=True)
class Zone:
    id: str
    kind: str
    timeframe: str
    lower: float
    upper: float
    origin_at: str
    confirmed_at: str
    supporting_pivots: tuple[str,...]
    evidence: tuple[str,...]
    historical_touches: tuple[str,...]
    retests: tuple[str,...]
    status: str
    broken_at: str | None
    invalidated_at: str | None
    potential_role_reversal: bool
    prior_structure: str
    reason_codes: tuple[str,...]


@dataclass(frozen=True)
class LiquidityPool:
    id: str
    kind: str
    timeframe: str
    level: float
    confirmed_at: str
    evidence: tuple[str,...]
    touches: int
    reason_codes: tuple[str,...]


@dataclass(frozen=True)
class LiquidityEvent:
    id: str
    pool_id: str
    event_type: str
    timeframe: str
    occurred_at: str
    available_at: str
    level: float
    candle: str
    evidence: tuple[str,...]
    reason_codes: tuple[str,...]


@dataclass(frozen=True)
class Evidence:
    id: str
    category: str
    timeframe: str
    direction: str
    observed_at: str
    available_at: str
    references: tuple[str,...]
    reason_codes: tuple[str,...]
    details: dict


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_type: str
    generated_at: str
    model_version: str
    configuration_version: int
    supporting_evidence: tuple[str,...]
    contradictory_evidence: tuple[str,...]
    assumptions: tuple[str,...]
    invalidation_conditions: tuple[str,...]
    relevant_zones: tuple[str,...]
    timeframe_context: dict
    data_quality_limitations: tuple[str,...]
    heuristic_score: float
    score_kind: str = 'HEURISTIC_EVIDENCE_NOT_PROBABILITY'


@dataclass(frozen=True)
class ContextReport:
    report_version: int
    model_version: str
    configuration_version: int
    configuration_sha256: str
    intelligence_configuration_sha256: str
    configuration: dict
    symbol: str
    analysis_at: str
    provenance: str
    data_quality: dict
    observed_facts: dict
    interpretations: dict
    evidence: tuple[Evidence,...]
    context: dict
    confluence: dict
    hypotheses: tuple[Hypothesis,...]
    abstention_reasons: tuple[str,...]
    explanation: tuple[str,...]
    mode: str = 'READ_ONLY_SHADOW'
    signal: str = 'WAIT'
    execution_allowed: bool = False

    def __post_init__(self):
        if self.mode!='READ_ONLY_SHADOW' or self.signal!='WAIT' or self.execution_allowed is not False:
            raise ValueError('Market context cannot authorize execution')

    def to_dict(self):
        return asdict(self)
