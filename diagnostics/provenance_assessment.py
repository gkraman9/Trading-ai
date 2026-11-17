"""Private, read-only provenance gap exports. No download, account or order functions."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.chart_benchmark import write_new
from iat.provenance_assessment import assess_historical_provenance,validate_provenance_assessment,provenance_text


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest')
    parser.add_argument('--broker-binding')
    parser.add_argument('--import-spec')
    parser.add_argument('--independent-review')
    parser.add_argument('--source-registry')
    parser.add_argument('--replay-report')
    parser.add_argument('--json-output',required=True)
    parser.add_argument('--text-output',required=True)
    args=parser.parse_args(argv)
    inputs=dict(broker_binding_path=args.broker_binding,import_spec_path=args.import_spec,
        independent_review_path=args.independent_review,source_registry_path=args.source_registry,replay_report_path=args.replay_report)
    try:
        supplied=[Path(p).resolve() for p in (args.manifest,*inputs.values()) if p is not None]
        outputs=[Path(p).resolve() for p in (args.json_output,args.text_output)]
        if len(set(outputs))!=2 or any(p.exists() or p in supplied for p in outputs):raise ValueError('New private outputs required')
        report=assess_historical_provenance(args.manifest,**inputs)
        validate_provenance_assessment(report,args.manifest,**inputs)
        write_new(outputs[0],report);write_new(outputs[1],provenance_text(report))
    except (ValueError,TypeError,KeyError,OSError,OverflowError):
        print('FAIL: PROVENANCE_INPUT_OR_EXPORT_INVALID. Verify local inputs and choose new private output filenames.')
        return 1
    print('Private provenance gap report written. Historical validation PENDING; WAIT; execution disabled.')
    print('Evidence gap labels: '+str(report['evidence_coverage']['label_counts']))
    return 3  # No path from this assessment to independent qualification or execution.


if __name__=='__main__':raise SystemExit(main())
