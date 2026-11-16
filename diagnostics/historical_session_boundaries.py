"""Read-only local research from explicit CSV columns; no qualification declarations."""
import argparse,csv,sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.historical_session_boundaries import boundary_research,unavailable
from iat.pilot_preparation import file_fingerprint,_bounded_lines
from iat.replay_dataset import read_bytes,strict_json,utc
from iat.session_config import compile_session_config
from iat.chart_benchmark import write_new,require,hashed


def read_window(path,mapping,start,end):
    before=file_fingerprint(path);rows=[];errors=Counter();scanned=0
    with Path(path).open('r',encoding='utf-8-sig',newline='') as handle:
        reader=csv.DictReader(_bounded_lines(handle),strict=True)
        require(reader.fieldnames and len(reader.fieldnames)==len(set(reader.fieldnames)) and set(mapping.values())<=set(reader.fieldnames),'Explicit CSV column mapping required')
        for record in reader:
            scanned+=1;require(scanned<=10_000_000,'Research scan limit')
            try:
                require(all(v is not None for v in record.values()) and set(record)==set(reader.fieldnames))
                at=utc(record[mapping['timestamp']])
                if not utc(start)<=at<utc(end):continue
                rows.append({'timestamp':at.isoformat(),**{k:float(record[mapping[k]]) for k in ('open','high','low','close')}})
                require(len(rows)<=5000,'Research selected row limit')
            except (ValueError,TypeError,KeyError,OverflowError):
                # A limit must not silently produce a truncated diagnostic.
                if len(rows)>5000:raise
                errors['CSV_OBSERVATION_INVALID']+=1
    require(file_fingerprint(path)==before,'Source changed during inspection')
    return rows,{'fingerprint':before,'scanned_row_count':scanned,'selected_row_count':len(rows),'parse_errors':dict(errors)}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--m1',required=True);p.add_argument('--m5',required=True);p.add_argument('--calendar',required=True)
    p.add_argument('--timestamp-column',required=True)
    for k in ('open','high','low','close'):p.add_argument('--'+k+'-column',default=k)
    p.add_argument('--start-utc',required=True);p.add_argument('--end-utc',required=True);p.add_argument('--report-path',required=True)
    a=p.parse_args(argv);report=unavailable('RESEARCH_INPUT_UNAVAILABLE')
    try:
        start,end=utc(a.start_utc),utc(a.end_utc);require(start<end and (end-start).total_seconds()/60<=20000)
        config=read_bytes(a.calendar);calendar=compile_session_config(strict_json(config))
        mapping={k:getattr(a,k+'_column') for k in ('timestamp','open','high','low','close')}
        rows={};sources={}
        for tf,path in (('M1',a.m1),('M5',a.m5)):rows[tf],sources[tf]=read_window(path,mapping,a.start_utc,a.end_utc)
        report=boundary_research(rows,calendar,a.start_utc,a.end_utc,observation_errors={tf:list(info['parse_errors']) for tf,info in sources.items()})
        report.pop('sha256');report['file_observations']={'origin':'USER_SELECTED_LOCAL_CSV_NOT_AUTHENTICATED',
            'price_basis':'UNVERIFIED','source_permissions':'UNVERIFIED','columns':mapping,'sources':sources,
            'calendar_file_fingerprint':file_fingerprint(a.calendar)}
        if any(s['parse_errors'] for s in sources.values()):report['reason_codes']=sorted(set(report.get('reason_codes',[]))|{'CSV_OBSERVATION_INVALID'})
        report=hashed(report)
    except (ValueError,OSError,TypeError,KeyError,OverflowError,csv.Error):report=unavailable('RESEARCH_INPUT_OR_CALENDAR_INVALID')
    try:write_new(a.report_path,report)
    except (ValueError,OSError):print('BLOCKED: use a fresh private report path.');return 3
    print('Research only; DATA_NOT_QUALIFIED; signal WAIT; execution_allowed=false.')
    return 3


if __name__=='__main__':raise SystemExit(main())
