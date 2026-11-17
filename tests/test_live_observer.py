"""SYNTHETIC mocked MT5 only; never live-terminal, broker or profitability validation."""
import ast
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from io import StringIO
import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from threading import Event,Thread
from iat.live_data import ReadOnlyMarketData
from iat.live_observer import LiveObserver,ShadowLog,research_label
from iat.live_dashboard import create_dashboard
from iat.intelligence.scenario_assessment import assess_scenarios
from iat.intelligence.context import analyze_context
from iat.intelligence.strategy_replay import digest
from iat.sessions import SessionCalendar
from iat.session_config import load_session_config
from test_scenario_assessment import context
from test_context_engine import two_frames,CONFIG,P7

NOW=datetime(2026,11,12,12,0,10,tzinfo=timezone.utc)


class MockMT5:
    TIMEFRAME_M1=1;TIMEFRAME_M5=5;ACCOUNT_TRADE_MODE_DEMO=0
    def __init__(self):
        self.calls=[];self.orders=0;self.connected=True;self.mode=0;self.visible=True;self.allowed=False;self.api_disabled=True
        self.mutate=None;self.tick_age=1;self.bid=100.;self.lag_m1=0
    def terminal_info(self):return SimpleNamespace(connected=self.connected,trade_allowed=self.allowed,tradeapi_disabled=self.api_disabled)
    def account_info(self):
        class Account:
            def __getattr__(self,k):raise AssertionError('Account identifiers must never be read')
        a=Account();a.trade_mode=self.mode;return a
    def symbol_info(self,symbol):return SimpleNamespace(visible=self.visible)
    def symbol_info_tick(self,symbol):
        epoch=int(NOW.timestamp())-self.tick_age
        return SimpleNamespace(bid=self.bid,time=epoch,time_msc=epoch*1000)
    def copy_rates_from_pos(self,symbol,tf,position,count):
        self.calls.append((symbol,tf,position,count));period=60 if tf==1 else 300
        end=int(NOW.timestamp())//period*period-(self.lag_m1 if tf==1 else 0)
        data=[dict(time=end-period*(count-i),open=100.,high=101.,low=99.,close=100.,tick_volume=10,spread=2,real_volume=0) for i in range(count)]
        return self.mutate(data,tf) if self.mutate else data
    def order_send(self,*a,**k):self.orders+=1;raise AssertionError('Orders forbidden')
    def order_check(self,*a,**k):self.orders+=1;raise AssertionError('Order functions forbidden')


