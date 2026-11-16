"""Private offline CSV inspection, import diagnostics and independent assessment."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.chart_benchmark import write_new
from iat.qualification_assistant import inspect_csv,validate_import,prepare_package,assess_candidate,ImportFailure,ACTIONS
from iat.replay_dataset import DatasetError


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    c=commands.add_parser('inspect');c.add_argument('--file',required=True);c.add_argument('--report-path',required=True)
    c=commands.add_parser('validate');c.add_argument('--spec',required=True);c.add_argument('--report-path',required=True)
    c=commands.add_parser('package');c.add_argument('--spec',required=True);c.add_argument('--output-directory',required=True)
    c=commands.add_parser('assess');c.add_argument('--package-directory',required=True);c.add_argument('--reviewed-manifest',required=True);c.add_argument('--independent-review',required=True);c.add_argument('--report-path',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='inspect':
            write_new(args.report_path,inspect_csv(args.file));print('INSPECTED: private header/hash report written; no qualification granted.');return 0
        if args.command=='validate':r=validate_import(args.spec);write_new(args.report_path,r)
        elif args.command=='package':r=prepare_package(args.spec,args.output_directory)
        else:
            r=assess_candidate(args.package_directory,args.reviewed_manifest,args.independent_review);write_new(args.report_path,r)
        print('Qualification: '+r['status'])
        if 'mechanical' in r:
            print('Mechanical: '+r['mechanical']['status'])
            for issue in r['issues']:print(issue['code']+': '+issue['action'])
        elif r['status']=='DATA_NOT_QUALIFIED':
            for code in r['reason_codes']:print(code+': '+ACTIONS.get(code,'See the private gate report and supply the required evidence.'))
        return 0 if r['status']=='HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED' else 3
    except (ImportFailure,DatasetError) as exc:
        print(exc.code+': '+ACTIONS.get(exc.code,'Inspect the declared input schema and local file availability.'));return 3
    except (OSError,ValueError,TypeError,KeyError):
        print('BLOCKED: output exists/unavailable or input is invalid. Use a fresh private destination and inspect the schema.');return 3


if __name__=='__main__':raise SystemExit(main())
