# Gemini research provider for IAT v3

Base: PR #35, exact commit `b265fa3f3a0b0f28952000c461c5d368a2e54578`.
Gemini is an optional evidence selector. It cannot write new market facts, change
scores/strategies, change qualification, authorize a direction or execute trades.
The OpenAI adapter and original v1/v2/v3 report contracts remain unchanged.

## Compatibility and qualification of results

The operator reports successful Windows Python 3.11 authentication, SDK generation,
provider initialization and simplified JSON generation using **google-genai 3.6.1**
and **gemini-3.5-flash-lite**. These are operator-reported checks, not Cloud terminal
or complete live IAT validation. The original expanded v3 schema reportedly
returned HTTP 400: “schema produces too many states for serving”.

This provider uses that SDK version, pinned in `requirements-gemini.txt`. Its serving
schema contains only a version, bundle ID, section names and fact-ID lists. It has
no repeated level objects, nullable unions, dynamic enumerations or nested full
claim records. This reduces schema state complexity. **The remote service's
acceptance of the complete real IAT packet is still a local validation**, not
proved by mocked tests. No paid Gemini request is made by automated tests.

## Windows 10 / Python 3.11 update

Stop the current server with Ctrl+C. Run commands separately, top to bottom.
Preserve any local edits shown by `git status`; no reset/force checkout is needed.

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
git status --short
git fetch origin refs/heads/feat/iat-v3-gemini-provider
$branch = 'local/iat-v3-gemini-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
git switch --no-track -c $branch FETCH_HEAD
git rev-parse HEAD
py -3.11 -m pip install -r requirements.txt MetaTrader5
py -3.11 -m pip install -r requirements-gemini.txt
```

Compare the SHA with the delivered PR head. The no-tracking branch switch handles
the operator's single-branch clone and never overwrites an existing local branch.
Normal deterministic runtime does not require the Gemini SDK. Development/CI
requirements install both optional SDKs for offline regression testing.

Keep the already authorized **demo** terminal connected, exact **XAUUSD** visible,
**Algo Trading OFF** and **external Python API trading disabled**. No broker
credentials are requested. Without AI:

```powershell
$logs = Join-Path 'E:\IAT2\IAT2-LiveLogs' ([Guid]::NewGuid().ToString('N'))
py -3.11 .\diagnostics\run_live_intelligence.py --log-directory $logs --interval 10 --port 8765
```

Open `http://127.0.0.1:8765/`. Status is DISABLED even if a key exists. Neither
provider is configured unless `--enable-llm` is present. Dashboard networking,
loopback protections, chart, deterministic commentary and evidence panels are
unchanged. Historical CSV intake is not a prerequisite; existing session and
quality blockers remain in force.

## Explicit Gemini enablement

Stop the old server with Ctrl+C. Never put a key in source, Git, command arguments,
a chat message, screenshots or an evidence report. Set it only in this PowerShell
process, with masked input:

```powershell
$geminiSecure = Read-Host 'Gemini API key' -AsSecureString
$env:IAT_GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', $geminiSecure).Password
$logs = Join-Path 'E:\IAT2\IAT2-LiveLogs' ([Guid]::NewGuid().ToString('N'))
try {
    py -3.11 .\diagnostics\run_live_intelligence.py --log-directory $logs --interval 10 --port 8765 --enable-llm --llm-provider gemini --llm-model gemini-3.5-flash-lite --llm-min-seconds 60
} finally {
    $env:IAT_GEMINI_API_KEY = $null
    Remove-Variable geminiSecure -ErrorAction SilentlyContinue
}
```

Gemini's default short model ID is `gemini-3.5-flash-lite` when `--llm-model` is
omitted. Other short `gemini-*` model IDs can be selected if available to your
account and compatible with structured streaming output. Availability/quota is
not assumed. URL/path model strings are rejected. Do not prefix `models/`.

The runner reads **only `IAT_GEMINI_API_KEY`** for Gemini, not GOOGLE_API_KEY,
GEMINI_API_KEY, OpenAI credentials or IAT_REASONING_MODEL. The SDK receives the
explicit validated key, Developer API mode and fixed API origin. Other SDK
environment variables cannot select Vertex/Enterprise mode or change the origin.

