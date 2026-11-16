"""Offline reported evidence and local reproduction; no qualification or execution."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.chart_benchmark import write_new,hashed
from iat.historical_evidence_manifest import (read_observations,create_manifest,verify_local,validate_manifest,qualification_gate,TOOL,REQUIRED_CODES,local_path)


def safe_output(path,inputs):
    target=local_path(path)
    if '..' in target.parts or target.suffix.lower()!='.json' or target.is_symlink() or target.exists():raise ValueError('UNSAFE_OR_EXISTING_DESTINATION')
    if any(parent.is_symlink() for parent in target.parents) or not target.parent.is_dir() or target.resolve() in [Path(p).resolve() for p in inputs if p is not None]:raise ValueError('UNSAFE_OR_EXISTING_DESTINATION')
    return target


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('reported','verify'))
    parser.add_argument('--observations',required=True);parser.add_argument('--report-path',required=True)
    for key in ('m1','m5','diagnostic','calendar'):parser.add_argument('--'+key)
    args=parser.parse_args(argv);paths=[args.observations,args.m1,args.m5,args.diagnostic,args.calendar]
    try:target=safe_output(args.report_path,paths)
    except (ValueError,OSError):print('BLOCKED: use a fresh .json path in an existing private output directory.');return 2
    try:
        supplied=[args.m1,args.m5,args.diagnostic,args.calendar]
        if args.mode=='verify' and not all(supplied) or args.mode=='reported' and any(supplied):raise ValueError('MODE_INPUTS_INVALID')
        observations=read_observations(args.observations)
        report=create_manifest(observations) if args.mode=='reported' else verify_local(observations,m1_path=args.m1,m5_path=args.m5,diagnostic_path=args.diagnostic,calendar_path=args.calendar)
        validate_manifest(report)
    except (ValueError,OSError,TypeError,KeyError,OverflowError,RecursionError):
        report=hashed({'manifest_schema_version':1,'kind':'HISTORICAL_EVIDENCE_INPUT_FAILURE','tool_version':TOOL,
            'evidence_state':'INVALID_OR_CONFLICTING_EVIDENCE',
            **qualification_gate(None)})
        # Gate reasons remain visible alongside the input error.
        report.pop('sha256');report['reason_codes']=sorted(set(report['reason_codes'])|set(REQUIRED_CODES)|{'EVIDENCE_INPUT_INVALID_OR_UNAVAILABLE'});report=hashed(report)
    try:
        if len(json.dumps(report,allow_nan=False).encode())>4*1024*1024:raise ValueError('REPORT_SIZE_LIMIT')
        write_new(target,report)
    except (ValueError,OSError):print('BLOCKED: report not published; inspect destination and choose a fresh filename.');return 2
    print('Evidence state: '+report['evidence_state'])
    print('DATA_NOT_QUALIFIED; PENDING; NOT_RUN; Exness BLOCKED; signal WAIT; execution_allowed=false.')
    print('Reason codes: '+', '.join(report['reason_codes']))
    return 2 if report['evidence_state']=='INVALID_OR_CONFLICTING_EVIDENCE' else 3


if __name__=='__main__':raise SystemExit(main())
