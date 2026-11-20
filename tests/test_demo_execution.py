"""SYNTHETIC Stage-A state machine only. No broker module, credential or order call."""
from copy import deepcopy
from dataclasses import asdict,replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,sqlite3,tempfile,threading,unittest
from iat.demo_execution.policy import Config,Signal,Blocked,readiness,load_config,risk_request
from iat.demo_execution.store import Store
from iat.demo_execution.service import RehearsalService
from iat.demo_execution.readiness import inspect_terminal,fingerprint

NOW=datetime(2026,11,20,12,0,1,tzinfo=timezone.utc);AT=NOW.isoformat();IDENTITY='a'*64


def snapshot():
    return dict(at=AT,connected=True,account_mode=0,account_fingerprint=IDENTITY,broker='EXNESS',currency='USD',
        account_trade_allowed=True,account_expert_allowed=True,terminal_trade_allowed=True,api_disabled=False,
        new_position_session_verified=True,calendar_sha256='b'*64,data_quality_valid=True,finality_verified=True,
        cutoffs={'M1':NOW.replace(second=0).isoformat(),'M5':NOW.replace(second=0).isoformat()},
        history_complete=True,baseline_verified=True,cashflow_categories_known=True,day='2026-11-20',starting_equity='10000',
        opening_unrealized='0',realized_profit='0',commissions='0',swaps='0',fees='0',unrealized_pnl='0',cashflows='0',equity='10000',
        positions=0,pending_orders=0,opening_order_ids_today=[],bid='1000.00',ask='1000.10',
        symbol=dict(name='XAUUSD',visible=True,trade_mode=4,volume_min='.01',volume_max='10',volume_step='.01',tick_size='.01',point='.01',digits=2,stops_level_points='10',filling_modes=['FOK'],validity_modes=['GTC']))


def signal(anchor='anchor-1',side='BUY'):
    return Signal('SYNTHETIC_STRATEGY','test-v1',side,(anchor,),NOW.replace(second=0).isoformat(),
        '999.00' if side=='BUY' else '1001.00','1002.00' if side=='BUY' else '999.00','synthetic-invalidation-evidence')


class SyntheticTransport:
    synthetic_only=True
    def __init__(self):self.s=snapshot();self.sent=[];self.history={};self.response=None;self.error=None;self.check_accepted=True;self.risk='2';self.before_submit=None;self.lock=threading.Lock()
    def snapshot(self,now):return deepcopy(self.s)
    def order_check(self,request,*,expected_account):
        if self.s['account_fingerprint']!=expected_account:raise RuntimeError('Synthetic switched account')
        return dict(accepted=self.check_accepted,currency='USD',loss_bound_verified=True,worst_case_loss=self.risk)
    def guarded_submit(self,request,*,expected_account):
        with self.lock:
            if self.before_submit:self.before_submit()
            if self.s['account_fingerprint']!=expected_account or self.s['account_mode']!=0 or self.s['positions']!=0:raise RuntimeError('Synthetic atomic guard')
            key=request['client_id']
            if key in self.history:return deepcopy(self.history[key])
            self.sent.append(deepcopy(request))
            result=self.response or dict(status='FILLED',volume='.01',price=request['price'],sl=request['sl'],tp=request['tp'],broker_reference='SYNTHETIC_BROKER_REFERENCE')
            self.history[key]=deepcopy(result)
            if self.error:raise RuntimeError('PRIVATE_SYNTHETIC_ERROR')
            self.s['positions']=1 if result['status'] in ('FILLED','PARTIAL') else 0
            self.s['opening_order_ids_today'].append(key)
            return deepcopy(result)
    def lookup(self,key,*,expected_account):
        if self.s['account_fingerprint']!=expected_account:raise RuntimeError('Synthetic switched account')
        return deepcopy(self.history.get(key))
    def symbol_point(self):return self.s['symbol']['point']
    def close_position(self):
        self.s['positions']=0
        for result in self.history.values():
            if result['status'] in ('FILLED','PARTIAL'):result['status']='CLOSED'


