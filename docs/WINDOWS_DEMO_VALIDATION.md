# Remaining Windows MT5 demo validation

This procedure remains **unperformed against a real terminal**. Offline tests
mock the diagnostic lifecycle; they do not prove broker connectivity, actual
session hours, OHLC accuracy or a strategy edge. Do not supply credentials in
chat, configuration, environment variables, commits or captured output.

1. On an operator-controlled Windows host, use Python 3.11 or 3.12 and create a
   virtual environment. Install `requirements.txt` (includes Windows IANA tzdata)
   and the optional official `MetaTrader5` Python package locally. The optional
   package is never installed or initialized by CI or the Flask application.
2. Keep automated trading disabled. Prepare an already authorized **demo** terminal
   locally. Do not use a real-money account. Obtain broker confirmation for the
   exact XAUUSD symbol/suffix, timezone/DST conventions, hours, breaks, holidays
   and exceptional closures. Record that non-secret provenance in a reviewed v1
   session file with coverage spanning at least 100 M5 bars through the test time.
3. In PowerShell, set the path and run the existing local diagnostic:

   ```powershell
   $env:IAT_SESSION_CONFIG = 'C:\iat\verified-session.json'
   python diagnostics/mt5_readonly_check.py
   ```

   The script loads the configuration, initializes only the local MT5 binding,
   verifies demo account mode, requests closed M1/M5 data for the configured
   symbol, prints quality diagnostics and read-only results, then shuts down the
   binding. It never calls login or submits orders and does not print account
   identifiers. A missing/invalid config stops before terminal initialization.
   Do not run it here without an independently authorized, prepared demo host.
4. Compare reported closed-candle UTC open times and OHLC against the actual
   terminal, including broker-specific symbol names. The current diagnostic
   reports summaries; independently inspect a redacted local candle sample for
   OHLC comparison. Confirm session boundaries, daily breaks, weekends/holidays,
   expected missing-bar handling, and M1/M5 freshness. Document broker behavior
   during minutes without ticks instead of inserting synthetic candles.
5. For HTTP integration, the MT5 binding must be initialized in the **same serving
   process** using a reviewed read-only host bootstrap. The standalone diagnostic
   shuts down its own binding and does not initialize a separate Flask process.
   Create the app with the verified config path and that prepared adapter. Test
   `/analyze?symbol=<exact-symbol>&timeframe=M1` and M5 locally. Confirm valid
   descriptive movement, structured quality, WAIT and execution_allowed=false;
   disconnected, stale, out-of-session and malformed data must return 503.
6. Retain only redacted non-secret evidence: commit, Python/MT5/tzdata versions,
   verification source/date, UTC test times, symbol, OHLC/time comparisons and
   quality reason codes. Avoid account numbers, personal details and broker
   error dumps. Stop on unexpected discrepancies; do not enable execution.

A genuine pass requires testing the actual terminal and independently verified
broker configuration. Neither a green CI run nor a valid JSON file establishes
that evidence. All existing draft PRs remain unmerged.
