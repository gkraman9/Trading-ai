"""Separate, causal offline research evaluations over existing IAT observations."""
from copy import deepcopy
from datetime import timedelta
from iat.replay_dataset import utc
from iat.intelligence.context import context_at
from iat.intelligence.context_models import ContextReport
from iat.intelligence.strategy_registry import registry


_DIRECTIONS = ('BULLISH', 'BEARISH')


def evaluate_strategies(report):
    """Observation-contract entry point. Call strategies_at for gated OHLC research.

    INVALIDATED describes the current anchored setup, not a persisted trade lifecycle.
    """
    if not isinstance(report, ContextReport):
        raise ValueError('Typed IAT context report required')
    if report.provenance not in ('SYNTHETIC_RESEARCH', 'HISTORICAL_RESEARCH'):
        raise ValueError('Offline research provenance required')
    at = utc(report.analysis_at)
    catalog = registry()
    evaluations = []
    for definition in catalog['strategies']:
        for direction in _DIRECTIONS:
            support, opposition, missing, invalid = [], [], [], []
            status = 'ABSTAINS'
            if not report.data_quality['valid']:
                missing.append('BLOCKED_DATA_QUALITY')
            elif (any(tf not in report.observed_facts for tf in ('M1', 'M5'))
                  or any(report.context.get(tf.lower() + '_structure') not in (*_DIRECTIONS, 'RANGING', 'TRANSITIONAL') for tf in ('M1', 'M5'))
                  or 'INSUFFICIENT_STRUCTURAL_CONTEXT' in report.context['limitations']):
                missing.append('INSUFFICIENT_HISTORY_OR_STRUCTURE')
            else:
                support, opposition, missing, invalid = _evaluate(report, definition['strategy_id'], direction, at)
                status = 'INVALIDATED' if invalid else 'ABSTAINS' if missing else 'QUALIFIES'
            evaluations.append({'strategy_id': definition['strategy_id'], 'rule_version': definition['rule_version'],
                                'direction': direction, 'status': status,
                                'reason_codes': sorted(set(invalid + missing)) if invalid or missing else ['ALL_EXPERIMENTAL_RULES_MET'],
                                'supporting_evidence': sorted(set(support)), 'contradictory_evidence': sorted(set(opposition))})
    return {'report_version': 1, 'registry_version': 1, 'registry_sha256': catalog['sha256'],
            'analysis_at': report.analysis_at, 'symbol': report.symbol, 'provenance': report.provenance,
            'context_configuration_sha256': report.configuration_sha256,
            'intelligence_configuration_sha256': report.intelligence_configuration_sha256,
            'data_quality': deepcopy(report.data_quality),
            'data_quality_limitations': list(report.context['limitations']),
            'validation_status': 'EXPERIMENTAL_SYNTHETIC_ONLY',
            'evaluations': evaluations, 'historical_validation': 'PENDING',
            'historical_decision_log_comparisons': 'NOT_RUN', 'exness': 'BLOCKED',
            'mode': 'READ_ONLY_SHADOW', 'signal': 'WAIT', 'execution_allowed': False}


def _evaluate(report, strategy, direction, at):
    support, opposition, missing, invalid = [], [], [], []
    sources = report.interpretations['source_registry']
    # Reject future or unresolved evidence rather than trusting an alignment label.
    for e in report.evidence:
        if (utc(e.available_at) > at or utc(e.observed_at) > utc(e.available_at)
                or any(r not in sources or utc(sources[r]['available_at']) > utc(e.available_at) for r in e.references)):
            return [], [], ['EVIDENCE_UNAVAILABLE_AT_TIMESTAMP'], []
    current = {tf: report.observed_facts[tf]['data_as_of'] for tf in ('M1', 'M5')}
    if any(utc(v) > at for v in current.values()):
        return [], [], ['UNCLOSED_FRAME'], []
    transitions = [e for e in report.evidence if e.category == 'TRANSITION' and e.timeframe == 'M1'
                   and e.available_at == current['M1'] and e.details.get('fresh')
                   and e.details.get('event_type') == e.direction + '_CHOCH']
    candles = [e for e in report.evidence if e.category == 'CANDLE' and e.timeframe == 'M1'
               and e.direction == direction and e.available_at == current['M1']]
    zones = [e for e in report.evidence if e.category in ('SUPPORT_RESISTANCE', 'SUPPLY_DEMAND')
             and e.direction == direction and e.available_at == current[e.timeframe]
             and e.details.get('status') in ('FRESH', 'TESTED', 'ROLE_REVERSAL_CANDIDATE')]
    if not candles: missing.append('CURRENT_DIRECTIONAL_M1_CANDLE_REQUIRED')
    if not zones: missing.append('CURRENT_ACTIVE_DIRECTIONAL_ZONE_REQUIRED')
    support.extend(e.id for e in candles + zones)
    if strategy == 'M5_TREND_M1_CONFIRMATION':
        anchor = report.context['m5_structure'] == direction
        if not anchor: missing.append('M5_TREND_NOT_ALIGNED')
        if report.context['m1_structure'] != direction: missing.append('M1_STRUCTURE_NOT_CONFIRMED')
        support.extend(e.id for e in report.evidence if e.category == 'STRUCTURE' and e.direction == direction)
    else:
        frame = report.interpretations['frames']['M1']
        pools = {p.id: p for p in frame['liquidity_pools']}
        sweeps = [e for e in frame['liquidity_events'] if e.event_type == 'CONFIRMED_SWEEP'
                  and e.pool_id in pools and pools[e.pool_id].kind.endswith('LOWS' if direction == 'BULLISH' else 'HIGHS')
                  and utc(e.occurred_at) <= utc(e.available_at)
                  and at - timedelta(minutes=5) <= utc(e.available_at) <= at
                  and utc(pools[e.pool_id].confirmed_at) <= utc(e.occurred_at)]
        anchor = bool(sweeps)
        if not anchor: missing.append('RECENT_CONFIRMED_M1_SWEEP_REQUIRED')
        # Latest event deterministically wins; identities never depend on list order.
        sweep = max(sweeps, key=lambda e: (utc(e.available_at), e.id)) if sweeps else None
        if sweep:
            support.append(sweep.id)
            changes = [e for e in transitions if e.direction == direction
                       and e.details.get('confirmation_policy') == 'CLOSE'
                       and utc(sweep.available_at) <= utc(e.observed_at)]
            if not changes: missing.append('POST_SWEEP_CLOSE_CONFIRMED_M1_CHOCH_REQUIRED')
            support.extend(e.id for e in changes)
            later = [v for v in sources.values() if v['kind'] == 'CANDLE' and v['timeframe'] == 'M1'
                     and utc(sweep.available_at) < utc(v['available_at']) <= at]
            beyond = [v for v in later if (v['ohlc']['close'] < sweep.level if direction == 'BULLISH' else v['ohlc']['close'] > sweep.level)]
            if beyond:
                invalid.append('SWEPT_LEVEL_RECLAIM_LOST')
                opposition.extend(k for k, v in sources.items() if v in beyond)
    opposing = [e for e in transitions if e.direction != direction]
    if anchor and opposing:
        invalid.append('FRESH_OPPOSING_M1_CHOCH')
        opposition.extend(e.id for e in opposing)
    return support, opposition, missing, invalid


def strategies_at(symbol, m1_history, m5_history, as_of, **options):
    """Filter unavailable bars before reusing the existing context/quality gates."""
    return evaluate_strategies(context_at(symbol, m1_history, m5_history, as_of, **options))
