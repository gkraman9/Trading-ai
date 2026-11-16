"""Research explanations for native session boundaries; ordinary gates stay intact."""
from collections import Counter
from datetime import timedelta
from iat.replay_dataset import utc
from iat.intelligence.models import iso,IntelligenceConfig
from iat.session_v2 import SessionCalendarV2,CLASSES,STATES
from iat.chart_benchmark import hashed,require
from iat.quality import assess_candles
from iat.analysis import validate_candles
from iat.historical_replay import safety

LIMIT=20000


def unavailable(code):
    return hashed({'boundary_report_version':1,'kind':'HISTORICAL_SESSION_BOUNDARY_RESEARCH','status':'UNAVAILABLE',
        'reason_codes':[code],'qualification':'DATA_NOT_QUALIFIED','historical_validation':'PENDING',
        'historical_comparisons':'NOT_RUN','ordinary_inputs_emitted':False,'safety':safety(),'exness':'BLOCKED'})


def boundary_research(rows,calendar,start,end,*,observation_errors=None,observation_origin='UNVERIFIED_INPUT'):
    """Calendar geometry is conditional; no missing OHLC, finality or permission is inferred."""
    if not isinstance(calendar,SessionCalendarV2):return unavailable('SESSION_V2_REQUIRED')
    require(observation_origin in ('UNVERIFIED_INPUT','SYNTHETIC_ONLY'))
    a,b=utc(start),utc(end);require(a<b and (b-a).total_seconds()/60<=LIMIT)
    require(set(rows)=={'M1','M5'} and all(isinstance(v,list) and len(v)<=5000 for v in rows.values()))
    public=calendar.public_state(b);context_known=(calendar.coverage_start<=a and b<calendar.coverage_end
        and b<calendar.expires_at and calendar.evidence_latest_at<=b)
    observation_errors={} if observation_errors is None else observation_errors
    records={};summaries={};codes=set(public['reason_codes']);indexes={};valid={}
    def classify(stamp,tf):
        nominal=calendar.classify_bar(stamp,tf,research=True) # No observed finality or as-of eligibility supplied.
        ordinary=calendar.classify_bar(stamp,tf)
        return {k:nominal[k] for k in ('classification','scheduled_open_utc','scheduled_end_utc','market_open_seconds','market_open_portions','phase_states','schedule_verified','broker_finality') }|{
            'ordinary_classification':ordinary['classification'],'schedule_context_valid':context_known,
            'ordinary_eligible':False,'scheduled_interval_elapsed_asof':utc(nominal['scheduled_end_utc'])<=b,'iat_execution_allowed':False}
    for tf in ('M1','M5'):
        counts=Counter();phases=Counter();opened=[];items=[];errors=list(observation_errors.get(tf,[]))
        for row in rows[tf]:
            try:
                t=utc(row['timestamp']);require(a<=t<b)
                item=classify(t,tf);items.append(item);opened.append(t);counts[item['classification']]+=1;phases.update(item['phase_states'])
            except (ValueError,TypeError,KeyError,OverflowError):errors.append('OBSERVATION_TIMESTAMP_OR_ALIGNMENT_INVALID')
        frequencies=Counter(opened);indexes[tf]={utc(r['timestamp']):r for r in rows[tf] if isinstance(r,dict) and isinstance(r.get('timestamp'),str) and _valid_stamp(r['timestamp'])}
        if any(n>1 for n in frequencies.values()):errors.append('TIMESTAMP_DUPLICATE')
        if any(y<x for x,y in zip(opened,opened[1:])):errors.append('TIMESTAMP_OUT_OF_ORDER')
        try:
            checked=validate_candles(rows[tf]);numeric_valid=True
            indexes[tf]={c.timestamp:{k:getattr(c,k) for k in ('open','high','low','close')} for c in checked}
        except (ValueError,TypeError,KeyError,OverflowError):numeric_valid=False;errors.append('OHLC_OR_HISTORY_INVALID')
        valid[tf]=numeric_valid and not errors
        # This is the unchanged ordinary gate with finality intentionally UNKNOWN.
        ordinary=assess_candles(rows[tf],tf,b,session_calendar=calendar,observed_finality=None).to_dict()
        expected_missing=0;trusted_missing=0;unresolved_missing=0;exhausted=False
        try:
            for n,t in enumerate(calendar.expected_intervals(a,b,timedelta(minutes=1 if tf=='M1' else 5))):
                if n>=LIMIT:exhausted=True;break
                if t not in frequencies:
                    item=classify(t,tf);expected_missing+=1
                    if valid[tf] and context_known and item['schedule_verified'] and item['classification']=='FULL_SESSION_BAR' and item['phase_states']==['FULL_TRADING']:trusted_missing+=1
                    else:unresolved_missing+=1
        except ValueError:exhausted=True
        if exhausted:codes.add('RESEARCH_LIMIT_EXCEEDED')
        records[tf]=items;summaries[tf]={'observed_count':len(rows[tf]),'classifications':{c:counts[c] for c in CLASSES},
            'phase_bar_counts':{s:phases[s] for s in STATES},'input_integrity_codes':sorted(set(errors)),
            'ordinary_quality_finality_unknown':ordinary,'nominal_missing_quote_slots':None if exhausted else expected_missing,
            'missing_full_under_verified_declarations':None if exhausted or not valid[tf] or not context_known or not calendar.quote_schedule_verified or any(c!='CANDLE_FINALITY_UNCERTAIN' for c in calendar.assurance_codes) else trusted_missing,
            'missing_unresolved_or_restricted_slots':None if exhausted else unresolved_missing}
        codes.update(errors)
        if any(c.startswith('PARTIAL_') or c=='CROSSES_SESSION_BREAK' for c,n in counts.items() if n):codes.add('PARTIAL_SESSION_CANDLE')
        if counts['OUTSIDE_SESSION']:codes.add('BAR_OUTSIDE_SESSION')
        if any(not i['schedule_verified'] or i['phase_states']==['UNKNOWN'] for i in items):codes.add('SESSION_PHASE_UNKNOWN')
        if any(i['phase_states']!=['FULL_TRADING'] for i in items):codes.add('BROKER_PHASE_RESTRICTED')
    m5=[];m1_counts=Counter(utc(r['timestamp']) for r in rows['M1'] if isinstance(r,dict) and isinstance(r.get('timestamp'),str) and _valid_stamp(r['timestamp']))
    comparison_counts=Counter();absence_counts=Counter()
    for item in records['M5']:
        opened=utc(item['scheduled_open_utc']);slots=[]
        for i in range(5):
            t=opened+timedelta(minutes=i);geometry=classify(t,'M1');present=m1_counts[t]
            if not a<=t<b:state='OUTSIDE_RESEARCH_WINDOW'
            elif present>1:state='PRESENT_DUPLICATE_AMBIGUOUS'
            elif present:state='PRESENT'
            elif not valid['M1']:state='MISSING_OBSERVATION_INPUT_INVALID'
            elif not context_known or not geometry['schedule_verified']:state='MISSING_UNESTABLISHED_UNVERIFIED_CALENDAR'
            elif geometry['classification']=='OUTSIDE_SESSION':state='CONFIGURED_OFF_QUOTE_ABSENCE'
            elif geometry['classification']=='FULL_SESSION_BAR' and geometry['phase_states']==['FULL_TRADING']:state='UNEXPECTED_MISSING_FULL_M1'
            elif geometry['classification']=='FULL_SESSION_BAR':state='MISSING_QUOTE_OBSERVATION_RESTRICTED_PHASE'
            else:state='MISSING_PARTIAL_OR_BREAK_SLOT'
            if state!='PRESENT':absence_counts[state]+=1
            slots.append({'timestamp_utc':iso(t),'observed_count':present,'assessment':state,'geometry':geometry})
        complete=all(s['assessment']=='PRESENT' for s in slots)
        comparison='NOT_COMPARED_FIVE_M1_UNAVAILABLE';differences=None
        if not valid['M1'] or not valid['M5']:comparison='NOT_COMPARED_INVALID_INPUT'
        elif item['classification']!='FULL_SESSION_BAR':comparison='NOT_COMPARED_PARTIAL_OR_UNKNOWN_SESSION'
        elif utc(item['scheduled_end_utc'])>b:comparison='NOT_COMPARED_UNELAPSED_SCHEDULED_INTERVAL'
        elif complete:
            original=indexes['M5'][opened];cs=[indexes['M1'][opened+timedelta(minutes=i)] for i in range(5)]
            derived={'open':cs[0]['open'],'high':max(c['high'] for c in cs),'low':min(c['low'] for c in cs),'close':cs[-1]['close']}
            differences={k:float(original[k])-float(v) for k,v in derived.items()}
            comparison='FIVE_M1_MATCH' if all(abs(v)<=IntelligenceConfig().epsilon for v in differences.values()) else 'FIVE_M1_MISMATCH'
        comparison_counts[comparison]+=1;m5.append({'geometry':item,'m1_slots':slots,'five_m1_comparison':comparison,'ohlc_differences':differences,
            'native_m5_replaced':False,'partial_finality':'UNESTABLISHED','ordinary_eligible':False})
    def priority(item):
        g=item['geometry']
        return (0 if g['classification']!='FULL_SESSION_BAR' else 1 if item['five_m1_comparison']!='FIVE_M1_MATCH' else 2 if g['phase_states']!=['FULL_TRADING'] else 3,g['scheduled_open_utc'])
    sample_geometry={tf:sorted(items,key=lambda g:(g['classification']=='FULL_SESSION_BAR',g['phase_states']==['FULL_TRADING'],g['scheduled_open_utc']))[:64] for tf,items in records.items()}
    return hashed({'boundary_report_version':1,'kind':'HISTORICAL_SESSION_BOUNDARY_RESEARCH','status':'RESEARCH_DIAGNOSTICS_ONLY',
        'scope':{'start':iso(a),'end':iso(b),'observations':'OPEN_WITHIN_WINDOW_INCLUDING_UNSUPPORTED_OR_UNELAPSED_BARS'},
        'observation_origin':observation_origin,
        'provenance':'SYNTHETIC_ONLY' if observation_origin=='SYNTHETIC_ONLY' or 'SYNTHETIC_TEST' in calendar.provenance_kinds else 'LOCAL_FILES_AND_CALENDAR_DECLARATIONS_UNVERIFIED',
        'calendar_state':public,'calendar_context_valid':context_known,'frames':summaries,'bar_geometry':sample_geometry,'per_frame_sample_limit':64,
        'm5_interval_total':len(m5),'m5_interval_sample_limit':64,'m5_intervals':sorted(m5,key=priority)[:64],'comparison_counts':dict(sorted(comparison_counts.items())),'m1_slot_absence_counts':dict(sorted(absence_counts.items())),
        'reason_codes':sorted(codes),'finality':'UNESTABLISHED_NO_FINALITY_FACT_INFERRED_FROM_CSV',
        'qualification':'DATA_NOT_QUALIFIED','ordinary_inputs_emitted':False,'historical_validation':'PENDING',
        'historical_comparisons':'NOT_RUN','safety':safety(),'exness':'BLOCKED'})


def _valid_stamp(value):
    try:utc(value);return True
    except (ValueError,TypeError):return False


def package_boundary_research(package_directory,start,end):
    """Read normalized candidates even when ordinary quality is blocked. Never clear a gate."""
    from pathlib import Path
    from iat.replay_dataset import load_dataset
    try:
        dataset=load_dataset(Path(package_directory)/'candidate-manifest.json')
        return boundary_research(dataset.rows,dataset.calendar,start,end,observation_origin='SYNTHETIC_ONLY' if dataset.metadata['dataset_kind']=='SYNTHETIC_FIXTURE' else 'UNVERIFIED_INPUT')
    except (OSError,ValueError,KeyError,TypeError):return unavailable('CANDIDATE_NORMALIZATION_OR_CALENDAR_UNAVAILABLE')
