"""Prepare a private, pending sample from the pinned CarlosSilva1 UTC bid-tick file."""
import argparse,csv,json
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.replay_dataset import utc
from iat.tick_sample import aggregate_bid_ticks

REVISION='d14fc64dc3b0452732e60662d94b500a6bb3d534'
RAW_SHA256='6dd18367ceed4385424a69c7d4380455cb526a866af8d352a59d25520e123bec'
CARD=f'https://huggingface.co/datasets/CarlosSilva1/xauusd-ticks/blob/{REVISION}/README.md'


def prepare(path,destination,*,start,evaluation_start,end,retrieved_at):
    import pyarrow.parquet as pq  # Optional preparation dependency, absent from runtime/CI requirements.
    if retrieved_at>datetime.now(timezone.utc):raise ValueError('Retrieval timestamp cannot be in the future')
    if not start<=evaluation_start<end:raise ValueError('Invalid evaluation range')
    source=Path(path)
    if source.stat().st_size>32*1024*1024:raise ValueError('Pinned source exceeds size bound')
    raw=source.read_bytes()
    if sha256(raw).hexdigest()!=RAW_SHA256:raise ValueError('Pinned archive checksum mismatch')
    def ticks():
        for batch in pq.ParquetFile(source).iter_batches(batch_size=65536,columns=['timestamp','bid_price']):
            for row in batch.to_pylist():
                # Dataset card explicitly declares its timezone-naive Arrow timestamp[ms] values UTC.
                at=row['timestamp']
                if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
                yield {'timestamp':at,'bid_price':row['bid_price']}
    one,five,audit=aggregate_bid_ticks(ticks(),start,end)
    target=Path(destination);target.mkdir(parents=True,exist_ok=False)
    frames={}
    for tf,rows in (('M1',one),('M5',five)):
        p=target/(tf.lower()+'.csv')
        with p.open('x',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['timestamp','open','high','low','close'],lineterminator='\n')
            writer.writeheader();writer.writerows(rows)
        frames[tf]={'file':p.name,'sha256':sha256(p.read_bytes()).hexdigest()}
    review={name:{'status':'VERIFIED','reference':CARD,'reason_code':'PUBLISHER_DECLARATION_REVIEWED'} for name in ('usage','instrument','timestamp','price_basis','calendar','finality')}
    review['calendar']={'status':'PENDING','reference':CARD,'reason_code':'DATED_SOURCE_CALENDAR_UNAVAILABLE'}
    review['finality']={'status':'PENDING','reference':CARD,'reason_code':'CAPTURE_COMPLETENESS_CONTRACT_UNAVAILABLE'}
    manifest={'version':2,'symbol':'XAUUSD','dataset_kind':'INDEPENDENT_HISTORICAL',
        'source':{'name':'Silva C XAUUSD Tick Data CC BY 4.0','reference':CARD,'retrieved_at_utc':retrieved_at.isoformat(),
                  'curation_id':'carlos-silva-2021-05-pilot-pending','independent_review':'PENDING'},
        'utc_range':{'start':start.isoformat(),'end':end.isoformat()},'frames':frames,'calendar':None,'finality_attested':False,
        'evaluation':{'start':evaluation_start.isoformat(),'end':end.isoformat()},
        'warmup':{tf:{'start':start.isoformat(),'end':evaluation_start.isoformat()} for tf in ('M1','M5')},
        'lineage':{'feed_id':'CarlosSilva1/xauusd-ticks','price_basis':'BID','timestamp_convention':'INTERVAL_OPEN_UTC',
                   'm5_origin':'AGGREGATED_FROM_M1','raw_sha256':RAW_SHA256},'evidence_review':review}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    (target/'preparation-audit.json').write_text(json.dumps(dict(audit,source_revision=REVISION,raw_sha256=RAW_SHA256),indent=2)+'\n',encoding='utf-8')
    return target/'manifest.json'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parquet',required=True);p.add_argument('--output-directory',required=True)
    p.add_argument('--start',required=True);p.add_argument('--evaluation-start',required=True);p.add_argument('--end',required=True)
    p.add_argument('--retrieved-at',required=True)
    a=p.parse_args()
    try:
        prepare(a.parquet,a.output_directory,start=utc(a.start),evaluation_start=utc(a.evaluation_start),end=utc(a.end),retrieved_at=utc(a.retrieved_at))
    except Exception:
        print('FAIL: SOURCE_SAMPLE_PREPARATION_FAILED');return 1
    print('Prepared private sample; calendar/finality/historical validation remain PENDING');return 0


if __name__=='__main__':raise SystemExit(main())
