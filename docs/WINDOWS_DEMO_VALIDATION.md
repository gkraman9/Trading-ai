# Windows read-only MT5 demo validation package

**No real terminal or broker schedule was validated in the cloud.** Python tests
use mocks. GitHub Windows CI tests Python, atomic report handling and PowerShell
preflight behavior without installing MT5 or contacting a broker. Native MQL5
compilation and real-terminal behavior remain unperformed.

This package performs scoped local checks, never independent broker certification
or strategy validation. Every outcome keeps `signal=WAIT` and
`execution_allowed=false`. No login, password, token, order or execution-enable
API is used. The Flask API remains separate and never initializes MT5.

## Prepare the existing environment

1. Review the local checkout of `feat/iat2-windows-demo`; do not merge PRs. Use an
   existing **64-bit Python 3.11 environment**. Activate it and confirm that
   `python` resolves to its executable. The runner rejects other versions and
   architectures; it does not download Python or create another environment.
2. Open the intended, already authorized **demo** MT5 terminal locally. Disable
   terminal Algo Trading and enable the terminal option disabling automated
   trading through the external Python API. Leave both disabled. The diagnostic
   checks `trade_allowed=false`, `tradeapi_disabled=true`, connectivity and demo
   account mode before any symbol/history or session-metadata requests.
3. Make the exact XAUUSD symbol visible in Market Watch. Confirm the asset is
   gold against USD; the diagnostic checks published XAU/USD currency metadata
   where available. Missing currency metadata produces WARN; conflicting asset
   metadata produces FAIL. The runtime never selects symbols or switches accounts.
4. Prepare an independently reviewed v1 session JSON file following
   [session configuration](SESSION_CONFIGURATION.md). Coverage must span the
   request and 100 closed M5 candles, including prior sessions where needed.
   Do not place any credentials, account IDs or server identifiers in it.

## Exact runner command

From the repository root, in the activated existing Python 3.11 environment:

```powershell
.\diagnostics\Run-IATDemoValidation.ps1 `
  -PythonExe (Get-Command python).Source `
  -SessionConfig 'C:\IAT\verified-session.json' `
  -ReportDirectory 'C:\IAT\evidence' `
  -InstallOptionalDependencies
$LASTEXITCODE
```

Use your actual reviewed configuration path. The install switch is optional;
when supplied, it installs requirements and `MetaTrader5` wheels from official
PyPI using isolated pip configuration, without upgrades, custom indexes, shell
bootstrap downloads or untrusted scripts. Existing installed packages are reused.
Installation errors are redacted; no raw pip logs are printed or persisted.

If several terminals are installed, explicitly select the intended trusted local
binary by adding, for example:

```powershell
-TerminalPath 'C:\Program Files\MetaTrader 5\terminal64.exe'
```

Use the actual installed binary path. Without this option, MT5's own default
binding selection applies; do not assume it selects a particular broker. The
script still rejects non-demo or unsafe terminal states before history access.
Initialization attaches/starts the local binding without login arguments. It
does not enable trading, select an account, or read stored password files.

The script does not change execution policy. If your organization blocks local
PowerShell scripts, use its normal review/signing process; do not globally bypass
policy or download a replacement runner. If a terminal or exporter requires
trading permission, stop rather than enabling it.

## Results and privacy

The runner prints a fixed status and generated filename. It discards all Python
child stdout/stderr, including possible native-library messages. It saves an
allowlisted UTF-8 JSON report with a unique UTC/UUID filename. The default folder,
when omitted, is the current user's LocalAppData\IAT\validation-evidence. Choose
an appropriately private local folder; actual ACL behavior is controlled by
Windows and the parent folder. There are no raw terminal/account dumps or log
files. See the [evidence contract](VALIDATION_EVIDENCE.md).

| Exit | Outcome | Interpretation |
| --- | --- | --- |
| 0 | PASS | All scoped checks passed, including complete matching dated metadata; still not independent certification. |
| 2 | WARN | Checks have explicit uncertainty, tolerated lag, unavailable/weekly-only session metadata, unavailable version/asset metadata, or a currently closed session. |
| 1 | FAIL | Connectivity/account/safety, configuration, data quality, metadata comparison, interruption, shutdown, preflight or report-publication failure. |

Standard Python MT5 normally lacks session schedule retrieval, so a healthy
terminal/data run without an additional supported metadata source normally
returns **WARN**, not a fabricated broker-calendar PASS. A closed market is an
expected session condition but cannot establish current candle quality; rerun
while open. Failed or unperformed checks have null counts/gap/freshness fields,
not zero gaps masquerading as success. The existing two-bar lag tolerance is
preserved and explicitly warns; it never enables execution.

## Optional broker-session collection

Follow [broker metadata collection](BROKER_SESSION_METADATA.md). A reviewed
read-only MQL5 source exporter is included; compile and run it locally only if
permitted with trading disabled. It exports weekly `SymbolInfoSessionTrade`
metadata and requires an explicitly confirmed IANA timezone. It never exports
account IDs, server names or credentials. Native compilation has not been tested
here. Its private metadata file contains the exact symbol for binding/comparison;
only the final evidence report is anonymized and intended for sharing.

Add the resulting local file to the same runner command:

```powershell
-BrokerMetadata 'C:\IAT\private-metadata\iat-sessions-generated.json'
```

Weekly metadata can compare baseline hours and breaks across DST conversion, but
cannot prove dated holidays, emergencies or exceptional closures. Those remain
WARN even when weekly hours match. Exports older than 24 hours or with a future
collection timestamp are rejected. Never infer timezone from quote offsets.

## Remaining operator validation

Compare actual terminal closed-candle UTC timestamps and a local OHLC sample
against the package's underlying MT5 rows. Raw OHLC prices are intentionally not
included in the shareable report. Verify M1/M5 availability, daily maintenance,
weekends/holidays, overnight sessions, DST, broker timestamps and minutes without
ticks. Do not fill sparse minutes with synthetic candles; preserve the failure
and investigate the broker's actual data semantics.

Keep only redacted evidence plus non-secret independently verified source notes.
The report contains package/Python versions, UTC test times, anonymous symbol
alias and timeframe summaries, freshness/gaps, session comparison and safety
checks. It deliberately omits broker identity and account details. Do not share
raw metadata or configuration files without separate review.

The standalone diagnostic shuts down its binding before publishing. It does not
initialize a separate Flask serving process. No live endpoint migration or
trading activation is performed by this package. All PRs remain draft/unmerged.

## Exness observed-schedule candidate

For the supplied XAUUSD display times, use the
[Exness-specific installation and E-drive instructions](EXNESS_LOCAL_WORKFLOW.md)
and [source reconciliation](EXNESS_SESSION_RESEARCH.md). The candidate is v1
schema-valid but explicitly blocked: the diagnostic records assurance failures
before initializing MT5. The 21:58 and Sunday 23:01 boundaries are preserved;
M5 support and second-level restricted phases are not guessed. A successful
local demo connection does not clear missing calendar evidence.
