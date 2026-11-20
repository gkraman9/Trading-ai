"""Additive v2 envelope and separate commentary journal; v1 identity is unchanged."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from threading import Lock
import json,os
from iat.live_readable import readable
from iat.live_observer import base
from iat.historical_replay import safety
from iat.live_commentary import CommentaryManager
from iat.intelligence.strategy_replay import digest


class CommentaryJournal:
    filename='commentary.jsonl'
    log_version=2
    def __init__(self,log_directory):
        root=Path(log_directory);repo=Path(__file__).resolve().parents[1]
        if not root.is_dir() or root.resolve().is_relative_to(repo) or any(p.is_symlink() for p in (root,*root.parents)):
            raise ValueError('Existing private log directory outside repository required')
        self.path=root/self.filename;self.path.open('xb').close()
        self.lock=Lock();self.last=None;self.previous=None
    def append(self,snapshot,view,commentary):
        key=digest([snapshot['snapshot_id'],view['claims']['bundle_id'],commentary])
        with self.lock:
            if key==self.last:return
            record=dict(commentary_log_version=self.log_version,source_snapshot_id=snapshot['snapshot_id'],
                claim_bundle_id=view['claims']['bundle_id'],recorded_at_utc=datetime.now(timezone.utc).isoformat(),
                commentary=commentary,previous_entry_sha256=self.previous,execution_allowed=False,signal='WAIT')
            record['sha256']=digest(record)
            with self.path.open('ab') as f:
                f.write((json.dumps(record,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode());f.flush();os.fsync(f.fileno())
            self.previous=record['sha256'];self.last=key


class LiveReasoning:
    def __init__(self,manager=None,journal=None):
        self.manager=manager or CommentaryManager();self.journal=journal;self.lock=Lock();self.last_id=None;self.last_view=None
    def envelope(self,snapshot):
        # The original frozen snapshot and its digest are not extended/mutated.
        source=deepcopy(snapshot)
        try:
            valid=(source['snapshot_id']==digest({k:v for k,v in source.items() if k!='snapshot_id'})
                and type(source['report_version']) is int and source['report_version']==1
                and source['model_version']=='IAT_LIVE_OBSERVER_V1' and source['symbol']=='XAUUSD'
                and source['mode']=='READ_ONLY_SHADOW' and source['research_assessment'] in ('WAIT','BUY_SCENARIO','SELL_SCENARIO','DATA_UNAVAILABLE')
                and source['safety']==safety() and source['signal']=='WAIT' and source['execution_allowed'] is False
                and source['broker_access'] is False and type(source['orders_requested']) is int and source['orders_requested']==0
                and source['exness']=='BLOCKED' and source['qualification']=='DATA_NOT_QUALIFIED'
                and source['historical_validation']=='PENDING' and source['historical_comparisons']=='NOT_RUN'
                and source['profitability_tested'] is False)
        except (KeyError,TypeError,ValueError,OverflowError):valid=False
        if not valid:source=base(None,'DETERMINISTIC_SNAPSHOT_INVALID')
        with self.lock:
            if source['snapshot_id']!=self.last_id:
                self.last_view=readable(source);self.last_id=source['snapshot_id']
            view=deepcopy(self.last_view)
        commentary=self.manager.commentary(view['claims'],allow_request=source['feed_status']=='CONNECTED')
        try:
            if self.journal:self.journal.append(source,view,commentary)
        except Exception:
            commentary=self.manager._fallback(view['claims'],'UNAVAILABLE','COMMENTARY_LOG_FAILED')
        result=dict(envelope_version=2,deterministic_snapshot=source,readable=view,commentary=commentary,
            signal='WAIT',execution_allowed=False,broker_access=False,orders_requested=0,
            profitability_tested=False,mode='READ_ONLY_SHADOW',historical_validation='PENDING',historical_comparisons='NOT_RUN',qualification='DATA_NOT_QUALIFIED',exness='BLOCKED')
        result['sha256']=digest(result);return result
    def close(self):self.manager.close()
