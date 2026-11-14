"""Additive read-only context HTTP adapter; existing Phase 7 endpoint is unchanged."""
from datetime import datetime,timedelta
from flask import Blueprint,jsonify,request
from iat.mt5_data import get_candle_snapshot,MarketDataError
from iat.quality import assess_candles,ClockValidationError
from iat.sessions import SessionValidationError
from iat.intelligence.context import context_at
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig


def register_context(app,*,mt5,clock,calendars,config_error,intelligence_config,context_config):
    config=ContextConfig() if context_config is None else context_config
    phase7=IntelligenceConfig() if intelligence_config is None else intelligence_config
    if not isinstance(config,ContextConfig) or not isinstance(phase7,IntelligenceConfig):
        raise ValueError('Typed analytical configurations required')
    bp=Blueprint('market_context_v1',__name__)
    @bp.after_request
    def no_cache(response):
        response.headers['Cache-Control']='no-store'
        return response
    @bp.route('/research/v1/context',methods=['GET'])
    def context():
        def blocked(status,code):
            return jsonify({'report_version':1,'model_version':'IAT_MARKET_CONTEXT_V1','mode':'READ_ONLY_SHADOW',
                'signal':'WAIT','execution_allowed':False,'status':'BLOCKED','reason_codes':[code],
                'data_quality':{'valid':False,'status':'BLOCKED'},'evidence':[],'hypotheses':[],
                'context':{'classification':'BLOCKED_DATA_QUALITY'},'abstention_reasons':[code]}),status
        symbol=request.args.get('symbol','').strip()
        if (set(request.args)!={'symbol'} or len(request.args.getlist('symbol'))!=1 or not symbol or len(symbol)>128
                or any(c.isspace() or ord(c)<32 for c in symbol)):return blocked(400,'INVALID_REQUEST')
        if config_error:return blocked(503,config_error)
        calendar=calendars.get(symbol)
        if calendar is None:return blocked(503,'SESSION_CALENDAR_UNAVAILABLE')
        try:
            snapshots={tf:get_candle_snapshot(symbol,tf,100,mt5=mt5,clock=clock,session_calendar=calendar) for tf in ('M1','M5')}
            now=clock()
            for tf,s in snapshots.items():
                calendar.validate_request(symbol,now,timedelta(minutes=1 if tf=='M1' else 5))
                q=assess_candles(s.candles,tf,now,session_calendar=calendar,observed_finality=True)
                if not q.valid:return blocked(503,q.diagnostics[0].code)
            at=datetime.fromisoformat(snapshots['M1'].candles[-1]['timestamp'])+timedelta(minutes=1)
            report=context_at(symbol,snapshots['M1'].candles,snapshots['M5'].candles,at,
                config=config,intelligence_config=phase7,provenance='VALIDATED_LIVE',calendar=calendar,
                observed_finality=True).to_dict()
            report['requested_at_utc']=now.isoformat()
            if getattr(calendar,'version',1)==2:report['session_v2']=calendar.public_state(now)
            return jsonify(report),200 if report['data_quality']['valid'] else 503
        except (MarketDataError,ClockValidationError) as exc:return blocked(503,exc.report.diagnostics[0].code)
        except SessionValidationError as exc:return blocked(503,exc.code)
        except Exception:return blocked(503,'CONTEXT_UNAVAILABLE')
    app.register_blueprint(bp)
