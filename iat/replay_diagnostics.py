"""Deterministic observations of validated replay outputs; never a decision engine."""
from collections import Counter
import re
from iat.scenario_replay import validate_scenario_replay
from iat.replay_dataset import utc
from iat.intelligence.confluence import CATEGORY_BUCKETS
from iat.intelligence.scenario_transitions import STATES
from iat.intelligence.scenario_assessment import plain, need
from iat.intelligence.strategy_replay import digest

VERSION = 1
KIND = 'REPLAY_DIAGNOSTICS_V1'
STAGES = ('market_intelligence', 'market_context', 'scenario_assessment', 'scenario_transition')
REQUIRED_REFS = STAGES + ('assessment_normalized_context', 'decision')
UNSUPPORTED = ['INDEPENDENT_SOURCE_AUTHENTICITY', 'SESSION_EXPIRY_INVALIDATION_PROOF', 'ZONE_INVALIDATION_PROOF']
# Diagnostic categories are explanations, never new upstream reason codes.
GROUPS = {
    'HISTORY_UNSCOPED': ('The upstream report identifies incomplete history without identifying its timeframe.',
                         'Obtain additional preceding history; do not guess which timeframe failed.'),
    'M1_HISTORY': ('M1 history is explicitly unavailable.', 'Supply eligible closed M1 history.'),
    'M5_HISTORY': ('M5 history is explicitly unavailable.', 'Supply eligible closed M5 history.'),
    'MEASUREMENT_WARMUP': ('An upstream measurement reports insufficient history.', 'Supply additional preceding eligible history without changing thresholds.'),
    'CONFIRMED_STRUCTURE': ('The report does not establish the required structural context.', 'Collect more causally confirmed observations; do not confirm future pivots early.'),
    'SCENARIO_EVIDENCE': ('Existing scenario eligibility rules are not satisfied.', 'Inspect recorded supporting and opposing evidence; preserve the current rules.'),
    'CONFLICTING_EVIDENCE': ('Upstream evidence conflicts under existing rules.', 'Retain both sides of the evidence; await new eligible observations.'),
    'VOLATILITY_RESTRICTION': ('The existing volatility research rule requires abstention.', 'Retain the abstention; do not optimize its threshold from this diagnostic.'),
    'UPSTREAM_BLOCK': ('A previous or current upstream assessment is blocked.', 'Inspect the corresponding assessment quality reasons.'),
    'CAUSAL_CONTEXT': ('The comparison lacks a required causal observation or scope.', 'Obtain the missing observation or retain the comparison abstention.'),
    'INVALID_INPUT': ('An upstream reason explicitly identifies invalid data or input.', 'Correct the source through its existing validation workflow; do not patch prices here.'),
    'SOURCE_QUALIFICATION': ('An existing source qualification condition is not satisfied.', 'Supply the required independent evidence through the existing qualification workflow.'),
    'DATA_GAP': ('The existing quality gate reports missing intervals or an unverified gap.', 'Obtain provider history or applicable session evidence; never interpolate candles.'),
    'FRESHNESS': ('The existing quality gate reports stale data.', 'Obtain a finalized export covering the declared observation time.'),
    'SESSION_SCOPE': ('The existing gate cannot establish session eligibility for this request.', 'Review the dated calendar and retained session reason; do not assume broker hours.'),
    'CROSS_FRAME_COVERAGE': ('The existing cross-frame check is unavailable or mismatched.', 'Supply matching declared M1/M5 coverage; aggregation alone is not native-feed proof.'),
    'UNAVAILABLE_OR_INVALID_INPUT': ('The upstream code does not distinguish unavailable from invalid assessment input.', 'Inspect the original assessment; do not guess which failure occurred.'),
    'SOURCE_UNAVAILABLE': ('The required dataset is unavailable.', 'Supply an authorized local dataset manifest; no synthetic fallback is permitted.'),
    'INCOMPARABLE_CONTEXT': ('Existing comparison scope or methodology is incompatible.', 'Compare only compatible source, model and configuration scopes.'),
    'UNATTRIBUTABLE': ('The retained reason does not establish a more specific cause.', 'Inspect the original reports; do not infer omitted evidence or causality.'),
}
CODE_GROUP = {}

