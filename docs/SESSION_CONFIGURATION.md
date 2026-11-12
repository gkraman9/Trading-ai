# Version 1 broker session configuration

The runtime supplies **no broker schedule**. Obtain and independently verify the
exact XAUUSD symbol's trading hours, maintenance breaks, holidays, exceptional
closures, and timezone with the broker before preparing configuration. A source
label is operator-provided metadata, not proof that a broker verified the file.
No market prices, account identifiers, or credentials belong in this file.

`config/session-calendar-v1.schema.json` describes the structural JSON schema.
`iat.session_config` is the authoritative strict runtime validator/compiler: it
also checks cross-field interval semantics, date bounds, IANA timezone validity,
DST uniqueness, and duplicate JSON keys. Unknown or missing fields, unsupported
versions, booleans in integer fields, NaN/Infinity, invalid UTF-8 and malformed JSON
are rejected. Files are limited to 1 MiB and coverage to 1–366 local civil days.

The following shape is **illustrative test configuration**, not verified trading
hours and not a supplied production default:

```json
{
  "version": 1,
  "symbol": "XAUUSD",
  "timezone": "America/New_York",
  "coverage": {"start": "2026-11-09", "end": "2026-11-16"},
  "verification": {
    "source": "ILLUSTRATIVE ONLY — replace with independently verified source",
    "verified_at": "2026-11-01T00:00:00Z"
  },
  "weekdays": {
    "mon": [{"open": "08:00", "close": "12:00", "close_day_offset": 0},
            {"open": "13:00", "close": "17:00", "close_day_offset": 0}],
    "tue": [], "wed": [], "thu": [], "fri": [], "sat": [], "sun": []
  },
  "holidays": [],
  "exceptions": {},
  "closures": []
}
```

All fields shown are required. Use an exact broker symbol, including any suffix;
no alias from XAUUSD to a broker-specific symbol is inferred. `timezone` must be
an installed IANA zone. `tzdata` is installed by requirements.txt for hosts such
as Windows without an operating-system IANA database.

- Coverage is `[start date at local midnight, end date at local midnight)`.
  Unknown dates outside coverage are never inferred open or closed.
- All seven weekday keys are required. Each contains zero to eight windows;
  empty means no session starts on that weekday. Separate windows represent
  intraday breaks. Each boundary uses strict `HH:MM` (00:00–23:59).
- `close_day_offset` must explicitly be integer 0 or 1. Zero requires close after
  open on the same date. One means next local date; close must be at or before
  open, limiting a window to one local day. Midnight-to-midnight is expressed as
  00:00 to 00:00 with offset 1. Overnight carry-in from the preceding date is
  compiled, then clipped to coverage. Overlapping open windows are rejected.
- `holidays` contains unique covered local dates. A holiday closes the entire
  civil date, including overnight sessions carried in from the previous date.
- `exceptions` maps covered ISO dates to replacement window arrays, using the
  same window schema. These replace sessions **starting** on that date, allowing
  shorter hours or exceptional weekend openings. An empty array cancels starts;
  it does not cancel a previous date's overnight carry-in. Use a holiday or
  explicit closure to close the entire civil date. A holiday and exception on
  the same date are rejected as conflicting instructions.
- `closures` contains up to 366 objects with `start` and `end` as local
  `YYYY-MM-DDTHH:MM` timestamps. These positive intervals must lie inside coverage
  and are subtracted from sessions. They support emergency, partial-day and
  multi-day closures. Overlapping closures combine as a union.
- `verification` requires a nonblank source label and timezone-aware ISO
  `verified_at` timestamp. It records provenance supplied by the operator; it
  cannot authenticate the broker or prove these hours are current.

Every relevant boundary is converted using the configured IANA zone. A local
boundary with two possible UTC instants (fall-back fold) or no UTC instant
(spring-forward gap) **rejects the entire configuration**. There is no implicit
fold choice or clock-time shifting. Sessions spanning a transition with unique
boundaries remain valid; both real fall-back hours have distinct UTC bars. If a
broker defines a boundary in a fold, this v1 format cannot represent it; obtain
unambiguous verified windows rather than guessing.

Compiled adjacent UTC windows are merged. M1/M5 analysis requires UTC session
boundaries aligned to the requested timeframe; a valid configuration with a
09:01 boundary can support M1 but fails closed for M5. No partial M5 bars are
invented. Refresh coverage before expiration; a 100-bar M5 history across a
weekend needs coverage spanning the entire history and request time.

## Loading

Set `IAT_SESSION_CONFIG` to a trusted local JSON path before creating the app, or
pass `create_app(session_config_path=path, mt5=already_initialized_adapter)`.
An explicit path takes precedence over the environment variable. The existing
`session_calendars={symbol: SessionCalendar(...)}` host interface is preserved;
combining it with a file/environment source is rejected rather than merged.
One file configures one exact symbol. There is no HTTP configuration-upload path.

The file is read once per app creation. Changes require application recreation
or restart; there is no automatic reload or fallback to earlier configuration.
An absent path leaves analysis unavailable. A configured missing/invalid file
returns 503 with a configuration reason code without contacting MT5. Health
checks remain available. Raw file contents and filesystem paths are not returned.

Neither this loader nor the HTTP app initializes MT5, authenticates, reads broker
credentials, or enables trading. The runtime still requires an initialized MT5
binding in the serving process, not merely an open terminal on the same machine.
