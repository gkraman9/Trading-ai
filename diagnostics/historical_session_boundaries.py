"""Read-only local research from explicit CSV columns; no qualification declarations."""
import argparse,csv,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.historical_session_boundaries import inspect_csv_files,read_window,unavailable
from iat.chart_benchmark import write_new


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--m1',required=True);p.add_argument('--m5',required=True);p.add_argument('--calendar',required=True)
    p.add_argument('--timestamp-column',required=True)
    for k in ('open','high','low','close'):p.add_argument('--'+k+'-column',default=k)
    p.add_argument('--start-utc',required=True);p.add_argument('--end-utc',required=True);p.add_argument('--report-path',required=True)
    a=p.parse_args(argv);report=unavailable('RESEARCH_INPUT_UNAVAILABLE')
    try:
        mapping={k:getattr(a,k+'_column') for k in ('timestamp','open','high','low','close')}
        report=inspect_csv_files(a.m1,a.m5,a.calendar,a.start_utc,a.end_utc,mapping)
    except (ValueError,OSError,TypeError,KeyError,OverflowError,csv.Error):report=unavailable('RESEARCH_INPUT_OR_CALENDAR_INVALID')
    try:write_new(a.report_path,report)
    except (ValueError,OSError):print('BLOCKED: use a fresh private report path.');return 3
    print('Research only; DATA_NOT_QUALIFIED; signal WAIT; execution_allowed=false.')
    return 3


if __name__=='__main__':raise SystemExit(main())
