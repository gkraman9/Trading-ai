"""Additive HTTP adapter. Analytics itself never imports or accesses a broker."""
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from iat.mt5_data import get_candle_snapshot, MarketDataError
from iat.quality import assess_candles, ClockValidationError
from iat.sessions import SessionValidationError
from iat.intelligence.engine import analyze_at
from iat.intelligence.models import IntelligenceConfig


def register_intelligence(app, *, mt5, clock, calendars, config_error, intelligence_config):
    blueprint = Blueprint('intelligence_v1',__name__)
    config = IntelligenceConfig() if intelligence_config is None else intelligence_config
    if not isinstance(config, IntelligenceConfig): raise ValueError('Typed intelligence configuration required')

    @blueprint.after_request
    def no_cache(response):
        response.headers['Cache-Control']='no-store'
        return response

    @blueprint.route('/research/v1/intelligence',methods=['GET'])
    def intelligence():
        def blocked(status,code):
            return jsonify({'report_version':1,'model_version':'IAT_MARKET_INTELLIGENCE_V1',
                'mode':'READ_ONLY_SHADOW','signal':'WAIT','execution_allowed':False,
                'status':'BLOCKED','error':code,'reason_codes':[code],
                'data_quality':{'valid':False,'status':'BLOCKED'},'frames':{},
                'research_hypotheses':[],'alignment':{'classification':'BLOCKED_DATA_QUALITY'},
                'reasoning':['Validated closed-candle intelligence is unavailable; execution remains disabled.']}),status
        symbol = request.args.get('symbol','').strip()
        if (set(request.args) != {'symbol'} or len(request.args.getlist('symbol'))!=1 or not symbol
                or len(symbol)>128 or any(c.isspace() or ord(c)<32 for c in symbol)):
            return blocked(400,'INVALID_REQUEST')
        if config_error is not None: return blocked(503,config_error)
        calendar = calendars.get(symbol)
        if calendar is None: return blocked(503,'SESSION_CALENDAR_UNAVAILABLE')
        try:
            snapshots = {tf:get_candle_snapshot(symbol,tf,100,mt5=mt5,clock=clock,session_calendar=calendar)
                         for tf in ('M1','M5')}
            final_now = clock()
            # Both snapshots must STILL be valid after the second fetch and current UTC sample.
            for tf,snapshot in snapshots.items():
                calendar.validate_request(symbol,final_now,timedelta(minutes=1 if tf=='M1' else 5))
                quality = assess_candles(snapshot.candles,tf,final_now,session_calendar=calendar,
                                         observed_finality=True)
                if not quality.valid: return blocked(503,quality.diagnostics[0].code)
            decision_at = datetime.fromisoformat(snapshots['M1'].candles[-1]['timestamp'])+timedelta(minutes=1)
            report = analyze_at(symbol,snapshots['M1'].candles,snapshots['M5'].candles,decision_at,
                    provenance='VALIDATED_LIVE',calendar=calendar,observed_finality=True,config=config).to_dict()
            report['requested_at_utc'] = final_now.isoformat()
            report['snapshot_quality']={tf:s.quality.to_dict() for tf,s in snapshots.items()}
            if getattr(calendar,'version',1)==2: report['session_v2']=calendar.public_state(final_now)
            return jsonify(report),200 if report['data_quality']['valid'] else 503
        except (MarketDataError,ClockValidationError) as exc:
            return blocked(503,exc.report.diagnostics[0].code)
        except SessionValidationError as exc:
            return blocked(503,exc.code)
        except Exception:
            return blocked(503,'INTELLIGENCE_UNAVAILABLE')

    app.register_blueprint(blueprint)
