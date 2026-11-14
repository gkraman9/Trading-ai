"""Manifest-gated reasoning journal with separate assessment and observation scopes."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import re
from iat.replay_dataset import load_dataset,DatasetError,utc
from iat.historical_replay import dataset_preflight,safety
from iat.evaluation_window import coverage
from iat.intelligence.models import IntelligenceConfig,iso
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.adaptive_models import AdaptiveConfig
from iat.intelligence.journal_policy import ReviewPolicy
from iat.intelligence.reasoning_journal import replay_reasoning_journal,journal_prefix,validate_reasoning_journal
from iat.intelligence.strategy_replay import digest


def empty_journal_dataset_report():
    return {'report_version':1,'kind':'JOURNAL_DATASET_EVALUATION','run_id':digest(None),'status':'BLOCKED',
            'reason_codes':['INDEPENDENT_DATASET_UNAVAILABLE'],'dataset':None,'preflight':None,
            'configuration_hashes':{'context':ContextConfig().digest,'intelligence':IntelligenceConfig().digest,
                                    'adaptive':AdaptiveConfig().digest,'review':ReviewPolicy().sha256},
            'scope':None,'evaluation_coverage':None,'reasoning_journal':None,'accounting':None,
            'historical_validation':'PENDING','historical_comparisons':'NOT_RUN','historical_metrics':None,
            'exness':'BLOCKED','safety':safety()}


def _stamp(value):return utc(iso(value)) if isinstance(value,datetime) else utc(value)


def _scope(metadata,evaluation_end,observation_cutoff):
    declared=metadata.get('evaluation',metadata['utc_range'])
    start,end=(utc(declared[k]) for k in ('start','end'))
    selected=_stamp(evaluation_end) if evaluation_end is not None else end
    requested=_stamp(observation_cutoff) if observation_cutoff is not None else utc(metadata['utc_range']['end'])
    if not start<selected<=requested<=end or selected.timestamp()%300 or requested.timestamp()%60:
        raise ValueError('Evaluation and observation scope invalid')
    return {'declared_evaluation':deepcopy(declared),'evaluation':{'start':iso(start),'end':iso(selected)},
            'requested_outcome_observation_cutoff_utc':iso(requested),
            'outcome_observation_cutoff_utc':None,
            'boundary_policy':'WARMUP_CLOSE_LE_START_EVALUATION_START_LT_CLOSE_LE_END_THEN_OBSERVATION_TAIL'}


def _leader(report):
    n=len(report['assessment']['top_scenarios'])
    return 'NONE' if not n else 'UNIQUE' if n==1 else 'TIED'


def _group(assessments,latest,horizon):
    rows=[latest[a['assessment_id'],horizon] for a in assessments]
    statuses=lambda values:{s:sum(v==s for v in values) for s in ('SUPPORTED','CONTRADICTED','UNRESOLVED')}
    counts=statuses([r['status'] for r in rows]);unresolved=[r for r in rows if r['status']=='UNRESOLVED']
    scenarios=[]
    for name in ('BULLISH','BEARISH','NEUTRAL'):
        all_rows=[o for r in rows for o in r['scenario_outcomes'] if o['scenario']==name]
        members=[o for o in all_rows if o['was_original_leader']]
        def measured(items):
            c=statuses([o['status'] for o in items])
            return {'denominator':len(items),'resolved_review_denominator':c['SUPPORTED']+c['CONTRADICTED'],'outcomes':c}
        scenarios.append({'scenario':name,'all_assessments':measured(all_rows),'original_leader_memberships':measured(members)})
    return {'all_assessment_denominator':len(assessments),
            'resolved_review_denominator':counts['SUPPORTED']+counts['CONTRADICTED'],'outcomes':counts,
            'elapsed_complete_horizons':sum(r['horizon_complete'] for r in rows),
            'incomplete_horizons':sum(not r['horizon_complete'] for r in rows),
            'unresolved_reason_counts':dict(sorted(Counter(c for r in unresolved for c in r['reason_codes']).items())),
            'original_status_denominators':{s:sum(a['adaptive_report']['status']==s for a in assessments) for s in ('READY','UNKNOWN','BLOCKED')},
            'leader_status_denominators':{s:sum(_leader(a['adaptive_report'])==s for a in assessments) for s in ('UNIQUE','TIED','NONE')},
            'scenario_reviews':scenarios}


def journal_window_accounting(journal,scope):
    """Project latest review versions at the observed cutoff, preserving originals."""
    start,end=(utc(scope['evaluation'][k]) for k in ('start','end'))
    latest={}
    for r in journal['outcome_reviews']:latest[r['assessment_id'],r['horizon_minutes']]=r
    cohorts={'warmup':[a for a in journal['assessments'] if utc(a['timestamp_utc'])<=start],
             'evaluation':[a for a in journal['assessments'] if start<utc(a['timestamp_utc'])<=end],
             'observation_tail':[a for a in journal['assessments'] if utc(a['timestamp_utc'])>end]}
    result={}
    for name,assessments in cohorts.items():
        ids={a['assessment_id'] for a in assessments};horizons=[]
        for h in ReviewPolicy().horizons_minutes:
            strata=[]
            for regime in ('TREND_UP','TREND_DOWN','RANGE','TRANSITION','UNKNOWN'):
                for leader in ('UNIQUE','TIED','NONE'):
                    selected=[a for a in assessments if a['adaptive_report']['regime']['directional']==regime and _leader(a['adaptive_report'])==leader]
                    if selected:strata.append({'original_regime':regime,'leader_status':leader,**_group(selected,latest,h)})
            horizons.append({'horizon_minutes':h,'total':_group(assessments,latest,h),'by_original_regime_and_leader_status':strata})
        result[name]={'assessment_count':len(assessments),'first_close_utc':assessments[0]['timestamp_utc'] if assessments else None,
                      'last_close_utc':assessments[-1]['timestamp_utc'] if assessments else None,
                      'material_changes':sum(r['assessment_id'] in ids for r in journal['assessment_revisions']),
                      'horizons':horizons}
    before=journal_prefix(journal,start)
    pending={}
    for r in before['outcome_reviews']:pending[r['assessment_id'],r['horizon_minutes']]=r
    result['state_at_evaluation_start']={'journal_prefix_sha256':before['sha256'],
        'last_warmup_assessment_id':cohorts['warmup'][-1]['assessment_id'] if cohorts['warmup'] else None,
        'pending_warmup_reviews':[{'assessment_id':aid,'horizon_minutes':h,'due_at_utc':r['due_at_utc']}
                                  for (aid,h),r in sorted(pending.items()) if not r['horizon_complete']]}
    return {'accounting_version':1,'scope':deepcopy(scope),'cohorts':result,
            'counting_policy':'LATEST_REVIEW_PER_ORIGINAL_ASSESSMENT_AND_HORIZON_NO_RETROSPECTIVE_TIE_WINNER'}


def run_journal_manifest(manifest_path=None,*,config=None,intelligence_config=None,evaluation_end=None,observation_cutoff=None):
    """Load checksummed inputs; a historical provenance label cannot bypass preflight."""
    result=empty_journal_dataset_report()
    config=ContextConfig() if config is None else config
    phase7=IntelligenceConfig() if intelligence_config is None else intelligence_config
    if not isinstance(config,ContextConfig) or not isinstance(phase7,IntelligenceConfig):raise ValueError('Typed analytical configurations required')
    result['configuration_hashes'].update(context=config.digest,intelligence=phase7.digest)
    if manifest_path is None:return result
    try:dataset=load_dataset(manifest_path)
    except DatasetError as exc:
        result.update(status='BLOCKED' if exc.code=='DATASET_UNAVAILABLE' else 'FAIL',reason_codes=[exc.code]);return result
    result['dataset']=deepcopy(dataset.metadata)
    result['run_id']=digest([dataset.metadata,result['configuration_hashes']])
    checked=dataset_preflight(dataset,intelligence_config=phase7)
    result['preflight']=checked['preflight']
    if checked['status']!='READY':result.update(status=checked['status'],reason_codes=checked['reason_codes']);return result
    try:scope=_scope(dataset.metadata,evaluation_end,observation_cutoff)
    except ValueError:result.update(status='FAIL',reason_codes=['JOURNAL_SCOPE_INVALID']);return result
    selected=replace(dataset,metadata=dict(dataset.metadata,evaluation=scope['evaluation']))
    result['scope']=scope;result['evaluation_coverage']=coverage(selected,phase7.epsilon)
    historical=dataset.metadata['dataset_kind']=='INDEPENDENT_HISTORICAL'
    if historical and not result['evaluation_coverage']['coverage_sufficient']:
        result.update(status='BLOCKED',reason_codes=['EVALUATION_COVERAGE_INSUFFICIENT']);return result
    cutoff=utc(scope['requested_outcome_observation_cutoff_utc'])
    journal=replay_reasoning_journal('XAUUSD',dataset.rows['M1'],dataset.rows['M5'],as_of=cutoff,
             config=config,intelligence_config=phase7,provenance=dataset.provenance,
             calendar=dataset.calendar,observed_finality=dataset.finality_attested)
    scope['outcome_observation_cutoff_utc']=journal['assessments'][-1]['timestamp_utc'] if journal['assessments'] else None
    accounting=journal_window_accounting(journal,scope)
    result.update(reasoning_journal=journal,accounting=accounting,status='WARN',
                  reason_codes=[] if historical else ['SYNTHETIC_EVIDENCE_HISTORICAL_VALIDATION_PENDING'])
    evaluation=accounting['cohorts']['evaluation'];eligible=sum(a['adaptive_report']['data_quality']['valid'] and a['adaptive_report']['status']!='BLOCKED' for a in journal['assessments']
                                    if utc(scope['evaluation']['start'])<utc(a['timestamp_utc'])<=utc(scope['evaluation']['end']))
    if not eligible:result.update(status='BLOCKED',reason_codes=result['reason_codes']+['NO_ELIGIBLE_ASSESSMENTS'])
    elif historical:result.update(status='PASS',historical_validation='DATASET_PIPELINE_CHECKS_PASSED',historical_metrics=deepcopy(evaluation))
    if any(h['total']['outcomes']['UNRESOLVED'] for h in evaluation['horizons']):
        result['reason_codes'].append('UNRESOLVED_REVIEWS_RETAINED')
        if result['status']=='PASS':result['status']='WARN'
    result['run_id']=digest([dataset.metadata,result['configuration_hashes'],scope])
    validate_journal_dataset_report(result);return result


def validate_journal_dataset_report(report):
    if (set(report)!=set(empty_journal_dataset_report()) or type(report['report_version']) is not int or report['report_version']!=1
            or report['kind']!='JOURNAL_DATASET_EVALUATION' or report['status'] not in ('PASS','WARN','FAIL','BLOCKED')
            or report['safety']!=safety() or report['exness']!='BLOCKED' or report['historical_comparisons']!='NOT_RUN'
            or not isinstance(report['run_id'],str) or not re.fullmatch('[a-f0-9]{64}',report['run_id'])):
        raise ValueError('Unsafe/unsupported journal dataset report')
    journal=report['reasoning_journal']
    if journal is None:
        if report['accounting'] is not None or report['status'] in ('PASS','WARN'):raise ValueError('Accounting/success without journal')
    else:
        validate_reasoning_journal(journal)
        preflight=report['preflight']
        if preflight is None or preflight['requirements'] or not all(v['valid'] for v in preflight['frames'].values()):raise ValueError('Journal bypassed preflight')
        if preflight['alignment']['mismatch_count'] or not preflight['alignment']['comparable_m5_bars']:raise ValueError('Journal bypassed consistency')
        if journal['review_policy_sha256']!=ReviewPolicy().sha256:raise ValueError('Journal review policy changed')
        hashes=report['configuration_hashes'];actual=journal['adaptive_configuration_hashes']
        if hashes['review']!=ReviewPolicy().sha256 or hashes['adaptive']!=AdaptiveConfig().digest:raise ValueError('Journal policy configuration mismatch')
        if actual is not None and any(actual[k]!=hashes[k] for k in ('context','intelligence','adaptive')):raise ValueError('Journal configuration mismatch')
        scope=report['scope'];expected=_scope(report['dataset'],scope['evaluation']['end'],scope['requested_outcome_observation_cutoff_utc'])
        expected['outcome_observation_cutoff_utc']=journal['assessments'][-1]['timestamp_utc'] if journal['assessments'] else None
        if expected!=scope:raise ValueError('Journal scope mismatch')
        if any(utc(a['timestamp_utc'])>utc(scope['requested_outcome_observation_cutoff_utc']) for a in journal['assessments']):raise ValueError('Future assessment beyond observation cutoff')
        if report['accounting']!=journal_window_accounting(journal,scope):raise ValueError('Journal cohort accounting mismatch')
    if report['historical_validation']=='DATASET_PIPELINE_CHECKS_PASSED':
        m=report['dataset']
        if (journal is None or m['dataset_kind']!='INDEPENDENT_HISTORICAL' or m['source']['independent_review']!='ATTESTED'
                or not m['finality_attested'] or m['session_config_sha256'] is None
                or m['manifest_version']==2 and not all(r['status']=='VERIFIED' for r in m['evidence_review'].values())
                or not report['evaluation_coverage']['coverage_sufficient'] or report['status'] not in ('PASS','WARN')
                or report['historical_metrics']!=report['accounting']['cohorts']['evaluation']):
            raise ValueError('Historical journal eligibility unestablished')
    elif report['historical_validation']!='PENDING' or report['historical_metrics'] is not None:raise ValueError('Historical metrics must remain unmeasured')
    return True
