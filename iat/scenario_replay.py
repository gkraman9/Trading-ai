"""Private, file-bound causal research replay. No terminal, network or order access."""
import base64
import json
import re
from collections import Counter
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from iat.replay_dataset import load_dataset, local_file, read_bytes, strict_json, utc, DatasetError, MAX_BYTES
from iat.historical_replay import dataset_preflight, safety
from iat.pilot_qualification import qualify_historical
from iat.intelligence.candles import prefix
from iat.intelligence.models import IntelligenceConfig, iso
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.engine import analyze_intelligence
from iat.intelligence.context import analyze_context
from iat.intelligence.context_evidence import ReplayLedger
from iat.intelligence.decision_log import DecisionLog, from_replay
from iat.intelligence.scenario_assessment import assess_scenarios, validate_scenario_assessment, plain, need
from iat.intelligence.scenario_transitions import assess_scenario_transition, validate_scenario_transition
from iat.intelligence.strategy_replay import digest

MODES = ('SYNTHETIC_RESEARCH', 'EXTERNAL_UNQUALIFIED_RESEARCH')
KIND = 'SCENARIO_REPLAY_AUDIT_V1'
POLICY = {'version': 1, 'observations': 'CLOSED_M1_FULL_PREFIX',
          'warmup': 'CLOSE_LE_EVALUATION_START', 'evaluation': 'START_LT_CLOSE_LE_END',
          'source_policy': 'EXTERNAL_REQUIRES_EXISTING_HUMAN_QUALIFICATION_GATE',
          'record_identity': 'STABLE_SOURCE_SCOPE_AND_CAUSAL_PREFIX_NOT_FULL_ARCHIVE_HASH'}
MAX_AUDIT_BYTES = 32 * 1024 * 1024


def _encoded(raw):
    return base64.b64encode(raw).decode('ascii')


