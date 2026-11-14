"""Strict local XAUUSD dataset import. No downloads, terminal or account access."""
import csv
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path,PurePosixPath
import re
from urllib.parse import urlsplit
from iat.session_config import compile_session_config
from iat.intelligence.models import iso

MAX_BYTES=4*1024*1024
MAX_ROWS=5000


class DatasetError(ValueError):
    def __init__(self,code):
        super().__init__(code)
        self.code=code


def require(condition,code='DATASET_SCHEMA_INVALID'):
    if not condition:raise DatasetError(code)


def keys(value,names):
    require(isinstance(value,dict) and set(value)==set(names.split()))


def utc(value):
    try:
        require(isinstance(value,str),'DATASET_TIMESTAMP_INVALID')
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        require(result.utcoffset()==timedelta(0),'DATASET_TIMESTAMP_INVALID')
        return result.astimezone(timezone.utc)
    except (TypeError,ValueError,OverflowError) as exc:
        raise DatasetError('DATASET_TIMESTAMP_INVALID') from exc


def digest(data):return sha256(data).hexdigest()


def strict_json(raw):
    def pairs(items):
        out={}
        for k,v in items:
            require(k not in out,'DATASET_DUPLICATE_KEY')
            out[k]=v
        return out
    def constant(_):
        raise DatasetError('DATASET_SCHEMA_INVALID')
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
    except (ValueError,TypeError,UnicodeError) as exc:
        if isinstance(exc,DatasetError):raise
        raise DatasetError('DATASET_SCHEMA_INVALID') from exc


def read_bytes(path):
    try:
        with Path(path).open('rb') as handle:data=handle.read(MAX_BYTES+1)
        require(len(data)<=MAX_BYTES,'DATASET_SIZE_LIMIT')
        return data
    except OSError as exc:raise DatasetError('DATASET_UNAVAILABLE') from exc


def local_file(root,name):
    require(isinstance(name,str) and name and '\\' not in name and ':' not in name,'DATASET_PATH_INVALID')
    parsed=PurePosixPath(name)
    require(not parsed.is_absolute() and '..' not in parsed.parts,'DATASET_PATH_INVALID')
    result=(root/name).resolve()
    require(result.is_relative_to(root.resolve()),'DATASET_PATH_INVALID')
    return result


@dataclass(frozen=True)
class Dataset:
    metadata: dict
    rows: dict
    calendar: object | None
    finality_attested: bool
    provenance: str


def load_dataset(manifest_path):
    raw=read_bytes(manifest_path)
    manifest=strict_json(raw)
    keys(manifest,'version symbol dataset_kind source utc_range frames calendar finality_attested')
    require(type(manifest['version']) is int and manifest['version']==1,'DATASET_VERSION_UNSUPPORTED')
    require(manifest['symbol']=='XAUUSD','DATASET_SYMBOL_UNSUPPORTED')
    require(manifest['dataset_kind'] in ('SYNTHETIC_FIXTURE','INDEPENDENT_HISTORICAL'))
    require(type(manifest['finality_attested']) is bool)
    source=manifest['source'];keys(source,'name reference retrieved_at_utc curation_id independent_review')
    require(isinstance(source['name'],str) and re.fullmatch(r'[A-Za-z0-9 ._()/:-]{1,100}',source['name']))
    require(isinstance(source['curation_id'],str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',source['curation_id']))
    require(source['independent_review'] in ('PENDING','ATTESTED'))
    retrieved=utc(source['retrieved_at_utc'])
    reference=source['reference']
    require(isinstance(reference,str) and len(reference)<=512)
    parsed=urlsplit(reference)
    require(not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,'SOURCE_REFERENCE_UNSAFE')
    if manifest['dataset_kind']=='SYNTHETIC_FIXTURE':
        require(reference.startswith('synthetic:') and source['independent_review']=='PENDING')
    else:
        require(parsed.scheme=='https' and bool(parsed.hostname),'SOURCE_REFERENCE_UNSAFE')
    keys(manifest['utc_range'],'start end')
    start,end=(utc(manifest['utc_range'][k]) for k in ('start','end'))
    require(start<end,'DATASET_RANGE_INVALID')
    keys(manifest['frames'],'M1 M5')
    root=Path(manifest_path).resolve().parent
    rows={};coverage={};checksums={}
    for tf,period in (('M1',60),('M5',300)):
        spec=manifest['frames'][tf];keys(spec,'file sha256')
        require(isinstance(spec['sha256'],str) and re.fullmatch('[a-f0-9]{64}',spec['sha256']))
        content=read_bytes(local_file(root,spec['file']))
        checksum=digest(content)
        require(checksum==spec['sha256'],'DATASET_CHECKSUM_MISMATCH')
        try:
            reader=csv.DictReader(StringIO(content.decode('utf-8-sig')),strict=True)
            require(reader.fieldnames==['timestamp','open','high','low','close'],'DATASET_COLUMNS_INVALID')
            frame=[]
            for row in reader:
                require(set(row)==set(reader.fieldnames) and all(v is not None for v in row.values()),'DATASET_COLUMNS_INVALID')
                opened=utc(row['timestamp'])
                require(start<=opened and opened+timedelta(seconds=period)<=end,'BAR_OUTSIDE_DATASET_RANGE')
                frame.append({'timestamp':iso(opened),**{k:float(row[k]) for k in ('open','high','low','close')}})
                require(len(frame)<=MAX_ROWS,'DATASET_ROW_LIMIT')
            require(len(frame)>=3,'HISTORY_INCOMPLETE')
        except (ValueError,TypeError,UnicodeError,csv.Error) as exc:
            if isinstance(exc,DatasetError):raise
            raise DatasetError('DATASET_CSV_INVALID') from exc
        rows[tf]=frame
        openings=[utc(r['timestamp']) for r in frame]
        coverage[tf]={'candle_count':len(frame),'start_utc':iso(min(openings)),
                      'end_utc':iso(max(openings)+timedelta(seconds=period))}
        checksums[tf]={'file_sha256':checksum,'normalized_ohlc_sha256':digest(json.dumps(frame,sort_keys=True,separators=(',',':'),allow_nan=True).encode())}
    calendar=None;calendar_sha=None
    if manifest['calendar'] is not None:
        keys(manifest['calendar'],'file sha256')
        spec=manifest['calendar'];content=read_bytes(local_file(root,spec['file']))
        require(isinstance(spec['sha256'],str) and digest(content)==spec['sha256'],'DATASET_CHECKSUM_MISMATCH')
        calendar_sha=digest(content)
        try:calendar=compile_session_config(strict_json(content))
        except (ValueError,TypeError,KeyError) as exc:raise DatasetError('SESSION_CONFIG_INVALID') from exc
        require(calendar.symbol=='XAUUSD','DATASET_SYMBOL_MISMATCH')
    metadata={'manifest_version':1,'manifest_sha256':digest(raw),'symbol':'XAUUSD','dataset_kind':manifest['dataset_kind'],
        'source':dict(source,retrieved_at_utc=iso(retrieved)),'utc_range':{'start':iso(start),'end':iso(end)},
        'coverage':coverage,'checksums':checksums,'session_config_sha256':calendar_sha,
        'finality_attested':manifest['finality_attested'],'source_authenticity':'OPERATOR_DECLARATION_NOT_AUTHENTICATED'}
    return Dataset(metadata,rows,calendar,manifest['finality_attested'],
                   'SYNTHETIC_RESEARCH' if manifest['dataset_kind']=='SYNTHETIC_FIXTURE' else 'HISTORICAL_RESEARCH')
