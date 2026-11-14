"""New endpoint preserves Phase 7 and all earlier session safety behavior."""
import json,unittest
from datetime import timedelta
from main import create_app
from iat.intelligence.context_models import ContextConfig
from iat.sessions import SessionCalendar
from iat.session_config import load_session_config,compile_session_config
from test_intelligence_api import DualProvider
from test_api import NOW,rates
from test_session_v2 import synthetic_v2,bounded_day


class ContextAPITests(unittest.TestCase):
    def client(self,provider=None,**options):
        if 'session_calendars' not in options and 'session_config_path' not in options:
            start=NOW.replace(hour=0,minute=0,second=0);end=start+timedelta(days=1)
            options['session_calendars']={'XAUUSD':SessionCalendar('XAUUSD',start,end,((start,end),))}
        return create_app(mt5=provider or DualProvider(),clock=lambda:NOW,**options).test_client()

    def safe(self,response,status):
        self.assertEqual(response.status_code,status,response.get_data(as_text=True))
        r=response.get_json();self.assertEqual(r['signal'],'WAIT');self.assertFalse(r['execution_allowed'])
        self.assertEqual(r['mode'],'READ_ONLY_SHADOW');self.assertEqual(response.headers['Cache-Control'],'no-store')
        return r

    def test_success_contains_explainable_context(self):
        p=DualProvider();r=self.safe(self.client(p).get('/research/v1/context?symbol=XAUUSD'),200)
        self.assertEqual(r['model_version'],'IAT_MARKET_CONTEXT_V1')
        self.assertTrue(r['data_quality']['valid']);self.assertTrue(r['observed_facts']);self.assertTrue(r['explanation'])
        self.assertTrue(r['abstention_reasons'])  # Flat doji history cannot create confirmed structure.
        self.assertEqual(p.calls,[('XAUUSD',1,1,100),('XAUUSD',5,1,100)])

    def test_existing_endpoints_preserved(self):
        c=self.client()
        p7=self.safe(c.get('/research/v1/intelligence?symbol=XAUUSD'),200)
        self.assertEqual(p7['model_version'],'IAT_MARKET_INTELLIGENCE_V1')
        old=self.safe(c.get('/analyze?symbol=XAUUSD&timeframe=M1'),200)
        self.assertNotIn('confluence',old)

    def test_bad_inputs_cannot_enable_trading_or_synthetic_mode(self):
        p=DualProvider();c=self.client(p)
        for query in ('','?symbol=','?symbol=XAUUSD&symbol=XAUUSD','?symbol=XAU%20USD',
                      '?symbol=XAUUSD&signal=BUY','?symbol=XAUUSD&provenance=SYNTHETIC_RESEARCH'):
            self.safe(c.get('/research/v1/context'+query),400)
        self.assertFalse(p.calls)

    def test_no_calendar_or_bad_config_no_provider_access(self):
        for opts in ({'session_calendars':{}},{'session_config_path':'missing-context-calendar.json'}):
            p=DualProvider();self.safe(self.client(p,**opts).get('/research/v1/context?symbol=XAUUSD'),503)
            self.assertFalse(p.calls)

    def test_exness_blocked_before_access(self):
        p=DualProvider();calendar=load_session_config('config/profiles/exness-xauusd-v2.candidate.json')
        r=self.safe(self.client(p,session_calendars={'XAUUSD':calendar}).get('/research/v1/context?symbol=XAUUSD'),503)
        self.assertFalse(r['hypotheses']);self.assertFalse(r['evidence']);self.assertFalse(p.calls)

    def test_provider_errors_redacted(self):
        class Bad(DualProvider):
            def terminal_info(self):raise RuntimeError('private-account-server-token-details')
        response=self.client(Bad()).get('/research/v1/context?symbol=XAUUSD')
        self.safe(response,503);self.assertNotIn('private-account',response.get_data(as_text=True))

    def test_bad_m5_quarantines_context(self):
        def bad(data,tf):
            if tf==5:data[0]['close']=float('nan')
            return data
        r=self.safe(self.client(DualProvider(mutate=bad)).get('/research/v1/context?symbol=XAUUSD'),503)
        self.assertFalse(r['hypotheses']);self.assertFalse(r['evidence'])

    def test_partial_m5_rejected(self):
        cfg=synthetic_v2();cfg['weekdays']['thu']=bounded_day('02:11:00','23:00:00')
        self.safe(self.client(session_calendars={'XAUUSD':compile_session_config(cfg)}).get('/research/v1/context?symbol=XAUUSD'),503)

    def test_current_v2_metadata_remains_execution_disabled(self):
        r=self.safe(self.client(session_calendars={'XAUUSD':compile_session_config(synthetic_v2())}).get('/research/v1/context?symbol=XAUUSD'),200)
        self.assertFalse(r['session_v2']['permissions']['iat_execution_allowed'])

    def test_m5_causal_to_m1_as_of(self):
        def lag(data,tf):return rates([100]*100,last_open=NOW.replace(minute=28,second=0)) if tf==1 else data
        r=self.safe(self.client(DualProvider(mutate=lag)).get('/research/v1/context?symbol=XAUUSD'),200)
        self.assertEqual(r['analysis_at'],'2026-11-12T10:29:00+00:00')
        self.assertEqual(r['context']['m5_as_of'],'2026-11-12T10:25:00+00:00')

    def test_trusted_app_context_configuration(self):
        r=self.safe(self.client(context_config=ContextConfig(minimum_score=10)).get('/research/v1/context?symbol=XAUUSD'),200)
        self.assertEqual(r['configuration']['minimum_score'],10)

    def test_backward_clock_blocks_context(self):
        moments=iter([NOW,NOW,NOW-timedelta(minutes=1)])
        start=NOW.replace(hour=0,minute=0,second=0);end=start+timedelta(days=1)
        app=create_app(mt5=DualProvider(),clock=lambda:next(moments),
            session_calendars={'XAUUSD':SessionCalendar('XAUUSD',start,end,((start,end),))})
        r=self.safe(app.test_client().get('/research/v1/context?symbol=XAUUSD'),503)
        self.assertEqual(r['reason_codes'],['CLOCK_MOVED_BACKWARD'])
    def test_second_fetch_becoming_stale_cannot_return_context(self):
        calls=iter([NOW,NOW,NOW,NOW,NOW+timedelta(minutes=20)])
        start=NOW.replace(hour=0,minute=0,second=0);end=start+timedelta(days=1)
        app=create_app(mt5=DualProvider(),clock=lambda:next(calls),
            session_calendars={'XAUUSD':SessionCalendar('XAUUSD',start,end,((start,end),))})
        r=self.safe(app.test_client().get('/research/v1/context?symbol=XAUUSD'),503)
        self.assertFalse(r['hypotheses'])
