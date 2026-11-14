"""DecisionLog comparison never mistakes two absent logs for repeatability."""
from iat.historical_replay import validate_replay_report
from iat.replay_dataset import utc


def compare_reports(first,second,prefix):
    for report in (first,second,prefix):validate_replay_report(report)
    result={'comparison_version':1,'repeated_report_identical':first==second,
            'repeatability':{'status':'NOT_RUN','decision_log_hashes':None,'equal':None,'reason':'NO_DECISION_LOG'},
            'prefix_equivalence':{'status':'NOT_RUN','compared_decisions':0,'differences':None,'reason':'NO_DECISION_LOG'},
            'signal':'WAIT','execution_allowed':False}
    a,b,p=(r['decision_log'] for r in (first,second,prefix))
    if a is not None and b is not None:
        hashes=[first['decision_log_sha256'],second['decision_log_sha256']]
        comparable=(first['dataset']==second['dataset']
                    and first['configurations']==second['configurations']
                    and a['configuration_hashes']==b['configuration_hashes'])
        same=hashes[0]==hashes[1]
        if not comparable:
            result['repeatability'].update(decision_log_hashes=hashes,reason='INPUT_OR_CONFIGURATION_MISMATCH')
        else:
            result['repeatability']={'status':'PASS' if same else 'FAIL','decision_log_hashes':hashes,'equal':same,'reason':'CANONICAL_DECISION_LOG_HASH_COMPARISON'}
    if a is not None and p is not None:
        keys=('context','intelligence','session')
        comparable=(all(a['configuration_hashes'][k]==p['configuration_hashes'][k] for k in keys)
                    and first['configurations']['window']==prefix['configurations']['window'])
        if not comparable:
            result['prefix_equivalence']['reason']='ANALYTICAL_CONFIGURATION_MISMATCH'
        elif not _same_prefix_origin(first['dataset'],prefix['dataset']):
            result['prefix_equivalence']['reason']='SOURCE_OR_WARMUP_MISMATCH'
        elif not _contained_range(first['dataset'],prefix['dataset']):
            result['prefix_equivalence']['reason']='PREFIX_RANGE_NOT_CONTAINED'
        elif not p['entries']:
            result['prefix_equivalence']['reason']='EMPTY_PREFIX'
        else:
            end=p['entries'][-1]['timestamp_utc']
            before=[row for row in a['entries'] if row['timestamp_utc']<=end]
            count=max(len(before),len(p['entries']))
            differences=sum((before[i] if i<len(before) else None)!=(p['entries'][i] if i<len(p['entries']) else None) for i in range(count))
            result['prefix_equivalence']={'status':'PASS' if differences==0 else 'FAIL','compared_decisions':count,
                                         'differences':differences,'reason':'FULL_PREFIX_ENTRIES_COMPARED_WITHOUT_FUTURE_OUTCOMES'}
    return result


def _same_prefix_origin(full, prefix):
    # File/manifest hashes necessarily change for a separately checksummed prefix.
    # Source identity, raw archive lineage and per-frame warm-up must not change.
    keys=('manifest_version','symbol','dataset_kind','source','lineage','warmup',
          'finality_attested','session_config_sha256','evidence_review')
    return (full is not None and prefix is not None
            and all(full.get(k)==prefix.get(k) for k in keys)
            and utc(full['utc_range']['start'])==utc(prefix['utc_range']['start'])
            and (full.get('evaluation') is None and prefix.get('evaluation') is None
                 or full.get('evaluation') is not None and prefix.get('evaluation') is not None
                 and utc(full['evaluation']['start'])==utc(prefix['evaluation']['start'])))


def _contained_range(full, prefix):
    start,end=(utc(prefix['utc_range'][k]) for k in ('start','end'))
    if not start<end<=utc(full['utc_range']['end']):return False
    if full.get('evaluation') is not None:
        a,b=(utc(prefix['evaluation'][k]) for k in ('start','end'))
        return start<=a<b<=end and b<=utc(full['evaluation']['end'])
    return True
