"""Pure intelligence orchestration over explicitly sourced, quality-gated OHLC."""
from dataclasses import asdict
from datetime import datetime
from math import isfinite
from typing import Mapping, Sequence
from iat.intelligence.models import (IntelligenceConfig, EvidenceRef, FrameReport,
                                      IntelligenceReport, DURATIONS, iso)
from iat.intelligence.candles import eligible, closed_at, prefix
from iat.intelligence.patterns import recognize
from iat.intelligence.swings import detect as detect_swings
from iat.intelligence.structure import classify
from iat.intelligence.bos_choch import detect as detect_events
from iat.intelligence.multi_timeframe import align
from iat.intelligence.explain import explain


def frame_report(candles, timeframe, as_of, config):
    references = tuple(EvidenceRef(f'{timeframe}:C:{i}', i, iso(c.timestamp), iso(closed_at(c,timeframe)))
                       for i,c in enumerate(candles))
    ids = [r.id for r in references]
    measurements, patterns = recognize(candles, timeframe, config, ids)
    confirmed, candidates = detect_swings(candles, timeframe, config, ids)
    structure = classify(confirmed, iso(as_of))
    events = detect_events(candles, timeframe, confirmed, config, ids)
    missing = []
    if structure.insufficient_evidence: missing.append('STRUCTURE_INSUFFICIENT_PIVOTS')
    if measurements['preceding_trend'] == 'UNKNOWN': missing.append('TREND_CONTEXT_UNESTABLISHED')
    if measurements['range_context_count'] < config.range_window: missing.append('RANGE_CONTEXT_WARMUP')
    if config.atr_multiplier and len(candles) < config.atr_period+2: missing.append('ATR_WARMUP')
    return FrameReport(timeframe, iso(as_of), iso(closed_at(candles[-1],timeframe)), len(candles),
                       references, measurements, patterns, confirmed, candidates, structure, events,
                       structure.reason_codes, tuple(missing))


def _finite_tree(value):
    if isinstance(value, float) and not isfinite(value):
        raise ValueError('Nonfinite derived arithmetic')
    if isinstance(value, dict):
        for child in value.values(): _finite_tree(child)
    if isinstance(value, (list, tuple)):
        for child in value: _finite_tree(child)


def analyze_intelligence(symbol: str, m1_rows: Sequence[Mapping] | None,
                         m5_rows: Sequence[Mapping] | None, as_of: datetime, *, config=None,
                         provenance='SYNTHETIC_RESEARCH', calendar=None, observed_finality=None) -> IntelligenceReport:
    """Rows must already be a causal closed prefix; future rows fail closed.

    Offline research requires explicit provenance and no live data is fetched here.
    If supplied, a session calendar is ALWAYS enforced, including research mode.
    """
    config = IntelligenceConfig() if config is None else config
    if not isinstance(config, IntelligenceConfig): raise ValueError('Typed configuration required')
    if not isinstance(symbol,str) or not symbol or len(symbol)>128 or any(c.isspace() or ord(c)<32 for c in symbol):
        raise ValueError('Invalid symbol')
    at = iso(as_of)
    frames, diagnostics, valid = {}, [], True
    if provenance not in ('SYNTHETIC_RESEARCH', 'HISTORICAL_RESEARCH', 'VALIDATED_LIVE'):
        provenance = 'UNVERIFIED'  # Never echo arbitrary provenance text into reports.
        diagnostics.append({'code':'PROVENANCE_INVALID','severity':'ERROR','message':'Explicit supported data provenance is required'})
        valid = False
    if calendar is not None and calendar.symbol != symbol:
        diagnostics.append({'code':'SYMBOL_MISMATCH','severity':'ERROR','message':'Calendar symbol differs from requested symbol'})
        valid = False
    for tf, rows in (('M1',m1_rows), ('M5',m5_rows)):
        if rows is None:
            diagnostics.append({'code':tf+'_HISTORY_UNAVAILABLE','severity':'WARNING','message':'Timeframe history is unavailable'})
            continue
        candles, quality = eligible(rows, tf, as_of, calendar=calendar, provenance=provenance,
                                     observed_finality=observed_finality)
        diagnostics.extend(dict(d.to_dict(), timeframe=tf) for d in quality.diagnostics)
        if not quality.valid:
            valid = False
        else:
            try:
                frame = frame_report(candles, tf, as_of, config)
                _finite_tree(asdict(frame))
                frames[tf] = frame
            except (ValueError, OverflowError, ZeroDivisionError):
                valid = False
                diagnostics.append({'code':'ARITHMETIC_UNSAFE','severity':'ERROR','message':'Derived arithmetic could not be established'})
    if not frames and valid:
        diagnostics.append({'code':'HISTORY_UNAVAILABLE','severity':'ERROR','message':'No eligible timeframe history'})
        valid = False
    if not valid: frames = {}  # Quarantine all derived directions on ANY critical failure.
    quality = {'valid':valid, 'status':'VALID' if valid else 'BLOCKED', 'diagnostics':diagnostics}
    alignment = align(frames,at,blocked=not valid)
    supporting = tuple(sorted({p.id for f in frames.values() for p in f.confirmed_pivots}
        | {ref for f in frames.values() for pattern in f.patterns for ref in pattern.evidence}
        | {ref for f in frames.values() for event in f.events for ref in event.evidence}))
    contradictions = tuple(f'{tf}:{c}' for tf,f in frames.items() for c in f.structure.contradictory_observations)
    if alignment.classification == 'STRUCTURAL_CONFLICT': contradictions += ('M1_M5_DIRECTION_CONFLICT',)
    contradictions += tuple(sorted({f'{tf}:CURRENT_'+event.event_type
        for tf, frame in frames.items() for event in frame.events
        if event.confirmed_at == frame.data_as_of
        and (event.event_type.endswith('_CHOCH') or event.event_type == 'FAILED_STRUCTURAL_BREAK')}))
    missing = tuple(sorted({m for f in frames.values() for m in f.missing_evidence}
                           | {tf+'_HISTORY_UNAVAILABLE' for tf in DURATIONS if tf not in frames}))
    hypotheses = []
    for tf,f in frames.items():
        if f.structure.classification in ('BULLISH','BEARISH','RANGING'):
            hypotheses.append({'type':'POSSIBLE_'+f.structure.classification+'_STRUCTURE', 'timeframe':tf,
                               'generated_at':at, 'evidence':f.structure.evidence,
                               'limitations':['DETERMINISTIC_INTERPRETATION_NOT_FORECAST','NO_VALIDATED_TRADING_EDGE']})
    codes = tuple(sorted({d['code'] for d in diagnostics}|set(alignment.reason_codes)))
    ambiguities = ['OHLC_PATTERNS_ARE_NOT_PREDICTIONS']
    if any(f.candidate_pivots for f in frames.values()):
        ambiguities.append('CANDIDATE_PIVOTS_UNCONFIRMED')
    if any(len(f.patterns) > 1 for f in frames.values()):
        ambiguities.append('OVERLAPPING_PATTERN_LABELS')
    return IntelligenceReport(1,'IAT_MARKET_INTELLIGENCE_V1',config.version,config.digest,asdict(config),symbol,at,
        'M1_M5',provenance,quality,frames,alignment,
        {tf:{'measurements':f.measurements,'candles':asdict(f)['evidence']} for tf,f in frames.items()},
        {tf:{'structure':asdict(f.structure),'patterns':asdict(f)['patterns'],
             'events':asdict(f)['events'],'confirmed_pivots':asdict(f)['confirmed_pivots']} for tf,f in frames.items()}, tuple(hypotheses), supporting, contradictions, codes,
        tuple(ambiguities), missing,
        explain(frames,alignment,quality,provenance))