def _register(group, codes):
    for code in codes.split():
        CODE_GROUP[code] = group

_register('HISTORY_UNSCOPED', 'HISTORY_INCOMPLETE')
_register('M1_HISTORY', 'M1_HISTORY_UNAVAILABLE')
_register('M5_HISTORY', 'M5_HISTORY_UNAVAILABLE')
_register('MEASUREMENT_WARMUP', 'M1_MOMENTUM_INSUFFICIENT M5_MOMENTUM_INSUFFICIENT M1_VOLATILITY_INSUFFICIENT M5_VOLATILITY_INSUFFICIENT')
_register('CONFIRMED_STRUCTURE', 'INSUFFICIENT_STRUCTURAL_CONTEXT STRUCTURE_INSUFFICIENT_PIVOTS')
_register('SCENARIO_EVIDENCE', 'INSUFFICIENT_HEURISTIC_SUPPORT HEURISTIC_MARGIN_TOO_SMALL NO_UNIQUE_ELIGIBLE_SCENARIO')
_register('CONFLICTING_EVIDENCE', 'MATERIAL_OPPOSING_EVIDENCE CONFLICTING_TIMEFRAME_STRUCTURE FRESH_OPPOSING_M1_CHOCH')
_register('VOLATILITY_RESTRICTION', 'HIGH_VOLATILITY_REQUIRES_FURTHER_RESEARCH')
_register('UPSTREAM_BLOCK', 'BLOCKED_DATA_QUALITY CURRENT_ASSESSMENT_BLOCKED PREVIOUS_ASSESSMENT_BLOCKED')
_register('CAUSAL_CONTEXT', 'PREVIOUS_OBSERVATION_MISSING OBSERVATION_GAP M5_OBSERVATION_GAP OBSERVATION_SCOPE_UNESTABLISHED UPSTREAM_HISTORY_OR_STRUCTURE_INSUFFICIENT SCORING_IDENTITY_UNAVAILABLE STRUCTURE_REVISION_WITHOUT_NEW_CONFIRMATION')
_register('INVALID_INPUT', 'PREVIOUS_ASSESSMENT_INVALID TIMESTAMP_DUPLICATE TIMESTAMP_OUT_OF_ORDER TIMEFRAME_MISALIGNED TIMESTAMP_MALFORMED OHLC_MALFORMED BAR_UNCLOSED REPLAY_INPUT_INVALID')
_register('DATA_GAP', 'CANDLES_MISSING GAP_UNVERIFIED')
_register('FRESHNESS', 'DATA_STALE')
_register('SESSION_SCOPE', 'SESSION_COVERAGE_UNKNOWN SESSION_ALIGNMENT_INVALID SESSION_INVALID SESSION_CLOSED')
_register('CROSS_FRAME_COVERAGE', 'M1_M5_OHLC_MISMATCH M1_M5_ALIGNMENT_UNESTABLISHED')
_register('UNAVAILABLE_OR_INVALID_INPUT', 'CURRENT_ASSESSMENT_UNAVAILABLE_OR_INVALID')
_register('INVALID_INPUT', 'DATASET_CHECKSUM_MISMATCH DATASET_TIMESTAMP_INVALID DATASET_SCHEMA_INVALID OBSERVATIONS_DUPLICATE_OR_REVERSED REVERSED_OBSERVATION_TIMESTAMPS DUPLICATE_OBSERVATION_TIMESTAMP')
_register('SOURCE_UNAVAILABLE', 'DATASET_UNAVAILABLE')
_register('INCOMPARABLE_CONTEXT', 'SCORING_METHOD_OR_CONFIGURATION_MISMATCH INSTRUMENT_MISMATCH SUPPORT_ANCHOR_SCOPE_CHANGED SUPPORT_CHANGE_NOT_COMPARABLE')
_register('SOURCE_QUALIFICATION', 'EXTERNAL_RESEARCH_REQUIRES_EXISTING_QUALIFICATION_GATE INDEPENDENT_REVIEW_PENDING SESSION_CALENDAR_REQUIRED SESSION_V2_REQUIRED CANDLE_FINALITY_UNCERTAIN M5_LINEAGE_UNVERIFIED PRICE_BASIS_UNVERIFIED TIMESTAMP_CONVENTION_UNVERIFIED HUMAN_QUALIFICATION_REVIEW_REQUIRED HUMAN_QUALIFICATION_REVIEW_INVALID HUMAN_APPROVAL_NOT_GRANTED SYNTHETIC_CALENDAR_NOT_REAL_EVIDENCE EVALUATION_COVERAGE_INSUFFICIENT MANIFEST_V2_REQUIRED SOURCE_METADATA_UNESTABLISHED REPLAY_SOURCE_MODE_MISMATCH REAL_HISTORICAL_DATA_REQUIRED')
for _item in ('usage', 'instrument', 'timestamp', 'price_basis', 'calendar', 'finality'):
    CODE_GROUP['EVIDENCE_' + _item.upper() + '_PENDING'] = 'SOURCE_QUALIFICATION'