OpenAI remains backward compatible: omit `--llm-provider`, or select
`--llm-provider openai`, with the existing IAT_OPENAI_API_KEY/IAT_REASONING_MODEL
configuration and optional `requirements-ai.txt`. Providers do not silently fail
over to one another. Missing/invalid Gemini configuration uses deterministic
fallback and never creates an OpenAI request.

In a second PowerShell window, inspect metadata only:

```powershell
$r = Invoke-RestMethod 'http://127.0.0.1:8765/live/v3/snapshot'
$r.commentary | Select-Object status,source,provider,model,validation,request_at_utc,response_at_utc,cached,reason_codes,latency_ms
$r.commentary.evidence_cutoffs
$r.commentary.usage
$r.ai_evidence | Select-Object bundle_id,policy,scope,fact_count
$r | Select-Object signal,execution_allowed,orders_requested,exness,qualification,historical_validation,historical_comparisons
```

ACTIVE must have provider **Google Gemini**, the configured model, successful
validation, matching evidence bundle/cutoffs and request/response UTC. A key,
REQUESTING, CONFIGURED, cached unrelated output or a standalone text-generation
test is not proof of a valid current IAT response. Use the evidence inspector to
confirm original canonical IDs. Requests completing after material changes are
rejected by the existing runtime. Feed disconnect/staleness removes the current
interpretation. Resolve session/quality evidence separately; never bypass it.

Disable Gemini by Ctrl+C (the `finally` block clears the key), then restart with a
fresh `$logs` directory and omit `--enable-llm`. Verify DISABLED. Neither provider
can change MT5 permissions; keep both trading permissions disabled throughout.

## Optional one-request API smoke test

This standalone command sends **clearly labeled synthetic contract facts**, no
candles, prices, broker/terminal information or private logs. It does not connect
to MT5. It is not a historical test or a live chart-validation result.

With no opt-in, it is offline and does not read a key:

```powershell
py -3.11 .\diagnostics\check_gemini_provider.py
```

To authorize one potentially billable real request:

```powershell
$geminiSecure = Read-Host 'Gemini API key' -AsSecureString
$env:IAT_GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', $geminiSecure).Password
try {
    py -3.11 .\diagnostics\check_gemini_provider.py --enable-llm --model gemini-3.5-flash-lite
} finally {
    $env:IAT_GEMINI_API_KEY = $null
    Remove-Variable geminiSecure -ErrorAction SilentlyContinue
}
```

Exit 0 / PASS_SYNTHETIC_PROVIDER_SMOKE means the remote compact response passed
strict reconstruction and v3 evidence validation on that synthetic packet. Exit 1
means a sanitized failure. A smoke PASS does not establish that the full real
catalog, session assurance, MT5, historical exports or profitability are validated.
The command makes no automatic retries or continuation requests. Re-running it
explicitly authorizes another request.

## Evidence and security boundary

The only outgoing fields are the existing whitelist: commentary_version, symbol,
bundle_id, cutoffs, cards, required_fact_ids, changes, limitations and scope. No raw
ticks, complete snapshot, source registry, private journal, account/server field or
unrelated data is projected. The provider has no terminal object or order imports.

Response shape:

```json
{"version":3,"bundle_id":"EXACT_CURRENT_BUNDLE_ID","sections":[{"section":"summary","fact_ids":["EXISTING_CATALOG_FACT_ID"]}]}
```

This snippet is intentionally incomplete. Real responses must include exactly
nine sections **in order**: summary, structure, price_action, levels, bullish,
bearish, conflicts, wait, next. Fact IDs are original full catalog IDs; they are
not silently replaced with window-relative aliases. Fact order within a section
may change. Missing, reordered, duplicate or unknown sections, malformed JSON,
duplicate JSON keys, extra fields, wrong version/bundle, unknown/duplicate IDs,
wrong-section facts and missing mandatory facts are rejected, never repaired.

Each selected ID resolves exclusively to local trusted fields: fact_id,
evidence_ids, timeframe, event_type, level and direction. The provider then calls
the existing `live_ai_evidence.validate()` unchanged. This verifies mandatory
opposition/uncertainty/WAIT and reconstructs text from the catalog, preserving
canonical evidence IDs, prices and event/timeframe facts. No model-supplied prose,
new price, probability, indicator, trade instruction or changed operational status
is accepted. No schema complexity is “fixed” by weakening that gate.

