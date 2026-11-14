"""Human-reviewed, file-bound real-data eligibility; never creates approvals."""
from pathlib import Path
from hashlib import sha256
from iat.replay_dataset import load_dataset,local_file,read_bytes,strict_json,utc,DatasetError
from iat.historical_replay import dataset_preflight,safety
from iat.intelligence.models import IntelligenceConfig
from iat.chart_benchmark import require,keys,text,identifier,check_hash
from iat.intelligence.strategy_replay import digest

ITEMS=('usage','provenance','instrument','timestamp','price_basis','calendar','finality')


def qualify_historical(manifest_path=None,review_path=None,*,intelligence_config=None):
    result={'qualification_version':1,'status':'DATA_NOT_QUALIFIED','reason_codes':[],
            'dataset_id':None,'dataset':None,'human_review_sha256':None,'preflight':None,
            'assurance':'HUMAN_ATTESTATIONS_AND_DOCUMENT_HASHES_NOT_EXTERNALLY_AUTHENTICATED',
            'historical_validation':'PENDING','historical_comparisons':'NOT_RUN','safety':safety(),'exness':'BLOCKED'}
    reasons=[]
    if manifest_path is None:result['reason_codes']=['DATASET_UNAVAILABLE'];return result
    try:dataset=load_dataset(manifest_path)
    except DatasetError as exc:result['reason_codes']=[exc.code];return result
    m=dataset.metadata;result.update(dataset=m,dataset_id=digest(m))
    if m['dataset_kind']!='INDEPENDENT_HISTORICAL':reasons.append('REAL_HISTORICAL_DATA_REQUIRED')
    if m['manifest_version']!=2:reasons.append('MANIFEST_V2_REQUIRED')
    checked=dataset_preflight(dataset,intelligence_config=intelligence_config)
    result['preflight']=checked['preflight'];reasons.extend(checked['reason_codes'])
    coverage=checked['preflight']['alignment'].get('evaluation',{})
    if not coverage.get('coverage_sufficient'):reasons.append('EVALUATION_COVERAGE_INSUFFICIENT')
    if dataset.calendar is not None and 'SYNTHETIC_TEST' in getattr(dataset.calendar,'provenance_kinds',()):reasons.append('SYNTHETIC_CALENDAR_NOT_REAL_EVIDENCE')
    if review_path is None:reasons.append('HUMAN_QUALIFICATION_REVIEW_REQUIRED')
    else:
        try:
            raw=read_bytes(review_path);r=strict_json(raw);check_hash(r)
            keys(r,'qualification_version dataset_id interval provider_entity feed_id instrument price_basis reviewer_code independent_review_attested reviewed_at_utc decision evidence sha256')
            require(type(r['qualification_version']) is int and r['qualification_version']==1)
            require(r['dataset_id']==result['dataset_id'] and r['interval']==m['utc_range'])
            for field in ('provider_entity','feed_id'):text(r[field])
            identifier(r['reviewer_code']);require(r['independent_review_attested'] is True)
            require(utc(r['reviewed_at_utc'])>=utc(m['source']['retrieved_at_utc']))
            require(r['instrument']=='XAUUSD' and r['feed_id']==m['lineage']['feed_id'] and r['price_basis']==m['lineage']['price_basis'])
            require(r['decision'] in ('APPROVED','PENDING','REJECTED'))
            if r['decision']!='APPROVED':reasons.append('HUMAN_APPROVAL_NOT_GRANTED')
            keys(r['evidence'],' '.join(ITEMS))
            for name,item in r['evidence'].items():
                keys(item,'status file sha256 reference scope explanation')
                require(item['status'] in ('VERIFIED','PENDING'));text(item['reference']);text(item['explanation'])
                require(item['scope']==m['utc_range'])
                if item['status']!='VERIFIED':reasons.append('HUMAN_EVIDENCE_'+name.upper()+'_PENDING')
                content=read_bytes(local_file(Path(review_path).resolve().parent,item['file']))
                require(content and sha256(content).hexdigest()==item['sha256'],'Qualification evidence checksum mismatch')
            result['human_review_sha256']=sha256(raw).hexdigest()
        except (ValueError,TypeError,KeyError,OSError):reasons.append('HUMAN_QUALIFICATION_REVIEW_INVALID')
    result['reason_codes']=sorted(set(reasons))
    if not reasons:result['status']='HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED'
    return result
