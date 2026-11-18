"""Optional bounded OpenAI commentary selection; never a fact or decision generator."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime,timezone
from threading import Lock,Thread
import json,re,time
import requests
from iat.replay_dataset import strict_json

ENDPOINT='https://api.openai.com/v1/chat/completions'


class CommentaryFailure(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)


def response_schema(packet):
    return dict(type='object',additionalProperties=False,required=['format_version','bundle_id','choices'],properties={
        'format_version':{'type':'integer','enum':[1]},'bundle_id':{'type':'string'},
        'choices':dict(type='array',minItems=len(packet['claims']),maxItems=len(packet['claims']),items=dict(type='object',
            additionalProperties=False,required=['claim_id','wording_id','evidence_ids'],properties={
                'claim_id':{'type':'string'},
                'wording_id':{'type':'string','enum':['plain','alternative']},
                'evidence_ids':{'type':'array','items':{'type':'string'},'maxItems':10000}}))})


def validate_choices(value,packet):
    """Exact claim coverage prevents dropping WAIT or opposition; no free prose accepted."""
    def need(ok):
        if not ok:raise CommentaryFailure('AI_RESPONSE_REJECTED')
    need(isinstance(value,dict) and set(value)=={'format_version','bundle_id','choices'})
    need(type(value['format_version']) is int and value['format_version']==1 and value['bundle_id']==packet['bundle_id'])
    need(isinstance(value['choices'],list) and len(value['choices'])==len(packet['claims']))
    claims={c['id']:c for c in packet['claims']};seen=set();rendered=[]
    for choice in value['choices']:
        need(isinstance(choice,dict) and set(choice)=={'claim_id','wording_id','evidence_ids'})
        key=choice['claim_id'];need(isinstance(key,str) and key in claims and key not in seen);seen.add(key)
        c=claims[key];need(isinstance(choice['wording_id'],str) and choice['wording_id'] in c['wordings'])
        need(choice['evidence_ids']==c['evidence_ids'])
        rendered.append(dict(claim_id=key,section=c['section'],text=c['wordings'][choice['wording_id']],evidence_ids=c['evidence_ids']))
    need(seen==set(claims))
    return rendered


class OpenAICommentary:
    """Only a fixed HTTPS endpoint, explicit key, strict JSON and bounded transport.

    Credentials are held only in memory/headers and never returned or logged.
    No redirects, environment proxies, raw logs or terminal objects are used.
    """
    provider_name='OpenAI'
    def __init__(self,key,model,*,session=None,timeout=8):
        if not isinstance(key,str) or not 10<=len(key)<=512 or any(ord(c)<33 for c in key):
            raise CommentaryFailure('LLM_KEY_UNAVAILABLE')
        if not isinstance(model,str) or not re.fullmatch('[A-Za-z0-9._:-]{1,100}',model):
            raise CommentaryFailure('LLM_MODEL_REQUIRED')
        if type(timeout) not in (float,int) or isinstance(timeout,bool) or not 1<=timeout<=15:
            raise CommentaryFailure('LLM_TIMEOUT_INVALID')
        self._key=key;self.model=model;self.timeout=timeout
        self._session=session or requests.Session();self._session.trust_env=False

    def request(self,packet):
        # Explicit projection: never serialize a live snapshot or private log.
        prompt=dict(symbol='XAUUSD',bundle_id=packet['bundle_id'],claims=packet['claims'])
        payload=dict(model=self.model,messages=[
            dict(role='system',content='Arrange the supplied approved market-observation statements into readable commentary. Return one choice for EVERY claim, including WAIT, opposing evidence and safety. Choose only a supplied wording_id and copy its evidence_ids exactly. Never add prose, prices, facts, recommendations or execution fields.'),
            dict(role='user',content=json.dumps(prompt,sort_keys=True,separators=(',',':'),allow_nan=False))],
            response_format=dict(type='json_schema',json_schema=dict(name='iat_approved_commentary_v1',strict=True,schema=response_schema(packet))),
            max_completion_tokens=1800)
        response=None;started=time.monotonic()
        try:
            response=self._session.post(ENDPOINT,json=payload,headers={'Authorization':'Bearer '+self._key},
                timeout=(min(3,self.timeout),self.timeout),allow_redirects=False,stream=True)
            if response.status_code!=200:raise CommentaryFailure('AI_PROVIDER_HTTP_ERROR')
            raw=bytearray()
            # Small reads allow a wall-budget check even for a trickling response body.
            for chunk in response.iter_content(chunk_size=1):
                if time.monotonic()-started>self.timeout:raise CommentaryFailure('AI_PROVIDER_TIMEOUT')
                raw.extend(chunk)
                if len(raw)>64*1024:raise CommentaryFailure('AI_RESPONSE_TOO_LARGE')
            data=strict_json(bytes(raw))
            if (not isinstance(data,dict) or not isinstance(data.get('choices'),list) or len(data['choices'])!=1
                or data['choices'][0].get('finish_reason')!='stop'):
                raise CommentaryFailure('AI_RESPONSE_REJECTED')
            message=data['choices'][0]['message']
            if message.get('refusal') or message.get('tool_calls') or not isinstance(message.get('content'),str):raise CommentaryFailure('AI_RESPONSE_REJECTED')
            return validate_choices(strict_json(message['content'].encode()),packet)
        except requests.Timeout:raise CommentaryFailure('AI_PROVIDER_TIMEOUT') from None
        except CommentaryFailure:raise
        except Exception:raise CommentaryFailure('AI_PROVIDER_UNAVAILABLE_OR_INVALID') from None
        finally:
            if response is not None:response.close()

    def close(self):self._session.close()


class CommentaryManager:
    """One in-flight call, failed-input caching, closed-evidence caching and global cooldown."""
    def __init__(self,provider=None,*,unavailable_code=None,min_seconds=60,clock=None):
        if type(min_seconds) is not int or not 30<=min_seconds<=3600:raise ValueError('LLM minimum interval is 30..3600 seconds')
        self.provider=provider;self.unavailable_code=unavailable_code;self.min_seconds=min_seconds
        self.clock=clock or time.monotonic;self.lock=Lock();self.cache=OrderedDict();self.running=None;self.next_at=0;self.closed=False;self.thread=None

    def _fallback(self,packet,status,code):
        return dict(status=status,source='DETERMINISTIC',provider=None if self.provider is None else self.provider.provider_name,
            model=None if self.provider is None else self.provider.model,validation='DETERMINISTIC_FALLBACK',
            reason_codes=[code] if code else [],commentary_at_utc=None,cached=False,
            statements=[dict(claim_id=c['id'],section=c['section'],text=c['wordings']['plain'],evidence_ids=c['evidence_ids']) for c in packet['claims']])

    def commentary(self,packet,*,allow_request=True):
        key=packet['bundle_id']
        with self.lock:
            if key in self.cache:
                out=deepcopy(self.cache[key]);self.cache.move_to_end(key);out['cached']=True;return out
            if self.provider is None:return self._fallback(packet,'UNAVAILABLE' if self.unavailable_code else 'DISABLED',self.unavailable_code)
            if self.closed or not allow_request:return self._fallback(packet,'UNAVAILABLE','NO_ELIGIBLE_CURRENT_FEED')
            if self.running is not None:return self._fallback(packet,'UNAVAILABLE','AI_REQUEST_PENDING')
            if self.clock()<self.next_at:return self._fallback(packet,'UNAVAILABLE','AI_RATE_LIMIT_WAIT')
            self.running=key;self.next_at=self.clock()+self.min_seconds
            # Packet has only whitelisted derived claims, not the MT5/observer capability.
            copied=deepcopy(packet)
            def work():
                try:
                    statements=self.provider.request(copied)
                    # Providers return locally validated selections; reconstruct and verify IDs/text again.
                    expected={c['id']:c for c in copied['claims']}
                    if len(statements)!=len(expected) or {s['claim_id'] for s in statements}!=set(expected):raise CommentaryFailure('AI_RESPONSE_REJECTED')
                    for item in statements:
                        c=expected[item['claim_id']]
                        if set(item)!={'claim_id','section','text','evidence_ids'} or item['section']!=c['section'] or item['text'] not in c['wordings'].values() or item['evidence_ids']!=c['evidence_ids']:
                            raise CommentaryFailure('AI_RESPONSE_REJECTED')
                    out=dict(status='ACTIVE',source='LLM_ASSISTED_APPROVED_WORDING',provider=self.provider.provider_name,
                        model=self.provider.model,validation='APPROVED_CLAIMS_AND_REFERENCES_ONLY',reason_codes=[],
                        commentary_at_utc=datetime.now(timezone.utc).isoformat(),cached=False,statements=statements)
                except Exception as exc:
                    out=self._fallback(copied,'UNAVAILABLE',exc.code if isinstance(exc,CommentaryFailure) else 'AI_PROVIDER_UNAVAILABLE_OR_INVALID')
                with self.lock:
                    self.cache[key]=deepcopy(out);self.running=None
                    while len(self.cache)>64:self.cache.popitem(last=False)
            self.thread=Thread(target=work,name='iat-commentary-only',daemon=True);self.thread.start()
            return self._fallback(packet,'UNAVAILABLE','AI_REQUEST_PENDING')

    def close(self):
        with self.lock:self.closed=True
        if self.thread is not None:self.thread.join(timeout=2)
        if self.provider is not None and (self.thread is None or not self.thread.is_alive()):self.provider.close()
