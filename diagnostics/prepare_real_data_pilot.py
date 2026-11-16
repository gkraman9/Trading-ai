"""Offline streaming archive/window preparation and qualified blind-review handoff."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.pilot_preparation import prepare_pilot,handoff_review


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);commands=p.add_subparsers(dest='command',required=True)
    for name in ('inspect','prepare'):
        c=commands.add_parser(name);c.add_argument('--spec');c.add_argument('--m1');c.add_argument('--m5',required=True)
        c.add_argument('--start-utc',required=True);c.add_argument('--end-utc',required=True);c.add_argument('--evaluation-start-utc',required=True)
        c.add_argument('--output-directory',required=True)
    c=commands.add_parser('handoff');c.add_argument('--preparation-directory',required=True)
    c.add_argument('--reviewed-manifest');c.add_argument('--independent-review');c.add_argument('--pilot-spec');c.add_argument('--output-directory',required=True)
    a=p.parse_args(argv)
    try:
        if a.command=='handoff':
            result=handoff_review(a.preparation_directory,a.reviewed_manifest,a.independent_review,a.pilot_spec,a.output_directory)
            print('Readiness: '+result['status'])
            for code in result['reason_codes']:print(code)
            return 0 if result['review_packets_created'] else 3
        result=prepare_pilot(a.spec,a.m1,a.m5,a.output_directory,start=a.start_utc,end=a.end_utc,evaluation_start=a.evaluation_start_utc,dry_run=a.command=='inspect')
        print('Readiness: BLOCKED; qualification DATA_NOT_QUALIFIED')
        for code in result['readiness']['reason_codes']:print(code)
        print('Inspect source-inspection.json, alignment-audit.json and evidence-checklist.json. Use a fresh output directory for the next step.')
        return 3
    except (ValueError,OSError,KeyError,TypeError,OverflowError):
        print('BLOCKED: supply readable authorized CSVs, explicit UTC boundaries/import metadata and a fresh private output directory. No files are overwritten.');return 3


if __name__=='__main__':raise SystemExit(main())