Google SDK automatic function calling and **automatic continuation are explicitly
disabled**; continuation otherwise defaults to true and can issue additional billed
requests. No tools are supplied. Retry attempts are one total, including for an
injected SDK client via per-request options. Each request has a 30-second timeout
in milliseconds, a streamed wall-budget check, 96 KiB input limit, 64 KiB selected
JSON text limit, 256 KiB cumulative decoded chunk limit and 8192-token output cap.
Truncation, CONTINUATION, refusal/safety finish reasons or non-text tool output
fail closed. Private thought text and opaque thought signatures are not displayed
or journaled. The decoded limit applies after SDK chunk parsing, not a claim about
absolute transport-buffer memory. HTTP read timeout also bounds stalled chunks.

Developer API HTTPS origin and v1beta are fixed; normal TLS stays enabled.
Environment proxy use and redirects are disabled. `store=false` is requested;
provider retention/terms still depend on Google's service/account policies.
Raw SDK errors, bodies, headers, keys, prompts and private reasoning are not logged.
Errors map to static IAT codes. Existing request telemetry and private hash-chained
journals capture validation, source IDs/cutoffs, model/provider, times, latency,
cache state and token counts when returned. Existing stale-result, disconnected
feed, audit-failure, deduplication, single-inflight and cooldown protections remain.

## Quotas, costs, failure recovery and limits

Default live interval is 60 seconds between provider requests (30..3600 allowed),
so at most 60 starts/hour per running process at the default interval while new
evidence arrives. Background observation continues when the browser is closed.
Unchanged successful/failed evidence is cached in the existing bounded 64-bundle
LRU. Manual smoke calls are separate explicit requests. Stop the server or omit
--enable-llm to stop network usage. Input/output token accounting and billable
pricing vary by model/account; no dollar estimate or free-tier availability is
invented. Review https://ai.google.dev/gemini-api/docs/rate-limits and
https://ai.google.dev/gemini-api/docs/pricing before extended use.

- LLM_KEY_UNAVAILABLE: set the process-only IAT variable using masked input.
- LLM_OPTIONAL_SDK_MISSING: install requirements-gemini.txt with `py -3.11`.
- LLM_MODEL_REQUIRED / LLM_CONFIGURATION_INVALID: use a short model ID, check the
  selected interpreter and reinstall the pinned optional SDK if needed.
- AI_PROVIDER_HTTP_ERROR: covers authentication, HTTP 400/404 and server errors.
  Confirm account/model access; a 400 may still mean remote schema compatibility.
  Do not loosen validation or paste raw request/error bodies containing secrets.
- AI_PROVIDER_RATE_LIMITED: wait for quota/cooldown; unchanged failed input is not
  retried repeatedly. Check account quota and avoid multiple running instances.
- AI_PROVIDER_TIMEOUT / AI_PROVIDER_ERROR: inspect network/account service status
  locally; the deterministic observer continues. There is no automatic retry.
- AI_RESPONSE_INCOMPLETE / REJECTED / EVIDENCE_VALIDATION_FAILED: unsupported,
  truncated or invalid selections were withheld. Preserve sanitized metadata.
- AI_RESPONSE_STALE_EVIDENCE: a material update superseded the request. Wait for a
  new permitted request; never display the old result as current.
- AI_AUDIT_WRITE_FAILED: use a new private log directory and check local disk
  space/permissions. Do not bypass auditing or overwrite existing journals.

Raw logs stay outside Git under E:\IAT2\IAT2-LiveLogs. They are append-only and
not automatically rotated/deleted; monitor disk use. Keep reports private.

All modes retain READ_ONLY_SHADOW, WAIT, execution_allowed=false,
orders_requested=0, Exness BLOCKED, DATA_NOT_QUALIFIED, historical PENDING,
comparisons NOT_RUN and profitability_tested=false. No PR merges, execution
adapter, account-permission changes or historical-data gate changes are included.

Official references reviewed November 20, 2026:
https://googleapis.github.io/python-genai/genai.html,
https://github.com/googleapis/python-genai,
https://ai.google.dev/gemini-api/docs/structured-output.