for _item in ('usage', 'provenance', 'instrument', 'timestamp', 'price_basis', 'calendar', 'finality'):
    CODE_GROUP['HUMAN_EVIDENCE_' + _item.upper() + '_PENDING'] = 'SOURCE_QUALIFICATION'
POLICY = {'version': VERSION, 'attribution': dict(sorted(CODE_GROUP.items())), 'explanations': GROUPS,
          'integrity': 'UPSTREAM_REPLAY_REGENERATION_NOT_AUTHENTICITY', 'required_references': REQUIRED_REFS,
          'sufficiency': 'UPSTREAM_ASSESSED_ONLY_NOT_GENERAL_MARKET_SUFFICIENCY',
          'runs': 'SAME_STATUS_AND_ADJACENT_60_SECOND_OBSERVATIONS', 'unsupported': UNSUPPORTED}


def attribute_reason_codes(codes):
    """Explain only retained codes; unknown/empty causes remain unattributable."""
    need(isinstance(codes, list) and all(isinstance(c, str) and re.fullmatch('[A-Z0-9_]{1,100}', c) for c in codes),
         'DIAGNOSTIC_REASON_CODES_INVALID')
    grouped = {}
    for code in sorted(set(codes)):
        grouped.setdefault(CODE_GROUP.get(code, 'UNATTRIBUTABLE'), []).append(code)
    if not grouped:
        grouped['UNATTRIBUTABLE'] = []
    return [{'category': k, 'upstream_codes': v, 'explanation': GROUPS[k][0], 'research_action': GROUPS[k][1]}
            for k, v in sorted(grouped.items())]


def metric(numerator, denominator, denominator_basis, *, unsupported=False):
    return {'numerator': None if unsupported else numerator, 'denominator': denominator,
            'denominator_basis': denominator_basis,
            'percent': None if unsupported or not denominator else 100 * numerator / denominator,
            'status': 'NOT_ESTABLISHED' if unsupported else 'NO_OBSERVATIONS' if not denominator else 'MEASURED'}


def _causal_alignment(record, decision):
    at = utc(record['timestamp_utc'])
    context = decision['timeframe_context']
    for tf, period in (('M1', 60), ('M5', 300)):
        close = context[tf.lower() + '_as_of']
        if (decision['data_quality_status'] != 'VALID' or close is None
                or close != record['available_candles'][tf]['last_close_utc']
                or utc(close) > at or utc(close).timestamp() % period):
            return False
    return context['m1_as_of'] == record['timestamp_utc']