class StageATests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='iat demo SYNTHETIC ');self.addCleanup(self.tmp.cleanup)
        self.config=Config(enabled=True,expected_account_fingerprint=IDENTITY,max_spread_points='20',max_slippage_points='5')
        self.root=Path(self.tmp.name)/'state';self.store=Store(self.root,self.config.sha256,create=True)
        self.store.emergency_stop(reset=True,acknowledge=True);self.broker=SyntheticTransport()
        self.service=RehearsalService(self.config,self.store,self.broker,opt_in=True)
    def process(self,s=None):return self.service.process(s or signal(),AT)
    def reject(self,code):
        r=self.process();self.assertEqual(r['status'],'BLOCKED');self.assertIn(code,r['reason_codes']);self.assertEqual(self.broker.sent,[])
    def test_readiness_remains_blocked_no_approval_booleans(self):
        r=readiness(self.config);self.assertEqual(r['status'],'BLOCKED');self.assertFalse(r['execution_allowed'])
        self.assertTrue(all(s['validation_status']=='EXPERIMENTAL_SYNTHETIC_ONLY' and not s['execution_eligible'] for s in r['strategies']))
    def test_no_real_transport_and_default_disabled(self):
        with self.assertRaises(Blocked):RehearsalService(self.config,self.store,SimpleNamespace(),opt_in=True)
        self.service.opt_in=False;self.reject('EXPLICIT_OPT_IN_REQUIRED')
        with self.assertRaises(Blocked):Config(volume='0.02')
        with self.assertRaises(Blocked):Config(daily_loss_fraction='.02')
        with self.assertRaises(Blocked):Config(max_trades_per_day=6)
    def test_successful_synthetic_buy_and_sell_preserve_real_safety(self):
        for index,side in enumerate(('BUY','SELL')):
            r=self.process(signal(str(index),side));self.assertEqual(r['status'],'SIMULATED_OPEN');self.assertEqual(r['orders_requested'],0)
            self.assertFalse(r['execution_allowed']);self.assertEqual(r['signal'],'WAIT')
            self.broker.close_position();self.service.reconcile()
        self.assertEqual(len(self.broker.sent),2);self.store.verify()
    def test_demo_real_and_contest_account_rejection(self):
        for mode in (1,2,True,None):
            self.broker.s['account_mode']=mode;self.reject('DEMO_ACCOUNT_REQUIRED')
    def test_identity_account_switch_and_broker_rejection(self):
        self.broker.s['account_fingerprint']='c'*64;self.reject('ACCOUNT_IDENTITY_MISMATCH')
        self.broker.s['account_fingerprint']=IDENTITY;self.broker.s['broker']='UNKNOWN';self.reject('BROKER_OR_CURRENCY_UNVERIFIED')
    def test_atomic_account_switch_guard_never_sends(self):
        self.broker.before_submit=lambda:self.broker.s.update(account_mode=2)
        r=self.process();self.assertIn('SUBMISSION_UNCERTAIN',r['reason_codes']);self.assertEqual(self.broker.sent,[])
        with self.store.connection() as db:self.assertEqual(self.store.stop_value(db),'1')
    def test_permission_failures(self):
        for key,value in (('connected',False),('account_trade_allowed',False),('account_expert_allowed',None),('terminal_trade_allowed',False),('api_disabled',True)):
            old=self.broker.s[key];self.broker.s[key]=value
            r=self.process();self.assertEqual(r['status'],'BLOCKED');self.assertEqual(self.broker.sent,[]);self.broker.s[key]=old
    def test_stale_future_and_unclosed_candles(self):
        for key in ('M1','M5'):
            old=self.broker.s['cutoffs'][key]
            for minutes in (-6,1):
                self.broker.s['cutoffs'][key]=(NOW+timedelta(minutes=minutes)).isoformat();self.reject('CANDLE_UNCLOSED_STALE_OR_MISALIGNED')
            self.broker.s['cutoffs'][key]=old
        self.broker.s['at']=(NOW-timedelta(seconds=3)).isoformat();self.reject('QUOTE_STALE_OR_FUTURE')
    def test_session_data_finality_and_ledger_gates(self):
        for key in ('new_position_session_verified','data_quality_valid','finality_verified','history_complete','baseline_verified','cashflow_categories_known'):
            self.broker.s[key]=False;r=self.process();self.assertEqual(r['status'],'BLOCKED');self.assertEqual(self.broker.sent,[]);self.broker.s[key]=True
    def test_gemini_or_unvalidated_signal_cannot_qualify(self):
        for source in ('GEMINI','DETERMINISTIC_STRATEGY','VALIDATED_LIVE'):
            r=self.process(replace(signal(),source=source));self.assertIn('UNVALIDATED_SIGNAL',r['reason_codes'])
        self.assertEqual(self.broker.sent,[])
    def test_spread_volume_filling_and_stops(self):
        self.broker.s['ask']='1000.21';self.reject('SPREAD_LIMIT');self.broker.s['ask']='1000.10'
        self.broker.s['symbol']['volume_step']='.02';self.reject('VOLUME_INVALID');self.broker.s['symbol']['volume_step']='.01'
        self.broker.s['symbol']['filling_modes']=['IOC'];self.reject('ORDER_POLICY_UNSUPPORTED');self.broker.s['symbol']['filling_modes']=['FOK']
        for sl,tp in (('0','1002'),('1000.01','1002'),('999','999'),('999.001','1002')):
            self.assertEqual(self.process(replace(signal(),stop_loss=sl,take_profit=tp))['status'],'BLOCKED')
        self.assertEqual(self.broker.sent,[])
    def test_loss_includes_realized_unrealized_commission_swap_and_fee(self):
        for field in ('realized_profit','commissions','swaps','fees','unrealized_pnl'):
            self.broker.s[field]='-100';self.broker.s['equity']='9900'
            with self.assertRaises(Blocked) as exc:risk_request(self.config,signal(),self.broker.s,AT)
            self.assertEqual(exc.exception.code,'DAILY_LOSS_LIMIT');self.broker.s[field]='0';self.broker.s['equity']='10000'
    def test_cashflows_do_not_reset_loss_budget(self):
        self.broker.s.update(realized_profit='-100',cashflows='1000',equity='10900')
        with self.assertRaises(Blocked) as exc:risk_request(self.config,signal(),self.broker.s,AT)
        self.assertEqual(exc.exception.code,'DAILY_LOSS_LIMIT')
        self.broker.s.update(realized_profit='0',cashflows='-1000',equity='9000')
        self.assertEqual(self.process()['status'],'SIMULATED_OPEN')
    def test_projected_stop_loss_and_missing_cost_bound(self):
        self.broker.risk='100';self.reject('PROJECTED_DAILY_LOSS_LIMIT')
        self.broker.risk='0';self.reject('PROJECTED_DAILY_LOSS_LIMIT')
    def test_opening_mark_and_day_boundary_accounting(self):
        self.broker.s.update(opening_unrealized='50',unrealized_pnl='0',equity='9950');self.assertEqual(self.process()['status'],'SIMULATED_OPEN')
        self.broker.close_position();self.service.reconcile();self.broker.s['day']='2026-11-19'
        self.assertIn('DAY_BOUNDARY_UNVERIFIED',self.process(signal('new'))['reason_codes'])
    def test_positions_pending_orders_and_max_five(self):
        for field in ('positions','pending_orders'):
            self.broker.s[field]=1;self.reject('POSITION_OR_PENDING_ORDER_LIMIT');self.broker.s[field]=0
        for i in range(5):
            self.assertEqual(self.process(signal(str(i)))['status'],'SIMULATED_OPEN');self.broker.close_position();self.service.reconcile()
        r=self.process(signal('sixth'));self.assertIn('DAILY_TRADE_LIMIT',r['reason_codes']);self.assertEqual(len(self.broker.sent),5)
    def test_external_trades_consume_daily_budget(self):
        self.broker.s['opening_order_ids_today']=[str(i) for i in range(5)];self.reject('DAILY_TRADE_LIMIT')
    def test_duplicate_signal_stable_across_price_or_stop_revision(self):
        self.assertEqual(self.process()['status'],'SIMULATED_OPEN');self.broker.close_position();self.service.reconcile()
        r=self.process(replace(signal(),stop_loss='998.00'));self.assertIn('DUPLICATE_SIGNAL',r['reason_codes']);self.assertEqual(len(self.broker.sent),1)
    def test_concurrent_admission_one_send(self):
        other=RehearsalService(self.config,Store(self.root,self.config.sha256),self.broker,opt_in=True);results=[]
        threads=[threading.Thread(target=lambda s=s:results.append(s.process(signal(),AT))) for s in (self.service,other)]
        for t in threads:t.start()
        for t in threads:t.join(3);self.assertFalse(t.is_alive())
        self.assertEqual(len(self.broker.sent),1);self.assertEqual(sum(r['status']=='SIMULATED_OPEN' for r in results),1);self.store.verify()
    def test_restart_duplicate_and_unknown_no_resubmission(self):
        self.broker.error=True;r=self.process();self.assertIn('SUBMISSION_UNCERTAIN',r['reason_codes']);self.assertEqual(len(self.broker.sent),1)
        service=RehearsalService(self.config,Store(self.root,self.config.sha256),self.broker,opt_in=True)
        service.reconcile();self.assertEqual(len(self.broker.sent),1)
        with self.store.connection() as db:self.assertEqual(self.store.stop_value(db),'1')
    def test_unknown_lookup_does_not_prove_non_execution(self):
        self.broker.error=True;self.process();self.broker.history={};r=self.service.reconcile()
        self.assertIn('RECONCILIATION_UNCERTAIN',r[0]['reason_codes']);self.assertEqual(len(self.broker.sent),1)
    def test_partial_fill_and_bad_slippage_latch_stop_no_topup(self):
        for volume,price in (('.005','1000.10'),('.01','1000.20')):
            temp=Path(self.tmp.name)/('state-'+volume+price);store=Store(temp,self.config.sha256,create=True);store.emergency_stop(reset=True,acknowledge=True)
            broker=SyntheticTransport();broker.response=dict(status='PARTIAL' if volume=='.005' else 'FILLED',volume=volume,price=price,sl='999',tp='1002',broker_reference='SYNTHETIC')
            service=RehearsalService(self.config,store,broker,opt_in=True);self.assertEqual(service.process(signal(),AT)['status'],'SIMULATED_PARTIAL' if volume=='.005' else 'SIMULATED_UNKNOWN')
            self.assertEqual(len(broker.sent),1)
            with store.connection() as db:self.assertEqual(store.stop_value(db),'1')
    def test_broker_order_check_and_rejection(self):
        self.broker.check_accepted=False;self.reject('BROKER_CHECK_REJECTED');self.broker.check_accepted=True
        self.broker.response=dict(status='REJECTED',volume='0',price='0',sl='0',tp='0',broker_reference='')
        self.assertEqual(self.process()['status'],'SIMULATED_REJECTED');self.assertEqual(len(self.broker.sent),1)
    def test_audit_failure_before_send_and_after_fill(self):
        with patch.object(self.store,'event',side_effect=OSError('PRIVATE')):
            r=self.process()
        self.assertEqual(r['status'],'BLOCKED');self.assertEqual(self.broker.sent,[]);self.assertNotIn('PRIVATE',json.dumps(r))
        self.service.failed=False;original=self.store.event
        def bad(db,kind,key,data):
            if kind=='STATE' and data.get('state')=='OPEN':raise OSError('PRIVATE')
            return original(db,kind,key,data)
        with patch.object(self.store,'event',side_effect=bad):r=self.process(signal('after'))
        self.assertEqual(r['status'],'BLOCKED');self.assertEqual(len(self.broker.sent),1)
        with self.store.connection() as db:self.assertEqual(db.execute("SELECT state FROM orders").fetchone()[0],'UNKNOWN')
    def test_emergency_stop_persistent_and_reset_barrier(self):
        self.store.emergency_stop();self.reject('EMERGENCY_STOP');reopened=Store(self.root,self.config.sha256)
        with reopened.connection() as db:self.assertEqual(reopened.stop_value(db),'1')
        reopened.emergency_stop(reset=True,acknowledge=True);self.process()
        with self.assertRaises(Blocked):reopened.emergency_stop(reset=True,acknowledge=True)
    def test_corrupt_state_or_configuration_never_sends(self):
        with sqlite3.connect(self.store.path) as db:db.execute("UPDATE meta SET value='fake' WHERE key='config'")
        r=self.process();self.assertEqual(r['status'],'BLOCKED');self.assertEqual(self.broker.sent,[])
        with self.assertRaises(Blocked):Store(self.root,self.config.sha256)
    def test_strict_config_and_source_files_unchanged(self):
        path=Path(self.tmp.name)/'config.json';path.write_text(json.dumps(asdict(self.config)))
        before=path.read_bytes();self.assertEqual(load_config(path),self.config);self.assertEqual(path.read_bytes(),before)
        for text in ('{}','{"enabled":true,"enabled":false}',json.dumps(asdict(self.config)|{'volume':'.02'})):
            path.write_text(text)
            with self.assertRaises(Blocked):load_config(path)
    def test_readiness_terminal_redaction_real_rejection_and_permissions(self):
        account=SimpleNamespace(trade_mode=0,login=123456789,server='PRIVATE_SERVER',company='Exness',trade_allowed=True,trade_expert=True)
        terminal=SimpleNamespace(connected=True,trade_allowed=False,tradeapi_disabled=True)
        module=SimpleNamespace(terminal_info=lambda:terminal,account_info=lambda:account,symbol_info=lambda s:SimpleNamespace(visible=True,trade_mode=4))
        r=inspect_terminal(module,fingerprint(account.login,account.server,account.company));self.assertTrue(r['identity_matches']);self.assertFalse(r['order_capability'])
        self.assertNotIn('123456789',json.dumps(r));self.assertNotIn('PRIVATE_SERVER',json.dumps(r));self.assertIn('TRADING_PERMISSION_BLOCKED',r['reason_codes'])
        account.trade_mode=2;r=inspect_terminal(module);self.assertEqual(r['reason_codes'],['DEMO_ACCOUNT_REQUIRED'])
    def test_cli_activation_refused_no_sdk_order_capability(self):
        from diagnostics.demo_execution import main
        from contextlib import redirect_stdout
        from io import StringIO
        with redirect_stdout(StringIO()) as output:self.assertEqual(main(['--enable-demo-auto-execution']),3)
        r=json.loads(output.getvalue());self.assertFalse(r['execution_allowed']);self.assertEqual(r['orders_requested'],0)
        self.assertIn('ACTIVATION_REFUSED_STAGE_A_NO_BROKER_ADAPTER',r['reason_codes'])
    def test_stage_a_does_not_introduce_actual_broker_order_calls(self):
        import ast
        root=Path(__file__).resolve().parents[1]
        for path in (root/'iat/demo_execution').glob('*.py'):
            tree=ast.parse(path.read_text());calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
            self.assertNotIn('order_send',calls);self.assertNotIn('login',calls);self.assertNotIn('symbol_select',calls)
    def test_daily_loss_breach_latches_after_equity_recovers(self):
        self.broker.s.update(realized_profit='-100',equity='9900');self.reject('DAILY_LOSS_LIMIT')
        self.broker.s.update(realized_profit='0',equity='10000');self.reject('EMERGENCY_STOP')
        self.store.emergency_stop(reset=True,acknowledge=True);self.reject('DAY_LOSS_LATCHED')
    def test_day_baseline_cannot_be_rebased_after_restart(self):
        self.process();self.broker.close_position();self.service.reconcile()
        self.broker.s.update(starting_equity='20000',equity='20000')
        r=self.process(signal('new'));self.assertIn('DAY_BASELINE_REVISED',r['reason_codes']);self.assertEqual(len(self.broker.sent),1)
    def test_no_duplicate_check_approval_is_inferred_from_reconnect(self):
        self.broker.error=True;self.process();self.broker.s['connected']=False
        self.assertEqual(self.process(signal('new'))['status'],'BLOCKED');self.broker.s['connected']=True
        self.assertEqual(self.process(signal('new'))['status'],'BLOCKED');self.assertEqual(len(self.broker.sent),1)
    def test_malformed_result_becomes_unknown_and_stops(self):
        self.broker.response={'status':'FILLED'};r=self.process();self.assertEqual(r['status'],'BLOCKED')
        with self.store.connection() as db:
            self.assertEqual(self.store.stop_value(db),'1');self.assertEqual(db.execute('SELECT state FROM orders').fetchone()[0],'UNKNOWN')
    def test_state_mirroring_detects_tampering_and_legal_transitions(self):
        self.process()
        with self.assertRaises(Blocked):self.store.transition(next(iter(self.broker.history)),'REJECTED',None)
        with sqlite3.connect(self.store.path) as db:db.execute("UPDATE orders SET state='CLOSED'")
        with self.assertRaises(Blocked):self.store.verify()
    def test_cli_template_state_and_stop_actions_never_activate(self):
        from diagnostics.demo_execution import main
        from contextlib import redirect_stdout
        from io import StringIO
        config=Path(self.tmp.name)/'disabled.json';state=Path(self.tmp.name)/'cli-state'
        with redirect_stdout(StringIO()):self.assertEqual(main(['--write-template',str(config)]),3)
        self.assertFalse(load_config(config).enabled)
        with redirect_stdout(StringIO()):self.assertEqual(main(['--config',str(config),'--state-directory',str(state),'--initialize-state']),3)
        with redirect_stdout(StringIO()):self.assertEqual(main(['--config',str(config),'--state-directory',str(state),'--emergency-stop']),3)
        store=Store(state,load_config(config).sha256)
        with store.connection() as db:self.assertEqual(store.stop_value(db),'1')
    def test_numeric_and_unexpected_errors_fail_closed(self):
        for value in ('NaN','Infinity',True,None):
            self.broker.s['bid']=value;r=self.process();self.assertEqual(r['status'],'BLOCKED');self.assertEqual(self.broker.sent,[])
            self.service.failed=False
        with self.assertRaises(Blocked):Config(volume=0.01)
    def test_signal_types_and_audit_scope_are_explicit(self):
        for field,value in (('strategy_id',True),('rule_version',2),('anchors',('x','x')),('stop_loss',True)):
            r=self.process(replace(signal(),**{field:value}));self.assertIn('UNVALIDATED_SIGNAL',r['reason_codes'])
        self.assertEqual(self.broker.sent,[]);self.process()
        with self.store.connection() as db:
            records=[json.loads(row[0]) for row in db.execute('SELECT body FROM audit')]
        self.assertTrue(all(r['scope']=='SYNTHETIC_REHEARSAL_ONLY' and r['execution_allowed'] is False and r['orders_requested']==0 for r in records))
        intent=next(r for r in records if r['event']=='INTENT');self.assertEqual(intent['data']['signal_reference']['source'],'SYNTHETIC_TEST_ONLY')