class WaveMT5(MockMT5):
    """SYNTHETIC non-flat OHLC produces real detector dataclasses, not real broker bars."""
    def __init__(self):
        super().__init__()
        wave=[100,101,102,103,104,103,102,101,100,99,98,99,100,101,102,103,104,105,106,105,104,103,102,101,100,101,102,103,104,105]
        end=int(NOW.timestamp())//300*300
        one=[]
        for i in range(500):
            close=wave[i%len(wave)]+(i//len(wave))*0.2
            one.append(dict(time=end-(500-i)*60,open=close,high=close+0.2,low=close-0.2,close=close,
                            tick_volume=10,spread=2,real_volume=0))
        five=[]
        for i in range(0,500,5):
            group=one[i:i+5]
            five.append(dict(time=group[0]['time'],open=group[0]['open'],high=max(r['high'] for r in group),
                low=min(r['low'] for r in group),close=group[-1]['close'],tick_volume=50,spread=2,real_volume=0))
        self.bars={1:one,5:five};self.bid=one[-1]['close']
    def copy_rates_from_pos(self,symbol,tf,position,count):
        self.calls.append((symbol,tf,position,count))
        return deepcopy(self.bars[tf][-count:])


class LiveObserverTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='iat live synthetic ');self.addCleanup(self.folder.cleanup)
        self.mt5=MockMT5();self.bridge=ReadOnlyMarketData(self.mt5);self.log=ShadowLog(Path(self.folder.name)/'private logs')
        self.observer=LiveObserver(self.bridge,self.log,clock=lambda:NOW)
    def safe(self,r):
        self.assertEqual(r['signal'],'WAIT');self.assertFalse(r['execution_allowed']);self.assertFalse(r['broker_access'])
        self.assertEqual(r['orders_requested'],0);self.assertEqual(self.mt5.orders,0)
        self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED');self.assertEqual(r['historical_validation'],'PENDING')
        self.assertEqual(r['historical_comparisons'],'NOT_RUN');self.assertEqual(r['exness'],'BLOCKED');self.assertFalse(r['profitability_tested'])
        json.dumps(r,allow_nan=False)
    def unavailable(self,code=None):
        r=self.observer.step();self.safe(r);self.assertEqual(r['research_assessment'],'DATA_UNAVAILABLE')
        self.assertFalse(r['observations']);self.assertIsNone(r['quote'])
        if code:self.assertIn(code,r['reason_codes'])
        return r
    def calendar(self):
        a=NOW.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=2);b=a+timedelta(days=4)
        return SessionCalendar('XAUUSD',a,b,((a,b),))  # SYNTHETIC calendar, not Exness evidence.
    def test_connected_real_adapter_path_has_descriptive_observations_without_session_bypass(self):
        r=self.observer.step();self.safe(r);self.assertEqual(r['feed_status'],'CONNECTED')
        self.assertEqual(r['research_assessment'],'WAIT');self.assertEqual(r['analysis_scope'],'DESCRIPTIVE_UNVERIFIED_SESSION')
        self.assertEqual(r['scenario']['status'],'BLOCKED');self.assertTrue(r['observations']['frames'])
        self.assertTrue(r['observations']['context']['M1']['volatility']);self.assertTrue(r['observations']['source_registry'])
        self.assertEqual(r['quote']['bid'],100.);self.assertIsNone(r['broker_server_wall_clock'])
        self.assertEqual(self.mt5.calls,[('XAUUSD',1,1,500),('XAUUSD',5,1,100)])
    def test_verified_synthetic_calendar_uses_existing_context_and_scenario_gates(self):
        self.observer.calendar=self.calendar();r=self.observer.step();self.safe(r)
        self.assertEqual(r['analysis_scope'],'SESSION_GATED_CONTEXT');self.assertEqual(r['research_assessment'],'WAIT')
        self.assertEqual(r['scenario']['status'],'ABSTAINED');self.assertEqual(len(r['scenario']['ranked_hypotheses']),6)
    def test_existing_exness_candidate_remains_blocked_but_raw_observations_remain_distinct(self):
        self.observer.calendar=load_session_config('config/profiles/exness-xauusd-v2.candidate.json')
        r=self.observer.step();self.safe(r);self.assertEqual(r['scenario']['status'],'BLOCKED')
        self.assertEqual(r['research_assessment'],'WAIT');self.assertTrue(r['observations'])
    def test_closed_position_one_excludes_forming_bar_and_causal_cutoffs(self):
        self.mt5.lag_m1=60;r=self.observer.step();self.safe(r)
        self.assertTrue(r['forming_candles']['position_zero_excluded']);self.assertFalse(r['forming_candles']['requested'])
        self.assertLessEqual(r['cutoffs']['M5'],r['cutoffs']['M1'])
        self.assertTrue(all(c[2]==1 for c in self.mt5.calls))
        for source in r['observations']['source_registry'].values():self.assertLessEqual(source['available_at'],r['analysis_at_utc'])
    def test_disconnected_returns_no_simulated_or_old_market_analysis(self):
        self.observer.step();self.mt5.connected=False;self.unavailable('PROVIDER_DISCONNECTED')
    def test_non_demo_or_enabled_trading_is_read_blocked_without_changing_permissions(self):
        for attr,value in (('mode',2),('allowed',True),('api_disabled',False)):
            old=getattr(self.mt5,attr);setattr(self.mt5,attr,value);self.unavailable();setattr(self.mt5,attr,old)
        self.assertEqual(self.mt5.calls,[])
    def test_missing_symbol_is_not_automatically_selected(self):
        self.mt5.visible=False;self.unavailable('SYMBOL_NOT_VISIBLE');self.assertFalse(self.mt5.calls)
    def test_timestamp_basis_ambiguity_blocks(self):
        self.bridge.timestamp_basis='BROKER_LOCAL_TIME_UNKNOWN';self.unavailable('TIMESTAMP_BASIS_UNVERIFIED')
    def test_future_or_stale_server_like_tick_offset_blocks(self):
        for age in (-3600,3600,31):self.mt5.tick_age=age;self.unavailable()
    def test_invalid_price_and_timestamp_blocks(self):
        for price in (0,-1,float('nan'),float('inf'),True):self.mt5.bid=price;self.unavailable('TICK_MALFORMED')
    def test_empty_incomplete_malformed_candles_do_not_fall_back(self):
        for mutate in (lambda d,t:None,lambda d,t:[],lambda d,t:d[:-1],lambda d,t:[{}]*len(d)):
            self.mt5.mutate=mutate;self.unavailable()
    def test_partial_m1_and_m5_from_faulty_provider_rejected(self):
        for tf in (1,5):
            def mutate(data,t):
                if t==tf:data[-1]['time']=int(NOW.timestamp())//(60 if t==1 else 300)*(60 if t==1 else 300)
                return data
            self.mt5.mutate=mutate;self.unavailable('BAR_UNCLOSED')
    def test_duplicate_out_of_order_misaligned_and_invalid_ohlc_fail_closed(self):
        for edit in (lambda d:d[1].update(time=d[0]['time']),lambda d:d.reverse(),
                     lambda d:d[0].update(time=d[0]['time']+1),lambda d:d[0].update(low=200),lambda d:d[0].update(close=float('nan'))):
            def mutate(data,tf):
                if tf==1:edit(data)
                return data
            self.mt5.mutate=mutate;self.unavailable()
    def test_gap_or_stale_bars_are_not_treated_as_verified_session_closures(self):
        self.mt5.lag_m1=180;self.unavailable('DATA_STALE');self.mt5.lag_m1=0
        def mutate(data,tf):
            if tf==1:
                for row in data[:20]:row['time']-=60
            return data
        self.mt5.mutate=mutate;self.unavailable('GAP_UNVERIFIED')
    def test_timeframe_ohlc_mismatch_blocks(self):
        def mutate(data,tf):
            if tf==5:data[-1]['close']=100.5
            return data
        self.mt5.mutate=mutate;self.unavailable('M1_M5_OHLC_MISMATCH')
    def test_insufficient_history_is_not_padded(self):
        self.mt5.mutate=lambda data,tf:data[-3:];self.unavailable('HISTORY_INCOMPLETE')
    def test_buy_and_sell_scenarios_only_map_existing_assessed_selection(self):
        for mirror,expected in ((False,'BUY_SCENARIO'),(True,'SELL_SCENARIO')):
            # Existing labeled SYNTHETIC fixtures; no invented market observations.
            s=assess_scenarios(context(mirror));self.assertEqual(s['status'],'ASSESSED')
            self.assertEqual(research_label(s),expected);self.assertEqual(s['signal'],'WAIT');self.assertFalse(s['execution_allowed'])
        self.assertEqual(research_label(assess_scenarios(None)),'WAIT')
    def test_opposing_m1_m5_structure_preserves_abstention(self):
        a,b,at=two_frames()
        for r in b:
            o,h,l,c=(r[k] for k in ('open','high','low','close'));r.update(open=200-o,high=200-l,low=200-h,close=200-c)
        s=assess_scenarios(analyze_context('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7))
        self.assertEqual(s['status'],'ABSTAINED');self.assertEqual(research_label(s),'WAIT')
    def test_optional_model_unavailable_and_conflicting_output_use_deterministic_fallback(self):
        def unavailable(payload):raise RuntimeError('private-token-never-output')
        for adapter in (unavailable,lambda payload:dict(payload,assessment='BUY_SCENARIO'),lambda payload:dict(payload,confidence=99)):
            self.observer.model_adapter=adapter;r=self.observer.step();self.safe(r)
            self.assertEqual(r['ai_model']['status'],'UNAVAILABLE');self.assertEqual(r['research_assessment'],'WAIT')
            self.assertNotIn('private-token',json.dumps(r));self.assertTrue(r['reasoning'])
    def test_model_default_disabled_and_validated_formatter_receives_no_private_source_data(self):
        r=self.observer.step();self.assertEqual(r['ai_model']['status'],'DISABLED')
        def adapter(payload):
            self.assertEqual(set(payload),{'assessment','evidence_ids','statements'});return payload
        self.observer.model_adapter=adapter;r=self.observer.step();self.assertEqual(r['ai_model']['status'],'ACTIVE');self.safe(r)
    def test_logs_are_append_only_separate_source_from_derived_and_hash_chained(self):
        a=self.observer.step();before=(self.log.root/'research.jsonl').read_bytes();self.observer.step()
        after=(self.log.root/'research.jsonl').read_bytes();self.assertTrue(after.startswith(before))
        entries=[json.loads(line) for line in after.splitlines()];self.assertEqual(len(entries),2)
        self.assertEqual(entries[1]['previous_entry_sha256'],entries[0]['sha256'])
        for entry in entries:self.assertEqual(entry['sha256'],digest({k:v for k,v in entry.items() if k!='sha256'}))
        raw=[json.loads(line) for line in (self.log.root/'raw-candles.jsonl').read_bytes().splitlines()]
        self.assertEqual(len(raw),1);self.assertIn('rates',raw[0]['raw']['M1']);self.assertNotIn('orders',json.dumps(raw))
        self.assertEqual(a['snapshot_id'],entries[0]['report']['snapshot_id'])
    def test_new_private_log_directory_required_outside_repo(self):
        for path in (self.log.root,Path(__file__).resolve().parents[1]/'forbidden-live-logs'):
            with self.assertRaises(ValueError):ShadowLog(path)
    def test_log_failure_withholds_analysis(self):
        with patch.object(self.log,'append',side_effect=OSError('private-path')):self.unavailable('SHADOW_LOG_FAILED')
    def test_provider_exception_is_redacted(self):
        with patch.object(self.bridge,'preflight',side_effect=RuntimeError('account-server-secret')):r=self.unavailable()
        self.assertNotIn('account-server-secret',json.dumps(r))
    def test_backward_clock_withholds_snapshot(self):
        self.observer.step();self.observer.clock.source=lambda:NOW-timedelta(seconds=1)
        self.unavailable('CLOCK_MOVED_BACKWARD')
    def test_stalled_observer_does_not_return_cached_analysis(self):
        self.observer.step();self.observer.clock.source=lambda:NOW+timedelta(seconds=31)
        r=self.observer.latest();self.safe(r);self.assertEqual(r['research_assessment'],'DATA_UNAVAILABLE')
        self.assertIn('OBSERVER_STALLED',r['reason_codes'])
    def test_http_is_local_read_only_no_cache_and_no_order_routes(self):
        self.observer.step();client=create_dashboard(self.observer).test_client()
        r=client.get('/live/v1/snapshot');self.assertEqual(r.status_code,200);self.safe(r.get_json())
        self.assertEqual(r.headers['Cache-Control'],'no-store');self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy'])
        self.assertEqual(client.post('/live/v1/snapshot').status_code,405)
        self.assertEqual(client.post('/order').status_code,404)
        self.assertEqual(client.get('/',headers={'Host':'evil.example'}).status_code,403)
        self.assertEqual(client.get('/',environ_base={'REMOTE_ADDR':'192.0.2.1'}).status_code,403)
        with client.get('/') as response:self.assertIn(b'EXECUTION DISABLED',response.data)
        with client.get('/live.js') as response:self.assertIn(b'DATA_UNAVAILABLE',response.data)
    def test_browser_requests_never_fetch_market_data(self):
        self.observer.step();calls=list(self.mt5.calls);client=create_dashboard(self.observer).test_client()
        for _ in range(4):client.get('/live/v1/snapshot')
        self.assertEqual(self.mt5.calls,calls)
    def test_http_read_does_not_wait_for_terminal_fetch(self):
        self.observer.step();entered=Event();release=Event()
        def blocked():entered.set();release.wait(3);raise RuntimeError('offline')
        with patch.object(self.bridge,'preflight',side_effect=blocked):
            worker=Thread(target=self.observer.step);worker.start();self.assertTrue(entered.wait(1))
            try:r=self.observer.latest();self.assertEqual(r['feed_status'],'CONNECTED')
            finally:release.set();worker.join(4)
    def test_refresh_interval_bounded(self):
        for interval in (0,1,61,True):
            with self.assertRaises(ValueError):LiveObserver(self.bridge,self.log,interval=interval)
    def test_no_execution_methods_reachable_on_bridge_and_no_order_calls_in_source(self):
        for name in ('order_send','order_check','login','initialize','symbol_select'):
            self.assertFalse(hasattr(self.bridge,name))
        for filename in ('iat/live_data.py','iat/live_observer.py','diagnostics/run_live_intelligence.py'):
            tree=ast.parse(Path(filename).read_text(encoding='utf-8'))
            calls=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
            self.assertFalse({'order_send','order_check','login','symbol_select'} & set(calls))

    def test_long_refresh_interval_never_hides_a_stale_quote(self):
        self.observer.interval=60;self.observer.step()
        self.observer.clock.source=lambda:NOW+timedelta(seconds=30)
        r=self.observer.latest();self.safe(r);self.assertEqual(r['research_assessment'],'DATA_UNAVAILABLE')
        self.assertIn('TICK_STALE',r['reason_codes']);self.assertIn('snapshot_id',r)

    def test_closed_evidence_revision_at_same_cutoff_is_withheld(self):
        self.observer.calendar=self.calendar();self.observer.step()
        def mutate(data,tf):data[-1]['close']=100.5;return data
        self.mt5.mutate=mutate;self.unavailable('CLOSED_CANDLE_REVISION_DETECTED')
        self.unavailable('CLOSED_CANDLE_REVISION_DETECTED')

    def test_unverified_descriptive_confluence_never_selects_a_hypothesis(self):
        r=self.observer.step();self.safe(r)
        self.assertEqual(r['observations']['confluence']['selected_hypothesis'],'NO_CLEAR_DIRECTIONAL_HYPOTHESIS')
        self.assertIn('BLOCKED_DATA_QUALITY',r['observations']['confluence']['abstention_reasons'])
        self.assertIn('M1:',r['reasoning'][1])

    def test_latest_snapshot_has_consistent_content_identity(self):
        self.observer.step();r=self.observer.latest()
        self.assertEqual(r['snapshot_id'],digest({k:v for k,v in r.items() if k!='snapshot_id'}))

    def test_background_worker_starts_updates_and_stops_without_orders(self):
        self.observer.start();self.addCleanup(self.observer.close)
        import time
        deadline=time.monotonic()+3
        while self.observer.latest()['feed_status']!='CONNECTED' and time.monotonic()<deadline:time.sleep(0.01)
        self.assertEqual(self.observer.latest()['feed_status'],'CONNECTED')
        self.observer.close();self.assertFalse(self.observer.thread.is_alive());self.assertEqual(self.mt5.orders,0)

    def test_windows_runner_attaches_without_credentials_and_binds_only_loopback(self):
        from diagnostics.run_live_intelligence import main
        from contextlib import redirect_stdout
        calls=[]
        self.mt5.initialize=lambda **kwargs:calls.append(('initialize',kwargs)) or True
        self.mt5.shutdown=lambda:calls.append(('shutdown',))
        with patch('sys.platform','win32'),patch('sys.version_info',(3,11)),patch.dict('sys.modules',{'MetaTrader5':self.mt5}),patch('flask.Flask.run') as serve,redirect_stdout(StringIO()):
            result=main(['--log-directory',str(Path(self.folder.name)/'runner logs')])
        self.assertEqual(result,0);self.assertEqual(calls[0],('initialize',{'timeout':10000}))
        self.assertEqual(calls[-1],('shutdown',));self.assertEqual(serve.call_args.kwargs['host'],'127.0.0.1')
        self.assertFalse(serve.call_args.kwargs['debug']);self.assertFalse(serve.call_args.kwargs['use_reloader'])
        self.assertEqual(self.mt5.orders,0)

    def test_malformed_raw_values_do_not_echo_private_strings_into_logs(self):
        def mutate(data,tf):data[0]['open']='private-account-server-token';return data
        self.mt5.mutate=mutate;self.unavailable('OHLC_MALFORMED')
        for filename in ('research.jsonl','raw-candles.jsonl'):
            self.assertNotIn(b'private-account-server-token',(self.log.root/filename).read_bytes())

    def test_nonflat_zone_pool_and_liquidity_events_serialize_through_hash_http_and_logs(self):
        self.mt5=WaveMT5();self.bridge=ReadOnlyMarketData(self.mt5)
        self.observer=LiveObserver(self.bridge,self.log,clock=lambda:NOW)
        r=self.observer.step();self.safe(r)
        self.assertEqual(r['feed_status'],'CONNECTED');self.assertEqual(r['research_assessment'],'WAIT')
        events=[];pools=[];zones=[]
        for frame in r['observations']['context'].values():
            events+=frame['liquidity_events'];pools+=frame['liquidity_pools']
            zones+=list(frame['support_resistance'])+list(frame['supply_demand'])
        self.assertTrue(events);self.assertTrue(pools);self.assertTrue(zones)
        self.assertTrue(all(isinstance(v,dict) for v in events+pools+zones))
        for event in events:
            self.assertEqual(r['observations']['source_registry'][event['id']]['kind'],'LIQUIDITY_EVENT')
        self.assertEqual(r['snapshot_id'],digest({k:v for k,v in r.items() if k!='snapshot_id'}))
        client=create_dashboard(self.observer).test_client();response=client.get('/live/v1/snapshot')
        self.assertEqual(response.status_code,200);self.assertEqual(response.get_json(),r)
        entry=json.loads((self.log.root/'research.jsonl').read_text().splitlines()[-1])
        self.assertEqual(entry['report'],r)

    def test_dataclass_conversion_preserves_all_event_fields_and_canonical_ids(self):
        from dataclasses import asdict
        import iat.live_observer as live
        original=live.derive;captured={}
        def capture(*args,**kwargs):
            result=original(*args,**kwargs);captured['context']=result[2];return result
        self.mt5=WaveMT5();self.bridge=ReadOnlyMarketData(self.mt5)
        self.observer=LiveObserver(self.bridge,self.log,clock=lambda:NOW)
        with patch.object(live,'derive',side_effect=capture):r=self.observer.step()
        self.safe(r);self.assertEqual(r['feed_status'],'CONNECTED')
        for tf,frame in captured['context'].items():
            for name in ('support_resistance','supply_demand','liquidity_pools','liquidity_events'):
                before=frame[name];after=r['observations']['context'][tf][name]
                self.assertEqual(len(before),len(after))
                for typed,serialized in zip(before,after):
                    self.assertEqual(json.loads(json.dumps(asdict(typed))),serialized)
                    self.assertEqual(typed.id,serialized['id'])

    def test_nonfinite_nested_liquidity_values_fail_closed_instead_of_stringifying(self):
        from dataclasses import replace
        import iat.live_observer as live
        original=live.derive
        def invalid(*args,**kwargs):
            result=original(*args,**kwargs);frame=result[2]['M1']
            self.assertTrue(frame['liquidity_events'])
            frame['liquidity_events']=(replace(frame['liquidity_events'][0],level=float('nan')),)
            return result
        self.mt5=WaveMT5();self.bridge=ReadOnlyMarketData(self.mt5)
        self.observer=LiveObserver(self.bridge,self.log,clock=lambda:NOW)
        with patch.object(live,'derive',side_effect=invalid):self.unavailable('LIVE_OBSERVATION_UNAVAILABLE')
        self.assertNotIn('NaN',(self.log.root/'research.jsonl').read_text())

    def test_snapshot_hash_serialization_failure_is_guarded_and_next_poll_recovers(self):
        with patch('iat.live_observer.research_label',return_value=object()):self.unavailable('SNAPSHOT_SERIALIZATION_FAILED')
        self.assertIsNone(self.observer.previous)
        r=self.observer.step();self.safe(r);self.assertEqual(r['feed_status'],'CONNECTED')
        entries=[json.loads(line) for line in (self.log.root/'research.jsonl').read_text().splitlines()]
        self.assertEqual(entries[0]['report']['reason_codes'],['SNAPSHOT_SERIALIZATION_FAILED'])
        self.assertEqual(entries[1]['report']['feed_status'],'CONNECTED')

    def test_worker_survives_unserializable_snapshot_and_continues_to_next_observation(self):
        import time
        import iat.live_observer as live
        original=live.research_label;first=Event()
        def once(scenario):
            if not first.is_set():first.set();return object()
            return original(scenario)
        self.observer.interval=2
        with patch.object(live,'research_label',side_effect=once):
            self.observer.start();self.addCleanup(self.observer.close)
            deadline=time.monotonic()+5
            while self.observer.latest()['feed_status']!='CONNECTED' and time.monotonic()<deadline:time.sleep(0.01)
            self.assertTrue(first.is_set());self.assertTrue(self.observer.thread.is_alive())
            self.assertEqual(self.observer.latest()['feed_status'],'CONNECTED')
            self.observer.close()
        entries=[json.loads(line) for line in (self.log.root/'research.jsonl').read_text().splitlines()]
        self.assertIn('SNAPSHOT_SERIALIZATION_FAILED',entries[0]['report']['reason_codes'])
        self.assertEqual(entries[-1]['report']['feed_status'],'CONNECTED');self.assertEqual(self.mt5.orders,0)
