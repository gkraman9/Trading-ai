"""Timestamp ledger behind the existing demo-only safety gates, never a strategy."""
from datetime import datetime, timedelta, timezone
from itertools import islice

from diagnostics.mt5_readonly_check import validate_demo
from iat.quality import ClockGuard
from iat.session_config import load_session_bundle
from iat.session_research import research_report
from iat.sessions import SessionValidationError


class CaptureAdapter:
    """Expose only existing read-only diagnostic methods and constants."""
    ALLOWED = {'initialize','shutdown','terminal_info','account_info','symbol_info','iat_session_metadata',
               'ACCOUNT_TRADE_MODE_DEMO','TIMEFRAME_M1','TIMEFRAME_M5'}

    def __init__(self, provider, calendar, clock):
        self.provider, self.calendar, self.clock = provider, calendar, clock
        self.observations = {'M1': [], 'M5': []}

    def __getattr__(self, name):
        if name not in self.ALLOWED:
            raise AttributeError('Unavailable in the read-only capture adapter')
        return getattr(self.provider, name)

    def copy_rates_from_pos(self, symbol, timeframe, position, count):
        raw = self.provider.copy_rates_from_pos(symbol,timeframe,position,count)
        tf = 'M1' if timeframe == self.provider.TIMEFRAME_M1 else 'M5'
        try:
            if position != 1 or type(count) is not int or count > 5000 or len(raw) != count:
                return raw
            for rate in islice(iter(raw),count):
                try:
                    value=rate['time'];seconds=int(value)
                    if isinstance(value,bool) or value != seconds:raise ValueError('Invalid timestamp')
                    opened=datetime.fromtimestamp(seconds,tz=timezone.utc)
                    result=self.calendar.classify_bar(opened,tf,research=True)
                    duration=timedelta(minutes=1 if tf=='M1' else 5)
                    complete=(self.calendar.finality_verified and result['classification']=='FULL_SESSION_BAR'
                              and opened+duration <= self.clock())
                    self.observations[tf].append({'timestamp':opened.isoformat(),'finalized':True if complete else None})
                except Exception:
                    self.observations[tf].append({'timestamp':None,'finalized':None})
        except Exception:
            pass
        return raw  # No repair, reordering, filtering or alteration for the validator.


def capture_demo_research(config_path, *, mt5=None, clock=None, metadata_path=None, terminal_path=None):
    config,calendar=load_session_bundle(config_path)
    if getattr(calendar,'version',1)!=2:
        raise ValueError('The research capture requires v2; v1 is not silently migrated')
    clock=ClockGuard(clock if clock is not None else lambda:datetime.now(timezone.utc))
    now=clock()
    try:
        calendar.validate_request(calendar.symbol,now,timedelta(minutes=1))
    except SessionValidationError as exc:
        return research_report(calendar,now,demo_codes=[exc.code])
    injected=mt5 is not None
    if mt5 is None:
        try:
            import MetaTrader5 as mt5
        except Exception:
            return research_report(calendar,now,demo_codes=['MT5_UNAVAILABLE'])
    adapter=CaptureAdapter(mt5,calendar,clock)
    demo=validate_demo(config_path,mt5=adapter,clock=clock,metadata_path=metadata_path,terminal_path=terminal_path)
    try:
        now=clock()
        codes=[item['code'] for item in demo['diagnostics']]
    except Exception:
        codes=['CLOCK_UNAVAILABLE']
    return research_report(calendar,now,adapter.observations,
                           origin='SYNTHETIC_TEST' if injected else 'LOCAL_DEMO_OBSERVATION',
                           demo_codes=codes,broker_comparison=demo['calendar'],
                           terminal_capture_attempted=demo['safety']['binding_initialization_attempted'])
