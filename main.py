"""HTTP interface for validated, read-only MT5 market analysis."""
from datetime import datetime, timezone
import os

from flask import Flask, jsonify, request

from iat.analysis import analyze as analyze_candles
from iat.mt5_data import TIMEFRAMES, MarketDataError, get_candle_snapshot
from iat.quality import ClockGuard, ClockValidationError, failed
from iat.session_config import SessionConfigError, load_session_config


def create_app(*, mt5=None, clock=None, session_calendars=None, session_config_path=None,
               intelligence_config=None, context_config=None):
    """Inject a read-only MT5 adapter and UTC clock for offline testing.

    The default adapter uses an already-connected terminal. This application
    never initializes a terminal, logs in, or submits orders.
    session_calendars maps exact symbols to independently verified calendars.
    """
    app = Flask(__name__)
    calendars = dict(session_calendars or {})
    config_error = None
    path = session_config_path if session_config_path is not None else os.environ.get("IAT_SESSION_CONFIG")
    if path is not None:
        try:
            if session_calendars is not None:
                raise SessionConfigError("Choose a configuration file or explicit calendars, not both")
            calendar = load_session_config(path)
            calendars = {calendar.symbol: calendar}
        except SessionConfigError as exc:
            calendars = {}
            config_error = exc.code
    utc_now = ClockGuard(clock if clock is not None else lambda: datetime.now(timezone.utc))

    @app.after_request
    def prevent_cached_analysis(response):
        if request.path == "/analyze":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/")
    def home():
        return jsonify({"status": "OK", "message": "Trading AI is running"})

    @app.route("/analyze")
    def analyze():
        symbol = request.args.get("symbol", "").strip()
        supplied_timeframe = request.args.get("timeframe", "").strip()
        timeframe = {"1m": "M1", "5m": "M5"}.get(
            supplied_timeframe.lower(), supplied_timeframe.upper()
        )

        session_details = None

        def failure(status, error, reason, quality=None):
            body = {
                "symbol": symbol, "timeframe": supplied_timeframe,
                "signal": "WAIT", "execution_allowed": False,
                "mode": "READ_ONLY_SHADOW", "data_source": "MT5",
                "market_state": "UNKNOWN", "last_closed_candle": None,
                "error": error, "reasoning": [reason],
                "quality": (quality if quality is not None else failed(error, reason)).to_dict(),
            }
            if session_details is not None:
                body['session_v2'] = session_details
            return jsonify(body), status

        if not symbol or len(symbol) > 128 or any(c.isspace() or ord(c) < 32 for c in symbol):
            return failure(400, "INVALID_REQUEST", "A valid broker symbol is required.")
        if timeframe not in TIMEFRAMES:
            return failure(400, "INVALID_REQUEST", "Supported timeframes: M1, M5 (aliases: 1m, 5m).")
        if len(request.args.getlist("symbol")) != 1 or len(request.args.getlist("timeframe")) != 1:
            return failure(400, "INVALID_REQUEST", "Supply symbol and timeframe exactly once.")

        if config_error is not None:
            return failure(503, config_error, "Broker session configuration is invalid; analysis withheld.")
        calendar = calendars.get(symbol)
        if calendar is None:
            return failure(503, "SESSION_CALENDAR_UNAVAILABLE",
                           "Verified broker session coverage is required; analysis withheld.")
        try:
            if getattr(calendar, 'version', 1) == 2:
                session_details = calendar.public_state(utc_now())
            snapshot = get_candle_snapshot(symbol=symbol, timeframe=timeframe,
                                      count=100, mt5=mt5, clock=utc_now,
                                      session_calendar=calendar)
            result = analyze_candles(symbol, timeframe, snapshot.candles)
        except (MarketDataError, ClockValidationError) as exc:
            return failure(503, "MARKET_DATA_UNAVAILABLE", exc.report.diagnostics[0].message, exc.report)
        except Exception:
            # Adapter failures must never yield a signal, leak provider details,
            # or fall back to synthetic prices. Do not log raw broker errors.
            app.logger.warning("Market analysis unavailable: data could not be validated")
            return failure(503, "MARKET_DATA_UNAVAILABLE",
                           "Validated closed-candle market data is unavailable; analysis withheld.")
        result.update({"timeframe": supplied_timeframe, "data_timeframe": timeframe,
                       "data_source": "MT5", "signal": "WAIT", "execution_allowed": False,
                       "quality": snapshot.quality.to_dict()})
        if session_details is not None:
            session_details['last_bar'] = calendar.classify_bar(
                datetime.fromisoformat(snapshot.candles[-1]['timestamp']), timeframe, observed_finalized=True,
                as_of=datetime.fromisoformat(session_details['evaluated_at_utc']))
            result['session_v2'] = session_details
        return jsonify(result)

    from iat.intelligence.api import register_intelligence
    register_intelligence(app, mt5=mt5, clock=utc_now, calendars=calendars,
                          config_error=config_error, intelligence_config=intelligence_config)
    from iat.context_api import register_context
    register_context(app, mt5=mt5, clock=utc_now, calendars=calendars,
                     config_error=config_error, intelligence_config=intelligence_config,
                     context_config=context_config)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