def _observation(record, decision, previous, run_length):
    evidence = decision['context_evidence']
    ids = set(record['evidence_ids'])
    old_ids = set(previous['evidence_ids']) if previous else set()
    elapsed = (utc(record['timestamp_utc']) - utc(previous['timestamp_utc'])).total_seconds() if previous else None
    refs = {key: bool(re.fullmatch('[a-f0-9]{64}', record['references'][key] or '')) for key in REQUIRED_REFS}
    snapshot_codes = decision['abstention_reasons'] if record['snapshot_status'] != 'ASSESSED' else []
    transition_codes = record['transition_reason_codes'] if record['transition_classification'] in ('ABSTAINED', 'BLOCKED') else []
    structures = {}
    for tf in ('M1', 'M5'):
        current = [e for e in evidence if e['timeframe'] == tf and e['category'] == 'STRUCTURE']
        known = current and decision['timeframe_context'][tf.lower() + '_structure'] != 'UNKNOWN'
        structures[tf] = {'status': 'CONFIRMED_CONTEXT' if known else 'INSUFFICIENT' if current else 'UNAVAILABLE',
                          'evidence_ids': sorted(e['id'] for e in current)}
    return {'diagnostic_observation_id': digest([VERSION, digest(POLICY), record['record_id'], record['sha256']]),
        'source_record_id': record['record_id'], 'source_record_sha256': record['sha256'],
        'timestamp_utc': record['timestamp_utc'], 'phase': record['phase'],
        'snapshot_status': record['snapshot_status'], 'transition_classification': record['transition_classification'],
        'upstream_reason_codes': list(record['reason_codes']), 'snapshot_reason_codes': list(snapshot_codes),
        'transition_reason_codes': list(transition_codes),
        'snapshot_attribution': attribute_reason_codes(snapshot_codes) if record['snapshot_status'] != 'ASSESSED' else [],
        'transition_attribution': attribute_reason_codes(transition_codes) if transition_codes else [],
        'stage_references_available': {k: refs[k] for k in STAGES},
        'stage_reference_integrity_valid': {k: refs[k] for k in STAGES},
        'complete_required_chain': all(refs.values()),
        'missing_required_references': [k for k in REQUIRED_REFS if not refs[k]],
        'sufficiency': 'UPSTREAM_RESEARCH_ELIGIBLE' if record['snapshot_status'] == 'ASSESSED' else
                       'QUALITY_BLOCKED' if record['snapshot_status'] == 'BLOCKED' else 'NOT_ESTABLISHED',
        'evidence': {'available_count': len(ids), 'available_ids': sorted(ids),
            'by_category': {k: sum(e['category'] == k for e in evidence) for k in sorted(CATEGORY_BUCKETS)},
            'by_timeframe': {tf: sum(e['timeframe'] == tf for e in evidence) for tf in ('M1', 'M5')},
            'confirmed_structure': structures,
            'context_frames_unavailable': [tf for tf in ('M1','M5') if decision['timeframe_context'][tf.lower()+'_as_of'] is None]},
        'available_candles': plain(record['available_candles']),
        'timeframe_context': plain(decision['timeframe_context']),
        'causal_frame_alignment_confirmed': _causal_alignment(record, decision),
        'temporal': {'previous_record_id': previous['record_id'] if previous else None,
            'elapsed_seconds': elapsed, 'adjacent_m1_observation': elapsed == 60 if previous else None,
            'snapshot_status_changed': record['snapshot_status'] != previous['snapshot_status'] if previous else None,
            'transition_classification_changed': record['transition_classification'] != previous['transition_classification'] if previous else None,
            'snapshot_run_length': run_length['snapshot'], 'transition_run_length': run_length['transition'],
            'evidence_added': sorted(ids - old_ids), 'evidence_removed': sorted(old_ids - ids),
            'frame_close_changed': {tf: record['available_candles'][tf]['last_close_utc'] != previous['available_candles'][tf]['last_close_utc'] if previous else None for tf in ('M1', 'M5')},
            'warmup_to_evaluation': bool(previous and previous['phase'] == 'WARMUP' and record['phase'] == 'EVALUATION'),
            'entered_upstream_eligibility': bool(previous and previous['snapshot_status'] != 'ASSESSED' and record['snapshot_status'] == 'ASSESSED'),
            'warmup_to_eligible': bool(previous and previous['phase']=='WARMUP' and previous['snapshot_status']!='ASSESSED' and record['snapshot_status']=='ASSESSED')}}


