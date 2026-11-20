"""Event-driven v3 research commentary. No data-provider or execution capability."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime,timezone
from threading import Lock,Thread,Event
import time
from iat.live_ai_evidence import fallback,catalog,validate,SECTIONS
from iat.live_commentary import CommentaryFailure
from iat.live_reasoning import LiveReasoning,CommentaryJournal
from iat.intelligence.strategy_replay import digest
from iat.live_observer import base


def now():return datetime.now(timezone.utc).isoformat()


class AIJournal(CommentaryJournal):
    filename='ai-commentary-v3.jsonl'
    log_version=3


class ResearchCommentary:
    """One request in flight. Current material evidence is the sole response authority."""
    def __init__(self,provider=None,*,error=None,min_seconds=60,clock=None,audit=None):
        if type(min_seconds) is not int or not 30<=min_seconds<=3600:raise ValueError('Interval must be 30..3600 seconds')
        self.provider=provider;self.error=error;self.min_seconds=min_seconds;self.clock=clock or time.monotonic;self.audit=audit
        self.lock=Lock();self.cache=OrderedDict();self.current=None;self.running=None;self.next_at=0;self.closed=False;self.thread=None
        self.counters=dict(requests=0,successes=0,failures=0,stale_rejections=0);self.last_success=None;self.last_context=None;self.audit_failed=False

    def _fallback(self,packet,status,code=None):
        return dict(status=status,source='DETERMINISTIC',fallback=True,validation='DETERMINISTIC_FALLBACK',
            provider=self.provider.provider_name if self.provider else None,model=self.provider.model if self.provider else None,
            sections=fallback(packet),reason_codes=[code] if code else [],bundle_id=packet['bundle_id'],
            evidence_cutoffs=packet['cutoffs'],request_snapshot_id=None,request_at_utc=None,response_at_utc=None,
            latency_ms=None,usage={},cached=False,commentary_id=None)

    def _annotate(self,out):
        out['metrics']=dict(self.counters);out['last_success_at_utc']=self.last_success
        out['last_success_provenance']=deepcopy(self.last_context)
        return out

    def poll(self,packet,context,*,connected=True,request=True):
        key=packet['bundle_id']
        with self.lock:
            self.current=key
            if not connected:return self._annotate(self._fallback(packet,'FALLBACK','NO_ELIGIBLE_CURRENT_FEED'))
            if self.audit_failed:return self._annotate(self._fallback(packet,'ERROR','AI_AUDIT_WRITE_FAILED'))
            if self.provider is None:return self._annotate(self._fallback(packet,'ERROR' if self.error else 'DISABLED',self.error))
            if key in self.cache:
                out=deepcopy(self.cache[key]);self.cache.move_to_end(key);out['cached']=True
                return self._annotate(out)
            if self.closed:return self._annotate(self._fallback(packet,'FALLBACK','AI_CLOSED'))
            if self.running:return self._annotate(self._fallback(packet,'REQUESTING','AI_REQUEST_IN_FLIGHT'))
            if self.clock()<self.next_at:return self._annotate(self._fallback(packet,'RATE_LIMITED','AI_MINIMUM_INTERVAL'))
            if not request:return self._annotate(self._fallback(packet,'CONFIGURED','AI_AWAITING_EVIDENCE_EVENT'))
            self.running=key;self.next_at=self.clock()+self.min_seconds;self.counters['requests']+=1
            copied=deepcopy(packet);provenance=deepcopy(context);requested=now()
            def work():
                started=time.monotonic()
                try:
                    result=self.provider.request(copied)
                    # Reconstruct a wire assertion from the rendered result to validate custom providers too.
                    by_id={c['fact_id']:c for c in copied['cards']};wire=[]
                    fields=('fact_id','evidence_ids','timeframe','event_type','level','direction')
                    for section in result['sections']:
                        claims=[]
                        for item in section['claims']:
                            fact=by_id[item['fact_id']]
                            if item!=dict(fact_id=fact['fact_id'],text=fact['text'],kind=fact['kind'],evidence_ids=fact['evidence_ids']):raise ValueError('Altered text')
                            claims.append({k:fact[k] for k in fields})
                        wire.append(dict(section=section['section'],claims=claims))
                    sections=validate(dict(version=3,bundle_id=key,sections=wire),copied)
                    usage=result.get('usage',{})
                    if not isinstance(usage,dict) or not set(usage)<= {'input_tokens','output_tokens','total_tokens'} or any(type(v) is not int or not 0<=v<=10**8 for v in usage.values()):raise ValueError('Invalid usage')
                    out=dict(status='ACTIVE',source='LLM_EVIDENCE_SELECTION',fallback=False,validation='TYPED_FACTS_REFERENCES_AND_COVERAGE_VALID',
                        provider=self.provider.provider_name,model=self.provider.model,sections=sections,reason_codes=[],bundle_id=key,
                        evidence_cutoffs=copied['cutoffs'],request_snapshot_id=provenance['snapshot_id'],request_at_utc=requested,
                        response_at_utc=now(),latency_ms=round((time.monotonic()-started)*1000),usage=usage,cached=False)
                except Exception as exc:
                    allowed={'AI_PROVIDER_TIMEOUT','AI_PROVIDER_RATE_LIMITED','AI_PROVIDER_HTTP_ERROR','AI_PROVIDER_ERROR',
                        'AI_INPUT_TOO_LARGE','AI_RESPONSE_TOO_LARGE','AI_RESPONSE_REJECTED','AI_RESPONSE_INCOMPLETE','AI_EVIDENCE_VALIDATION_FAILED'}
                    code=exc.code if isinstance(exc,CommentaryFailure) and exc.code in allowed else 'AI_EVIDENCE_VALIDATION_FAILED'
                    out=self._fallback(copied,'RATE_LIMITED' if code=='AI_PROVIDER_RATE_LIMITED' else 'ERROR',code)
                    out.update(request_snapshot_id=provenance['snapshot_id'],request_at_utc=requested,response_at_utc=now(),latency_ms=round((time.monotonic()-started)*1000))
                with self.lock:
                    stale=self.current!=key or self.closed
                    if stale:
                        self.counters['stale_rejections']+=1
                        rejected=self._fallback(copied,'FALLBACK','AI_RESPONSE_STALE_EVIDENCE')
                        for k in ('request_snapshot_id','request_at_utc','response_at_utc','latency_ms','usage'):rejected[k]=out[k]
                        out=rejected
                    if out['status']=='ACTIVE':
                        self.counters['successes']+=1;self.last_success=out['response_at_utc']
                        self.last_context=dict(snapshot_id=provenance['snapshot_id'],bundle_id=key,cutoffs=copied['cutoffs'])
                    else:self.counters['failures']+=1
                    out['commentary_id']='commentary:'+digest(out)
                # Audit before publishing ACTIVE; a disk failure cannot report unaudited success.
                try:
                    if self.audit:self.audit(provenance,copied,out)
                except Exception:
                    with self.lock:self.audit_failed=True
                with self.lock:
                    if not stale and not self.audit_failed:self.cache[key]=deepcopy(out)
                    self.running=None
                    while len(self.cache)>64:self.cache.popitem(last=False)
            self.thread=Thread(target=work,name='iat-ai-research-only',daemon=True);self.thread.start()
            return self._annotate(self._fallback(packet,'REQUESTING','AI_REQUEST_IN_FLIGHT'))

    def close(self):
        with self.lock:self.closed=True
        if self.thread:self.thread.join(timeout=2)
        if self.provider and (self.thread is None or not self.thread.is_alive()):self.provider.close()


class LiveAIReasoning:
    def __init__(self,manager=None,journal=None):
        self.journal=journal;self.manager=manager or ResearchCommentary();self.manager.audit=self._audit
        self.validator=LiveReasoning();self.entry_lock=Lock();self.lock=Lock();self.packet=None;self.view=None;self.material=None
        self.stop=Event();self.thread=None;self.audit_issue=False
    def _audit(self,context,packet,commentary):
        if self.journal:self.journal.append({'snapshot_id':context['snapshot_id']},{'claims':packet},commentary)
    def envelope(self,snapshot,*,request=True):
        with self.entry_lock:return self._envelope(snapshot,request=request)
    def _envelope(self,snapshot,*,request=True):
        # V1 and V2 remain unchanged; this layer has its own version and private journal.
        try:legacy=self.validator.envelope(snapshot)
        except Exception:legacy=self.validator.envelope(base(None,'AI_SOURCE_INVALID'))
        source=legacy['deterministic_snapshot'];view=legacy['readable']
        with self.lock:
            material=view['claims']['bundle_id']
            try:
                if material!=self.material:
                    packet=catalog(source,view,self.view)
                    self.packet=packet;self.view=deepcopy(view);self.material=material
                packet=deepcopy(self.packet)
            except Exception:
                source=base(None,'AI_EVIDENCE_CHRONOLOGY_OR_VALUES_INVALID');legacy=self.validator.envelope(source);view=legacy['readable']
                packet=catalog(source,view);self.packet=packet;self.view=deepcopy(view);self.material=view['claims']['bundle_id']
        context=dict(snapshot_id=source['snapshot_id'],cutoffs=source['cutoffs'])
        commentary=self.manager.poll(packet,context,connected=source['feed_status']=='CONNECTED',request=request)
        # Successful cached output is usable only for this exact packet/cutoff; quote-only changes are nonmaterial.
        if commentary['bundle_id']!=packet['bundle_id'] or commentary['evidence_cutoffs']!=source['cutoffs']:
            commentary=self.manager._fallback(packet,'FALLBACK','AI_RESPONSE_STALE_EVIDENCE')
        if self.audit_issue:commentary=self.manager._fallback(packet,'ERROR','AI_AUDIT_WRITE_FAILED')
        try:self._audit(context,packet,commentary)
        except Exception:
            self.audit_issue=True;commentary=self.manager._fallback(packet,'ERROR','AI_AUDIT_WRITE_FAILED')
        result={k:deepcopy(v) for k,v in legacy.items() if k not in ('sha256','commentary','envelope_version')}
        result.update(envelope_version=3,commentary=commentary,ai_evidence=dict(bundle_id=packet['bundle_id'],cutoffs=packet['cutoffs'],
            changes=packet['changes'],policy='MATERIAL_CLOSED_EVIDENCE_V1',fact_count=len(packet['cards']),
            scope=packet['scope']),observed_snapshot_id=source['snapshot_id'])
        result['sha256']=digest(result);return result
    def start(self,observer):
        if self.thread:raise ValueError('AI observer already started')
        def run():
            while not self.stop.is_set():
                try:self.envelope(observer.latest())
                except Exception:pass # Observer capability is separate; do not expose exception text.
                self.stop.wait(1)
        self.thread=Thread(target=run,name='iat-ai-evidence-watcher',daemon=True);self.thread.start()
    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=2)
        self.manager.close();self.validator.close()
