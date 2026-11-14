"""Offline historical pipeline runner. Never imports MT5 or downloads datasets."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.evidence import AtomicEvidence
from iat.replay_dataset import load_dataset,read_bytes,strict_json,DatasetError
from iat.historical_replay import empty_report,validate_replay_report,run_dataset
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',help='Local v1 manifest; omitted means independent dataset unavailable')
    parser.add_argument('--report-path',required=True)
    parser.add_argument('--context-config')
    parser.add_argument('--intelligence-config')
    parser.add_argument('--window',type=int,default=100)
    args=parser.parse_args(argv)
    # Reserve failure before parsing/importing any user-supplied dataset. No old success reused.
    request=[]
    for path in (args.manifest,args.context_config,args.intelligence_config):
        try:request.append(sha256(read_bytes(path)).hexdigest() if path else None)
        except DatasetError:request.append('UNAVAILABLE')
    run_id=sha256(json.dumps([request,args.window],separators=(',',':')).encode()).hexdigest()
    report=empty_report(run_id)
    try:writer=AtomicEvidence(args.report_path,report,validator=validate_replay_report)
    except (OSError,ValueError):
        print('FAIL: REPLAY_REPORT_UNAVAILABLE');return 1
    try:
        if args.manifest is None:
            report.update(status='BLOCKED',reason_codes=['INDEPENDENT_DATASET_UNAVAILABLE'])
        else:
            context=ContextConfig.from_dict(strict_json(read_bytes(args.context_config))) if args.context_config else ContextConfig()
            intelligence=IntelligenceConfig.from_dict(strict_json(read_bytes(args.intelligence_config))) if args.intelligence_config else IntelligenceConfig()
            report=run_dataset(load_dataset(args.manifest),config=context,intelligence_config=intelligence,window=args.window)
            report['run_id']=run_id
    except DatasetError as exc:
        report=empty_report(run_id)
        report.update(status='BLOCKED' if exc.code=='DATASET_UNAVAILABLE' else 'FAIL',reason_codes=[exc.code])
    except (KeyboardInterrupt,SystemExit):
        report=empty_report(run_id);report['reason_codes']=['REPLAY_INTERRUPTED']
    except Exception:
        report=empty_report(run_id);report['reason_codes']=['REPLAY_FAILED']
    try:writer.publish(report)
    except (OSError,ValueError):
        print('FAIL: REPLAY_PUBLICATION_FAILED');return 1
    print('Status: '+report['status'])
    print('Historical validation: '+report['historical_validation'])
    return {'PASS':0,'WARN':2,'FAIL':1,'BLOCKED':3}[report['status']]


if __name__=='__main__':raise SystemExit(main())
