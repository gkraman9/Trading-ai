"""DecisionLog comparison never mistakes two absent logs for repeatability."""
from iat.historical_replay import validate_replay_report


def compare_reports(first,second,prefix):
    for report in (first,second,prefix):validate_replay_report(report)
    result={'comparison_version':1,'repeated_report_identical':first==second,
            'repeatability':{'status':'NOT_RUN','decision_log_hashes':None,'equal':None,'reason':'NO_DECISION_LOG'},
            'prefix_equivalence':{'status':'NOT_RUN','compared_decisions':0,'differences':None,'reason':'NO_DECISION_LOG'},
            'signal':'WAIT','execution_allowed':False}
    a,b,p=(r['decision_log'] for r in (first,second,prefix))
    if a is not None and b is not None:
        hashes=[first['decision_log_sha256'],second['decision_log_sha256']]
        same=hashes[0]==hashes[1]
        result['repeatability']={'status':'PASS' if same else 'FAIL','decision_log_hashes':hashes,'equal':same,'reason':'CANONICAL_DECISION_LOG_HASH_COMPARISON'}
    if a is not None and p is not None:
        keys=('context','intelligence','session')
        comparable=(all(a['configuration_hashes'][k]==p['configuration_hashes'][k] for k in keys)
                    and first['configurations']['window']==prefix['configurations']['window'])
        if not comparable:
            result['prefix_equivalence']['reason']='ANALYTICAL_CONFIGURATION_MISMATCH'
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
