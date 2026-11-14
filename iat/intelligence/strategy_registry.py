"""Versioned original IAT research compositions; no validated trading methods."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json


@dataclass(frozen=True)
class Strategy:
    strategy_id: str
    rule_version: str
    author: str
    source: str
    summary: str
    timeframes: tuple[str, ...]
    required_evidence: tuple[str, ...]
    eligibility: tuple[str, ...]
    invalidation: tuple[str, ...]
    iat_choices: tuple[str, ...]
    validation_status: str = 'EXPERIMENTAL_SYNTHETIC_ONLY'

    def __post_init__(self):
        if self.rule_version != '1.0.0' or self.validation_status != 'EXPERIMENTAL_SYNTHETIC_ONLY':
            raise ValueError('Unsupported strategy rules or validation claim')
        if self.timeframes != ('M1', 'M5'):
            raise ValueError('Strategies require both M1 and M5')
        for name in ('strategy_id', 'author', 'source', 'summary'):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError('Strategy attribution and description required')
        for name in ('required_evidence', 'eligibility', 'invalidation', 'iat_choices'):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
                raise ValueError('Explicit nonempty strategy rules required')


_COMMON = ('Quality-valid closed M1/M5 prefixes; both structures established.',
           'Current directional M1 candlestick and nearby active M1/M5 directional zone.')
_INVALIDATION = ('Fresh opposing M1 CHoCH invalidates an anchored setup regardless of alignment label.',)
_STRATEGIES = (
    Strategy('M5_TREND_M1_CONFIRMATION', '1.0.0', 'IAT 2.0 research implementation',
             'ORIGINAL_IAT_RULE_COMPOSITION',
             'Research continuation when M5 trend and M1 structure agree at a nearby zone with a directional candle.',
             ('M1', 'M5'), ('M5 structure', 'M1 structure', 'M1 candle', 'current zone', 'M1 CHoCH contradictions'),
             _COMMON + ('M5 and M1 structures match the evaluated direction.',), _INVALIDATION,
             ('Evaluate bullish and bearish independently; no score or probability.',
              'Require existing current-zone evidence and current M1 pattern; ignore confluence leader.')),
    Strategy('SWEEP_M1_STRUCTURE_CHANGE', '1.0.0', 'IAT 2.0 research implementation',
             'ORIGINAL_IAT_RULE_COMPOSITION',
             'Research reversal after a confirmed M1 swing-level rejection and a subsequent close-confirmed M1 CHoCH.',
             ('M1', 'M5'), ('confirmed M1 sweep and pool', 'fresh M1 CHoCH', 'M1 candle', 'current zone'),
             _COMMON + ('M1 LOWS sweep for bullish, HIGHS for bearish, available within five minutes.',
                        'Fresh same-direction CLOSE-policy CHoCH break candle opens after the sweep is available.'),
             _INVALIDATION + ('A later M1 close beyond the swept level invalidates the reversal.',),
             ('Five-minute sweep age is an IAT research choice, not an empirical optimum.',
              'M5 directional agreement is not required for reversal; M5 structure must be established.',
              'A same-candle sweep/CHoCH cannot establish order from OHLC and abstains.')),
)


def registry(version=1):
    if type(version) is not int or version != 1:
        raise ValueError('Unsupported strategy registry version')
    result = {'registry_version': version, 'strategies': [asdict(s) for s in _STRATEGIES]}
    result['sha256'] = sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result
