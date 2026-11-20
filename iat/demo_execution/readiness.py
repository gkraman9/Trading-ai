"""Read-only terminal checks. Retains no order, login or account-switch callable."""
from hashlib import sha256
import json
from math import isfinite


def fingerprint(login,server,company):
    if type(login) is not int or login<=0 or not isinstance(server,str) or not server or not isinstance(company,str) or not company:raise ValueError('Identity unavailable')
    return sha256(json.dumps([login,server,company],separators=(',',':')).encode()).hexdigest()


def inspect_terminal(module,expected_fingerprint='',*,include_fingerprint=False):
    result=dict(connected=False,demo_verified=False,identity_matches=False,new_order_permissions=False,
        symbol_available=False,atomic_account_binding=False,order_capability=False,reason_codes=[])
    try:
        terminal=module.terminal_info()
        if terminal is None or getattr(terminal,'connected',None) is not True:result['reason_codes']=['TERMINAL_DISCONNECTED'];return result
        result['connected']=True;account=module.account_info()
        if type(getattr(account,'trade_mode',None)) is not int or account.trade_mode!=0:
            result['reason_codes']=['DEMO_ACCOUNT_REQUIRED'];return result
        result['demo_verified']=True
        actual=fingerprint(account.login,account.server,account.company)
        result['identity_matches']=bool(expected_fingerprint) and actual==expected_fingerprint
        if include_fingerprint:result['local_demo_fingerprint']=actual
        result['new_order_permissions']=(getattr(account,'trade_allowed',None) is True and getattr(account,'trade_expert',None) is True
            and getattr(terminal,'trade_allowed',None) is True and getattr(terminal,'tradeapi_disabled',None) is False)
        symbol=module.symbol_info('XAUUSD');result['symbol_available']=bool(symbol is not None and getattr(symbol,'visible',None) is True and getattr(symbol,'trade_mode',None)==4)
        if symbol:
            # Redacted declaration only; no account balance, IDs, server or terminal path.
            fields=('digits','point','trade_tick_size','trade_stops_level','volume_min','volume_max','volume_step','filling_mode','expiration_mode')
            result['symbol_specifications']={key:(v if type(v) in (int,float) and isfinite(v) else None) for key in fields for v in (getattr(symbol,key,None),)}
        result['reason_codes']=['ACCOUNT_BOUND_ATOMIC_TRANSPORT_UNAVAILABLE','STRATEGY_NOT_EXECUTION_VALIDATED']
        if not result['identity_matches']:result['reason_codes'].append('ACCOUNT_IDENTITY_UNVERIFIED')
        if not result['new_order_permissions']:result['reason_codes'].append('TRADING_PERMISSION_BLOCKED')
        else:result['reason_codes'].append('SHARED_TERMINAL_READ_ONLY_PERMISSION_CONFLICT')
        if not result['symbol_available']:result['reason_codes'].append('SYMBOL_UNAVAILABLE')
        if 'exness' not in str(getattr(account,'company','')).casefold():result['reason_codes'].append('BROKER_UNVERIFIED')
    except Exception:
        result=dict(connected=False,demo_verified=False,identity_matches=False,new_order_permissions=False,
            symbol_available=False,atomic_account_binding=False,order_capability=False,reason_codes=['TERMINAL_STATE_UNCERTAIN'])
    return result
