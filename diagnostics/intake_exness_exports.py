"""Offline private Exness export intake. No terminal, network, credentials or orders."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.exness_intake import intake_exports


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('m1','m5','output-directory','start-utc','end-utc','evaluation-start-utc','retrieved-at-utc','source-reference'):
        p.add_argument('--'+name,required=True)
    for tf in ('m1','m5'):
        p.add_argument('--'+tf+'-sha256',required=True)
        p.add_argument('--'+tf+'-bytes',type=int,required=True)
        p.add_argument('--'+tf+'-rows',type=int,required=True)
    p.add_argument('--authorized-local-use',action='store_true',help='Operator confirms permission for local offline inspection, not independent rights approval.')
    p.add_argument('--synthetic-fixture',action='store_true',help='Label generated test files explicitly; never use for real exports.')
    a=p.parse_args(argv)
    expected={tf.upper():dict(sha256=getattr(a,tf+'_sha256'),byte_count=getattr(a,tf+'_bytes'),row_count=getattr(a,tf+'_rows')) for tf in ('m1','m5')}
    try:
        r=intake_exports(a.m1,a.m5,a.output_directory,expected=expected,retrieved_at=a.retrieved_at_utc,
            reference=a.source_reference,start=a.start_utc,end=a.end_utc,evaluation_start=a.evaluation_start_utc,
            authorized_local_use=a.authorized_local_use,dataset_kind='SYNTHETIC_FIXTURE' if a.synthetic_fixture else 'INDEPENDENT_HISTORICAL')
    except (ValueError,OSError,KeyError,TypeError,OverflowError):
        print('BLOCKED: verify authorization, explicit UTC windows, expected hashes/counts and local file paths. Use a new private output directory; no existing output is replaced.')
        return 1
    if r['status']=='BLOCKED':
        print('BLOCKED: inspect intake-report.json for the failed stage. Freeze originals, verify expected values and retry in a new output directory.')
        print('Reason codes: '+', '.join(r['reason_codes'])+'; '+r.get('error_detail',''))
        return 1
    print('Private evidence prepared: intake-report.json, alignment-audit.json, candidate-package and provenance-assessment.json/.txt.')
    print('DATA_NOT_QUALIFIED; historical validation PENDING; comparisons NOT_RUN; Exness BLOCKED; WAIT; execution disabled.')
    return 3  # Evidence preparation is never historical validation or qualification.


if __name__=='__main__':raise SystemExit(main())
