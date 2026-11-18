"""SYNTHETIC transport and mocked HTTP only. No terminal or actual LLM validation."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from threading import Event
import json,tempfile,time,unittest
from unittest.mock import patch
import requests
from iat.live_data import ReadOnlyMarketData
from iat.live_observer import LiveObserver,ShadowLog,base
from iat.live_readable import readable
from iat.live_commentary import OpenAICommentary,CommentaryManager,CommentaryFailure,validate_choices,ENDPOINT
from iat.live_reasoning import LiveReasoning,CommentaryJournal
from iat.live_dashboard import create_dashboard
from iat.live_stability import assess_samples,StabilitySampler
from iat.intelligence.strategy_replay import digest
from test_live_observer import MockMT5,WaveMT5,NOW


def choices(packet):
    return dict(format_version=1,bundle_id=packet['bundle_id'],choices=[dict(claim_id=c['id'],wording_id='alternative',evidence_ids=c['evidence_ids']) for c in packet['claims']])


class FakeResponse:
    def __init__(self,data,status=200):self.data=data;self.status_code=status;self.closed=False
    def iter_content(self,chunk_size):yield self.data
    def close(self):self.closed=True


class FakeHTTP:
    def __init__(self,mutate=None,status=200,error=None):self.calls=[];self.mutate=mutate;self.status=status;self.error=error
    def post(self,url,**kwargs):
        self.calls.append((url,kwargs))
        if self.error:raise self.error
        prompt=json.loads(kwargs['json']['messages'][1]['content']);value=choices(prompt)
        if self.mutate:self.mutate(value)
        result=dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(value)))])
        return FakeResponse(json.dumps(result).encode(),self.status)
    def close(self):pass


class AdvancingMT5(MockMT5):
    def __init__(self):super().__init__();self.now=NOW
    def symbol_info_tick(self,symbol):
        from types import SimpleNamespace
        epoch=int(self.now.timestamp())-self.tick_age
        return SimpleNamespace(bid=self.bid,time=epoch,time_msc=epoch*1000)
    def copy_rates_from_pos(self,symbol,tf,position,count):
        self.calls.append((symbol,tf,position,count));period=60 if tf==1 else 300;end=int(self.now.timestamp())//period*period
        return [dict(time=end-period*(count-i),open=100.,high=101.,low=99.,close=100.,tick_volume=10,spread=2,real_volume=0) for i in range(count)]


class LiveReasoningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='iat reasoning synthetic ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.mt5=WaveMT5();self.log=ShadowLog(self.root/'private logs')
        self.observer=LiveObserver(ReadOnlyMarketData(self.mt5),self.log,clock=lambda:NOW)
        self.snapshot=self.observer.step();self.view=readable(self.snapshot);self.packet=self.view['claims']
    def provider(self,http=None):return OpenAICommentary('synthetic-not-a-real-api-key','test-structured-model',session=http or FakeHTTP())
    def wait_manager(self,manager):
        if manager.thread:manager.thread.join(2)
        self.assertFalse(manager.thread and manager.thread.is_alive())
    def safe(self,envelope):
        s=envelope['deterministic_snapshot']
        self.assertEqual(s['signal'],'WAIT');self.assertFalse(s['execution_allowed']);self.assertFalse(s['broker_access'])
        self.assertEqual(s['orders_requested'],0);self.assertEqual(self.mt5.orders,0)
        self.assertEqual(s['exness'],'BLOCKED');self.assertEqual(s['qualification'],'DATA_NOT_QUALIFIED')
        self.assertEqual(s['historical_validation'],'PENDING');self.assertEqual(s['historical_comparisons'],'NOT_RUN')
        self.assertEqual(s['snapshot_id'],digest({k:v for k,v in s.items() if k!='snapshot_id'}))
        self.assertEqual(envelope['sha256'],digest({k:v for k,v in envelope.items() if k!='sha256'}))
    def test_readable_m1_m5_and_confirmed_swing_evidence_preserved(self):
        for tf in ('M1','M5'):
            f=self.view['structures'][tf];old=self.snapshot['observations']['frames'][tf]
            self.assertEqual(f['state'],old['structure']['classification']);self.assertIn(tf,f['summary'])
            self.assertEqual([p['price'] for p in f['recent_swings']],[p['price'] for p in old['confirmed_pivots'][-6:]])
            for p in f['recent_swings']:self.assertTrue(p['evidence_ids'])
    def test_actual_levels_and_source_ids_are_not_fabricated(self):
        source={}
        for tf,frame in self.snapshot['observations']['context'].items():
            for collection in ('support_resistance','supply_demand','liquidity_pools'):
                for z in frame[collection]:source[z['id']]=z
        self.assertEqual({z['id'] for z in self.view['levels']},set(source))
        for z in self.view['levels']:
            self.assertEqual(z['lower'],source[z['id']].get('lower',source[z['id']].get('level')))
            self.assertEqual(z['upper'],source[z['id']].get('upper',source[z['id']].get('level')))
    def test_mixed_timeframes_and_session_blockers_explained_separately(self):
        kinds={b['category'] for b in self.view['wait']['blockers']}
        self.assertIn('session',kinds);self.assertIn('mixed_timeframes',kinds)
        for p in self.view['scenarios'].values():
            self.assertEqual(p['formal_status'],'NOT_ASSESSED');self.assertFalse(p['selected']);self.assertFalse(p['invalidation_conditions'])
            self.assertIn('No formal',p['summary'])
    def test_empty_levels_missing_structure_and_unavailable_feed_are_readable(self):
        v=readable(base(NOW.isoformat(),'TICK_STALE'))
        self.assertFalse(v['levels']);self.assertEqual(v['structures']['M1']['state'],'UNKNOWN')
        self.assertIn('stale',v['wait']['summary']);self.assertEqual(v['overview']['research_assessment'],'DATA_UNAVAILABLE')
    def test_support_and_opposition_follow_existing_evidence_directions(self):
        for direction,panel in self.view['scenarios'].items():
            source=self.snapshot['observations']['evidence']
            self.assertEqual({x['id'] for x in panel['supporting']},{e['id'] for e in source if e['direction']==direction})
            self.assertEqual({x['id'] for x in panel['contradictory']},{e['id'] for e in source if e['direction'] in ('BULLISH','BEARISH','RANGING') and e['direction']!=direction})
    def test_snapshot_and_evidence_identities_unchanged_by_v2(self):
        before=deepcopy(self.snapshot);env=LiveReasoning().envelope(self.snapshot);self.safe(env)
        self.assertEqual(self.snapshot,before);self.assertEqual(env['deterministic_snapshot'],before)
        self.assertEqual(env['readable']['source_snapshot_id'],before['snapshot_id'])
    def test_quote_only_changes_do_not_invalidate_closed_commentary_bundle(self):
        modified=deepcopy(self.snapshot);modified['quote']['bid']+=1;modified['acquired_at_utc']=(NOW+timedelta(seconds=10)).isoformat()
        modified['snapshot_id']=digest({k:v for k,v in modified.items() if k!='snapshot_id'})
        other=readable(modified);self.assertNotEqual(other['source_snapshot_id'],self.view['source_snapshot_id'])
        self.assertEqual(other['claims']['bundle_id'],self.packet['bundle_id'])
    def test_changed_closed_evidence_invalidates_bundle_even_if_structure_unchanged(self):
        modified=deepcopy(self.snapshot);key=next(k for k,v in modified['observations']['source_registry'].items() if v['kind']=='CANDLE')
        modified['observations']['source_registry'][key]['ohlc']['close']+=.01
        self.assertNotEqual(readable(modified)['claims']['bundle_id'],self.packet['bundle_id'])
    def test_real_adapter_request_uses_fixed_endpoint_and_strict_schema_with_no_private_payload(self):
        http=FakeHTTP();provider=self.provider(http);packet=deepcopy(self.packet)
        packet['private_logs']='PRIVATE_ACCOUNT_SERVER_SECRET';out=provider.request(packet)
        url,options=http.calls[0];self.assertEqual(url,ENDPOINT);self.assertFalse(options['allow_redirects']);self.assertFalse(http.trust_env)
        self.assertEqual(options['timeout'],(3,8));self.assertTrue(options['json']['response_format']['json_schema']['strict'])
        prompt=options['json']['messages'][1]['content'];self.assertNotIn('PRIVATE_ACCOUNT_SERVER_SECRET',prompt)
        self.assertNotIn('source_registry',prompt);self.assertNotIn('quote',prompt)
        self.assertEqual(len(out),len(self.packet['claims']))
    def test_optional_provider_missing_key_or_model_is_rejected_without_network(self):
        for key,model in ((None,'model'),('synthetic-valid-key',None),('bad\nkey-value','model')):
            with self.assertRaises(CommentaryFailure):OpenAICommentary(key,model,session=FakeHTTP())
    def test_timeout_and_http_failure_are_redacted(self):
        for http,code in ((FakeHTTP(error=requests.Timeout('secret-api-key')), 'AI_PROVIDER_TIMEOUT'),(FakeHTTP(status=401),'AI_PROVIDER_HTTP_ERROR')):
            with self.assertRaises(CommentaryFailure) as exc:self.provider(http).request(self.packet)
            self.assertEqual(exc.exception.code,code);self.assertNotIn('secret',str(exc.exception))
    def test_fabricated_evidence_ids_free_text_prices_and_confidence_rejected(self):
        for mutate in (lambda v:v['choices'][0]['evidence_ids'].append('fabricated'),
                       lambda v:v.update(text='Buy now',price=9999,confidence=99),
                       lambda v:v['choices'][0].update(wording_id='invented'),
                       lambda v:v.update(bundle_id='other-dataset')):
            with self.assertRaises(CommentaryFailure):self.provider(FakeHTTP(mutate)).request(self.packet)
    def test_omitting_safety_or_duplicating_a_claim_is_rejected(self):
        for mutate in (lambda v:v['choices'].pop(),lambda v:v['choices'].__setitem__(1,deepcopy(v['choices'][0]))):
            value=choices(self.packet);mutate(value)
            with self.assertRaises(CommentaryFailure):validate_choices(value,self.packet)
    def test_invalid_provider_json_or_truncated_output_is_rejected(self):
        for data in (b'not json',b'{"choices":[]}',json.dumps({'choices':[{'finish_reason':'length','message':{'content':'{}'}}]}).encode()):
            http=FakeHTTP();http.post=lambda *a,**k:FakeResponse(data)
            with self.assertRaises(CommentaryFailure):self.provider(http).request(self.packet)
    def test_default_disabled_and_unavailable_provider_both_keep_deterministic_commentary(self):
        for manager,status in ((CommentaryManager(),'DISABLED'),(CommentaryManager(unavailable_code='LLM_KEY_UNAVAILABLE'),'UNAVAILABLE')):
            env=LiveReasoning(manager).envelope(self.snapshot);self.safe(env)
            self.assertEqual(env['commentary']['status'],status);self.assertEqual(env['commentary']['source'],'DETERMINISTIC')
    def test_success_is_active_only_after_request_completes_and_is_cached(self):
        http=FakeHTTP();m=CommentaryManager(self.provider(http));self.addCleanup(m.close)
        first=m.commentary(self.packet);self.assertNotEqual(first['status'],'ACTIVE')
        self.wait_manager(m);result=m.commentary(self.packet)
        self.assertEqual(result['status'],'ACTIVE');self.assertTrue(result['cached'])
        for _ in range(5):m.commentary(self.packet)
        self.assertEqual(len(http.calls),1)
    def test_provider_failure_is_cached_without_retries_on_unchanged_input(self):
        http=FakeHTTP(error=requests.Timeout('sensitive'));m=CommentaryManager(self.provider(http));self.addCleanup(m.close)
        m.commentary(self.packet);self.wait_manager(m)
        for _ in range(5):result=m.commentary(self.packet)
        self.assertEqual(len(http.calls),1);self.assertEqual(result['status'],'UNAVAILABLE');self.assertEqual(result['source'],'DETERMINISTIC')
    def test_changed_bundle_is_rate_limited_then_requested_without_changing_market_assessment(self):
        tick=[0];http=FakeHTTP();m=CommentaryManager(self.provider(http),clock=lambda:tick[0]);self.addCleanup(m.close)
        m.commentary(self.packet);self.wait_manager(m)
        other=deepcopy(self.packet);other['bundle_id']='changed-key'
        self.assertIn('AI_RATE_LIMIT_WAIT',m.commentary(other)['reason_codes']);self.assertEqual(len(http.calls),1)
        tick[0]=61;m.commentary(other);self.wait_manager(m);self.assertEqual(len(http.calls),2)
        env=LiveReasoning(m).envelope(self.snapshot);self.safe(env);self.assertEqual(env['deterministic_snapshot']['research_assessment'],'WAIT')
    def test_inflight_request_does_not_block_observation_or_multiple_tabs(self):
        entered=Event();release=Event();http=FakeHTTP();original=http.post
        def delayed(*a,**k):entered.set();release.wait(2);return original(*a,**k)
        http.post=delayed;m=CommentaryManager(self.provider(http));self.addCleanup(m.close)
        try:
            m.commentary(self.packet);self.assertTrue(entered.wait(1))
            for _ in range(4):self.assertIn('AI_REQUEST_PENDING',m.commentary(self.packet)['reason_codes'])
            r=self.observer.step();self.assertEqual(r['feed_status'],'CONNECTED')
        finally:release.set();self.wait_manager(m)
        self.assertEqual(len(http.calls),1)
    def test_provider_cannot_change_fact_text_even_with_valid_evidence(self):
        class BadProvider:
            provider_name='Mock';model='test'
            def request(_self,packet):return [dict(claim_id=c['id'],section=c['section'],text='Invented price: 99999',evidence_ids=c['evidence_ids']) for c in packet['claims']]
            def close(_self):pass
        m=CommentaryManager(BadProvider());self.addCleanup(m.close);m.commentary(self.packet);self.wait_manager(m)
        result=m.commentary(self.packet);self.assertEqual(result['status'],'UNAVAILABLE')
        self.assertNotIn('99999',json.dumps(result))
    def test_commentary_journal_separate_append_only_hash_bound_and_no_secrets(self):
        before=(self.log.root/'research.jsonl').read_bytes();journal=CommentaryJournal(self.log.root)
        service=LiveReasoning(journal=journal);a=service.envelope(self.snapshot);self.safe(a)
        data=journal.path.read_bytes();service.envelope(self.snapshot);self.assertEqual(journal.path.read_bytes(),data)
        changed=deepcopy(self.snapshot);changed['quote']['bid']+=.01;changed['snapshot_id']=digest({k:v for k,v in changed.items() if k!='snapshot_id'});service.envelope(changed)
        self.assertTrue(journal.path.read_bytes().startswith(data));self.assertEqual((self.log.root/'research.jsonl').read_bytes(),before)
        entries=[json.loads(line) for line in journal.path.read_text().splitlines()]
        self.assertEqual(entries[0]['source_snapshot_id'],self.snapshot['snapshot_id'])
        self.assertEqual(entries[1]['previous_entry_sha256'],entries[0]['sha256'])
        self.assertNotIn('synthetic-not-a-real-api-key',journal.path.read_text())
    def test_commentary_logging_failure_falls_back_without_mutating_market_snapshot(self):
        journal=CommentaryJournal(self.log.root)
        with patch.object(journal,'append',side_effect=OSError('private-path')):
            env=LiveReasoning(journal=journal).envelope(self.snapshot)
        self.safe(env);self.assertEqual(env['deterministic_snapshot'],self.snapshot)
        self.assertIn('COMMENTARY_LOG_FAILED',env['commentary']['reason_codes'])
    def test_v1_http_compatible_v2_additive_and_primary_ui_not_json(self):
        client=create_dashboard(self.observer).test_client()
        self.assertEqual(client.get('/live/v1/snapshot').get_json(),self.snapshot)
        self.safe(client.get('/live/v2/snapshot').get_json())
        with client.get('/') as response:
            self.assertIn(b'Bullish evidence',response.data);self.assertIn(b'Bearish evidence',response.data)
            self.assertIn(b'<details class="technical">',response.data);self.assertIn(b'EXECUTION DISABLED',response.data)
        self.assertEqual(client.post('/live/v2/snapshot').status_code,405)
    def test_formal_regime_not_invented_from_unverified_descriptive_alignment(self):
        self.assertEqual(self.view['overview']['market_regime'],'UNKNOWN');self.assertFalse(self.view['overview']['session_eligible'])
    def test_stale_or_disconnected_envelope_never_uses_old_commentary_facts(self):
        service=LiveReasoning();service.envelope(self.snapshot)
        self.mt5.connected=False;bad=self.observer.step();env=service.envelope(bad);self.safe(env)
        self.assertEqual(env['readable']['overview']['research_assessment'],'DATA_UNAVAILABLE')
        self.assertFalse(env['readable']['levels']);self.assertFalse(env['deterministic_snapshot']['observations'])
        self.assertNotEqual(env['readable']['claims']['bundle_id'],self.packet['bundle_id'])


    def test_tampered_snapshot_identity_is_quarantined_without_reusing_old_view(self):
        service=LiveReasoning();service.envelope(self.snapshot)
        wrong=deepcopy(self.snapshot);wrong['quote']['bid']+=100
        env=service.envelope(wrong);self.safe(env)
        self.assertEqual(env['readable']['overview']['research_assessment'],'DATA_UNAVAILABLE')
        self.assertIn('DETERMINISTIC_SNAPSHOT_INVALID',env['deterministic_snapshot']['reason_codes'])
        self.assertFalse(env['readable']['levels'])

    def test_commentary_journal_refuses_repository_and_existing_file(self):
        with self.assertRaises(ValueError):CommentaryJournal(Path(__file__).resolve().parents[1])
        journal=CommentaryJournal(self.log.root)
        with self.assertRaises(FileExistsError):CommentaryJournal(self.log.root)
        self.assertEqual(journal.path.read_bytes(),b'')


class LivePollingStabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='iat advancing SYNTHETIC ');self.addCleanup(self.temp.cleanup)
        self.mt5=AdvancingMT5();self.log=ShadowLog(Path(self.temp.name)/'private')
        self.observer=LiveObserver(ReadOnlyMarketData(self.mt5),self.log,clock=lambda:self.mt5.now)
    def test_bid_time_and_m1_m5_closed_transitions_over_repeated_polls(self):
        records=[];before=None
        for seconds in (0,10,60,120,300,360):
            self.mt5.now=NOW+timedelta(seconds=seconds);self.mt5.bid=100+seconds/1000
            records.append(self.observer.step())
            if before:self.assertTrue((self.log.root/'research.jsonl').read_bytes().startswith(before))
            before=(self.log.root/'research.jsonl').read_bytes()
        report=assess_samples(records)
        self.assertEqual(report['status'],'PASS');self.assertGreaterEqual(report['closed_cutoff_transitions']['M1'],4)
        self.assertGreaterEqual(report['closed_cutoff_transitions']['M5'],1);self.assertEqual(report['bid_changes'],5)
        self.assertEqual(report['quote_timestamp_updates'],5);self.assertEqual(self.mt5.orders,0)
        self.assertNotIn('bid',report['samples'][0]);self.assertNotIn('observations',report['samples'][0])
    def test_disconnect_stale_clearing_and_reconnect_preserve_continuity_log(self):
        records=[self.observer.step()];self.mt5.connected=False;records.append(self.observer.step())
        self.mt5.now+=timedelta(seconds=10);self.mt5.connected=True;records.append(self.observer.step())
        self.mt5.tick_age=40;records.append(self.observer.step());self.mt5.tick_age=1;self.mt5.now+=timedelta(seconds=10);records.append(self.observer.step())
        for r in (records[1],records[3]):self.assertIsNone(r['quote']);self.assertFalse(r['observations'])
        report=assess_samples(records);self.assertEqual(report['reconnections'],2);self.assertEqual(report['status'],'WARN')
        self.assertEqual(report['blocked_samples'],2);self.assertEqual(self.mt5.orders,0)
    def test_stability_diagnostic_does_not_certify_constant_or_invalid_input(self):
        r=self.observer.step();report=assess_samples([r,r]);self.assertEqual(report['status'],'WARN')
        self.assertIn('M5_CLOSE_TRANSITION_NOT_OBSERVED',report['issues'])
        unsafe=deepcopy(r);unsafe['execution_allowed']=True
        self.assertEqual(assess_samples([unsafe])['status'],'FAIL')
        self.assertEqual(assess_samples([{'diagnostic_error':'LOCAL_OBSERVER_UNAVAILABLE'}])['status'],'FAIL')
    def test_unexpected_step_error_cannot_terminate_worker(self):
        original=self.observer.step;first=Event()
        def bad_once():
            if not first.is_set():first.set();raise RuntimeError('private-token')
            return original()
        self.observer.interval=2
        with patch.object(self.observer,'step',side_effect=bad_once):
            self.observer.start();self.addCleanup(self.observer.close)
            until=time.monotonic()+5
            while self.observer.latest()['feed_status']!='CONNECTED' and time.monotonic()<until:time.sleep(.01)
            self.assertTrue(first.is_set());self.assertTrue(self.observer.thread.is_alive())
            self.assertEqual(self.observer.latest()['feed_status'],'CONNECTED');self.observer.close()
        text=(self.log.root/'research.jsonl').read_text();self.assertNotIn('private-token',text)
        self.assertIn('OBSERVER_POLL_FAILED',text);self.assertEqual(self.mt5.orders,0)


    def test_sampling_rejects_a_self_consistent_hash_with_stale_quote(self):
        r=self.observer.step();r['quote']['observed_at_utc']=(NOW-timedelta(seconds=40)).isoformat()
        r['snapshot_id']=digest({k:v for k,v in r.items() if k!='snapshot_id'})
        self.assertEqual(assess_samples([r])['status'],'FAIL')


class LiveStabilityCLITests(unittest.TestCase):
    def test_local_sampling_writes_only_metadata_and_never_requests_commentary(self):
        from diagnostics.check_live_stability import main
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory(prefix='iat stability SYNTHETIC ') as folder:
            root=Path(folder);log=ShadowLog(root/'logs');mt5=MockMT5()
            observer=LiveObserver(ReadOnlyMarketData(mt5),log,clock=lambda:NOW);snapshot=observer.step()
            class Response:
                status_code=200
                def json(self):return deepcopy(snapshot)
                def close(self):pass
            class Session:
                def __init__(self):self.calls=[]
                def get(self,url,**kwargs):self.calls.append(url);return Response()
                def close(self):pass
            session=Session();dest=root/'stability.json'
            with patch('diagnostics.check_live_stability.requests.Session',return_value=session),patch('diagnostics.check_live_stability.time.monotonic',side_effect=[0,31]),redirect_stdout(StringIO()):
                self.assertEqual(main(['--seconds','30','--report-path',str(dest)]),3)
            r=json.loads(dest.read_text());self.assertEqual(r['status'],'WARN')
            self.assertEqual(session.calls,['http://127.0.0.1:8765/live/v1/snapshot'])
            self.assertFalse(session.trust_env);self.assertNotIn('quote',r['samples'][0]);self.assertEqual(mt5.orders,0)
    def test_existing_diagnostic_report_is_not_overwritten(self):
        from diagnostics.check_live_stability import main
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as folder:
            dest=Path(folder)/'existing.json';dest.write_bytes(b'preserve')
            with patch('diagnostics.check_live_stability.requests.Session') as session,redirect_stdout(StringIO()):
                self.assertEqual(main(['--report-path',str(dest)]),1)
            session.assert_not_called();self.assertEqual(dest.read_bytes(),b'preserve')
