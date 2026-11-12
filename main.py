"""HTTP interface for validated, read-only MT5 market analysis."""
from datetime import datetime, timezone

from flask import Flask, jsonify, request

from iat.analysis import analyze as analyze_candles
from iat.mt5_data import TIMEFRAMES, get_closed_candles


def create_app(*, mt5=None, clock=None, session_calendars=None):
    """Inject a read-only MT5 adapter and UTC clock for offline testing.

    The default adapter uses an already-connected terminal. This application
    never initializes a terminal, logs in, or submits orders.
    session_calendars maps exact symbols to independently verified calendars.
    """
    app = Flask(__name__)
    calendars = dict(session_calendars or {})
    utc_now = clock if clock is not None else lambda: datetime.now(timezone.utc)

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

        def failure(status, error, reason):
            return jsonify({
                "symbol": symbol, "timeframe": supplied_timeframe,
                "signal": "WAIT", "execution_allowed": False,
                "mode": "READ_ONLY_SHADOW", "data_source": "MT5",
                "market_state": "UNKNOWN", "last_closed_candle": None,
                "error": error, "reasoning": [reason],
            }), status

        if not symbol or len(symbol) > 128 or any(c.isspace() or ord(c) < 32 for c in symbol):
            return failure(400, "INVALID_REQUEST", "A valid broker symbol is required.")
        if timeframe not in TIMEFRAMES:
            return failure(400, "INVALID_REQUEST", "Supported timeframes: M1, M5 (aliases: 1m, 5m).")
        if len(request.args.getlist("symbol")) != 1 or len(request.args.getlist("timeframe")) != 1:
            return failure(400, "INVALID_REQUEST", "Supply symbol and timeframe exactly once.")

        calendar = calendars.get(symbol)
        if calendar is None:
            return failure(503, "SESSION_CALENDAR_UNAVAILABLE",
                           "Verified broker session coverage is required; analysis withheld.")
        try:
            rows = get_closed_candles(symbol=symbol, timeframe=timeframe,
                                      count=100, mt5=mt5, clock=utc_now,
                                      session_calendar=calendar)
            result = analyze_candles(symbol, timeframe, rows)
        except Exception:
            # Adapter failures must never yield a signal, leak provider details,
            # or fall back to synthetic prices. Do not log raw broker errors.
            app.logger.warning("Market analysis unavailable: data could not be validated")
            return failure(503, "MARKET_DATA_UNAVAILABLE",
                           "Validated closed-candle market data is unavailable; analysis withheld.")
        result.update({"timeframe": supplied_timeframe, "data_timeframe": timeframe,
                       "data_source": "MT5", "signal": "WAIT", "execution_allowed": False})
        return jsonify(result)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
