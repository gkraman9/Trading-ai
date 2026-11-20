"""SYNTHETIC data and real SDK with mocked transport; never actual API/MT5 validation."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import json,tempfile,time,unittest
import httpx2 as httpx
from openai import OpenAI
from jsonschema import validate as json_validate
from test_live_observer import WaveMT5,NOW
from test_live_reasoning import AdvancingMT5
from iat.live_data import ReadOnlyMarketData
from iat.live_observer import LiveObserver,ShadowLog,base
from iat.live_readable import readable
from iat.live_ai_evidence import catalog,schema,validate,fallback
from iat.live_ai_provider import OpenAIResearchProvider
from iat.live_ai_runtime import LiveAIReasoning,ResearchCommentary,AIJournal
from iat.live_commentary import CommentaryFailure
from iat.live_dashboard import create_dashboard
from iat.intelligence.strategy_replay import digest

FIELDS=('fact_id','evidence_ids','timeframe','event_type','level','direction')


def wire(packet):
    return deepcopy(dict(version=3,bundle_id=packet['bundle_id'],sections=[dict(section=s,claims=[{k:c[k] for k in FIELDS} for c in packet['cards'] if c['section']==s]) for s in packet['required_fact_ids']]))


def rehash(snapshot):
    snapshot['snapshot_id']=digest({k:v for k,v in snapshot.items() if k!='snapshot_id'});return snapshot


class MockResearchProvider:
    provider_name='SYNTHETIC_MOCK';model='not-a-real-model'
    def __init__(self,error=None):self.calls=[];self.error=error;self.entered=Event();self.release=None
    def request(self,packet):
        self.calls.append(deepcopy(packet));self.entered.set()
        if self.release:self.release.wait(3)
        if self.error:raise CommentaryFailure(self.error)
        return dict(sections=validate(wire(packet),packet),usage={'input_tokens':100,'output_tokens':50,'total_tokens':150})
    def close(self):pass


class LiveAIV3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='iat-v3-SYNTHETIC-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.mt5=WaveMT5();self.log=ShadowLog(self.root/'logs')
        self.observer=LiveObserver(ReadOnlyMarketData(self.mt5),self.log,clock=lambda:NOW)
        self.snapshot=self.observer.step();self.view=readable(self.snapshot);self.packet=catalog(self.snapshot,self.view)
        self.context={'snapshot_id':self.snapshot['snapshot_id']}
    def manager(self,provider=None,**kwargs):
        m=ResearchCommentary(provider,**kwargs);self.addCleanup(m.close);return m
    def finish(self,m):
        if m.thread:m.thread.join(4)
        self.assertFalse(m.thread and m.thread.is_alive())
    def sdk(self,mutate=None,*,status=200,body=None,error=None):
        calls=[]
        def transport(request):
            calls.append(request)
            if error:raise error
            if body is not None:return httpx.Response(status,content=body)
            prompt=json.loads(json.loads(request.content)['input']);value=wire(prompt)
            if mutate:mutate(value)
            payload=dict(status='completed',error=None,incomplete_details=None,output=[dict(type='message',role='assistant',content=[dict(type='output_text',text=json.dumps(value))])],usage=dict(input_tokens=123,output_tokens=45,total_tokens=168))
            return httpx.Response(status,json=payload)
        client=OpenAI(api_key='synthetic-no-real-key',max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(transport),trust_env=False,follow_redirects=False),timeout=30)
        provider=OpenAIResearchProvider('synthetic-no-real-key','gpt-4.1-mini',client=client);self.addCleanup(provider.close)
        return provider,calls
    def safe(self,result):
        self.assertEqual(result['sha256'],digest({k:v for k,v in result.items() if k!='sha256'}))
        for r in (result,result['deterministic_snapshot']):
            self.assertEqual(r['signal'],'WAIT');self.assertIs(r['execution_allowed'],False);self.assertEqual(r['orders_requested'],0)
            self.assertEqual(r['exness'],'BLOCKED');self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED')
            self.assertEqual(r['historical_validation'],'PENDING');self.assertEqual(r['historical_comparisons'],'NOT_RUN');self.assertFalse(r['profitability_tested'])
        self.assertEqual(self.mt5.orders,0)
    def test_default_disabled_preserves_all_gates_and_v1_identity(self):
        v=LiveAIReasoning().envelope(self.snapshot);self.safe(v)
        self.assertEqual(v['commentary']['status'],'DISABLED');self.assertEqual(v['deterministic_snapshot'],self.snapshot)
        self.assertIn('SESSION_CALENDAR_UNAVAILABLE',json.dumps(v));self.assertIn('BLOCKED_DATA_QUALITY',json.dumps(v))
    def test_missing_key_and_model_fail_without_network(self):
        for key,model,code in ((None,'m','LLM_KEY_UNAVAILABLE'),('synthetic-123',None,'LLM_MODEL_REQUIRED'),('secret\nkey-123','m','LLM_KEY_UNAVAILABLE')):
            with self.assertRaises(CommentaryFailure) as e:OpenAIResearchProvider(key,model)
            self.assertEqual(e.exception.code,code)
        v=LiveAIReasoning(self.manager(error='LLM_KEY_UNAVAILABLE')).envelope(self.snapshot)
        self.assertEqual(v['commentary']['status'],'ERROR');self.assertTrue(v['commentary']['fallback'])
    def test_optional_sdk_missing_keeps_import_and_fallback_working(self):
        import builtins
        original=builtins.__import__
        def missing(name,*a,**k):
            if name=='openai':raise ImportError('synthetic missing')
            return original(name,*a,**k)
        with patch('builtins.__import__',side_effect=missing):
            with self.assertRaises(CommentaryFailure) as exc:OpenAIResearchProvider('synthetic-123','m')
        self.assertEqual(exc.exception.code,'LLM_OPTIONAL_SDK_MISSING')
    def test_actual_sdk_construction_has_fixed_url_zero_retry_and_no_proxy(self):
        p=OpenAIResearchProvider('synthetic-123','gpt-4.1-mini');self.addCleanup(p.close)
        self.assertEqual(str(p.client.base_url),'https://api.openai.com/v1/');self.assertEqual(p.client.max_retries,0)
        self.assertFalse(p.client._client._trust_env);self.assertFalse(p.client._client.follow_redirects)
    def test_sdk_responses_api_valid_structured_response(self):
        p,calls=self.sdk();out=p.request(self.packet)
        self.assertEqual(len(out['sections']),9);self.assertEqual(out['usage']['total_tokens'],168)
        self.assertEqual(str(calls[0].url),'https://api.openai.com/v1/responses')
        payload=json.loads(calls[0].content);self.assertFalse(payload['store']);self.assertEqual(payload['tools'],[])
        self.assertTrue(payload['text']['format']['strict']);self.assertEqual(payload['max_output_tokens'],12000)
        json_validate(wire(self.packet),schema())
    def test_sdk_only_projects_public_research_packet(self):
        p,calls=self.sdk();packet=deepcopy(self.packet);packet['raw_log']='PRIVATE_ACCOUNT_TOKEN_SERVER'
        p.request(packet);payload=calls[0].content.decode()
        self.assertNotIn('PRIVATE_ACCOUNT_TOKEN_SERVER',payload);self.assertNotIn('synthetic-no-real-key',payload)
        self.assertNotIn('source_registry',payload);self.assertNotIn('quote',json.loads(payload)['input'])
    def test_sdk_timeout_sanitized(self):
        p,calls=self.sdk(error=httpx.ReadTimeout('sensitive-key'))
        with self.assertRaises(CommentaryFailure) as e:p.request(self.packet)
        self.assertEqual(e.exception.code,'AI_PROVIDER_TIMEOUT');self.assertNotIn('sensitive',str(e.exception));self.assertEqual(len(calls),1)
    def test_sdk_rate_limit_zero_automatic_retries(self):
        p,calls=self.sdk(status=429,body=b'{"error":{"message":"PRIVATE_SECRET","type":"rate_limit_error"}}')
        with self.assertRaises(CommentaryFailure) as e:p.request(self.packet)
        self.assertEqual(e.exception.code,'AI_PROVIDER_RATE_LIMITED');self.assertEqual(len(calls),1);self.assertNotIn('PRIVATE',str(e.exception))
    def test_invalid_structured_response_and_refusal_rejected(self):
        for raw in (b'not json',b'{"status":"incomplete","output":[]}',b'{"status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"refusal","refusal":"secret"}]}]}'):
            p,_=self.sdk(body=raw)
            with self.assertRaises(CommentaryFailure):p.request(self.packet)
    def test_response_size_limit(self):
        p,_=self.sdk(body=b'x'*(256*1024+1))
        with self.assertRaises(CommentaryFailure) as e:p.request(self.packet)
        self.assertEqual(e.exception.code,'AI_RESPONSE_TOO_LARGE')
    def test_fabricated_fact_or_evidence_reference_rejected(self):
        for field in ('fact_id','evidence_ids'):
            value=wire(self.packet);value['sections'][0]['claims'][0][field]='made-up' if field=='fact_id' else ['made-up']
            with self.assertRaises(ValueError):validate(value,self.packet)
    def test_unsupported_price_level_rejected(self):
        value=wire(self.packet);claim=next(c for s in value['sections'] for c in s['claims'] if c['level'])
        claim['level']['lower']+=.01
        with self.assertRaises(ValueError):validate(value,self.packet)
    def test_contradictory_direction_event_or_timeframe_rejected(self):
        for field,bad in (('direction','BULLISH'),('timeframe','M5'),('event_type','FABRICATED_BOS')):
            value=wire(self.packet);value['sections'][0]['claims'][0][field]=bad
            with self.assertRaises(ValueError):validate(value,self.packet)
    def test_free_prose_execution_fields_or_probabilities_rejected(self):
        for extra in ({'text':'BUY now'},{'execution_allowed':True},{'entry':123,'stop_loss':100},{'confidence':.9}):
            value=wire(self.packet);value.update(extra)
            with self.assertRaises(ValueError):validate(value,self.packet)
    def test_dropping_wait_safety_opposition_or_duplicate_inflation_rejected(self):
        for section in ('summary','wait','bullish','bearish','conflicts'):
            value=wire(self.packet);target=next(s for s in value['sections'] if s['section']==section);target['claims']=[c for c in target['claims'] if c['fact_id']!=self.packet['required_fact_ids'][section][0]]
            with self.assertRaises(ValueError):validate(value,self.packet)
        value=wire(self.packet);value['sections'][0]['claims'].append(deepcopy(value['sections'][0]['claims'][0]))
        with self.assertRaises(ValueError):validate(value,self.packet)
    def test_wrong_bundle_rejected(self):
        value=wire(self.packet);value['bundle_id']='old'
        with self.assertRaises(ValueError):validate(value,self.packet)
    def test_configured_requesting_active_and_usage_truthful(self):
        p=MockResearchProvider();m=self.manager(p)
        self.assertEqual(m.poll(self.packet,self.context,request=False)['status'],'CONFIGURED')
        self.assertEqual(m.poll(self.packet,self.context)['status'],'REQUESTING');self.finish(m)
        c=m.poll(self.packet,self.context);self.assertEqual(c['status'],'ACTIVE');self.assertFalse(c['fallback'])
        self.assertEqual(c['metrics'],dict(requests=1,successes=1,failures=0,stale_rejections=0))
        self.assertEqual(c['request_snapshot_id'],self.context['snapshot_id']);self.assertEqual(c['evidence_cutoffs'],self.snapshot['cutoffs'])
        self.assertEqual(c['usage']['total_tokens'],150);self.assertIsInstance(c['latency_ms'],int)
    def test_duplicate_requests_and_cached_commentary(self):
        p=MockResearchProvider();m=self.manager(p);m.poll(self.packet,self.context);self.finish(m)
        for _ in range(8):self.assertTrue(m.poll(self.packet,self.context)['cached'])
        self.assertEqual(len(p.calls),1)
    def test_failed_input_cached_and_fallback_keeps_observer_running(self):
        p=MockResearchProvider('AI_PROVIDER_TIMEOUT');m=self.manager(p);service=LiveAIReasoning(m)
        service.envelope(self.snapshot);self.finish(m)
        for _ in range(3):v=service.envelope(self.observer.step())
        self.assertEqual(v['commentary']['status'],'ERROR');self.assertTrue(v['commentary']['fallback']);self.assertEqual(len(p.calls),1);self.safe(v)
    def test_provider_rate_limited_fallback(self):
        m=self.manager(MockResearchProvider('AI_PROVIDER_RATE_LIMITED'));m.poll(self.packet,self.context);self.finish(m)
        self.assertEqual(m.poll(self.packet,self.context)['status'],'RATE_LIMITED')
    def test_material_changes_subject_to_minimum_interval(self):
        tick=[0];p=MockResearchProvider();m=self.manager(p,clock=lambda:tick[0]);m.poll(self.packet,self.context);self.finish(m)
        other=deepcopy(self.packet);other['bundle_id']='new'
        self.assertEqual(m.poll(other,self.context)['status'],'RATE_LIMITED')
        tick[0]=60;m.poll(other,self.context);self.finish(m);self.assertEqual(len(p.calls),2)
    def test_stale_inflight_result_rejected_and_audited(self):
        p=MockResearchProvider();p.release=Event();events=[];m=self.manager(p,audit=lambda *a:events.append(a))
        m.poll(self.packet,self.context);self.assertTrue(p.entered.wait(1))
        other=deepcopy(self.packet);other['bundle_id']='changed';m.poll(other,self.context,request=False)
        p.release.set();self.finish(m)
        self.assertNotIn(self.packet['bundle_id'],m.cache);self.assertEqual(m.counters['stale_rejections'],1)
        self.assertEqual(events[0][2]['reason_codes'],['AI_RESPONSE_STALE_EVIDENCE'])
    def test_feed_disconnect_invalidates_inflight_and_no_old_interpretation(self):
        p=MockResearchProvider();p.release=Event();m=self.manager(p);service=LiveAIReasoning(m)
        service.envelope(self.snapshot);self.assertTrue(p.entered.wait(1))
        self.mt5.connected=False;v=service.envelope(self.observer.step());self.assertEqual(v['commentary']['status'],'FALLBACK')
        self.assertFalse(v['readable']['levels']);self.assertIsNone(v['deterministic_snapshot']['quote'])
        p.release.set();self.finish(m);self.assertEqual(m.counters['stale_rejections'],1);self.safe(v)
    def test_quote_only_updates_preserve_evidence_cache(self):
        p=MockResearchProvider();m=self.manager(p);service=LiveAIReasoning(m);a=service.envelope(self.snapshot);self.finish(m)
        changed=deepcopy(self.snapshot);changed['quote']['bid']+=.5;changed['acquired_at_utc']=(NOW+timedelta(seconds=5)).isoformat();rehash(changed)
        b=service.envelope(changed);self.assertEqual(a['ai_evidence'],b['ai_evidence']);self.assertEqual(b['commentary']['status'],'ACTIVE')
        self.assertEqual(len(p.calls),1);self.assertEqual(b['commentary']['request_snapshot_id'],self.snapshot['snapshot_id']);self.assertNotEqual(b['observed_snapshot_id'],self.snapshot['snapshot_id'])
    def test_m1_and_m5_close_changes_and_what_changed(self):
        mt5=AdvancingMT5();o=LiveObserver(ReadOnlyMarketData(mt5),ShadowLog(self.root/'advancing'),clock=lambda:mt5.now)
        service=LiveAIReasoning();a=service.envelope(o.step());mt5.now+=timedelta(minutes=1);b=service.envelope(o.step())
        self.assertNotEqual(a['ai_evidence']['bundle_id'],b['ai_evidence']['bundle_id']);self.assertIn('M1 closed-candle cutoff advanced',str(b['ai_evidence']['changes']))
        mt5.now+=timedelta(minutes=4);c=service.envelope(o.step());self.assertIn('M5 closed-candle cutoff advanced',str(c['ai_evidence']['changes']))
    def test_evidence_future_chronology_rejected_even_when_hash_recomputed(self):
        r=deepcopy(self.snapshot);key=next(iter(r['observations']['source_registry']))
        r['observations']['source_registry'][key]['available_at']=(NOW+timedelta(minutes=1)).isoformat();rehash(r)
        v=LiveAIReasoning().envelope(r);self.assertEqual(v['deterministic_snapshot']['feed_status'],'DATA_UNAVAILABLE');self.safe(v)
    def test_unsupported_or_malformed_candles_fail_closed(self):
        r=deepcopy(self.snapshot);c=next(s for s in r['observations']['source_registry'].values() if s['kind']=='CANDLE');c['ohlc']['high']=0;rehash(r)
        v=LiveAIReasoning().envelope(r);self.assertEqual(v['commentary']['status'],'FALLBACK')
    def test_duplicate_evidence_cannot_inflate_model_packet(self):
        r=deepcopy(self.snapshot);r['observations']['evidence'].append(deepcopy(r['observations']['evidence'][0]));rehash(r)
        self.assertEqual(LiveAIReasoning().envelope(r)['deterministic_snapshot']['feed_status'],'DATA_UNAVAILABLE')
    def test_fake_provider_cannot_inject_text_even_with_real_fact_ids(self):
        p=MockResearchProvider();original=p.request
        def malicious(packet):
            result=original(packet);result['sections'][0]['claims'][0]['text']='Buy at 9999';return result
        p.request=malicious;m=self.manager(p);m.poll(self.packet,self.context);self.finish(m)
        out=m.poll(self.packet,self.context);self.assertEqual(out['status'],'ERROR');self.assertNotIn('Buy at 9999',json.dumps(out))
    def test_deterministic_packet_and_hash_repeatability(self):
        again=catalog(self.snapshot,readable(self.snapshot));self.assertEqual(self.packet,again)
        a=LiveAIReasoning().envelope(self.snapshot);b=LiveAIReasoning().envelope(self.snapshot);self.assertEqual(a,b)
    def test_future_append_cannot_mutate_earlier_assessment(self):
        mt5=AdvancingMT5();o=LiveObserver(ReadOnlyMarketData(mt5),ShadowLog(self.root/'append'),clock=lambda:mt5.now)
        service=LiveAIReasoning();early=service.envelope(o.step());frozen=deepcopy(early);mt5.now+=timedelta(minutes=5);service.envelope(o.step())
        self.assertEqual(early,frozen)
        replay=LiveAIReasoning().envelope(early['deterministic_snapshot']);self.assertEqual(early,replay)
    def test_separate_private_log_redaction_hash_chain_and_no_decision_mutation(self):
        before=(self.log.root/'research.jsonl').read_bytes();journal=AIJournal(self.log.root)
        m=self.manager(MockResearchProvider());service=LiveAIReasoning(m,journal);service.envelope(self.snapshot);self.finish(m);service.envelope(self.snapshot)
        records=[json.loads(line) for line in journal.path.read_text().splitlines()]
        self.assertTrue(any(r['commentary']['status']=='ACTIVE' for r in records))
        for i,r in enumerate(records):
            self.assertEqual(r['sha256'],digest({k:v for k,v in r.items() if k!='sha256'}));self.assertEqual(r['commentary_log_version'],3)
            self.assertEqual(r['previous_entry_sha256'],records[i-1]['sha256'] if i else None)
        text=journal.path.read_text();self.assertNotIn('api_key',text);self.assertNotIn('source_registry',text)
        self.assertEqual((self.log.root/'research.jsonl').read_bytes(),before);self.assertEqual(journal.path.name,'ai-commentary-v3.jsonl')
    def test_audit_failure_blocks_active_commentary(self):
        journal=AIJournal(self.log.root);m=self.manager(MockResearchProvider());service=LiveAIReasoning(m,journal)
        with patch.object(journal,'append',side_effect=OSError('PRIVATE_SECRET')):
            service.envelope(self.snapshot);self.finish(m);v=service.envelope(self.snapshot)
        self.assertEqual(v['commentary']['status'],'ERROR');self.assertTrue(v['commentary']['fallback']);self.assertNotIn('PRIVATE_SECRET',json.dumps(v))
    def test_background_observation_no_browser_refresh_required(self):
        p=MockResearchProvider();m=self.manager(p);service=LiveAIReasoning(m,AIJournal(self.log.root));self.addCleanup(service.close)
        service.start(self.observer);self.assertTrue(p.entered.wait(2));self.finish(m)
        self.assertEqual(len(p.calls),1);self.assertTrue(self.observer.latest()['feed_status']=='CONNECTED')
    def test_v1_v2_compatibility_and_v3_get_only_endpoint(self):
        client=create_dashboard(self.observer).test_client()
        self.assertEqual(client.get('/live/v1/snapshot').get_json(),self.snapshot)
        self.assertEqual(client.get('/live/v2/snapshot').get_json()['envelope_version'],2)
        v=client.get('/live/v3/snapshot').get_json();self.safe(v);self.assertEqual(v['envelope_version'],3)
        self.assertEqual(client.post('/live/v3/snapshot').status_code,405)
        self.assertEqual(client.get('/live/v3/snapshot?enable=true').status_code,400)
        self.assertEqual(client.get('/live/v3/snapshot',headers={'Host':'evil.example'}).status_code,403)
        with client.get('/') as r:self.assertIn(b'AI Market Intelligence',r.data)
    def test_complete_sdk_service_flow_uses_real_sdk_with_mocked_transport(self):
        provider,calls=self.sdk();m=self.manager(provider);service=LiveAIReasoning(m,AIJournal(self.log.root))
        first=service.envelope(self.snapshot);self.assertEqual(first['commentary']['status'],'REQUESTING');self.finish(m)
        second=service.envelope(self.snapshot);self.assertEqual(second['commentary']['status'],'ACTIVE')
        self.assertEqual(second['commentary']['usage']['total_tokens'],168);self.safe(second);self.assertEqual(len(calls),1)
    def test_inflight_model_does_not_block_market_data_worker(self):
        p=MockResearchProvider();p.release=Event();m=self.manager(p);service=LiveAIReasoning(m)
        try:
            service.envelope(self.snapshot);self.assertTrue(p.entered.wait(1));before=time.monotonic()
            report=self.observer.step();self.assertLess(time.monotonic()-before,2)
            self.assertEqual(report['feed_status'],'CONNECTED');self.assertEqual(len(p.calls),1)
        finally:p.release.set();self.finish(m)
    def test_no_secrets_in_custom_provider_errors(self):
        p=MockResearchProvider('PRIVATE_SECRET_API_KEY');m=self.manager(p);m.poll(self.packet,self.context);self.finish(m)
        result=m.poll(self.packet,self.context);self.assertNotIn('PRIVATE_SECRET',json.dumps(result))
        self.assertEqual(result['reason_codes'],['AI_EVIDENCE_VALIDATION_FAILED'])
    def test_no_order_capability_in_research_provider_boundary(self):
        for name in ('live_ai_evidence.py','live_ai_provider.py','live_ai_runtime.py'):
            text=(Path(__file__).resolve().parents[1]/'iat'/name).read_text()
            for forbidden in ('order_send(','order_check(','from MetaTrader5','import MetaTrader5','from iat.execution'):
                self.assertNotIn(forbidden,text)
        service=LiveAIReasoning(self.manager(MockResearchProvider()));self.safe(service.envelope(self.snapshot));self.finish(service.manager)
    def test_inflight_disconnect_recovery_and_provider_rearming(self):
        tick=[0];p=MockResearchProvider();m=self.manager(p,clock=lambda:tick[0]);service=LiveAIReasoning(m)
        service.envelope(self.snapshot);self.finish(m);self.assertEqual(service.envelope(self.snapshot)['commentary']['status'],'ACTIVE')
        self.mt5.connected=False;bad=service.envelope(self.observer.step());self.assertEqual(bad['commentary']['status'],'FALLBACK')
        self.mt5.connected=True;good=service.envelope(self.observer.step());self.assertEqual(good['commentary']['status'],'RATE_LIMITED')
        tick[0]=60;service.envelope(self.snapshot);self.finish(m);good=service.envelope(self.snapshot)
        self.assertEqual(good['commentary']['status'],'ACTIVE')
        self.assertEqual(good['commentary']['evidence_cutoffs'],self.snapshot['cutoffs']);self.assertEqual(len(p.calls),2)
    def test_bounded_request_input_and_no_response_polling_retries(self):
        p,calls=self.sdk();packet=deepcopy(self.packet);packet['limitations']=['x'*100000]
        with self.assertRaises(CommentaryFailure) as exc:p.request(packet)
        self.assertEqual(exc.exception.code,'AI_INPUT_TOO_LARGE');self.assertEqual(calls,[])
    def test_maximum_request_interval_validation(self):
        for v in (True,0,29,3601):
            with self.assertRaises(ValueError):ResearchCommentary(min_seconds=v)
    def test_common_cutoff_prefix_and_full_observation_packets_match(self):
        mt5=AdvancingMT5();o=LiveObserver(ReadOnlyMarketData(mt5),ShadowLog(self.root/'prefix-source'),clock=lambda:mt5.now)
        sequence=[]
        for minutes in (0,1,5):
            mt5.now=NOW+timedelta(minutes=minutes);sequence.append(o.step())
        full=LiveAIReasoning();prefix=LiveAIReasoning()
        whole=[full.envelope(s) for s in sequence];partial=[prefix.envelope(s) for s in sequence[:2]]
        self.assertEqual(whole[:2],partial)
    def test_json_boolean_cannot_masquerade_as_a_numeric_level(self):
        value=wire(self.packet);claim=next(c for s in value['sections'] for c in s['claims'] if c['level'])
        claim['level']['lower']=True
        with self.assertRaises(ValueError):validate(value,self.packet)
    def test_future_confirmed_event_is_not_released_to_provider(self):
        r=deepcopy(self.snapshot);r['observations']['frames']['M1']['events'][-1]['confirmed_at']=(NOW+timedelta(minutes=1)).isoformat();rehash(r)
        p=MockResearchProvider();m=self.manager(p);v=LiveAIReasoning(m).envelope(r)
        self.assertEqual(v['deterministic_snapshot']['feed_status'],'DATA_UNAVAILABLE');self.assertEqual(p.calls,[])
    def test_duplicate_market_events_do_not_inflate_catalog(self):
        r=deepcopy(self.snapshot);f=r['observations']['frames']['M1'];f['events'].append(deepcopy(f['events'][-1]));rehash(r)
        v=LiveAIReasoning().envelope(r);self.assertEqual(v['deterministic_snapshot']['feed_status'],'DATA_UNAVAILABLE')