def _decoded(text):
    need(isinstance(text, str) and len(text) <= 4 * ((MAX_BYTES + 2) // 3), 'REPLAY_ARTIFACT_SIZE_LIMIT')
    try:
        raw = base64.b64decode(text, validate=True)
    except ValueError as exc:
        raise ValueError('REPLAY_ARTIFACT_ENCODING_INVALID') from exc
    need(len(raw) <= MAX_BYTES and _encoded(raw) == text, 'REPLAY_ARTIFACT_ENCODING_INVALID')
    return raw


def _names(document, kind):
    if kind == 'DATASET':
        names = [document['frames'][tf]['file'] for tf in ('M1', 'M5')]
        if document['calendar'] is not None:
            names.append(document['calendar']['file'])
    else:
        names = [item['file'] for item in document['evidence'].values()]
    need(all(isinstance(n, str) and 0 < len(n) <= 512 for n in names), 'REPLAY_ARTIFACT_PATH_INVALID')
    return sorted(set(names))


def _capture(path, kind):
    raw = read_bytes(path)
    document = strict_json(raw)
    names = _names(document, kind)
    root = Path(path).resolve().parent
    return {'bundle_version': 1, 'kind': kind, 'document': _encoded(raw),
            'files': {name: _encoded(read_bytes(local_file(root, name))) for name in names}}


def _restore(bundle, root, kind):
    need(isinstance(bundle, dict) and set(bundle) == {'bundle_version', 'kind', 'document', 'files'}
         and type(bundle['bundle_version']) is int and bundle['bundle_version'] == 1
         and bundle['kind'] == kind, 'REPLAY_BUNDLE_SCHEMA_INVALID')
    raw = _decoded(bundle['document'])
    names = _names(strict_json(raw), kind)
    need(isinstance(bundle['files'], dict) and set(bundle['files']) == set(names), 'REPLAY_ARTIFACT_SET_INVALID')
    paths = [local_file(root, name) for name in names]
    document_path = root / '__iat_replay_document.json'
    while document_path in paths or any(document_path in p.parents for p in paths):
        document_path = document_path.with_name('_' + document_path.name)
    # Temporary copies only. User files and source directories are never modified.
    for name, path in zip(names, paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_decoded(bundle['files'][name]))
    document_path.write_bytes(raw)
    return document_path


def _source_scope(dataset, mode):
    m = dataset.metadata
    return {'version': 1, 'symbol': m['symbol'], 'mode': mode,
            'source': {k: m['source'][k] for k in ('name', 'reference', 'curation_id')},
            'lineage': {k: m['lineage'][k] for k in ('feed_id', 'price_basis', 'timestamp_convention', 'm5_origin')},
            'calendar_sha256': m['session_config_sha256'], 'finality_attested': dataset.finality_attested}


def _summary(records):
    def count(rows):
        return {'snapshots': len(rows),
                'quality_blocked_snapshots': sum(r['snapshot_status'] == 'BLOCKED' for r in rows),
                'assessed_snapshots': sum(r['snapshot_status'] == 'ASSESSED' for r in rows),
                'abstained_snapshots': sum(r['snapshot_status'] == 'ABSTAINED' for r in rows),
                'transition_counts': dict(sorted(Counter(r['transition_classification'] for r in rows).items())),
                'reason_counts': dict(sorted(Counter(c for r in rows for c in r['reason_codes']).items()))}
    return {'all': count(records), 'warmup': count([r for r in records if r['phase'] == 'WARMUP']),
            'evaluation': count([r for r in records if r['phase'] == 'EVALUATION'])}


def _derive(inputs):
    need(isinstance(inputs, dict) and set(inputs) == {'dataset_bundle', 'review_bundle', 'input_error',
         'mode', 'configuration', 'observation_times', 'cutoff_utc'}, 'REPLAY_INPUT_SCHEMA_INVALID')
    mode = inputs['mode']
    need(mode in MODES, 'REPLAY_MODE_UNSUPPORTED')
    need(set(inputs['configuration']) == {'context', 'intelligence'}, 'REPLAY_CONFIGURATION_INVALID')
    config = ContextConfig.from_dict(inputs['configuration']['context'])
    phase7 = IntelligenceConfig.from_dict(inputs['configuration']['intelligence'])
    need(asdict(config) == inputs['configuration']['context'] and asdict(phase7) == inputs['configuration']['intelligence'],
         'REPLAY_CONFIGURATION_INVALID')
    report = {'audit_version': 1, 'kind': KIND, 'inputs': inputs, 'run_id': digest(inputs),
              'status': 'BLOCKED', 'reason_codes': [], 'replay_manifest': None,
              'preflight': None, 'qualification_review': None, 'records': [],
              'decision_log': None, 'decision_log_sha256': None, 'summary': _summary([]),
              'mode': 'READ_ONLY_SHADOW', 'signal': 'WAIT', 'execution_allowed': False,
              'safety': safety(), 'exness': 'BLOCKED', 'qualification': 'DATA_NOT_QUALIFIED',
              'historical_validation': 'PENDING', 'historical_comparisons': 'NOT_RUN',
              'limitations': ['HASHES_ARE_CONTENT_CONSISTENCY_NOT_AUTHENTICITY',
                  'ELIGIBLE_ARCHIVE_ADMISSION_PRECEDES_CAUSAL_SNAPSHOT_ANALYSIS',
                  'PRIVATE_REPORT_EMBEDS_SOURCE_FILES_AND_MUST_NOT_BE_PUBLISHED',
                  'SYNTHETIC_RESULTS_ARE_SOFTWARE_EVIDENCE_ONLY',
                  'NO_PROFITABILITY_OR_BROKER_EQUIVALENCE_CLAIM']}
    def finish(*reasons):
        report['reason_codes'] = sorted(set(reasons))
        report['summary'] = _summary(report['records'])
        return dict(report, sha256=digest(report))
    if inputs['input_error'] is not None:
        need(inputs['dataset_bundle'] is None and inputs['review_bundle'] is None
             and isinstance(inputs['input_error'], str) and re.fullmatch('[A-Z0-9_]{1,100}', inputs['input_error']),
             'REPLAY_INPUT_ERROR_INVALID')
        return finish(inputs['input_error'])
    if inputs['dataset_bundle'] is None:
        need(inputs['review_bundle'] is None, 'REPLAY_ORPHAN_REVIEW')
        return finish('DATASET_UNAVAILABLE')
    with TemporaryDirectory(prefix='iat-offline-replay-') as folder:
        root = Path(folder)
        (root / 'dataset').mkdir()
        manifest_path = _restore(inputs['dataset_bundle'], root / 'dataset', 'DATASET')
        dataset = load_dataset(manifest_path)
        meta = dataset.metadata
        if meta['manifest_version'] != 2:
            return finish('MANIFEST_V2_REQUIRED')
        if (meta['dataset_kind'] == 'SYNTHETIC_FIXTURE') != (mode == 'SYNTHETIC_RESEARCH'):
            return finish('REPLAY_SOURCE_MODE_MISMATCH')
        lineage = meta['lineage']
        if lineage['price_basis'] == 'UNKNOWN' or lineage['timestamp_convention'] != 'INTERVAL_OPEN_UTC' or lineage['m5_origin'] == 'UNKNOWN':
            return finish('SOURCE_METADATA_UNESTABLISHED')
        source_scope = _source_scope(dataset, mode)
        dataset_id = digest(source_scope)
        report['replay_manifest'] = {'replay_manifest_version': 1, 'dataset_id': dataset_id,
            'source_scope': source_scope, 'dataset': plain(meta), 'provenance': mode,
            'engine_provenance': dataset.provenance, 'input_bundle_sha256': digest(inputs['dataset_bundle']),
            'configuration_hashes': {'context': config.digest, 'intelligence': phase7.digest},
            'policy': dict(POLICY), 'policy_sha256': digest(POLICY)}
        checked = dataset_preflight(dataset, intelligence_config=phase7)
        report['preflight'] = checked
        if mode == 'EXTERNAL_UNQUALIFIED_RESEARCH':
            review_path = None
            if inputs['review_bundle'] is not None:
                (root / 'review').mkdir()
                review_path = _restore(inputs['review_bundle'], root / 'review', 'REVIEW')
            qualification = qualify_historical(manifest_path, review_path, intelligence_config=phase7)
            report['qualification_review'] = qualification
            if qualification['status'] != 'HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED':
                return finish('EXTERNAL_RESEARCH_REQUIRES_EXISTING_QUALIFICATION_GATE', *qualification['reason_codes'])
        else:
            need(inputs['review_bundle'] is None, 'SYNTHETIC_REVIEW_NOT_PERMITTED')
        if checked['status'] != 'READY':
            return finish(*checked['reason_codes'])
        if not dataset.finality_attested:
            return finish('CANDLE_FINALITY_UNCERTAIN')
        end = utc(meta['utc_range']['end'])
        cutoff = end if inputs['cutoff_utc'] is None else utc(inputs['cutoff_utc'])
        if not utc(meta['utc_range']['start']) < cutoff <= end or cutoff.timestamp() % 60:
            return finish('REPLAY_CUTOFF_INVALID')
        available = [iso(utc(r['timestamp']) + timedelta(minutes=1)) for r in dataset.rows['M1']
                     if utc(r['timestamp']) + timedelta(minutes=1) <= cutoff]
        times = available if inputs['observation_times'] is None else inputs['observation_times']
        need(isinstance(times, list) and len(times) <= 5000, 'REPLAY_OBSERVATIONS_INVALID')
        moments = [utc(t) for t in times]
        if any(b <= a for a, b in zip(moments, moments[1:])):
            return finish('OBSERVATIONS_DUPLICATE_OR_REVERSED')
        if any(iso(t) not in available for t in moments):
            return finish('OBSERVATION_NOT_AVAILABLE')
        previous = None
        ledger = ReplayLedger()
        decisions = []
        evaluation_start = utc(meta['evaluation']['start'])
        for at in moments:
            selected = {tf: prefix(dataset.rows[tf], tf, at) for tf in ('M1', 'M5')}
            options = dict(provenance=dataset.provenance, calendar=dataset.calendar,
                           observed_finality=dataset.finality_attested)
            intelligence = analyze_intelligence('XAUUSD', selected['M1'], selected['M5'], at, config=phase7, **options)
            context = analyze_context('XAUUSD', selected['M1'], selected['M5'], at,
                                      config=config, intelligence_config=phase7, **options)
            assessment = assess_scenarios(context, as_of=at)
            validate_scenario_assessment(assessment)
            transition = assess_scenario_transition(previous, assessment)
            validate_scenario_transition(transition)
            phase = 'WARMUP' if at <= evaluation_start else 'EVALUATION'
            decision = replace(from_replay(ledger.record(context)), phase=phase)
            decisions.append(decision)
            boundaries = {}
            for tf, minutes in (('M1', 1), ('M5', 5)):
                rows = selected[tf]
                boundaries[tf] = {'closed_count': len(rows), 'prefix_sha256': digest(rows),
                    'first_open_utc': rows[0]['timestamp'] if rows else None,
                    'last_open_utc': rows[-1]['timestamp'] if rows else None,
                    'last_close_utc': iso(utc(rows[-1]['timestamp']) + timedelta(minutes=minutes)) if rows else None}
            refs = {'market_intelligence': digest(plain(intelligence.to_dict())),
                    'market_context': digest(plain(context.to_dict())),
                    'assessment_normalized_context': assessment['context_report_sha256'],
                    'scenario_assessment': assessment['sha256'], 'scenario_transition': transition['sha256'],
                    'decision': digest(plain(asdict(decision)))}
            reasons = sorted(set(assessment['reason_codes'] + assessment['abstention_reasons'] + transition['reason_codes']
                + [d['code'] for d in intelligence.data_quality['diagnostics'] if d['code'] != 'DATA_VALID']))
            record = {'record_version': 1, 'dataset_id': dataset_id, 'provenance': mode,
                'engine_provenance': dataset.provenance, 'timestamp_utc': iso(at), 'phase': phase,
                'available_candles': boundaries, 'configuration_hashes': report['replay_manifest']['configuration_hashes'],
                'policy_sha256': digest(POLICY), 'references': refs,
                'evidence_ids': [e['id'] for e in assessment['evidence_index']],
                'selected_hypothesis': assessment['selected_hypothesis'], 'snapshot_status': assessment['status'],
                'transition_classification': transition['classification'], 'transition_id': transition['transition_id'],
                'transition_reason_codes': transition['reason_codes'], 'invalidation_evidence': transition['invalidation_evidence'],
                'evidence_validation': 'PASSED_INTEGRITY_NOT_AUTHENTICITY', 'reason_codes': reasons,
                'mode': 'READ_ONLY_SHADOW', 'signal': 'WAIT', 'execution_allowed': False}
            record['record_id'] = digest(record)
            record['sha256'] = digest(record)
            report['records'].append(record)
            previous = assessment
        log = DecisionLog(1, report['replay_manifest']['configuration_hashes'], tuple(decisions))
        report.update(decision_log=plain(log.to_dict()), decision_log_sha256=log.sha256,
                      status='COMPLETED' if report['records'] else 'BLOCKED')
        return finish('RESEARCH_ONLY_HISTORICAL_VALIDATION_PENDING' if report['records'] else 'NO_OBSERVATIONS')


def run_scenario_replay(manifest_path=None, *, mode='SYNTHETIC_RESEARCH', review_path=None,
                        config=None, intelligence_config=None, observation_times=None, cutoff_utc=None):
    """Read original files only; admission uses unchanged loader/preflight/qualification gates."""
    config = ContextConfig() if config is None else config
    phase7 = IntelligenceConfig() if intelligence_config is None else intelligence_config
    need(isinstance(config, ContextConfig) and isinstance(phase7, IntelligenceConfig), 'REPLAY_CONFIGURATION_INVALID')
    need(mode in MODES, 'REPLAY_MODE_UNSUPPORTED')
    inputs = {'dataset_bundle': None, 'review_bundle': None, 'input_error': None, 'mode': mode,
              'configuration': {'context': asdict(config), 'intelligence': asdict(phase7)},
              'observation_times': plain(observation_times), 'cutoff_utc': cutoff_utc}
    try:
        if manifest_path is not None:
            load_dataset(manifest_path)  # Strict path/schema/checksum checks before capturing any file.
            inputs['dataset_bundle'] = _capture(manifest_path, 'DATASET')
        if review_path is not None:
            inputs['review_bundle'] = _capture(review_path, 'REVIEW')
        report = _derive(plain(inputs))
        need(len(json.dumps(report, separators=(',', ':')).encode()) <= MAX_AUDIT_BYTES, 'REPLAY_AUDIT_SIZE_LIMIT')
        return report
    except DatasetError as exc:
        inputs.update(dataset_bundle=None, review_bundle=None, input_error=exc.code)
        return _derive(plain(inputs))
    except (ValueError, TypeError, KeyError, OSError, OverflowError):
        inputs.update(dataset_bundle=None, review_bundle=None, input_error='REPLAY_INPUT_INVALID')
        return _derive(plain(inputs))


def validate_scenario_replay(report):
    """Re-open embedded private copies through existing gates and re-derive every record."""
    need(isinstance(report, dict) and type(report.get('audit_version')) is int and report['audit_version'] == 1,
         'REPLAY_VERSION_UNSUPPORTED')
    encoded = plain(report)
    need(len(json.dumps(encoded, separators=(',', ':')).encode()) <= MAX_AUDIT_BYTES, 'REPLAY_AUDIT_SIZE_LIMIT')
    need(report.get('sha256') == digest({k: v for k, v in report.items() if k != 'sha256'}), 'REPLAY_CHECKSUM_INVALID')
    expected = _derive(plain(report['inputs']))
    need(set(report) == set(expected) and report == expected and report['sha256'] == expected['sha256'],
         'REPLAY_EVIDENCE_CHAIN_OR_SEMANTICS_INVALID')
    return True
