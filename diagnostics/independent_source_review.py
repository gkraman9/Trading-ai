"""Generate an offline source-evidence review packet; no approval or network access."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.independent_source_evidence import read_registry,review_registry,validate_source_report,REPORT_KIND
from iat.historical_evidence_manifest import qualification_gate,REQUIRED_CODES
from iat.chart_benchmark import write_new,hashed
from diagnostics.historical_evidence_manifest import safe_output


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry',required=True);p.add_argument('--manifest');p.add_argument('--artifact-root');p.add_argument('--report-path',required=True)
    a=p.parse_args(argv)
    try:target=safe_output(a.report_path,[a.registry,a.manifest,a.artifact_root])
    except (ValueError,OSError):print('BLOCKED: choose a fresh local .json path in an existing private directory.');return 2
    try:
        registry,fingerprint=read_registry(a.registry)
        report=review_registry(registry,artifact_root=a.artifact_root,manifest_path=a.manifest);validate_source_report(report)
        report.pop('sha256');report['registry_file_fingerprint']=fingerprint;report=hashed(report)
    except (ValueError,OSError,TypeError,KeyError,OverflowError,RecursionError,IndexError):
        report=hashed({**qualification_gate(None),'source_review_version':1,'kind':'HISTORICAL_SOURCE_REVIEW_INPUT_FAILURE',
            'reason_codes':sorted(set(REQUIRED_CODES)|{'INDEPENDENT_QUALIFICATION_REQUIRED','SOURCE_REVIEW_INPUT_INVALID_OR_UNAVAILABLE'})})
    try:
        if len(json.dumps(report,allow_nan=False).encode())>4*1024*1024:raise ValueError('SOURCE_REPORT_SIZE_LIMIT')
        write_new(target,report)
    except (ValueError,OSError):print('BLOCKED: report not published; use a fresh private filename.');return 2
    print('DATA_NOT_QUALIFIED; historical validation PENDING; comparisons NOT_RUN; Exness BLOCKED; signal WAIT; execution_allowed=false.')
    if report['kind']==REPORT_KIND:
        for entry in report['claim_matrix']:print(entry['claim']['id']+': '+entry['classification'])
    print('Reason codes: '+', '.join(report['reason_codes']))
    invalid=(report['kind']!=REPORT_KIND or report['local_manifest_inspection']['status']=='INVALID_OR_CONFLICTING_MANIFEST'
        or any(e['source_integrity']['status'] in ('MISMATCH','UNAVAILABLE') for e in report.get('source_assessments',[])))
    return 2 if invalid else 3


if __name__=='__main__':raise SystemExit(main())
