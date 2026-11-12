# Read-only market analysis API

`GET /analyze?symbol=XAUUSD&timeframe=M1` requests 100 closed candles from
MT5 through `iat.mt5_data.get_closed_candles`, then analyzes the validated rows.
There is no synthetic-price fallback or trade execution path.

The existing `symbol`, `timeframe`, `signal`, and `reasoning` response fields are
preserved. `timeframe` echoes the supplied value; `data_timeframe` identifies the
canonical MT5 interval. Supported intervals are M1 and M5, with case-insensitive
aliases `1m` and `5m`. Symbol names are broker-specific (for example XAUUSDm).
Both parameters are required, nonempty, and must occur exactly once.

Every analysis response includes `signal: "WAIT"`, `execution_allowed: false`,
and `mode: "READ_ONLY_SHADOW"`. These values cannot be enabled through query
parameters. Successful responses additionally describe `market_state`,
`last_closed_candle` (UTC bar-open timestamp), and `data_source: "MT5"`.
Three closing prices describe short-term movement, not validated trading logic.

| Status | Meaning |
| --- | --- |
| 200 | Candle history passed validation and descriptive analysis is available. |
| 400 | Missing, ambiguous, or unsupported request parameters (`INVALID_REQUEST`). |
| 503 | Session calendar missing (`SESSION_CALENDAR_UNAVAILABLE`), or market closed, coverage invalid, MT5 unavailable/disconnected, data stale/incomplete/malformed/gapped, or analysis failed (`MARKET_DATA_UNAVAILABLE`). |

Failures include the original response fields, `market_state: "UNKNOWN"`, and
`last_closed_candle: null`; no market movement is inferred. Raw provider exception
messages are not exposed or logged. `/analyze` responses use `Cache-Control:
no-store` to prevent a cached response being mistaken for current data.

## Runtime boundary

The HTTP app never initializes MT5, authenticates, reads account credentials, or
submits orders. The default adapter requires the optional Windows MetaTrader5
package and an **already initialized binding in the serving Python process**
connected to a terminal. Opening the terminal alone is not sufficient. Without
that setup the endpoint intentionally returns 503, rather than invented data.
An independently prepared read-only host may construct the app using
`create_app(mt5=existing_adapter, session_calendars=verified_calendars)`; initialization is outside this application's
scope. No live integration was performed for this change.

Validation checks count, UTC chronology and uniqueness, timeframe-aligned epoch
seconds, finite positive OHLC ranges, closure, session coverage, missing bars,
and freshness. [Session configuration](MARKET_SESSIONS.md) requires independently
verified finite broker windows for each exact symbol. Missing calendar coverage,
closed sessions, and data gaps return 503. No default broker hours are assumed.
All trade proposals remain disabled pending independent data and trading-logic
validation.

Legacy `decision.get_signal(symbol, timeframe)` always returns WAIT.
`reasoning.explain(symbol, timeframe)` discloses missing data; optional supplied
rows are validated before generating descriptive reasoning. The HTTP route uses
one candle snapshot for both market state and reasoning.

## Offline verification

Install `requirements.txt`, then run `python -m unittest discover -s tests -v`.
Endpoint tests inject raw fake MT5 rates through the real validator and exercise
bullish/bearish/range inputs, M5 aliases, request rejection, stale/forming/bad
candles, missing/disconnected adapters, error privacy, and read-only invariants.
They do not initialize MT5 or contact a broker.
