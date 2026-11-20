"""Strict policy and finite risk calculations; no credentials, model or terminal capability."""
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from hashlib import sha256
import json,re
from iat.replay_dataset import strict_json
from iat.intelligence.strategy_registry import registry


class Blocked(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)


def need(ok,code):
    if not ok:raise Blocked(code)


def number(value):
    need(type(value) in (str,int,float,Decimal),'NUMERIC_INVALID')
    try:v=Decimal(str(value))
    except (InvalidOperation,ValueError):raise Blocked('NUMERIC_INVALID') from None
    need(v.is_finite(),'NUMERIC_INVALID');return v


def utc(value):
    try:at=datetime.fromisoformat(value)
    except (ValueError,TypeError):raise Blocked('UTC_INVALID') from None
    need(at.tzinfo is not None and at.utcoffset().total_seconds()==0,'UTC_INVALID');return at


def digest(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Config:
    version:int=1
    enabled:bool=False
    symbol:str='XAUUSD'
    volume:str='0.01'
    max_positions:int=1
    max_trades_per_day:int=5
    daily_loss_fraction:str='0.01'
    expected_account_fingerprint:str=''
    currency:str='USD'
    max_spread_points:str='0'
    max_slippage_points:str='0'
    max_quote_age_seconds:int=2
    def __post_init__(self):
        need(type(self.version) is int and self.version==1,'CONFIG_INVALID')
        need(type(self.enabled) is bool and self.symbol=='XAUUSD','CONFIG_INVALID')
        need(all(type(getattr(self,k)) is str for k in ('volume','daily_loss_fraction','max_spread_points','max_slippage_points')),'CONFIG_INVALID')
        need(type(self.max_positions) is int and self.max_positions==1 and type(self.max_trades_per_day) is int and self.max_trades_per_day==5,'CONFIG_LIMITS_INVALID')
        need(number(self.volume)==Decimal('.01') and number(self.daily_loss_fraction)==Decimal('.01'),'CONFIG_LIMITS_INVALID')
        need(isinstance(self.expected_account_fingerprint,str) and (self.expected_account_fingerprint=='' and not self.enabled or re.fullmatch('[a-f0-9]{64}',self.expected_account_fingerprint)),'ACCOUNT_IDENTITY_REQUIRED')
        need(isinstance(self.currency,str) and re.fullmatch('[A-Z]{3}',self.currency),'CURRENCY_INVALID')
        need(number(self.max_spread_points)>=0 and number(self.max_slippage_points)>=0,'CONFIG_LIMITS_INVALID')
        need(type(self.max_quote_age_seconds) is int and 1<=self.max_quote_age_seconds<=2,'CONFIG_LIMITS_INVALID')
    @property
    def sha256(self):return digest(asdict(self))


def load_config(path):
    try:
        raw=path.read_bytes();need(len(raw)<=64*1024,'CONFIG_TOO_LARGE');value=strict_json(raw)
        need(type(value) is dict and set(value)==set(asdict(Config())),'CONFIG_INVALID')
        return Config(**value)
    except Blocked:raise
    except Exception:raise Blocked('CONFIG_UNAVAILABLE_OR_INVALID') from None


def readiness(config=None):
    # Registry labels are inspected, not promoted by caller booleans or provenance strings.
    strategies=[dict(strategy_id=s['strategy_id'],rule_version=s['rule_version'],validation_status=s['validation_status'],
        execution_eligible=False,reason_codes=['NO_EXECUTABLE_ENTRY_SL_TP_POLICY','QUALIFIED_BACKTEST_PENDING']) for s in registry()['strategies']]
    return dict(version=1,status='BLOCKED',stage='A_REHEARSAL_ONLY',signal='WAIT',execution_allowed=False,orders_requested=0,
        exness='BLOCKED',qualification='DATA_NOT_QUALIFIED',historical_validation='PENDING',historical_comparisons='NOT_RUN',
        profitability_tested=False,strategies=strategies,reason_codes=['STRATEGY_NOT_EXECUTION_VALIDATED',
            'ACCOUNT_BOUND_ATOMIC_TRANSPORT_UNAVAILABLE','VERIFIED_SESSION_AND_FINALITY_REQUIRED',
            'STARTING_EQUITY_AND_COMPLETE_COST_LEDGER_REQUIRED'],config_sha256=config.sha256 if config else None)


@dataclass(frozen=True)
class Signal:
    strategy_id:str
    rule_version:str
    side:str
    anchors:tuple
    occurred_at:str
    stop_loss:str
    take_profit:str
    invalidation_reference:str
    source:str='SYNTHETIC_TEST_ONLY'
    def identity(self,account):
        need(self.source=='SYNTHETIC_TEST_ONLY','UNVALIDATED_SIGNAL')
        need(self.side in ('BUY','SELL') and isinstance(self.anchors,tuple) and 1<=len(self.anchors)<=32 and all(isinstance(x,str) and 0<len(x)<=512 for x in self.anchors),'UNVALIDATED_SIGNAL')
        need(all(type(getattr(self,k)) is str and 0<len(getattr(self,k))<=512 for k in ('strategy_id','rule_version','stop_loss','take_profit','occurred_at','invalidation_reference')),'UNVALIDATED_SIGNAL')
        need(len(set(self.anchors))==len(self.anchors) and bool(self.strategy_id) and bool(self.rule_version) and bool(self.invalidation_reference),'UNVALIDATED_SIGNAL')
        return digest([account,self.strategy_id,self.rule_version,'XAUUSD',self.side,sorted(self.anchors)])


def risk_request(config,signal,snapshot,now):
    """Snapshot comes from the synthetic transport only; never a live-data approval label."""
    need(config.enabled,'DISABLED');at=utc(now);observed=utc(snapshot['at'])
    need(0<=(at-observed).total_seconds()<=config.max_quote_age_seconds,'QUOTE_STALE_OR_FUTURE')
    need(snapshot['connected'] is True,'DISCONNECTED')
    need(type(snapshot['account_mode']) is int and snapshot['account_mode']==0,'DEMO_ACCOUNT_REQUIRED')
    need(snapshot['account_fingerprint']==config.expected_account_fingerprint and bool(config.expected_account_fingerprint),'ACCOUNT_IDENTITY_MISMATCH')
    need(snapshot['broker']=='EXNESS' and snapshot['currency']==config.currency,'BROKER_OR_CURRENCY_UNVERIFIED')
    need(snapshot['account_trade_allowed'] is True and snapshot['account_expert_allowed'] is True and snapshot['terminal_trade_allowed'] is True and snapshot['api_disabled'] is False,'TRADING_PERMISSION_BLOCKED')
    need(snapshot['new_position_session_verified'] is True,'SESSION_UNVERIFIED_OR_CLOSED')
    need(snapshot['calendar_sha256'] and snapshot['data_quality_valid'] is True and snapshot['finality_verified'] is True,'DATA_QUALITY_OR_FINALITY_BLOCKED')
    for tf,seconds in (('M1',60),('M5',300)):
        stamp=utc(snapshot['cutoffs'][tf]);epoch=int(stamp.timestamp())
        need(stamp.microsecond==0 and epoch%seconds==0 and 0<=(at-stamp).total_seconds()<seconds,'CANDLE_UNCLOSED_STALE_OR_MISALIGNED')
    need(0<=(at-utc(signal.occurred_at)).total_seconds()<=60,'SIGNAL_STALE_OR_FUTURE')
    need(snapshot['history_complete'] is True and snapshot['baseline_verified'] is True and snapshot['cashflow_categories_known'] is True,'DAY_LEDGER_UNVERIFIED')
    need(snapshot['day']==at.date().isoformat(),'DAY_BOUNDARY_UNVERIFIED')
    start=number(snapshot['starting_equity']);opening=number(snapshot['opening_unrealized']);need(start>0,'DAY_LEDGER_UNVERIFIED')
    pnl=sum((number(snapshot[k]) for k in ('realized_profit','commissions','swaps','fees','unrealized_pnl')),Decimal(0))-opening
    need(number(snapshot['equity'])==start+number(snapshot['cashflows'])+pnl,'DAY_LEDGER_INCONSISTENT')
    need(pnl>-start*Decimal('.01'),'DAILY_LOSS_LIMIT')
    need(type(snapshot['positions']) is int and snapshot['positions']==0 and type(snapshot['pending_orders']) is int and snapshot['pending_orders']==0,'POSITION_OR_PENDING_ORDER_LIMIT')
    need(isinstance(snapshot['opening_order_ids_today'],list) and all(isinstance(v,str) and v for v in snapshot['opening_order_ids_today']),'DAY_LEDGER_UNVERIFIED')
    spec=snapshot['symbol'];need(spec['name']=='XAUUSD' and spec['visible'] is True and type(spec['trade_mode']) is int and spec['trade_mode']==4,'SYMBOL_UNAVAILABLE')
    volume=number(config.volume);step=number(spec['volume_step']);tick=number(spec['tick_size']);point=number(spec['point'])
    need(step>0 and tick>0 and point>0 and number(spec['volume_min'])<=volume<=number(spec['volume_max']) and volume%step==0,'VOLUME_INVALID')
    need(type(spec['digits']) is int and 0<=spec['digits']<=10 and tick>=Decimal(10)**(-spec['digits']),'SYMBOL_PRECISION_INVALID')
    bid=number(snapshot['bid']);ask=number(snapshot['ask']);sl=number(signal.stop_loss);tp=number(signal.take_profit)
    need(ask>=bid>0 and sl>0 and tp>0,'PRICE_INVALID')
    need(all(v%tick==0 and v==v.quantize(Decimal(10)**(-spec['digits'])) for v in (bid,ask,sl,tp)),'PRICE_PRECISION_INVALID')
    need((ask-bid)/point<=number(config.max_spread_points),'SPREAD_LIMIT')
    distance=number(spec['stops_level_points'])*point;need(distance>=0,'SYMBOL_STOPS_INVALID')
    if signal.side=='BUY':need(sl<bid and sl<=bid-distance and tp>ask and tp>=ask+distance,'SL_TP_INVALID')
    elif signal.side=='SELL':need(sl>ask and sl>=ask+distance and tp<bid and tp<=bid-distance,'SL_TP_INVALID')
    else:raise Blocked('UNVALIDATED_SIGNAL')
    need('FOK' in spec['filling_modes'] and 'GTC' in spec['validity_modes'],'ORDER_POLICY_UNSUPPORTED')
    return dict(symbol='XAUUSD',side=signal.side,volume=str(volume),price=str(ask if signal.side=='BUY' else bid),
        sl=str(sl),tp=str(tp),max_deviation_points=config.max_slippage_points,fill_policy='FOK',validity='GTC'),pnl,start
