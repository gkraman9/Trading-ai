"""MT5 read capabilities only. Importing never attaches to a terminal."""
from datetime import datetime,timezone
from math import isfinite
from types import SimpleNamespace
from iat.mt5_data import MarketDataError

FIELDS=('time','open','high','low','close','tick_volume','spread','real_volume')


def scalar(value):
    if hasattr(value,'item'):value=value.item()
    if value is None or type(value) in (bool,int):return value
    if type(value) is float:return value if isfinite(value) else {'invalid_numeric':True}
    return {'unsupported_type':True}


class ReadOnlyMarketData:
    """Retain only read callables, never the MT5 module or an order/login capability."""
    timestamp_basis='MT5_API_UTC_EPOCH'
    quote_max_age_seconds=30  # Existing legacy quote freshness policy, unchanged.
    def __init__(self,mt5):
        self._terminal=mt5.terminal_info;self._account=mt5.account_info
        self._symbol=mt5.symbol_info;self._tick=mt5.symbol_info_tick;self._rates=mt5.copy_rates_from_pos
        self.TIMEFRAME_M1=mt5.TIMEFRAME_M1;self.TIMEFRAME_M5=mt5.TIMEFRAME_M5
        self._demo=getattr(mt5,'ACCOUNT_TRADE_MODE_DEMO',None)
        self.raw={};self.diagnostics={};self._point=None

    def terminal_info(self):
        t=self._terminal()
        return SimpleNamespace(connected=t is not None and getattr(t,'connected',None) is True)

    def preflight(self):
        self.raw={};self._point=None;self.diagnostics={}
        t=self._terminal()
        self.diagnostics=dict(connected=t is not None and getattr(t,'connected',None) is True,
            demo_verified=None,terminal_trading_disabled=None,python_api_trading_disabled=None,symbol_visible=None)
        self.diagnostics['terminal_trading_disabled']=None if type(getattr(t,'trade_allowed',None)) is not bool else getattr(t,'trade_allowed') is False
        self.diagnostics['python_api_trading_disabled']=None if type(getattr(t,'tradeapi_disabled',None)) is not bool else getattr(t,'tradeapi_disabled') is True
        if t is None:raise MarketDataError('Terminal information unavailable','TERMINAL_INFO_UNAVAILABLE')
        if getattr(t,'connected',None) is not True:raise MarketDataError('Disconnected','PROVIDER_DISCONNECTED')
        if self.diagnostics['terminal_trading_disabled'] is None or self.diagnostics['python_api_trading_disabled'] is None:raise MarketDataError('Safety information unavailable','SAFETY_INFORMATION_UNAVAILABLE')
        if getattr(t,'trade_allowed',None) is not False or getattr(t,'tradeapi_disabled',None) is not True:
            raise MarketDataError('Disable both terminal trading permissions','TRADING_PERMISSIONS_NOT_DISABLED')
        # Read only trade_mode; never read/serialize account ID, server or credentials.
        mode=getattr(self._account(),'trade_mode',None)
        self.diagnostics['demo_verified']=None if type(mode) is not int or type(self._demo) is not int else type(mode) is int and type(self._demo) is int and self._demo==0 and mode==0
        if self.diagnostics['demo_verified'] is None:raise MarketDataError('Demo verification unavailable','SAFETY_INFORMATION_UNAVAILABLE')
        if type(mode) is not int or type(self._demo) is not int or self._demo!=0 or mode!=0:raise MarketDataError('Demo account required','DEMO_ACCOUNT_REQUIRED')
        symbol=self._symbol('XAUUSD')
        self.diagnostics['symbol_visible']=symbol is not None and getattr(symbol,'visible',None) is True
        point=getattr(symbol,'point',None)
        self._point=float(point) if type(point) in (int,float) and isfinite(point) and point>0 else None
        if symbol is None or getattr(symbol,'visible',None) is not True:raise MarketDataError('Make XAUUSD visible manually','SYMBOL_NOT_VISIBLE')
        if self.timestamp_basis!='MT5_API_UTC_EPOCH':raise MarketDataError('Unverified time basis','TIMESTAMP_BASIS_UNVERIFIED')

    def copy_rates_from_pos(self,symbol,tf,position,count):
        if symbol!='XAUUSD' or tf not in (self.TIMEFRAME_M1,self.TIMEFRAME_M5) or position!=1 or type(count) is not int or not 3<=count<=5000:
            raise ValueError('Read-only closed-candle request required')
        data=self._rates(symbol,tf,position,count)
        name='M1' if tf==self.TIMEFRAME_M1 else 'M5'
        if data is not None:
            captured=[]
            for row in data:
                fields={}
                for key in FIELDS:
                    try:fields[key]=scalar(row[key])
                    except (KeyError,ValueError,TypeError,IndexError):fields[key]=None
                captured.append(fields)
                if len(captured)>count:break
            self.raw[name]={'position':1,'requested_count':count,'rates':captured}
        return data

    def quote(self,now):
        tick=self._tick('XAUUSD')
        if tick is None:raise MarketDataError('No current quote','TICK_UNAVAILABLE')
        price=getattr(tick,'bid',None);epoch=getattr(tick,'time',None);msc=getattr(tick,'time_msc',None)
        if isinstance(price,bool) or not isinstance(price,(int,float)) or not isfinite(price) or price<=0:
            raise MarketDataError('Invalid quote','TICK_MALFORMED')
        if isinstance(epoch,bool) or type(epoch) not in (int,float) or not isfinite(epoch) or epoch!=int(epoch):
            raise MarketDataError('Invalid quote time','TIMESTAMP_MALFORMED')
        if msc is not None and (type(msc) not in (int,float) or isinstance(msc,bool) or not isfinite(msc) or int(msc)//1000!=int(epoch)):
            raise MarketDataError('Inconsistent quote time','TIMESTAMP_MALFORMED')
        at=datetime.fromtimestamp(epoch if msc is None else msc/1000,tz=timezone.utc)
        latency=(now-at).total_seconds()
        if latency < -2:raise MarketDataError('Future quote','TICK_FUTURE_OR_TIME_BASIS_AMBIGUOUS')
        if latency>30:raise MarketDataError('Stale quote','TICK_STALE')
        ask=getattr(tick,'ask',None)
        if ask is not None and (type(ask) not in (int,float) or not isfinite(ask) or ask<float(price)):
            raise MarketDataError('Invalid ask','TICK_MALFORMED')
        return dict(bid=float(price),ask=float(ask) if ask is not None else None,
                    broker_point=self._point,spread_points=(float(ask)-float(price))/self._point if ask is not None and self._point is not None else None,
                    observed_at_utc=at.isoformat(),epoch_seconds=epoch,
                    epoch_milliseconds=msc,age_seconds=latency,price_basis='OBSERVED_MT5_BID')
