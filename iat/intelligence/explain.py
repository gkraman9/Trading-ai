"""Text is rendered from actual observations, never generated market commentary."""


def explain(frames, alignment, quality, provenance):
    if not quality['valid']:
        return ('Analysis blocked by data-quality checks: '+', '.join(d['code'] for d in quality['diagnostics'])+'.',
                'No directional hypothesis is available. Execution remains disabled.')
    lines = [f'{provenance}: historical candle observations only; no demonstrated trading performance.']
    for tf, frame in frames.items():
        names = ', '.join(p.name for p in frame.patterns) or 'no configured patterns'
        lines.append(f'{tf}: {frame.candle_count} eligible closed candles; {names}; '
                     f'{len(frame.confirmed_pivots)} confirmed pivots; structure {frame.structure.classification}.')
    lines.append(f'M1/M5 context: {alignment.classification}. Patterns and structural events do not guarantee price movement.')
    lines.append('Signal WAIT. Execution remains disabled.')
    return tuple(lines)
