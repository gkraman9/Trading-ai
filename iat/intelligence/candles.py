"""Eligibility gate and candle arithmetic. Research never certifies broker data."""
from datetime import datetime, timedelta
from math import fsum, isfinite
from iat.analysis import Candle, validate_candles
from iat.quality import assess_candles, failed
from iat.intelligence.models import DURATIONS, iso


def eligible(rows, timeframe, as_of, *, calendar=None, provenance='SYNTHETIC_RESEARCH', observed_finality=None):
    iso(as_of)
    if provenance not in ('SYNTHETIC_RESEARCH', 'HISTORICAL_RESEARCH', 'VALIDATED_LIVE'):
        return (), failed('PROVENANCE_INVALID', 'Explicit supported data provenance is required')
    if provenance == 'VALIDATED_LIVE' and calendar is None:
        return (), failed('SESSION_CALENDAR_UNAVAILABLE', 'Live intelligence requires verified sessions')
    if not isinstance(rows, (list, tuple)) or len(rows) > 5000:
        return (), failed('HISTORY_LIMIT', 'History must contain at most 5000 candles')
    # Historical research evaluates at an explicit historical timestamp, never at wall time.
    quality = assess_candles(rows, timeframe, as_of, session_calendar=calendar,
                             observed_finality=observed_finality)
    if not quality.valid:
        return (), quality
    candles = tuple(validate_candles(rows))
    # Finite prices alone do not establish finite derived arithmetic (e.g. tiny denominators).
    for c in candles:
        if not isfinite((c.high - c.low) / max(c.low, 1e-300)):
            return (), failed('ARITHMETIC_UNSAFE', 'Candle scale cannot be analyzed safely')
    return candles, quality


def closed_at(candle, timeframe):
    return candle.timestamp + timedelta(seconds=DURATIONS[timeframe])


def prefix(rows, timeframe, as_of):
    """Causal selection only; selected rows still require complete quality validation."""
    iso(as_of)
    duration = timedelta(seconds=DURATIONS[timeframe])
    selected = []
    for row in rows:
        opened = datetime.fromisoformat(str(row['timestamp']).replace('Z', '+00:00'))
        iso(opened)
        if opened + duration > as_of:
            break  # Ordered source: later rows are not available yet and must not be inspected.
        selected.append(row)
    return selected


def average(values):
    return fsum(v / len(values) for v in values) if values else None


def measure(candle: Candle, preceding, config):
    span = candle.high - candle.low
    body = abs(candle.close - candle.open)
    upper = max(0.0, candle.high - max(candle.open, candle.close))
    lower = max(0.0, min(candle.open, candle.close) - candle.low)
    baseline = average([c.high - c.low for c in preceding[-config.range_window:]])
    zero = span <= config.epsilon
    doji = zero or body <= config.doji_ratio * span + config.epsilon
    return {'range': span, 'body': body, 'upper_wick': upper, 'lower_wick': lower,
            'body_to_range': None if zero else body / span,
            'upper_wick_to_body': None if body <= config.epsilon else upper / body,
            'lower_wick_to_body': None if body <= config.epsilon else lower / body,
            'direction': 'DOJI' if doji else ('BULLISH' if candle.close > candle.open else 'BEARISH'),
            'zero_range': zero, 'preceding_range_mean': baseline,
            'range_context_count': min(len(preceding), config.range_window),
            'relative_range': span / baseline if baseline is not None and baseline > config.epsilon else None}


def atr(candles, period):
    """Arithmetic mean true range; includes gaps, excludes the current break candle."""
    if len(candles) < period + 1:
        return None
    values = [max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
              for p, c in zip(candles[-period-1:-1], candles[-period:])]
    return average(values)
