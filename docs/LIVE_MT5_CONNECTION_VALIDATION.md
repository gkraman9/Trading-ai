# Connection validation and Windows procedure

Parent PR50:5c9b965fe9fa3c6b50122f566620605d18e6aaae.
Cloud validation is synthetic only; no actual terminal was attached.

## Automated evidence

The initial42 deterministic lifecycle/probe cases passed locally on Python3.11.9 (1.898s)
and3.12.14 (1.739s). A43rd case then verifies sanitized native-shutdown failure reporting; the draft PR records final focused/full results. They cover initialization False/exception, unavailable module/
API capabilities, missing/disconnected terminal, IPC loss during acquisition,
startup/restart recovery, capped backoff, interruptible retry shutdown, native-call
ownership/overdue handling, repeated start/stop, no overlap, new demo/permission/
symbol failures after reattachment, stale/missing quotes, incomplete M5, unchanged
GAP_UNVERIFIED, cache invalidation, HTTP isolation and sanitized diagnostics.
Probe tests cover inspect-only with no SDK load, same-owner attachment, redaction
and failed initialization. Existing AI tests now mock MT5Connection, the new runner
boundary; their provider/opt-in assertions are unchanged.

The inherited live group first exposed two obsolete mock targets (ReadOnlyMarketData
in the runner). They were changed to the new dependency; production compatibility
was not restored by retaining an unused unsafe initialization path. No existing
assertion was weakened. See the draft PR's final results for full-suite counts and
four-environment CI; do not interpret these initial focused results as completed CI.

CI runs Linux/Windows ×Python3.11.9/3.12, the unchanged actual PowerShell5.1 startup
regression, and a new PowerShell5.1 comparison ValidateOnly check. That comparison
loads no SDK, attaches to no terminal and starts no journal, network or service.
The new branch uses PR-triggered CI; existing branches' push checks are preserved.

## First local operator command only

After checking out this draft branch, open PowerShell in its project root. Keep
Algo Trading and the external Python trading API disabled. First run only:

```powershell
powershell.exe -NoProfile -File .\diagnostics\Test-IATMT5Connection.ps1 -ValidateOnly
```

This compares the selected Python environments without importing/initializing MT5.
Default selections resolve py-3.11's exact executable for both roles. Optional
RunnerPythonExe and IndependentPythonExe select different actual local executables;
paths are resolved privately and never included in JSON. No packages are installed
and no script is downloaded. Share only the generated redacted JSON for review.

The same diagnostic without ValidateOnly performs two sequential read-only local
attachments, not a dashboard/service launch. Do not perform that next step until
the environment-only result has been inspected; provide one operator command at
a time. A running demo terminal with both trading permissions disabled is required.
The SDK may launch its locally installed terminal when attaching; it never receives
credentials or an account-selection request from this code. The explicit dashboard
TerminalPath option is available for later controlled terminal selection, not a
calendar or account approval.

## Interpreting the comparison

same_executable_path compares resolved local paths without publishing them.
same_python_binary compares executable SHA256; same_mt5_package compares module
version labels; same_mt5_module_binary compares module bytes when available.
same_terminal_attachment is null in ValidateOnly and when an attachment path cannot
be read. For actual attachments, comparison uses one per-run secret nonce and
keyed tokens that PowerShell removes. No persistent machine/terminal identifier,
account number or server identifier is emitted. A null value means unknown.

The probe does not fetch candles; acquisition is explicitly NOT_RUN. Successful
attachment is not historical qualification. Neither comparison can prove which
interpreter or terminal an earlier process actually used without operator evidence.
If Python/SDK versions differ, select the actual dashboard and independent-diagnostic
executables. If attachment differs or remains unknown, inspect terminal selection
privately. Initialization/IPC failure codes help separate attachment failure from
healthy connectivity with missing data. Do not upload raw console traces or paths.

## Required real Windows follow-up

After environment comparison, compare prospective attachments. Then, in a separate
controlled observer run, collect a private fresh journal and examine initialization,
generation, safety and acquisition diagnostics before/after a manually observed
terminal disconnection/restart. Do not change permissions, accounts or calendar
approval to make a test pass. Do not start B.2/B.3 or parallel dashboards. Any newly
visible GAP_UNVERIFIED is a separate unresolved session-evidence issue.

Actual operator/runtime diagnosis, native-call behavior and long-run recovery remain
UNVERIFIED. A subprocess transport for hard native cancellation is deferred. No
claim of a permanently resolved Windows root cause, broker certification, historical
validation, paper activation or trading readiness is made by cloud tests.

## Redaction correction verification

An unchanged inherited privacy assertion caught one failure in the initial full
Python3.12 run (2,052 tests). Typed transport messages must be treated as untrusted,
even when their error code is recognizable. The final boundary retains only a
small allowlist of lifecycle codes, reconstructs fixed diagnostic text and maps
other codes to PROVIDER_FAILURE. The inherited assertion was not weakened.
After correction, all25 quality tests pass and44 lifecycle/probe tests pass on
Python3.11.9 (6.120s) and3.12.14 (5.590s). Earlier in-flight local runs were stopped
as superseded, and complete suites were restarted on the corrected tree. Consult
the draft PR for the final full-suite/CI evidence, not the superseded run.
