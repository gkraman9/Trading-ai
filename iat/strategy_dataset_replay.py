"""Manifest-gated strategy replay; scoped accounting wraps unchanged log v1."""
from collections import Counter
import re
from copy import deepcopy
from iat.historical_replay import dataset_preflight, safety
from iat.replay_dataset import load_dataset, DatasetError, utc
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig, iso
from iat.intelligence.strategy_registry import registry
from iat.intelligence.strategy_replay import replay_strategies, validate_strategy_replay_log, digest, POLICY


def empty_strategy_dataset_report():
    return {'report_version':1, 'kind':'STRATEGY_DATASET_REPLAY', 'run_id':digest(None), 'status':'BLOCKED',
            'configuration_hashes':{'context':ContextConfig().digest,'intelligence':IntelligenceConfig().digest,
                                    'registry':registry()['sha256'],'lifecycle_policy':digest(POLICY)},
            'reason_codes':['INDEPENDENT_DATASET_UNAVAILABLE'], 'dataset':None,
            'preflight':None, 'strategy_replay_log':None, 'window_accounting':None,
            'historical_validation':'PENDING', 'historical_comparisons':'NOT_RUN',
            'historical_metrics':None, 'exness':'BLOCKED', 'safety':safety()}


def window_accounting(log, evaluation):
    """Closing timestamps: warm-up <= start; evaluation start < close <= end.

    Reconstruct inventory from causal events, never from future terminal states.
    """
    validate_strategy_replay_log(log)
    a,b=(utc(evaluation[k]) for k in ('start','end'))
    if not a<b:raise ValueError('Invalid strategy evaluation window')
    warm=[e for e in log['entries'] if utc(e['timestamp_utc'])<=a]
    selected=[e for e in log['entries'] if a<utc(e['timestamp_utc'])<=b]
    metadata={s['setup_id']:s for s in log['setups']}
    def phase(entries, carried):
        active=set(carried)
        first,invalid,expired,unqualified=set(),set(),set(),set()
        for e in entries:
            for event in e['lifecycle_events']:
                sid,kind=event['setup_id'],event['event']
                if kind=='QUALIFIED':first.add(sid);active.add(sid)
                elif kind=='INVALIDATED_QUALIFIED_SETUP':invalid.add(sid);active.remove(sid)
                elif kind=='EXPIRED':expired.add(sid);active.remove(sid)
                elif kind=='INVALIDATION_WITHOUT_QUALIFICATION':unqualified.add(sid)
        groups=[]
        for spec in registry()['strategies']:
            for direction in ('BULLISH','BEARISH'):
                def belongs(sid):
                    return metadata[sid]['strategy_id']==spec['strategy_id'] and metadata[sid]['direction']==direction
                rows=[r for e in entries for r in e['evaluations']
                      if r['strategy_id']==spec['strategy_id'] and r['direction']==direction]
                identities={'carried_in_active':carried,'first_qualified':first,'invalidated_qualified':invalid,
                            'expired_qualified':expired,'unqualified_invalidated':unqualified,'active_at_end':active}
                groups.append({'strategy_id':spec['strategy_id'], 'direction':direction,
                               'snapshot_outcomes':{k:sum(r['snapshot_outcome']==k for r in rows)
                                                    for k in ('QUALIFIES','ABSTAINS','INVALIDATED','BLOCKED_DATA')},
                               'reason_counts':dict(sorted(Counter(c for r in rows for c in r['reason_codes']).items())),
                               'setup_ids':{k:sorted(s for s in ids if belongs(s)) for k,ids in identities.items()},
                               'setup_counts':{k:sum(belongs(s) for s in ids) for k,ids in identities.items()}})
        return {'timestamps':len(entries),'directional_snapshots':len(entries)*4,
                'blocked_timestamps':sum(not e['data_quality']['valid'] for e in entries),
                'start_close_utc':entries[0]['timestamp_utc'] if entries else None,
                'end_close_utc':entries[-1]['timestamp_utc'] if entries else None,'groups':groups},active
    warm_summary,carried=phase(warm,set())
    evaluation_summary,_=phase(selected,carried)
    return {'accounting_version':1,'evaluation':deepcopy(evaluation),
            'boundary_policy':'WARMUP_CLOSE_LE_START_EVALUATION_START_LT_CLOSE_LE_END',
            'warmup':warm_summary,'evaluation_window':evaluation_summary}