def _runs(observations, field):
    runs = []
    for row in observations:
        status = row[field]
        if status not in ('ABSTAINED', 'BLOCKED'):
            continue
        prev = runs[-1] if runs else None
        if (prev and prev['status'] == status and
                (utc(row['timestamp_utc']) - utc(prev['end_utc'])).total_seconds() == 60):
            prev['end_utc'] = row['timestamp_utc']; prev['observations'] += 1
        else:
            runs.append({'status': status, 'start_utc': row['timestamp_utc'], 'end_utc': row['timestamp_utc'], 'observations': 1})
    return runs


def _frequency(rows, codes, denominator_basis):
    counts = Counter(c for row in rows for c in set(codes(row)))
    return {'denominator': len(rows), 'denominator_basis': denominator_basis,
            'codes': dict(sorted(counts.items()))}


def _project(replay):
    records = replay['records']
    decisions = replay['decision_log']['entries'] if replay['decision_log'] else []
    observations = []
    lengths = {'snapshot': 0, 'transition': 0}
    previous = None
    for record, decision in zip(records, decisions):
        adjacent = previous and (utc(record['timestamp_utc']) - utc(previous['timestamp_utc'])).total_seconds() == 60
        for scope, key in (('snapshot', 'snapshot_status'), ('transition', 'transition_classification')):
            lengths[scope] = lengths[scope] + 1 if adjacent and record[key] == previous[key] else 1
        observations.append(_observation(record, decision, previous, lengths))
        previous = record
    n = len(observations)
    basis = 'ALL_REPLAY_OBSERVATIONS'
    coverage = {k: metric(sum(o['stage_reference_integrity_valid'][k] for o in observations), n, basis) for k in STAGES}
    coverage.update(complete_required_chain=metric(sum(o['complete_required_chain'] for o in observations), n, basis),
        causal_frame_alignment=metric(sum(o['causal_frame_alignment_confirmed'] for o in observations), n, basis),
        available_context_evidence=metric(sum(o['evidence']['available_count'] > 0 for o in observations), n, basis),
        upstream_research_eligible=metric(sum(o['sufficiency'] == 'UPSTREAM_RESEARCH_ELIGIBLE' for o in observations), n, basis),
        missing_required_chain_observations=metric(sum(not o['complete_required_chain'] for o in observations), n, basis),
        invalid_chain_observations=metric(0, n, 'OBSERVATIONS_IN_ACCEPTED_VALIDATED_REPLAYS_INVALID_INPUTS_ARE_REJECTED'),
        independently_qualified=metric(None, n, basis, unsupported=True),
        blocked_without_context_evidence=metric(sum(o['snapshot_status']=='BLOCKED' and not o['evidence']['available_count'] for o in observations), n, 'ALL_OBSERVATIONS_ASSOCIATION_NOT_CAUSAL_ATTRIBUTION'),
        invalid_evidence_in_rejected_inputs=metric(None, n, 'REJECTED_INPUTS_NOT_PART_OF_ACCEPTED_REPLAY', unsupported=True))
    for stage in STAGES:
        coverage[stage + '_available'] = metric(sum(o['stage_references_available'][stage] for o in observations), n, basis)
    for tf in ('M1', 'M5'):
        coverage[tf + '_confirmed_structure'] = metric(sum(o['evidence']['confirmed_structure'][tf]['status'] == 'CONFIRMED_CONTEXT' for o in observations), n, basis)
        coverage[tf + '_candles_available'] = metric(sum(o['available_candles'][tf]['closed_count'] > 0 for o in observations), n, basis)
    reasons = {'observation_all': _frequency(observations, lambda o: o['upstream_reason_codes'], basis),
        'snapshot_abstained': _frequency([o for o in observations if o['snapshot_status'] == 'ABSTAINED'], lambda o:o['snapshot_reason_codes'], 'SNAPSHOT_ABSTAINED_OBSERVATIONS'),
        'snapshot_blocked': _frequency([o for o in observations if o['snapshot_status'] == 'BLOCKED'], lambda o:o['snapshot_reason_codes'], 'SNAPSHOT_BLOCKED_OBSERVATIONS'),
        'transition_abstained': _frequency([o for o in observations if o['transition_classification'] == 'ABSTAINED'], lambda o:o['transition_reason_codes'], 'TRANSITION_ABSTAINED_OBSERVATIONS'),
        'transition_blocked': _frequency([o for o in observations if o['transition_classification'] == 'BLOCKED'], lambda o:o['transition_reason_codes'], 'TRANSITION_BLOCKED_OBSERVATIONS'),
        'admission': {'denominator': 1, 'denominator_basis': 'INPUT_REPLAY_RUNS', 'codes': dict(sorted(Counter(replay['reason_codes']).items()))}}
    q = replay['qualification_review']
    m = replay['replay_manifest']
    temporal = {'snapshot_runs': _runs(observations, 'snapshot_status'),
        'transition_runs': _runs(observations, 'transition_classification'),
        'snapshot_status_changes': metric(sum(o['temporal']['snapshot_status_changed'] is True for o in observations), max(0, n-1), 'CONSECUTIVE_OBSERVED_PAIRS_NOT_NECESSARILY_CONTIGUOUS'),
        'transition_classification_changes': metric(sum(o['temporal']['transition_classification_changed'] is True for o in observations), max(0, n-1), 'CONSECUTIVE_OBSERVED_PAIRS_NOT_NECESSARILY_CONTIGUOUS'),
        'contiguous_pairs': metric(sum(o['temporal']['adjacent_m1_observation'] is True for o in observations), max(0,n-1), 'CONSECUTIVE_OBSERVED_PAIRS'),
        'warmup_to_evaluation_count': sum(o['temporal']['warmup_to_evaluation'] for o in observations),
        'entered_upstream_eligibility_count': sum(o['temporal']['entered_upstream_eligibility'] for o in observations),
        'warmup_to_eligible_count': sum(o['temporal']['warmup_to_eligible'] for o in observations)}
    result = {'diagnostics_version': VERSION, 'kind': KIND, 'policy_sha256': digest(POLICY),
        'diagnostic_id': digest([VERSION, digest(POLICY), replay['sha256']]), 'input_replay_sha256': replay['sha256'],
        'input_replay_run_id': replay['run_id'], 'dataset_id': m['dataset_id'] if m else None,
        'provenance': replay['inputs']['mode'], 'upstream_run_status': replay['status'], 'observation_count': n,
        'snapshot_status_counts': {k:sum(o['snapshot_status']==k for o in observations) for k in ('ABSTAINED','ASSESSED','BLOCKED')},
        'transition_counts': {k:sum(o['transition_classification']==k for o in observations) for k in sorted(STATES)},
        'phase_counts': dict(sorted(Counter(o['phase'] for o in observations).items())),
        'reason_distributions': reasons, 'admission_attribution': attribute_reason_codes(replay['reason_codes']) if replay['status'] == 'BLOCKED' else [],
        'coverage': coverage,
        'evidence_category_coverage': {key:{
            'available':metric(sum(o['evidence']['by_category'][key]>0 for o in observations),n,basis),
            'integrity_valid':metric(sum(o['evidence']['by_category'][key]>0 for o in observations),n,basis),
            'sufficient':metric(None,n,basis,unsupported=True)} for key in sorted(CATEGORY_BUCKETS)},
        'temporal': temporal, 'observations': observations,
        'source_qualification': {'status': replay['qualification'], 'existing_gate_status': q['status'] if q else 'NOT_AVAILABLE',
            'existing_gate_reason_codes': list(q['reason_codes']) if q else [], 'independent_authenticity': 'NOT_ESTABLISHED'},
        'dataset_coverage': {'status': 'AVAILABLE' if replay['preflight'] else 'UNAVAILABLE',
            'preflight_requirements': list(replay['preflight']['preflight']['requirements']) if replay['preflight'] else [],
            'alignment': plain(replay['preflight']['preflight']['alignment']) if replay['preflight'] else None,
            'frame_quality': {tf:{'valid':v['valid'], 'upstream_codes':[d['code'] for d in v['diagnostics']],
                'attribution':attribute_reason_codes([d['code'] for d in v['diagnostics']]) if not v['valid'] else []}
                for tf,v in replay['preflight']['preflight']['frames'].items()} if replay['preflight'] else None,
            'declared_warmup': plain(m['dataset']['warmup']) if m else None},
        'unsupported_evidence_categories': list(UNSUPPORTED),
        'limitations': ['INTEGRITY_NOT_AUTHENTICITY', 'SUFFICIENCY_ONLY_AS_REPORTED_BY_UPSTREAM',
            'UNSCOPED_HISTORY_REASONS_DO_NOT_IDENTIFY_A_TIMEFRAME', 'NO_CAUSAL_ROOT_CAUSE_INFERENCE_FROM_EMPTY_REASONS',
            'AGGREGATES_SUMMARIZE_COMPLETED_REPLAY_AND_NEVER_CHANGE_DECISIONS', 'PRIVATE_LOCAL_OUTPUT_ONLY'],
        'mode': 'READ_ONLY_SHADOW', 'signal': 'WAIT', 'execution_allowed': False,
        'exness': 'BLOCKED', 'historical_validation': 'PENDING', 'historical_comparisons': 'NOT_RUN'}
    return dict(result, sha256=digest(result))


