"""Offline or demo-gated v2 research comparison; no approval or execution switch."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diagnostics.mt5_readonly_check import load_metadata, SafeParser
from iat.broker_sessions import compare_broker_sessions
from iat.evidence import AtomicEvidence, diagnostic, publish_research_preflight_failure
from iat.session_config import load_session_bundle, SessionConfigError
from iat.session_research import new_research_report, research_report, validate_research_report
from iat.session_capture import capture_demo_research


def main(argv=None):
    parser=SafeParser(description='Read-only v2 research; blocked calendars remain blocked')
    parser.add_argument('--config',required=True)
    parser.add_argument('--report-path',required=True)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--observations')
    modes.add_argument('--capture-demo',action='store_true')
    parser.add_argument('--broker-metadata')
    parser.add_argument('--terminal-path')
    writer=None
    args=None
    try:
        args=parser.parse_args(argv)
        config,calendar=load_session_bundle(args.config)
        if getattr(calendar,'version',1)!=2:raise ValueError('Explicit v2 required')
        if args.terminal_path is not None and not args.capture_demo:raise ValueError('Terminal path only applies to capture')
        now=datetime.now(timezone.utc)
        initial=new_research_report(calendar,now)
        writer=AtomicEvidence(args.report_path,initial,validator=validate_research_report)
        if args.capture_demo:
            report=capture_demo_research(args.config,metadata_path=args.broker_metadata,terminal_path=args.terminal_path)
        else:
            observations=None
            if args.observations is not None:
                payload=load_metadata(args.observations)
                if not isinstance(payload,dict) or set(payload)!={'version','frames'} or type(payload['version']) is not int or payload['version']!=1:raise ValueError('Invalid timestamp observation file')
                observations=payload['frames']
            comparison=None
            if args.broker_metadata is not None:
                comparison=compare_broker_sessions(object(),config,calendar,load_metadata(args.broker_metadata),now=now)
            report=research_report(calendar,now,observations,
                                   origin='FILE_UNVERIFIED' if observations is not None else 'CONFIG_ONLY',
                                   broker_comparison=comparison)
        report['run_id']=initial['run_id']
        writer.publish(report)
        print(json.dumps(report,indent=2,allow_nan=False))
        return {'PASS':0,'WARN':2,'FAIL':1,'BLOCKED':3}[report['status']]
    except (Exception,KeyboardInterrupt) as exc:
        code=diagnostic(exc.code)['code'] if isinstance(exc,SessionConfigError) else 'QUALITY_UNESTABLISHED'
        if args is not None and writer is None:
            try:publish_research_preflight_failure(args.report_path,code)
            except Exception:pass
        print(json.dumps({'status':'FAIL','code':code,'signal':'WAIT','execution_allowed':False}))
        return 1


if __name__=='__main__':raise SystemExit(main())