def run_strategy_manifest(manifest_path=None, *, config=None, intelligence_config=None):
    """No caller provenance override: provenance is derived by the strict loader."""
    report=empty_strategy_dataset_report()
    config=ContextConfig() if config is None else config
    phase7=IntelligenceConfig() if intelligence_config is None else intelligence_config
    if not isinstance(config,ContextConfig) or not isinstance(phase7,IntelligenceConfig):
        raise ValueError('Typed analytical configurations required')
    report['configuration_hashes'].update(context=config.digest,intelligence=phase7.digest)
    if manifest_path is None:return report
    try:dataset=load_dataset(manifest_path)
    except DatasetError as exc:
        report.update(status='BLOCKED' if exc.code=='DATASET_UNAVAILABLE' else 'FAIL',reason_codes=[exc.code])
        return report
    report['dataset']=deepcopy(dataset.metadata)
    report['run_id']=digest([dataset.metadata,report['configuration_hashes']])
    checked=dataset_preflight(dataset,intelligence_config=phase7)
    report['preflight']=checked['preflight']
    if checked['status']!='READY':
        report.update(status=checked['status'],reason_codes=checked['reason_codes'])
        return report
    historical=dataset.metadata['dataset_kind']=='INDEPENDENT_HISTORICAL'
    # Existing coverage eligibility is required before publishing historical strategy metrics.
    if historical and not checked['preflight']['alignment']['evaluation']['coverage_sufficient']:
        report.update(status='BLOCKED',reason_codes=['EVALUATION_COVERAGE_INSUFFICIENT'])
        return report
    log=replay_strategies('XAUUSD',dataset.rows['M1'],dataset.rows['M5'],config=config,intelligence_config=phase7,
                          provenance=dataset.provenance,calendar=dataset.calendar,observed_finality=dataset.finality_attested)
    evaluation=dataset.metadata.get('evaluation',dataset.metadata['utc_range'])
    accounting=window_accounting(log,evaluation)
    report.update(status='WARN',reason_codes=['SYNTHETIC_EVIDENCE_HISTORICAL_VALIDATION_PENDING'] if not historical else [],
                  strategy_replay_log=log,window_accounting=accounting)
    valid=accounting['evaluation_window']['timestamps']-accounting['evaluation_window']['blocked_timestamps']
    if not valid:
        report.update(status='BLOCKED',reason_codes=report['reason_codes']+['NO_ELIGIBLE_SNAPSHOTS'])
    elif historical:
        report.update(status='PASS',historical_validation='DATASET_PIPELINE_CHECKS_PASSED',
                      historical_metrics=deepcopy(accounting['evaluation_window']))
    if accounting['evaluation_window']['blocked_timestamps']:
        report['reason_codes'].append('BLOCKED_SNAPSHOTS_RECORDED')
        if report['status']=='PASS':report['status']='WARN'
    validate_strategy_dataset_report(report)
    return report


def validate_strategy_dataset_report(report):
    if (set(report)!=set(empty_strategy_dataset_report()) or type(report['report_version']) is not int
            or report['report_version']!=1 or report['kind']!='STRATEGY_DATASET_REPLAY'
            or report['status'] not in ('PASS','WARN','FAIL','BLOCKED') or report['safety']!=safety()
            or report['exness']!='BLOCKED' or report['historical_comparisons']!='NOT_RUN'
            or not isinstance(report['run_id'],str) or not re.fullmatch('[a-f0-9]{64}',report['run_id'])):
        raise ValueError('Unsafe/unsupported strategy dataset report')
    log=report['strategy_replay_log']
    if log is None:
        if report['status'] in ('PASS','WARN'):raise ValueError('Completed strategy report requires a log')
        if report['window_accounting'] is not None:raise ValueError('Accounting without strategy log')
    else:
        validate_strategy_replay_log(log)
        meta=report['dataset']
        if report['preflight'] is None:raise ValueError('Strategy log without dataset preflight')
        if any(log['configuration_hashes'][k]!=v for k,v in report['configuration_hashes'].items()):
            raise ValueError('Strategy analytical configuration mismatch')
        if not all(q['valid'] for q in report['preflight']['frames'].values()) or report['preflight']['requirements']:
            raise ValueError('Strategy log bypassed preflight')
        if report['preflight']['alignment']['mismatch_count'] or not report['preflight']['alignment']['comparable_m5_bars']:
            raise ValueError('Strategy log bypassed consistency gate')
        evaluation=meta.get('evaluation',meta['utc_range'])
        if report['window_accounting']!=window_accounting(log,evaluation):raise ValueError('Strategy window accounting mismatch')
    established=report['historical_validation']=='DATASET_PIPELINE_CHECKS_PASSED'
    if report['historical_validation'] not in ('PENDING','DATASET_PIPELINE_CHECKS_PASSED'):
        raise ValueError('Unsupported historical validation claim')
    if established:
        meta=report['dataset']
        if (log is None or meta['dataset_kind']!='INDEPENDENT_HISTORICAL' or meta['source']['independent_review']!='ATTESTED'
                or not meta['finality_attested'] or meta['session_config_sha256'] is None
                or meta['manifest_version']==2 and not all(r['status']=='VERIFIED' for r in meta['evidence_review'].values())
                or report['preflight']['requirements']
                or not report['preflight']['alignment']['evaluation']['coverage_sufficient']
                or report['historical_metrics']!=report['window_accounting']['evaluation_window']
                or report['window_accounting']['evaluation_window']['timestamps']<=report['window_accounting']['evaluation_window']['blocked_timestamps']
                or report['status'] not in ('PASS','WARN')):
            raise ValueError('Historical strategy eligibility unestablished')
    elif report['historical_metrics'] is not None:
        raise ValueError('Unmeasured historical metrics must be null')
    return True
