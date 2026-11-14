"""Combine independently eligible frames without extrapolating higher-timeframe state."""
from iat.intelligence.models import Alignment


def align(frames, at, *, blocked=False):
    m1, m5 = frames.get('M1'), frames.get('M5')
    evidence = tuple(p for f in (m1, m5) if f for p in f.structure.evidence)
    if blocked: state = 'BLOCKED_DATA_QUALITY'
    elif not m1 or not m5 or any(f.structure.insufficient_evidence for f in (m1,m5)):
        state = 'INSUFFICIENT_EVIDENCE'
    else:
        a, b = m1.structure.classification, m5.structure.classification
        if a == b == 'BULLISH': state = 'BULLISH_ALIGNMENT'
        elif a == b == 'BEARISH': state = 'BEARISH_ALIGNMENT'
        elif any(e.event_type == ('BULLISH_CHOCH' if b == 'BEARISH' else 'BEARISH_CHOCH')
                 and e.confirmed_at == m1.data_as_of for e in m1.events) and b in ('BULLISH','BEARISH'):
            state = 'COUNTERTREND_TRANSITION'
        elif {a,b} == {'BULLISH','BEARISH'}: state = 'STRUCTURAL_CONFLICT'
        else: state = 'RANGING_OR_MIXED'
    return Alignment(state, at, m1.data_as_of if m1 else None, m5.data_as_of if m5 else None,
                     evidence, ('ALIGNMENT_'+state,))
