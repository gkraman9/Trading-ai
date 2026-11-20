"""SYNTHETIC observations and mocked Gemini SDK/HTTP. No paid API calls."""
from copy import deepcopy
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import builtins,json,os,tempfile,unittest
import httpx2 as httpx
from google import genai
from google.genai import types
from jsonschema import validate as json_validate
from test_live_observer import WaveMT5,NOW
from iat.live_data import ReadOnlyMarketData
from iat.live_observer import LiveObserver,ShadowLog
from iat.live_readable import readable
from iat.live_ai_evidence import catalog,SECTIONS,validate
from iat.live_ai_gemini import GeminiResearchProvider,DEFAULT_MODEL,compact_schema,reconstruct
from iat.live_ai_runtime import ResearchCommentary,LiveAIReasoning,AIJournal
from iat.live_commentary import CommentaryFailure


def selection(packet):
    return dict(version=3,bundle_id=packet['bundle_id'],sections=[dict(section=s,fact_ids=[c['fact_id'] for c in packet['cards'] if c['section']==s]) for s in SECTIONS])


def chunk(text='',finish='STOP',**extras):
    return types.GenerateContentResponse(candidates=[types.Candidate(index=0,content=types.Content(role='model',parts=[types.Part(text=text)]),finish_reason=finish)],**extras)


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='iat GEMINI SYNTHETIC ');self.addCleanup(self.temp.cleanup)
        self.log=ShadowLog(Path(self.temp.name)/'logs');self.mt5=WaveMT5()
        self.observer=LiveObserver(ReadOnlyMarketData(self.mt5),self.log,clock=lambda:NOW)
        self.snapshot=self.observer.step();self.packet=catalog(self.snapshot,readable(self.snapshot))
    def sdk(self,mutate=None,*,status=200,body=None,error=None,finish='STOP'):
        calls=[]
        def handler(request):
            calls.append(request)
            if error:raise error
            if status!=200:return httpx.Response(status,json={'error':{'code':status,'message':'PRIVATE_PROVIDER_SECRET','status':'UNAVAILABLE'}})
            data=json.loads(request.content);prompt=json.loads(data['contents'][0]['parts'][0]['text']);value=selection(prompt)
            if mutate:mutate(value)
            payload=chunk(json.dumps(value) if body is None else body,finish,
                usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100,candidates_token_count=50,total_token_count=150))
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=('data: '+payload.model_dump_json(by_alias=True,exclude_none=True)+'\n\n').encode())
        http=httpx.Client(transport=httpx.MockTransport(handler),trust_env=False,follow_redirects=False);self.addCleanup(http.close)
        client=genai.Client(api_key='synthetic-not-an-api-key',vertexai=False,http_options=types.HttpOptions(httpx_client=http,retry_options=types.HttpRetryOptions(attempts=3),timeout=30000))
        p=GeminiResearchProvider('synthetic-not-an-api-key',client=client);self.addCleanup(p.close)
        return p,calls,http
    def fake(self,chunks):
        calls=[]
        def generate(**kwargs):calls.append(kwargs);return iter(chunks)
        client=SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate),close=lambda:None)
        return GeminiResearchProvider('synthetic-not-an-api-key',client=client),calls
    def manager(self,p):
        m=ResearchCommentary(p);self.addCleanup(m.close);return m
    def finish(self,m):
        m.thread.join(4);self.assertFalse(m.thread.is_alive())
    def test_initialization_default_model_and_sdk_transport_controls(self):
        p=GeminiResearchProvider('synthetic-not-an-api-key');self.addCleanup(p.close)
        self.assertEqual(p.model,DEFAULT_MODEL);o=p.client._api_client._http_options
        self.assertEqual(o.timeout,30000);self.assertEqual(o.retry_options.attempts,1)
        self.assertEqual(o.base_url,'https://generativelanguage.googleapis.com');self.assertFalse(p.client.vertexai)
        self.assertFalse(o.client_args['trust_env']);self.assertFalse(o.client_args['follow_redirects'])
    def test_invalid_credentials_models_and_timeouts(self):
        for key in (None,'','short','secret\nkeyvalue','秘密0123456789'):
            with self.assertRaises(CommentaryFailure):GeminiResearchProvider(key)
        for model in ('','models/gemini-x','https://evil.test/model','gemini-x?key=secret','gpt-4.1-mini'):
            with self.assertRaises(CommentaryFailure):GeminiResearchProvider('synthetic-key',model)
        for timeout in (True,0,31,float('inf')):
            with self.assertRaises(CommentaryFailure):GeminiResearchProvider('synthetic-key',timeout=timeout)
    def test_optional_sdk_and_initialization_fault_sanitized(self):
        original=builtins.__import__
        def missing(name,*args,**kwargs):
            if name=='google':raise ImportError('PRIVATE')
            return original(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=missing):
            with self.assertRaises(CommentaryFailure) as e:GeminiResearchProvider('synthetic-key')
        self.assertEqual(e.exception.code,'LLM_OPTIONAL_SDK_MISSING')
        with patch('google.genai.Client',side_effect=RuntimeError('PRIVATE')):
            with self.assertRaises(CommentaryFailure) as e:GeminiResearchProvider('synthetic-key')
        self.assertEqual(e.exception.code,'LLM_CONFIGURATION_INVALID');self.assertNotIn('PRIVATE',str(e.exception))
    def test_actual_sdk_valid_nine_sections_and_usage(self):
        p,calls,_=self.sdk();out=p.request(self.packet)
        self.assertEqual([s['section'] for s in out['sections']],list(SECTIONS));self.assertEqual(out['usage']['total_tokens'],150)
        self.assertEqual(calls[0].url.host,'generativelanguage.googleapis.com');self.assertNotIn('key',calls[0].url.params)
        data=json.loads(calls[0].content);self.assertEqual(data['generationConfig']['responseMimeType'],'application/json')
        self.assertEqual(data['generationConfig']['responseJsonSchema'],compact_schema());self.assertEqual(len(calls),1)
        json_validate(selection(self.packet),compact_schema())
    def test_model_selection_and_bounded_config(self):
        p,calls=self.fake([chunk(json.dumps(selection(self.packet))) ]);p.model='gemini-3.5-flash-lite'
        p.request(self.packet);self.assertEqual(calls[0]['model'],p.model)
        cfg=calls[0]['config'];self.assertFalse(cfg['automatic_continuation']);self.assertTrue(cfg['automatic_function_calling']['disable'])
        self.assertEqual(cfg['http_options'],{'timeout':30000,'retry_options':{'attempts':1}});self.assertEqual(cfg['tools'],[]);self.assertEqual(cfg['max_output_tokens'],8192)
    def test_existing_validator_is_called_on_local_reconstruction(self):
        expected=validate(dict(version=3,bundle_id=self.packet['bundle_id'],sections=[dict(section=s,claims=[{k:deepcopy(c[k]) for k in ('fact_id','evidence_ids','timeframe','event_type','level','direction')} for c in self.packet['cards'] if c['section']==s]) for s in SECTIONS]),self.packet)
        with patch('iat.live_ai_gemini.validate',wraps=validate) as checked:
            out=reconstruct(selection(self.packet),self.packet)
        checked.assert_called_once();self.assertEqual(out,expected)
    def test_unknown_fact_id(self):
        v=selection(self.packet);v['sections'][0]['fact_ids'][0]='F_NOT_REAL'
        with self.assertRaises(CommentaryFailure):reconstruct(v,self.packet)
    def test_duplicate_fact_id(self):
        v=selection(self.packet);v['sections'][0]['fact_ids'].append(v['sections'][0]['fact_ids'][0])
        with self.assertRaises(CommentaryFailure):reconstruct(v,self.packet)
    def test_wrong_section_assignment(self):
        v=selection(self.packet);v['sections'][0]['fact_ids'][0]=v['sections'][1]['fact_ids'][0]
        with self.assertRaises(CommentaryFailure):reconstruct(v,self.packet)
    def test_missing_required_fact_rejected_by_original_gate(self):
        v=selection(self.packet);s='summary';v['sections'][0]['fact_ids'].remove(self.packet['required_fact_ids'][s][0])
        with self.assertRaises(ValueError):reconstruct(v,self.packet)
    def test_missing_duplicate_unknown_and_reordered_sections(self):
        for mutate in (lambda v:v['sections'].pop(),lambda v:v['sections'].reverse(),lambda v:v['sections'][0].update(section='trend'),lambda v:v['sections'].__setitem__(0,deepcopy(v['sections'][1]))):
            v=selection(self.packet);mutate(v)
            with self.assertRaises(CommentaryFailure):reconstruct(v,self.packet)
    def test_wrong_bundle_version_and_extra_fields(self):
        for mutate in (lambda v:v.update(bundle_id='old'),lambda v:v.update(version=True),lambda v:v.update(version=2),lambda v:v.update(signal='BUY'),lambda v:v['sections'][0].update(price=9999)):
            v=selection(self.packet);mutate(v)
            with self.assertRaises(CommentaryFailure):reconstruct(v,self.packet)
    def test_non_string_ids_and_empty_sections_rejected(self):
        for ids in ([],[{}],[None],['invented']*33):
            v=selection(self.packet);v['sections'][0]['fact_ids']=ids
            with self.assertRaises(CommentaryFailure):reconstruct(v,self.packet)
    def test_no_silent_repair_or_directional_cherry_picking(self):
        for s in ('bullish','bearish','conflicts','wait'):
            v=selection(self.packet);part=next(x for x in v['sections'] if x['section']==s);part['fact_ids'].pop()
            with self.assertRaises(ValueError):reconstruct(v,self.packet)
    def test_fact_order_within_section_can_change_without_mutating_catalog(self):
        before=deepcopy(self.packet);v=selection(self.packet);v['sections'][0]['fact_ids'].reverse();out=reconstruct(v,self.packet)
        self.assertEqual([c['fact_id'] for c in out[0]['claims']],v['sections'][0]['fact_ids']);self.assertEqual(self.packet,before)
    def test_malformed_duplicate_json_keys_and_empty_responses(self):
        for body in ('not json','{"version":3,"version":3}','', '{"version":NaN}'):
            p,_,_=self.sdk(body=body)
            with self.assertRaises(CommentaryFailure):p.request(self.packet)
    def test_http_errors_and_no_retries(self):
        for status in (400,401,403,404,429,500,503):
            p,calls,_=self.sdk(status=status)
            with self.assertRaises(CommentaryFailure) as e:p.request(self.packet)
            self.assertEqual(e.exception.code,'AI_PROVIDER_RATE_LIMITED' if status==429 else 'AI_PROVIDER_HTTP_ERROR')
            self.assertEqual(len(calls),1);self.assertNotIn('PRIVATE',str(e.exception))
    def test_timeouts_and_network_failures_are_sanitized(self):
        for error,code in ((httpx.ReadTimeout('PRIVATE'),'AI_PROVIDER_TIMEOUT'),(httpx.ConnectError('PRIVATE'),'AI_PROVIDER_ERROR')):
            p,calls,_=self.sdk(error=error)
            with self.assertRaises(CommentaryFailure) as e:p.request(self.packet)
            self.assertEqual(e.exception.code,code);self.assertEqual(len(calls),1);self.assertNotIn('PRIVATE',str(e.exception))
    def test_continuation_and_truncation_never_trigger_hidden_requests(self):
        for reason in ('CONTINUATION','MAX_TOKENS','SAFETY'):
            p,calls,_=self.sdk(finish=reason)
            with self.assertRaises(CommentaryFailure):p.request(self.packet)
            self.assertEqual(len(calls),1)
    def test_bounded_input_and_response(self):
        p,calls=self.fake([chunk('x'*(64*1024+1))])
        with self.assertRaises(CommentaryFailure) as e:p.request(self.packet)
        self.assertEqual(e.exception.code,'AI_RESPONSE_TOO_LARGE')
        packet=deepcopy(self.packet);packet['limitations']=['x'*100000]
        with self.assertRaises(CommentaryFailure) as e:p.request(packet)
        self.assertEqual(e.exception.code,'AI_INPUT_TOO_LARGE');self.assertEqual(len(calls),1)
    def test_request_projection_excludes_credentials_ticks_logs(self):
        p,calls,_=self.sdk();packet=deepcopy(self.packet);packet.update(raw_ticks='PRIVATE',api_key='PRIVATE',source_registry='PRIVATE',snapshot='PRIVATE')
        p.request(packet);body=calls[0].content.decode();self.assertNotIn('PRIVATE',body);self.assertNotIn('synthetic-not-an-api-key',body)
    def test_stream_chunks_reassemble_json_and_private_thoughts_not_displayed(self):
        text=json.dumps(selection(self.packet));parts=[types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model',parts=[types.Part(thought=True,text='PRIVATE_REASONING')]))]),chunk(text[:50],None),chunk(text[50:])]
        p,_=self.fake(parts);out=p.request(self.packet);self.assertNotIn('PRIVATE_REASONING',json.dumps(out))
    def test_tools_and_nontext_parts_rejected(self):
        c=types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model',parts=[types.Part(function_call=types.FunctionCall(name='order_send',args={}))]),finish_reason='STOP')])
        p,_=self.fake([c])
        with self.assertRaises(CommentaryFailure):p.request(self.packet)
    def test_sdk_client_closure(self):
        p,_,http=self.sdk()
        with patch.object(p.client,'close',wraps=p.client.close) as close:p.close();close.assert_called_once()
    def test_runtime_valid_response_preserves_session_quality_and_safety(self):
        p,_,_=self.sdk();m=self.manager(p);service=LiveAIReasoning(m,AIJournal(self.log.root));service.envelope(self.snapshot);self.finish(m)
        r=service.envelope(self.snapshot);self.assertEqual(r['commentary']['status'],'ACTIVE');self.assertEqual(r['commentary']['provider'],'Google Gemini')
        self.assertEqual(r['deterministic_snapshot'],self.snapshot);self.assertEqual(r['signal'],'WAIT');self.assertFalse(r['execution_allowed']);self.assertEqual(self.mt5.orders,0)
        self.assertIn('SESSION_CALENDAR_UNAVAILABLE',json.dumps(r));self.assertIn('BLOCKED_DATA_QUALITY',json.dumps(r));self.assertEqual(r['historical_validation'],'PENDING')
        self.assertNotIn('synthetic-not-an-api-key',(self.log.root/'ai-commentary-v3.jsonl').read_text())
    def test_invalid_response_runtime_fallback(self):
        p,_,_=self.sdk(lambda v:v.update(signal='BUY'));m=self.manager(p);s=LiveAIReasoning(m);s.envelope(self.snapshot);self.finish(m)
        r=s.envelope(self.snapshot);self.assertEqual(r['commentary']['status'],'ERROR');self.assertTrue(r['commentary']['fallback']);self.assertFalse(r['execution_allowed'])
    def test_stale_inflight_and_audit_failure_use_existing_gates(self):
        entered=Event();release=Event();p,calls=self.fake([chunk(json.dumps(selection(self.packet)))])
        original=p.request
        def delayed(packet):entered.set();release.wait(3);return original(packet)
        p.request=delayed;m=self.manager(p);service=LiveAIReasoning(m,AIJournal(self.log.root));service.envelope(self.snapshot);self.assertTrue(entered.wait(1))
        self.mt5.connected=False;r=service.envelope(self.observer.step());self.assertEqual(r['commentary']['status'],'FALLBACK');release.set();self.finish(m)
        self.assertEqual(m.counters['stale_rejections'],1)
        p,_,_=self.sdk();m=self.manager(p);journal=AIJournal(ShadowLog(Path(self.temp.name)/'other').root);s=LiveAIReasoning(m,journal)
        with patch.object(journal,'append',side_effect=OSError('PRIVATE')):
            s.envelope(self.snapshot);self.finish(m);r=s.envelope(self.snapshot)
        self.assertEqual(r['commentary']['status'],'ERROR');self.assertNotIn('PRIVATE',json.dumps(r))
    def test_provider_factory_reads_only_selected_environment_key(self):
        from diagnostics.run_live_intelligence import configured_provider
        with patch('diagnostics.run_live_intelligence.os.environ.get',side_effect=lambda k: {'IAT_GEMINI_API_KEY':'gemini-key','IAT_OPENAI_API_KEY':'openai-key','IAT_REASONING_MODEL':'old-model'}[k]) as env:
            with patch('diagnostics.run_live_intelligence.GeminiResearchProvider') as provider:
                configured_provider('gemini');provider.assert_called_once_with('gemini-key',DEFAULT_MODEL)
            self.assertEqual([c.args[0] for c in env.call_args_list],['IAT_GEMINI_API_KEY'])
        with patch.dict('os.environ',{'IAT_OPENAI_API_KEY':'openai-key','IAT_REASONING_MODEL':'old-model'}):
            with patch('diagnostics.run_live_intelligence.OpenAIResearchProvider') as provider:
                configured_provider('openai');provider.assert_called_once_with('openai-key','old-model')
    def test_no_execution_or_terminal_imports_in_provider(self):
        text=(Path(__file__).resolve().parents[1]/'iat/live_ai_gemini.py').read_text()
        for value in ('order_send(','order_check(','import MetaTrader5','from iat.execution'):self.assertNotIn(value,text)
    def test_signed_text_metadata_is_ignored_but_no_new_claims_allowed(self):
        c=chunk(json.dumps(selection(self.packet)));c.candidates[0].content.parts[0].thought_signature=b'opaque-signature'
        p,_=self.fake([c]);out=p.request(self.packet);self.assertEqual(len(out['sections']),9);self.assertNotIn('opaque-signature',json.dumps(out))
    def test_wall_budget_rejects_late_chunks(self):
        p,_=self.fake([chunk(json.dumps(selection(self.packet)))])
        with patch('iat.live_ai_gemini.time.monotonic',side_effect=[0,31]):
            with self.assertRaises(CommentaryFailure) as e:p.request(self.packet)
        self.assertEqual(e.exception.code,'AI_PROVIDER_TIMEOUT')
    def test_smoke_requires_opt_in_and_never_reads_a_key_when_disabled(self):
        from diagnostics.check_gemini_provider import main
        from io import StringIO
        from contextlib import redirect_stdout
        output=StringIO()
        with patch('diagnostics.check_gemini_provider.os.environ.get',wraps=os.environ.get) as env,patch('diagnostics.check_gemini_provider.GeminiResearchProvider') as provider,redirect_stdout(output):
            self.assertEqual(main([]),0)
        self.assertNotIn('IAT_GEMINI_API_KEY',[c.args[0] for c in env.call_args_list]);provider.assert_not_called();self.assertEqual(json.loads(output.getvalue())['status'],'DISABLED')
    def test_manual_smoke_mocked_success_and_sanitized_failure(self):
        from diagnostics.check_gemini_provider import main,smoke_packet
        from io import StringIO
        from contextlib import redirect_stdout
        p,calls=self.fake([chunk(json.dumps(selection(smoke_packet())))])
        with patch('diagnostics.check_gemini_provider.GeminiResearchProvider',return_value=p),redirect_stdout(StringIO()) as output:
            self.assertEqual(main(['--enable-llm']),0)
        r=json.loads(output.getvalue());self.assertEqual(r['status'],'PASS_SYNTHETIC_PROVIDER_SMOKE');self.assertEqual(len(calls),1);self.assertEqual(r['orders_requested'],0)
        with patch('diagnostics.check_gemini_provider.GeminiResearchProvider',side_effect=RuntimeError('PRIVATE')),redirect_stdout(StringIO()) as output:
            self.assertEqual(main(['--enable-llm']),1)
        self.assertNotIn('PRIVATE',output.getvalue())
    def test_default_runner_does_not_configure_either_provider(self):
        from diagnostics.run_live_intelligence import main
        from io import StringIO
        from contextlib import redirect_stdout
        fake_module=SimpleNamespace(initialize=lambda **k:True,shutdown=lambda:None)
        fake_observer=SimpleNamespace(start=lambda:None,close=lambda:None,thread=None)
        fake_reasoner=SimpleNamespace(start=lambda o:None,close=lambda:None)
        with patch('diagnostics.run_live_intelligence.sys.platform','win32'),patch('diagnostics.run_live_intelligence.sys.version_info',(3,11)),patch.dict('sys.modules',{'MetaTrader5':fake_module}),patch('diagnostics.run_live_intelligence.ReadOnlyMarketData'),patch('diagnostics.run_live_intelligence.LiveObserver',return_value=fake_observer),patch('diagnostics.run_live_intelligence.LiveAIReasoning',return_value=fake_reasoner),patch('diagnostics.run_live_intelligence.create_dashboard') as dashboard,patch('diagnostics.run_live_intelligence.configured_provider') as provider,redirect_stdout(StringIO()):
            self.assertEqual(main(['--log-directory',str(Path(self.temp.name)/'disabled')]),0)
        provider.assert_not_called();dashboard.return_value.run.assert_called_once_with(host='127.0.0.1',port=8765,debug=False,use_reloader=False,threaded=True)
    def test_runner_provider_flags_and_default_openai_are_backward_compatible(self):
        from diagnostics.run_live_intelligence import main
        from io import StringIO
        from contextlib import redirect_stdout
        for name,args,model in (('gemini',['--llm-provider','gemini','--llm-model',DEFAULT_MODEL],DEFAULT_MODEL),('openai',[],None)):
            fake_module=SimpleNamespace(initialize=lambda **k:True,shutdown=lambda:None)
            observer=SimpleNamespace(start=lambda:None,close=lambda:None,thread=None)
            reasoner=SimpleNamespace(start=lambda o:None,close=lambda:None)
            with patch('diagnostics.run_live_intelligence.sys.platform','win32'),patch('diagnostics.run_live_intelligence.sys.version_info',(3,11)),patch.dict('sys.modules',{'MetaTrader5':fake_module}),patch('diagnostics.run_live_intelligence.ReadOnlyMarketData'),patch('diagnostics.run_live_intelligence.LiveObserver',return_value=observer),patch('diagnostics.run_live_intelligence.LiveAIReasoning',return_value=reasoner),patch('diagnostics.run_live_intelligence.create_dashboard'),patch('diagnostics.run_live_intelligence.configured_provider') as provider,redirect_stdout(StringIO()):
                self.assertEqual(main(['--log-directory',str(Path(self.temp.name)/('flag-'+name)),'--enable-llm',*args]),0)
            provider.assert_called_once_with(name,model)
