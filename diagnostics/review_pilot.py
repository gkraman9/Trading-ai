"""Local, private blinded pilot operator commands. No broker or network access."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.chart_benchmark import read_json,write_new,packet_html,require
from iat.pilot_qualification import qualify_historical
from iat.review_pilot import register_plan,generate_pilot,annotation_v2_template,pilot_receipt,reveal_pilot,validate_pilot


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);commands=p.add_subparsers(dest='command',required=True)
    c=commands.add_parser('qualify');c.add_argument('--manifest');c.add_argument('--qualification');c.add_argument('--report-path',required=True)
    for name in ('register','register-synthetic'):
        c=commands.add_parser(name);c.add_argument('--manifest',required=True);c.add_argument('--qualification');c.add_argument('--spec',required=True);c.add_argument('--pilot-directory',required=True)
    c=commands.add_parser('packets');c.add_argument('--manifest',required=True);c.add_argument('--qualification');c.add_argument('--pilot-directory',required=True)
    c=commands.add_parser('submit');c.add_argument('--pilot-directory',required=True);c.add_argument('--annotation',required=True)
    c=commands.add_parser('reveal');c.add_argument('--pilot-directory',required=True);c.add_argument('--authorize-reveal',action='store_true')
    args=p.parse_args(argv)
    try:
        if args.command=='qualify':
            r=qualify_historical(args.manifest,args.qualification);write_new(args.report_path,r)
            print(r['status']);return 3 if r['status']=='DATA_NOT_QUALIFIED' else 0
        root=Path(args.pilot_directory);private=root/'private'
        if args.command in ('register','register-synthetic'):
            plan,q=register_plan(args.manifest,read_json(args.spec),args.qualification,synthetic_only=args.command=='register-synthetic')
            if plan is None:print('DATA_NOT_QUALIFIED');return 3
            root.mkdir(exist_ok=False);private.mkdir();(private/'receipts').mkdir()
            write_new(private/'qualification.json',q);write_new(private/'plan.json',plan)
            print('REGISTERED: plan locked before replay.');return 0
        plan=read_json(private/'plan.json')
        if args.command=='packets':
            bundle=generate_pilot(plan,args.manifest,args.qualification)
            public=root/'reviewer-packets';public.mkdir(exist_ok=False)
            write_new(private/'bundle.json',bundle)
            for packet in bundle['benchmark']['packets']:
                stem=packet['packet_id'];write_new(public/(stem+'.json'),packet);write_new(public/(stem+'.html'),packet_html(packet))
                # Templates stay private until individually assigned; don't reveal the roster.
                for reviewer in plan['reviewer_codes']:write_new(private/(stem+'.'+reviewer+'.template.json'),annotation_v2_template(packet,reviewer))
            write_new(root/'PACKETS_COMPLETE.json',{'pilot_version':1,'plan_sha256':plan['sha256'],'mode':plan['mode'],'signal':'WAIT','execution_allowed':False})
            print('PACKETS_READY: share only assigned packet and individual template.');return 0
        require((root/'PACKETS_COMPLETE.json').exists(),'Packet publication incomplete')
        bundle=read_json(private/'bundle.json');validate_pilot(bundle);require(bundle['plan']==plan)
        if args.command=='submit':
            r=pilot_receipt(bundle,read_json(args.annotation));a=r['annotation']
            write_new(private/'receipts'/(a['packet_id']+'.'+a['reviewer_id']+'.json'),r)
            print('SUBMITTED: immutable receipt.');return 0
        expected={p['packet_id']+'.'+r+'.json' for p in bundle['benchmark']['packets'] for r in plan['reviewer_codes']}
        folder=private/'receipts';require({p.name for p in folder.iterdir()}==expected)
        result=reveal_pilot(bundle,[read_json(folder/name) for name in sorted(expected)],authorized=args.authorize_reveal)
        write_new(private/'revealed.json',result['private_review'])
        write_new(root/'anonymous-report.json',result['export'])
        print('REVEALED: anonymous report; original annotations and identity mapping remain private.');return 0
    except (ValueError,TypeError,KeyError,OSError,OverflowError):
        print('BLOCKED: invalid pilot input, qualification, submission, authorization or publication.');return 3


if __name__=='__main__':raise SystemExit(main())
