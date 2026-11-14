"""Versioned immutable intelligence contracts; no broker or execution dependencies."""
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Literal

Timeframe = Literal['M1', 'M5']
DURATIONS = {'M1': 60, 'M5': 300}


def iso(value: datetime) -> str:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError('An aware timestamp is required')
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class IntelligenceConfig:
    version: int = 1
    epsilon: float = 1e-8
    doji_ratio: float = 0.1
    small_body_ratio: float = 0.35
    long_wick_body: float = 2.0
    short_wick_range: float = 0.15
    momentum_body_ratio: float = 0.7
    momentum_relative_range: float = 1.2
    range_window: int = 14
    trend_window: int = 3
    star_recovery: float = 0.5
    left_strength: int = 2
    right_strength: int = 2
    equal_tolerance: float = 1e-6
    break_policy: str = 'CLOSE'
    min_break_distance: float = 0.0
    atr_period: int = 14
    atr_multiplier: float = 0.0

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError('Unsupported intelligence configuration version')
        for name in ('range_window', 'trend_window', 'left_strength', 'right_strength', 'atr_period'):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 100:
                raise ValueError('Invalid intelligence window')
        if self.trend_window < 2:
            raise ValueError('Trend context requires at least two preceding candles')
        for field in fields(self):
            if field.name in ('version', 'break_policy', 'range_window', 'trend_window', 'left_strength', 'right_strength', 'atr_period'):
                continue
            value = getattr(self, field.name)
            if type(value) not in (float, int) or not isfinite(value) or value < 0:
                raise ValueError('Invalid finite nonnegative threshold')
        for name in ('doji_ratio', 'small_body_ratio', 'short_wick_range', 'momentum_body_ratio', 'star_recovery'):
            if not 0 < getattr(self, name) < 1:
                raise ValueError('Ratio must lie strictly between zero and one')
        if self.doji_ratio >= self.small_body_ratio or self.break_policy not in ('CLOSE', 'WICK'):
            raise ValueError('Conflicting pattern or break policy')
        if self.long_wick_body < 1 or self.momentum_relative_range < 1:
            raise ValueError('Invalid relative size threshold')

    @property
    def digest(self):
        return sha256(json.dumps(asdict(self), sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict) or 'version' not in raw or set(raw) - {f.name for f in fields(cls)}:
            raise ValueError('Explicit version and known configuration fields required')
        return cls(**raw)


@dataclass(frozen=True)
class EvidenceRef:
    id: str
    index: int
    opened_at: str
    available_at: str


@dataclass(frozen=True)
class Pattern:
    name: str
    detected_at: str
    evidence: tuple[str, ...]
    interpretation: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class Pivot:
    id: str
    kind: str
    index: int
    occurred_at: str
    confirmation_index: int | None
    confirmed_at: str | None
    price: float
    relation: str
    evidence: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class Structure:
    classification: str
    available_at: str
    evidence: tuple[str, ...]
    reason_codes: tuple[str, ...]
    contradictory_observations: tuple[str, ...]
    insufficient_evidence: bool


@dataclass(frozen=True)
class StructuralEvent:
    id: str
    event_type: str
    level: float
    pivot_id: str
    prior_structure: str
    break_candle: str
    confirmed_at: str
    break_distance: float
    threshold: float
    policy: str
    evidence: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class FrameReport:
    timeframe: str
    analysis_at: str
    data_as_of: str
    candle_count: int
    evidence: tuple[EvidenceRef, ...]
    measurements: dict
    patterns: tuple[Pattern, ...]
    confirmed_pivots: tuple[Pivot, ...]
    candidate_pivots: tuple[Pivot, ...]
    structure: Structure
    events: tuple[StructuralEvent, ...]
    reason_codes: tuple[str, ...]
    missing_evidence: tuple[str, ...]


@dataclass(frozen=True)
class Alignment:
    classification: str
    evaluated_at: str
    m1_as_of: str | None
    m5_as_of: str | None
    evidence: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class IntelligenceReport:
    report_version: int
    model_version: str
    configuration_version: int
    configuration_sha256: str
    configuration: dict
    symbol: str
    analysis_at: str
    timeframe: str
    provenance: str
    data_quality: dict
    frames: dict[str, FrameReport]
    alignment: Alignment
    observed_facts: dict
    derived_structure: dict
    research_hypotheses: tuple[dict, ...]
    supporting_evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    reason_codes: tuple[str, ...]
    ambiguities: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    explanation: tuple[str, ...]
    mode: str = 'READ_ONLY_SHADOW'
    signal: str = 'WAIT'
    execution_allowed: bool = False

    def __post_init__(self):
        if self.mode != 'READ_ONLY_SHADOW' or self.signal != 'WAIT' or self.execution_allowed is not False:
            raise ValueError('Intelligence reports cannot authorize execution')

    def to_dict(self):
        return asdict(self)
