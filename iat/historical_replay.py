"""Offline dataset pipeline validation only. No broker or profitability operations."""
from collections import Counter
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
import json
import re
from iat.replay_dataset import Dataset,utc
from iat.quality import assess_candles
from iat.intelligence.models import IntelligenceConfig,iso
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.context import replay_context
from iat.intelligence.decision_log import DecisionLog,from_replay


def safety():
    return {'mode':'READ_ONLY_SHADOW','signal':'WAIT','execution_allowed':False,
            'broker_access':False,'orders_requested':0,'profitability_tested':False}


def empty_report(run_id):
    return {'report_version':1,'kind':'HISTORICAL_PIPELINE_REPLAY','run_id':run_id,'status':'FAIL',
            'reason_codes':['RUN_INCOMPLETE'],'historical_validation':'PENDING','dataset':None,
            'configurations':{},'preflight':{},'decision_log':None,'decision_log_sha256':None,
            'summary':{},'safety':safety()}


def validate_replay_report(report):
    expected=set(empty_report('placeholder'))
    if not isinstance(report,dict) or set(report)!=expected or type(report['report_version']) is not int or report['report_version']!=1 or report['kind']!='HISTORICAL_PIPELINE_REPLAY':
        raise ValueError('Invalid replay report schema')
    if not isinstance(report['run_id'],str) or not re.fullmatch('[a-f0-9]{64}',report['run_id']):raise ValueError('Invalid replay run ID')
    if report['status'] not in ('PASS','WARN','FAIL','BLOCKED') or report['safety']!=safety():
        raise ValueError('Unsafe replay report')
    if report['historical_validation'] not in ('PENDING','FAILED','DATASET_PIPELINE_CHECKS_PASSED'):
        raise ValueError('Invalid historical validation state')
    dataset=report['dataset']
    if dataset is not None and dataset['dataset_kind']=='SYNTHETIC_FIXTURE' and report['historical_validation']!='PENDING':
        raise ValueError('Synthetic data cannot certify historical validation')
    if report['historical_validation']=='DATASET_PIPELINE_CHECKS_PASSED':
        if (dataset is None or dataset['dataset_kind']!='INDEPENDENT_HISTORICAL'
                or dataset['source']['independent_review']!='ATTESTED' or not dataset['finality_attested']
                or dataset['session_config_sha256'] is None or report['decision_log'] is None
                or report['summary'].get('valid_snapshots',0)<1 or report['status'] not in ('PASS','WARN')):
            raise ValueError('Historical check scope is not established')
    if report['status'] in ('PASS','WARN') and report['decision_log'] is None:
        raise ValueError('Completed replay requires a DecisionLog')
    if report['decision_log'] is not None:
        log=report['decision_log']
        if set(log)!={'log_version','configuration_hashes','entries'} or type(log['log_version']) is not int or log['log_version']!=1:
            raise ValueError('Invalid DecisionLog')
        previous=None
        for row in log['entries']:
            if row['signal']!='WAIT' or row['execution_allowed'] is not False or row['mode']!='READ_ONLY_SHADOW':
                raise ValueError('Unsafe DecisionLog')
            at=utc(row['timestamp_utc'])
            if previous is not None and at<=previous:raise ValueError('Nonchronological DecisionLog')
            previous=at
            if any(utc(e['available_at'])>at for e in row['context_evidence']):raise ValueError('Future evidence in log')
        checksum=sha256(json.dumps(log,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        if checksum!=report['decision_log_sha256']:raise ValueError('DecisionLog checksum mismatch')
    json.dumps(report,allow_nan=False)


def alignment_check(dataset,tolerance):
    one={utc(r['timestamp']):r for r in dataset.rows['M1']}
    comparable=uncovered=mismatches=0
    for bar in dataset.rows['M5']:
        opened=utc(bar['timestamp'])
        times=[opened+timedelta(minutes=i) for i in range(5)]
        if not all(t in one for t in times):uncovered+=1;continue
        rows=[one[t] for t in times]
        comparable+=1
        expected={'open':rows[0]['open'],'high':max(r['high'] for r in rows),
                  'low':min(r['low'] for r in rows),'close':rows[-1]['close']}
        if any(abs(expected[k]-bar[k])>tolerance for k in expected):mismatches+=1
    return {'policy':'FIVE_M1_TO_M5_OHLC_ABSOLUTE_TOLERANCE','tolerance':tolerance,
            'comparable_m5_bars':comparable,'uncovered_m5_bars':uncovered,'mismatch_count':mismatches}


def summarize(entries):
    selected=Counter(e.selected_hypothesis for e in entries)
    reasons=Counter(reason for e in entries if e.abstained for reason in e.abstention_reasons)
    quality=Counter(reason for e in entries if e.data_quality_status=='BLOCKED' for reason in e.abstention_reasons)
    changes=sum(a.selected_hypothesis!=b.selected_hypothesis for a,b in zip(entries,entries[1:]))
    event_changes=sum(r['previous_evidence_id'] is not None for e in entries for r in e.evidence_revisions)
    return {'snapshots':len(entries),'valid_snapshots':sum(e.data_quality_status=='VALID' for e in entries),
            'blocked_snapshots':sum(e.data_quality_status=='BLOCKED' for e in entries),
            'abstentions':sum(e.abstained for e in entries),'abstention_reason_counts':dict(sorted(reasons.items())),
            'blocked_reason_counts':dict(sorted(quality.items())),'selected_hypothesis_counts':dict(sorted(selected.items())),
            'hypothesis_changes':changes,'evidence_appearances':sum(len(e.evidence_ids) for e in entries),
            'unique_contextual_evidence_versions':entries[-1].unique_evidence_count if entries else 0,
            'unique_choch_events':entries[-1].unique_event_count if entries else 0,
            'choch_context_revisions':event_changes,
            'decision_start_utc':entries[0].timestamp_utc if entries else None,
            'decision_end_utc':entries[-1].timestamp_utc if entries else None}


def run_dataset(dataset,*,config=None,intelligence_config=None,window=100):
    if not isinstance(dataset,Dataset):raise ValueError('Validated dataset container required')
    if type(window) is not int or not 3<=window<=5000:raise ValueError('Replay window must be in [3,5000]')
    config=ContextConfig() if config is None else config
    phase7=IntelligenceConfig() if intelligence_config is None else intelligence_config
    if not isinstance(config,ContextConfig) or not isinstance(phase7,IntelligenceConfig):raise ValueError('Typed configurations required')
    replay_policy={'version':1,'window':window,'as_of_policy':'M1_CLOSED_PREFIX',
                   'alignment_policy':'FIVE_M1_TO_M5_OHLC_ABSOLUTE_TOLERANCE','alignment_tolerance':phase7.epsilon}
    hashes={'context':config.digest,'intelligence':phase7.digest,'session':dataset.metadata['session_config_sha256'],
            'replay_policy':sha256(json.dumps(replay_policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    run_id=sha256(json.dumps([dataset.metadata,hashes,window],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    report=empty_report(run_id)
    report['dataset']=dataset.metadata
    report['configurations']={'hashes':hashes,'context':asdict(config),'intelligence':asdict(phase7),'window':window}
    historical=dataset.metadata['dataset_kind']=='INDEPENDENT_HISTORICAL'
    requirements=[]
    if historical:
        if dataset.metadata['source']['independent_review']!='ATTESTED':requirements.append('INDEPENDENT_REVIEW_PENDING')
        if dataset.calendar is None:requirements.append('SESSION_CALENDAR_REQUIRED')
        elif getattr(dataset.calendar,'version',1)!=2:requirements.append('SESSION_V2_REQUIRED')
        if not dataset.finality_attested:requirements.append('CANDLE_FINALITY_UNCERTAIN')
    end=utc(dataset.metadata['utc_range']['end'])
    checks={}
    for tf in ('M1','M5'):
        checks[tf]=assess_candles(dataset.rows[tf],tf,end,session_calendar=dataset.calendar,
            observed_finality=dataset.finality_attested).to_dict()
    report['preflight']={'frames':checks,'alignment':{},'requirements':requirements}
    errors=[d['code'] for q in checks.values() if not q['valid'] for d in q['diagnostics']]
    if requirements or errors:
        report.update(status='BLOCKED',reason_codes=sorted(set(requirements+errors)))
        validate_replay_report(report);return report
    alignment=alignment_check(dataset,phase7.epsilon)
    report['preflight']['alignment']=alignment
    if alignment['mismatch_count'] or not alignment['comparable_m5_bars']:
        report.update(status='FAIL',reason_codes=['M1_M5_OHLC_MISMATCH' if alignment['mismatch_count'] else 'M1_M5_ALIGNMENT_UNESTABLISHED'],
                      historical_validation='FAILED' if historical else 'PENDING')
        validate_replay_report(report);return report
    decisions=tuple(from_replay(entry) for entry in replay_context('XAUUSD',dataset.rows['M1'],dataset.rows['M5'],
        window=window,config=config,intelligence_config=phase7,provenance=dataset.provenance,
        calendar=dataset.calendar,observed_finality=dataset.finality_attested))
    log=DecisionLog(1,hashes,decisions)
    summary=summarize(decisions)
    report.update(decision_log=log.to_dict(),decision_log_sha256=log.sha256,summary=summary)
    report['reason_codes']=[]
    if not historical:report['reason_codes'].append('SYNTHETIC_EVIDENCE_HISTORICAL_VALIDATION_PENDING')
    if summary['blocked_snapshots']:report['reason_codes'].append('BLOCKED_SNAPSHOTS_RECORDED')
    if not summary['valid_snapshots']:
        report.update(status='BLOCKED',historical_validation='PENDING')
        report['reason_codes'].append('NO_ELIGIBLE_SNAPSHOTS')
    else:
        report['status']='WARN' if report['reason_codes'] else 'PASS'
        report['historical_validation']='DATASET_PIPELINE_CHECKS_PASSED' if historical else 'PENDING'
    validate_replay_report(report)
    return report
