"""Local Windows MT5 read-only diagnostic; never sends orders.

Run from repository root: python diagnostics/mt5_readonly_check.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iat.analysis import analyze
from iat.mt5_data import MarketDataError, get_candle_snapshot
from iat.session_config import SessionConfigError, load_session_config


def main() -> int:
    path = os.environ.get("IAT_SESSION_CONFIG")
    if not path:
        print("ERROR: IAT_SESSION_CONFIG must identify a verified broker calendar.")
        return 2
    try:
        calendar = load_session_config(path)
    except SessionConfigError as exc:
        print("ERROR:", exc.code)
        return 2
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("ERROR: Install MetaTrader5 in the active Python environment.")
        return 2

    if not mt5.initialize():
        print("ERROR: Could not initialize the local MT5 terminal.")
        return 2

    try:
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        if terminal is None or not terminal.connected or account is None:
            print("ERROR: Terminal or account is not connected.")
            return 2

        # Do not print account numbers, broker credentials or personal details.
        if not account.trade_mode == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", -1):
            print("ERROR: This diagnostic requires an MT5 DEMO account.")
            return 2

        symbol = calendar.symbol
        info = mt5.symbol_info(symbol)
        if info is None or not info.visible:
            print("ERROR: Configured symbol must be visible in Market Watch.")
            return 2

        results = {}
        for timeframe in ("M1", "M5"):
            snapshot = get_candle_snapshot(symbol=symbol, timeframe=timeframe, count=100,
                                           mt5=mt5, session_calendar=calendar)
            rows = snapshot.candles
            decision = analyze(symbol, timeframe, rows)
            if decision["signal"] != "WAIT" or decision["execution_allowed"] is not False:
                raise RuntimeError("Safety invariant violated")
            results[timeframe] = {
                "count": len(rows),
                "last_closed_bar_open_utc": rows[-1]["timestamp"],
                "market_state": decision["market_state"],
                "signal": decision["signal"],
                "execution_allowed": decision["execution_allowed"],
                "quality": snapshot.quality.to_dict(),
            }
        print(json.dumps({"status": "PASS", "mode": "READ_ONLY_SHADOW",
                          "symbol": symbol, "timeframes": results}, indent=2))
        return 0
    except MarketDataError as exc:
        print(json.dumps({"status": "FAIL", "quality": exc.report.to_dict()}))
        return 1
    except RuntimeError:
        print("ERROR: Read-only safety check failed")
        return 1
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
