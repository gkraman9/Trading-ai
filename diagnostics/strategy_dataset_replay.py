"""Private manifest-gated strategy replay. No network, credentials or broker imports."""
import argparse
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.evidence import AtomicEvidence
from iat.replay_dataset import read_bytes,strict_json,DatasetError
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.strategy_replay import digest
from iat.strategy_dataset_replay import (run_strategy_manifest,empty_strategy_dataset_report,
                                         validate_strategy_dataset_report)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest')
    parser.add_argument('--report-path',required=True)
    parser.add_argument('--context-config')
    parser.add_argument('--intelligence-config')
    args=parser.parse_args(argv)
    report=empty_strategy_dataset_report()
    report.update(status='FAIL',reason_codes=['RUN_INCOMPLETE'])
    identities=[]
    for path in (args.manifest,args.context_config,args.intelligence_config):
        try:identities.append(sha256(read_bytes(path)).hexdigest() if path else None)
        except DatasetError:identities.append('UNAVAILABLE')
    run_id=digest(identities);report['run_id']=run_id
    try:writer=AtomicEvidence(args.report_path,report,validator=validate_strategy_dataset_report)
    except (OSError,ValueError):
        print('FAIL: STRATEGY_REPORT_UNAVAILABLE');return 1
    try:
        context=ContextConfig.from_dict(strict_json(read_bytes(args.context_config))) if args.context_config else None
        intelligence=IntelligenceConfig.from_dict(strict_json(read_bytes(args.intelligence_config))) if args.intelligence_config else None
        report=run_strategy_manifest(args.manifest,config=context,intelligence_config=intelligence)
    except DatasetError as exc:
        report=empty_strategy_dataset_report();report.update(status='FAIL',reason_codes=[exc.code])
    except (KeyboardInterrupt,SystemExit):
        report=empty_strategy_dataset_report();report.update(status='FAIL',reason_codes=['REPLAY_INTERRUPTED'])
    except Exception:
        report=empty_strategy_dataset_report();report.update(status='FAIL',reason_codes=['STRATEGY_REPLAY_FAILED'])
    report['run_id']=run_id
    try:writer.publish(report)
    except (OSError,ValueError):
        print('FAIL: STRATEGY_REPORT_PUBLICATION_FAILED');return 1
    print('Status: '+report['status'])
    print('Historical validation: '+report['historical_validation'])
    print('Historical comparisons: '+report['historical_comparisons'])
    return {'PASS':0,'WARN':2,'FAIL':1,'BLOCKED':3}[report['status']]


if __name__=='__main__':raise SystemExit(main())