def generate_replay_diagnostics(replay):
    """Validate using PR #28, then apply a pure projection with no new market analysis."""
    validate_scenario_replay(replay)
    return _project(replay)


def validate_replay_diagnostics(report, replay):
    """A source replay is required: checksums alone cannot establish diagnostic semantics."""
    need(isinstance(report, dict) and type(report.get('diagnostics_version')) is int and report['diagnostics_version'] == VERSION,
         'DIAGNOSTIC_VERSION_UNSUPPORTED')
    validate_scenario_replay(replay)
    expected = _project(replay)
    need(report.get('sha256') == digest({k:v for k,v in report.items() if k != 'sha256'}), 'DIAGNOSTIC_CHECKSUM_INVALID')
    need(set(report) == set(expected) and report == expected and report['sha256'] == expected['sha256'], 'DIAGNOSTIC_SEMANTIC_MISMATCH')
    return True


def diagnostics_text(report):
    """Fixed-vocabulary local summary; caller must validate against its source before export."""
    lines = ['IAT replay diagnostics v1 — PRIVATE LOCAL RESEARCH',
        'Observations: ' + str(report['observation_count']),
        'Snapshot statuses: ' + str(report['snapshot_status_counts']),
        'Scenario transitions: ' + str(report['transition_counts']), 'Coverage (numerator/denominator):']
    for key, value in sorted(report['coverage'].items()):
        percentage = 'unknown' if value['percent'] is None else f"{value['percent']:.4f}%"
        lines.append(f"  {key}: {value['numerator']}/{value['denominator']} ({percentage}; {value['status']})")
    for scope in ('snapshot_abstained','snapshot_blocked','transition_abstained','transition_blocked','admission'):
        values = report['reason_distributions'][scope]
        lines.append(f"{scope} reasons (denominator {values['denominator']}): {values['codes']}")
    lines.extend(['Unsupported: ' + ', '.join(report['unsupported_evidence_categories']),
        'Exness BLOCKED; WAIT; execution_allowed=false; historical validation PENDING; comparisons NOT_RUN.',
        'Coverage is not a probability, source certification or trading-performance measure.'])
    return '\n'.join(lines) + '\n'
