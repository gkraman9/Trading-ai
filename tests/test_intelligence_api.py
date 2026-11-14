"""Read-only additive API with real validation, mocked terminal transport only."""
import ast
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from main import create_app
from iat.sessions import SessionCalendar
from iat.session_config import compile_session_config, load_session_config
from iat.intelligence import IntelligenceConfig
from test_api import NOW, rates
from test_session_v2 import synthetic_v2, bounded_day


class DualProvider:
    TIMEFRAME_M1=1
    TIMEFRAME_M5=5
    def __init__(self,*,mutate=None):self.calls=[];self.mutate=mutate
    def terminal_info(self):return SimpleNamespace(connected=True)
    def copy_rates_from_pos(self,symbol,tf,position,count):
        self.calls.append((symbol,tf,position,count))
        data=rates([100]*count,period=60 if tf==1 else 300)
        return self.mutate(data,tf) if self.mutate else data
    # No account/initialize/login/order API exists; any such call would fail.


class IntelligenceAPITests(unittest.TestCase):
    def client(self,provider=None,**options):
        if 'session_calendars' not in options and 'session_config_path' not in options:
            start=NOW.replace(hour=0,minute=0,second=0)
            end=start+timedelta(days=1)
            options['session_calendars']={'XAUUSD':SessionCalendar('XAUUSD',start,end,((start,end),))}
        return create_app(mt5=provider or DualProvider(),clock=lambda:NOW,**options).test_client()

    def safe(self,response,status):
        self.assertEqual(response.status_code,status,response.get_data(as_text=True))
        r=response.get_json()
        self.assertEqual(r['signal'],'WAIT');self.assertFalse(r['execution_allowed'])
        self.assertEqual(r['mode'],'READ_ONLY_SHADOW')
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        return r

    def test_success_through_both_provider_quality_gates(self):
        provider=DualProvider()
        r=self.safe(self.client(provider).get('/research/v1/intelligence?symbol=XAUUSD'),200)
        self.assertEqual(r['provenance'],'VALIDATED_LIVE')
        self.assertEqual(r['report_version'],1)
        self.assertEqual(r['analysis_at'],'2026-11-12T10:30:00+00:00')
        self.assertEqual(r['requested_at_utc'],NOW.isoformat())
        self.assertTrue(r['data_quality']['valid'])
        self.assertEqual(provider.calls,[('XAUUSD',1,1,100),('XAUUSD',5,1,100)])
        self.assertLessEqual(r['frames']['M5']['data_as_of'],r['analysis_at'])

    def test_existing_analyze_unchanged(self):
        client=self.client()
        old=self.safe(client.get('/analyze?symbol=XAUUSD&timeframe=M1'),200)
        self.assertEqual(old['market_state'],'RANGE')
        self.assertNotIn('frames',old)

    def test_invalid_inputs_no_fetch(self):
        provider=DualProvider();client=self.client(provider)
        for query in ('','?symbol=','?symbol=XAU%20USD','?symbol=XAUUSD&symbol=XAUUSD',
                      '?symbol=XAUUSD&execution_allowed=true','?symbol=XAUUSD&timeframe=M1'):
            self.safe(client.get('/research/v1/intelligence'+query),400)
        self.assertFalse(provider.calls)

    def test_missing_calendar_no_fetch(self):
        provider=DualProvider()
        self.safe(self.client(provider,session_calendars={}).get('/research/v1/intelligence?symbol=XAUUSD'),503)
        self.assertFalse(provider.calls)

    def test_config_failure_no_fetch(self):
        provider=DualProvider()
        self.safe(self.client(provider,session_config_path='missing-intelligence-config.json').get('/research/v1/intelligence?symbol=XAUUSD'),503)
        self.assertFalse(provider.calls)

    def test_m5_malformed_quarantines_both_frames(self):
        def malformed(data,tf):
            if tf==5:data[0]['high']=1
            return data
        r=self.safe(self.client(DualProvider(mutate=malformed)).get('/research/v1/intelligence?symbol=XAUUSD'),503)
        self.assertFalse(r['frames']);self.assertFalse(r['research_hypotheses'])

    def test_provider_exception_redacted(self):
        class Bad(DualProvider):
            def terminal_info(self):raise RuntimeError('private-secret-provider-details')
        response=self.client(Bad()).get('/research/v1/intelligence?symbol=XAUUSD')
        self.safe(response,503);self.assertNotIn('private-secret',response.get_data(as_text=True))

    def test_v2_verified_fixture_additive_state(self):
        calendar=compile_session_config(synthetic_v2())
        r=self.safe(self.client(session_calendars={'XAUUSD':calendar}).get('/research/v1/intelligence?symbol=XAUUSD'),200)
        self.assertEqual(r['session_v2']['version'],2)
        self.assertFalse(r['session_v2']['permissions']['iat_execution_allowed'])

    def test_exness_blocked_before_provider_access(self):
        provider=DualProvider()
        calendar=load_session_config('config/profiles/exness-xauusd-v2.candidate.json')
        r=self.safe(self.client(provider,session_calendars={'XAUUSD':calendar}).get('/research/v1/intelligence?symbol=XAUUSD'),503)
        self.assertFalse(r['frames']);self.assertFalse(provider.calls)

    def test_partial_m5_boundary_blocked(self):
        config=synthetic_v2();config['weekdays']['thu']=bounded_day('00:01:00','23:00:00')
        calendar=compile_session_config(config)
        # M5's 100 bars start 02:10 at this clock: add a real partial opening there.
        config['weekdays']['thu']=bounded_day('02:11:00','23:00:00')
        calendar=compile_session_config(config)
        self.safe(self.client(session_calendars={'XAUUSD':calendar}).get('/research/v1/intelligence?symbol=XAUUSD'),503)

    def test_live_m5_later_than_stale_m1_not_used(self):
        def lag(data,tf):
            return rates([100]*100,last_open=NOW.replace(minute=28,second=0)) if tf==1 else data
        r=self.safe(self.client(DualProvider(mutate=lag)).get('/research/v1/intelligence?symbol=XAUUSD'),200)
        self.assertEqual(r['analysis_at'],'2026-11-12T10:29:00+00:00')
        self.assertEqual(r['frames']['M5']['data_as_of'],'2026-11-12T10:25:00+00:00')

    def test_clock_regression_blocks(self):
        moments=iter([NOW,NOW,NOW-timedelta(minutes=1)])
        start=NOW.replace(hour=0,minute=0,second=0)-timedelta(days=1);end=start+timedelta(days=3)
        app=create_app(mt5=DualProvider(),clock=lambda:next(moments),
                       session_calendars={'XAUUSD':SessionCalendar('XAUUSD',start,end,((start,end),))})
        r=self.safe(app.test_client().get('/research/v1/intelligence?symbol=XAUUSD'),503)
        self.assertEqual(r['error'],'CLOCK_MOVED_BACKWARD')

    def test_configurable_app_thresholds(self):
        r=self.safe(self.client(intelligence_config=IntelligenceConfig(left_strength=3)).get('/research/v1/intelligence?symbol=XAUUSD'),200)
        self.assertEqual(r['configuration']['left_strength'],3)

    def test_core_has_no_broker_execution_or_credential_imports(self):
        for p in Path('iat/intelligence').glob('*.py'):
            if p.name=='api.py':continue
            tree=ast.parse(p.read_text())
            imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
            self.assertFalse(any(x.startswith(('MetaTrader5','iat.mt5_data','diagnostics')) for x in imports),p)
            forbidden={'order_send','order_check','login','account_info','initialize','symbol_select'}
            self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in forbidden for n in ast.walk(tree)),p)
