"""Offline blinded chart packets, immutable annotations and private reveal."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.chart_benchmark import (prepare_benchmark,validate_bundle,annotation_template,receipt_for,
    compare_benchmark,packet_html,write_new,read_json,require)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare');p.add_argument('--manifest',required=True);p.add_argument('--at',action='append',required=True)
    p.add_argument('--reviewer',action='append',required=True);p.add_argument('--output-directory',required=True)
    p=commands.add_parser('record');p.add_argument('--private-bundle',required=True);p.add_argument('--annotation',required=True);p.add_argument('--receipts-directory',required=True)
    p=commands.add_parser('reveal');p.add_argument('--private-bundle',required=True);p.add_argument('--receipts-directory',required=True);p.add_argument('--report-path',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='prepare':
            # Fresh directory only. Share reviewer-packets only; keep private/ inaccessible to reviewers.
            bundle=prepare_benchmark(args.manifest,args.at,args.reviewer)
            root=Path(args.output_directory);root.mkdir(exist_ok=False)
            public=root/'reviewer-packets';public.mkdir();private=root/'private';private.mkdir();(private/'receipts').mkdir()
            write_new(private/'bundle.json',bundle)
            for packet in bundle['packets']:
                stem=packet['packet_id'];write_new(public/(stem+'.json'),packet);write_new(public/(stem+'.html'),packet_html(packet))
                for reviewer in bundle['reviewer_ids']:write_new(public/(stem+'.'+reviewer+'.annotation.json'),annotation_template(packet,reviewer))
            write_new(root/'COMPLETE.json',{'workflow_version':1,'status':'PREPARED','packet_count':len(bundle['packets']),
                'independent_analyst_agreement':'UNMEASURED','signal':'WAIT','execution_allowed':False,'exness':'BLOCKED'})
            print('PREPARED: share only reviewer-packets; keep private directory inaccessible to reviewers.');return 0
        bundle=read_json(args.private_bundle);validate_bundle(bundle);receipts=Path(args.receipts_directory)
        if args.command=='record':
            receipt=receipt_for(bundle,read_json(args.annotation));a=receipt['annotation']
            require(receipts.is_dir(),'Receipt directory unavailable')
            write_new(receipts/(a['packet_id']+'.'+a['reviewer_id']+'.json'),receipt)
            print('RECORDED: immutable annotation receipt.');return 0
        # Read exactly the frozen roster. Extra files are rejected to expose accidental mixing.
        expected={p['packet_id']+'.'+r+'.json' for p in bundle['packets'] for r in bundle['reviewer_ids']}
        require(receipts.is_dir() and {p.name for p in receipts.iterdir()}==expected,'Missing or unexpected receipts')
        report=compare_benchmark(bundle,[read_json(receipts/name) for name in sorted(expected)])
        write_new(args.report_path,report)
        print('REVEALED: private agreement report; independent agreement '+report['independent_analyst_agreement']);return 0
    except (OSError,ValueError,TypeError,KeyError,OverflowError):
        # No exception text, source paths, OHLC, annotation prose or account details on stdout.
        print('BLOCKED: benchmark input, blinding gate or publication invalid; no completed result produced.');return 3


if __name__=='__main__':raise SystemExit(main())