def analyze_at(symbol, m1_history, m5_history, as_of, **options):
    """Historical causal query: unfinished and future candles never reach analysis."""
    selected = [prefix(rows,tf,as_of) if rows is not None else None
                for tf,rows in (('M1',m1_history),('M5',m5_history))]
    return analyze_intelligence(symbol,*selected,as_of,**options)


def replay(symbol, m1_history, m5_history, **options):
    """Chronological prefix-only reference implementation, not a profitability backtest."""
    from datetime import timedelta
    previous = None
    for row in m1_history:
        moment = datetime.fromisoformat(str(row['timestamp']).replace('Z','+00:00')) + timedelta(minutes=1)
        iso(moment)
        if previous is not None and moment <= previous:
            raise ValueError('Replay M1 history must be strictly chronological')
        previous = moment
        yield analyze_at(symbol,m1_history,m5_history,moment,**options)


class IntelligenceStream:
    """Append-only offline reference stream; recomputation is intentional and bounded."""
    def __init__(self,symbol,**options):
        self.symbol, self.options = symbol,options
        self.rows = {'M1':[],'M5':[]}
        self.previous_as_of = None

    def append(self,timeframe,row):
        from copy import deepcopy
        if timeframe not in DURATIONS: raise ValueError('Unsupported timeframe')
        candidate = deepcopy(row)
        opened = datetime.fromisoformat(str(candidate['timestamp']).replace('Z','+00:00'))
        iso(opened)
        rows = self.rows[timeframe]
        if rows and opened <= datetime.fromisoformat(str(rows[-1]['timestamp']).replace('Z','+00:00')):
            raise ValueError('Stream must be strictly chronological per timeframe')
        if len(rows)>=5000: raise ValueError('Stream history limit reached')
        # Late data must never revise an already emitted observation.
        from datetime import timedelta
        if self.previous_as_of is not None and opened+timedelta(seconds=DURATIONS[timeframe]) <= self.previous_as_of:
            raise ValueError('Late candle would revise an emitted prefix')
        rows.append(candidate)

    def snapshot(self,as_of):
        iso(as_of)
        if self.previous_as_of is not None and as_of < self.previous_as_of:
            raise ValueError('Stream clock moved backwards')
        report = analyze_at(self.symbol,self.rows['M1'],self.rows['M5'],as_of,**self.options)
        self.previous_as_of = as_of
        return report
