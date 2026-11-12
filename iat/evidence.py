"""Redacted evidence vocabulary and atomic, non-overwriting run publication."""
import json
import os
import tempfile
from pathlib import Path
from iat.calendar_assurance import ASSURANCE_MESSAGES
from iat.session_v2 import V2_MESSAGES

# All explanations are fixed vocabulary. Never copy exception text or arbitrary
# strings from terminal/account/symbol/bridge records into evidence.
MESSAGES = {
    'RUN_INCOMPLETE': ('ERROR', 'This run has not published a completed validation result.'),
    'CONFIG_INVALID': ('ERROR', 'Session configuration is missing or invalid.'),
    'CLOCK_UNAVAILABLE': ('ERROR', 'A trustworthy UTC clock is unavailable.'),
    'CLOCK_MOVED_BACKWARD': ('ERROR', 'UTC clock moved backwards.'),
    'MT5_UNAVAILABLE': ('ERROR', 'The optional MT5 package is unavailable.'),
    'VERSION_UNAVAILABLE': ('WARNING', 'An installed package version could not be established.'),
    'INITIALIZATION_FAILED': ('ERROR', 'The local terminal binding could not initialize.'),
    'TERMINAL_DISCONNECTED': ('ERROR', 'The local terminal is disconnected.'),
    'DEMO_ACCOUNT_REQUIRED': ('ERROR', 'A confirmed demo account is required.'),
    'AUTOTRADING_NOT_DISABLED': ('ERROR', 'Terminal algorithmic trading must be disabled.'),
    'EXTERNAL_API_NOT_DISABLED': ('ERROR', 'External Python trading must be disabled in the terminal.'),
    'SYMBOL_NOT_VISIBLE': ('ERROR', 'The configured symbol is missing or not visible.'),
    'SYMBOL_ASSET_MISMATCH': ('ERROR', 'Published asset metadata does not identify XAU against USD.'),
    'SYMBOL_ASSET_UNVERIFIED': ('WARNING', 'Asset currency metadata is unavailable.'),
    'SYMBOL_METADATA_INVALID': ('ERROR', 'Published non-secret symbol metadata is malformed.'),
    'BROKER_SESSIONS_UNAVAILABLE': ('WARNING', 'The provider has no supported broker-session metadata interface.'),
    'BROKER_METADATA_STALE': ('ERROR', 'Broker metadata is older than 24 hours or has a future collection time.'),
    'BROKER_METADATA_INVALID': ('ERROR', 'Broker-session metadata is malformed, ambiguous or incomplete.'),
    'BROKER_SESSION_MISMATCH': ('ERROR', 'Broker-published session intervals differ from configured intervals.'),
    'BROKER_SESSIONS_MATCH': ('INFO', 'Dated broker metadata matches the configured coverage.'),
    'BROKER_WEEKLY_MATCH': ('INFO', 'Published weekly baseline hours match within common UTC coverage.'),
    'BROKER_EXCEPTIONS_UNVERIFIED': ('WARNING', 'Weekly metadata cannot establish dated holidays or exceptional closures.'),
    'PROVIDER_UNAVAILABLE': ('ERROR', 'MT5 market data is unavailable.'),
    'PROVIDER_DISCONNECTED': ('ERROR', 'The data provider disconnected.'),
    'PROVIDER_FAILURE': ('ERROR', 'A provider request failed.'),
    'HISTORY_INCOMPLETE': ('ERROR', 'The requested closed-candle history is incomplete.'),
    'HISTORY_MALFORMED': ('ERROR', 'The provider history container is malformed.'),
    'TIMESTAMP_MALFORMED': ('ERROR', 'A candle timestamp is malformed.'),
    'TIMESTAMP_DUPLICATE': ('ERROR', 'Candle timestamps contain duplicates.'),
    'TIMESTAMP_OUT_OF_ORDER': ('ERROR', 'Candle timestamps are out of order.'),
    'TIMEFRAME_MISALIGNED': ('ERROR', 'A candle open is not aligned with its timeframe.'),
    'BAR_UNCLOSED': ('ERROR', 'An unclosed or future bar was returned.'),
    'BAR_OUTSIDE_SESSION': ('ERROR', 'A candle lies outside a verified session.'),
    'OHLC_MALFORMED': ('ERROR', 'Candle OHLC integrity failed.'),
    'CANDLES_MISSING': ('ERROR', 'Expected in-session candles are missing.'),
    'GAP_UNVERIFIED': ('ERROR', 'A history gap has no verified session explanation.'),
    'DATA_STALE': ('ERROR', 'The latest closed candle is stale.'),
    'SESSION_COVERAGE_UNKNOWN': ('ERROR', 'Session coverage does not establish this history and request time.'),
    'SESSION_ALIGNMENT_INVALID': ('ERROR', 'Session boundaries do not support the requested timeframe.'),
    'SESSION_INVALID': ('ERROR', 'Session validation failed.'),
    'SESSION_CLOSED': ('WARNING', 'The verified session is closed; data validation cannot complete now.'),
    'SESSION_CLOSURE_SKIPPED': ('INFO', 'History gaps correspond to configured closures.'),
    'RECENT_BARS_MISSING': ('WARNING', 'Recent bars are missing within the existing freshness tolerance.'),
    'DATA_VALID': ('INFO', 'Closed-candle data passed the configured checks.'),
    'QUALITY_UNESTABLISHED': ('ERROR', 'Data quality could not be established.'),
    'SHUTDOWN_FAILED': ('ERROR', 'The terminal binding did not confirm clean shutdown.'),
    'INTERRUPTED': ('ERROR', 'Validation was interrupted.'),
    'VALIDATION_FAILED': ('ERROR', 'An unexpected validation error occurred.'),
    'CHECKS_PASSED': ('INFO', 'The scoped read-only checks completed; this is not independent broker certification.'),
}


MESSAGES.update({code: ("ERROR", message) for code, message in ASSURANCE_MESSAGES.items()})
MESSAGES.update({code: ("ERROR", message) for code, message in V2_MESSAGES.items()})
MESSAGES["RESEARCH_LIMIT_EXCEEDED"]=("ERROR","The bounded research comparison limit was exceeded; missing counts remain unknown.")
MESSAGES.update({"OBSERVATIONS_UNAVAILABLE": ("WARNING", "No observed candle timestamps were supplied."),
                 "FILE_OBSERVATIONS_UNVERIFIED": ("WARNING", "Observation file provenance is not independently verified."),
                 "SYNTHETIC_EVIDENCE": ("WARNING", "Inputs are explicitly synthetic offline test evidence."),
                 "OBSERVATIONS_MALFORMED": ("ERROR", "Observation records are malformed."),
                 "MISSING_PARTIAL_SESSION_BAR": ("WARNING", "Expected partial-interval observation is absent; no finality is inferred.")})
MESSAGES["BROKER_PHASE_METADATA_UNVERIFIED"] = ("WARNING", "Available broker metadata does not independently establish v2 phases and quote coverage.")

def diagnostic(code):
    if code not in MESSAGES:
        code = 'QUALITY_UNESTABLISHED'
    severity, explanation = MESSAGES[code]
    return {'code': code, 'severity': severity, 'explanation': explanation}


def outcome(codes):
    levels = [MESSAGES.get(code, MESSAGES['QUALITY_UNESTABLISHED'])[0] for code in codes]
    return 'FAIL' if 'ERROR' in levels else 'WARN' if 'WARNING' in levels else 'PASS'


class AtomicEvidence:
    """Reserve a new run path with FAIL, then atomically replace after shutdown.

    Existing reports are never overwritten. A crash or failed final publication
    leaves the reserved RUN_INCOMPLETE failure, never an earlier success result.
    """
    def __init__(self, path, initial, *, validator=None):
        self.validator = validate_report if validator is None else validator
        self.validator(initial)
        self.path = Path(path)
        self.run_id = initial['run_id']
        if initial['status'] != 'FAIL':
            raise ValueError('Initial evidence must fail closed')
        encoded = json.dumps(initial, allow_nan=False, indent=2).encode('utf-8') + b'\n'
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

    def publish(self, report):
        self.validator(report)
        if report['run_id'] != self.run_id or report['status'] not in ('PASS', 'WARN', 'FAIL', 'BLOCKED'):
            raise ValueError('Invalid evidence publication')
        if report['safety']['execution_allowed'] is not False or report['safety']['signal'] != 'WAIT':
            raise ValueError('Unsafe evidence publication')
        encoded = json.dumps(report, allow_nan=False, indent=2).encode('utf-8') + b'\n'
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.iat-evidence-', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


def validate_report(report):
    """Reject schema drift or arbitrary strings before any report is serialized."""
    import math
    import re
    from datetime import datetime
    from uuid import UUID

    def keys(value, names):
        if not isinstance(value, dict) or set(value) != set(names.split()):
            raise ValueError('Invalid redacted evidence schema')

    def boolean(value):
        if value is not None and type(value) is not bool:
            raise ValueError('Invalid boolean evidence')

    def number(value, integer=False):
        if value is not None and (type(value) not in ((int,) if integer else (int, float))
                                  or not math.isfinite(value) or value < 0):
            raise ValueError('Invalid numeric evidence')

    def timestamp(value):
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T[0-9:.]+\+00:00', value):
                raise ValueError('Invalid UTC evidence timestamp')
            datetime.fromisoformat(value)

    def codes(values):
        if not isinstance(values, list) or any(value not in MESSAGES for value in values):
            raise ValueError('Unrecognized evidence code')

    if 'session_v2' in report:
        validate_session_summary(report['session_v2'])
    keys({k:v for k,v in report.items() if k != 'session_v2'}, 'report_version run_id started_at_utc finished_at_utc status diagnostics runtime symbol terminal calendar timeframes safety')
    if type(report['report_version']) is not int or report['report_version'] != 1:
        raise ValueError('Unsupported evidence version')
    if str(UUID(report['run_id'])) != report['run_id']:
        raise ValueError('Invalid evidence run ID')
    timestamp(report['started_at_utc'])
    timestamp(report['finished_at_utc'])
    if not isinstance(report['diagnostics'], list) or not report['diagnostics']:
        raise ValueError('Missing evidence diagnostics')
    for value in report['diagnostics']:
        if not isinstance(value, dict) or value != diagnostic(value.get('code')):
            raise ValueError('Unrecognized evidence explanation')
    if report['status'] != outcome([value['code'] for value in report['diagnostics']]):
        raise ValueError('Misleading evidence outcome')
    keys(report['runtime'], 'python mt5_package')
    for value in report['runtime'].values():
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r'\d{1,5}(?:\.\d{1,5}){1,3}', value)):
            raise ValueError('Invalid redacted version')
    keys(report['symbol'], 'alias requested_asset visible asset_metadata_match digits')
    if report['symbol']['alias'] != 'SYMBOL_1' or report['symbol']['requested_asset'] != 'XAUUSD':
        raise ValueError('Unredacted symbol')
    boolean(report['symbol']['visible'])
    boolean(report['symbol']['asset_metadata_match'])
    number(report['symbol']['digits'], True)
    keys(report['terminal'], 'connected demo_account algo_trading_disabled external_api_trading_disabled')
    for value in report['terminal'].values():
        boolean(value)
    keys(report['calendar'], 'scope comparison configured_window_count broker_window_count configured_exception_rules metadata_age_seconds mismatch_intervals dated_exceptions_covered codes')
    calendar = report['calendar']
    if calendar['scope'] not in ('UNAVAILABLE', 'DATED', 'WEEKLY', 'PHASES_V2') or calendar['comparison'] not in ('NOT_RUN', 'UNAVAILABLE', 'INVALID', 'MISMATCH', 'MATCH', 'UNCERTAIN'):
        raise ValueError('Invalid calendar evidence')
    for name in ('configured_window_count', 'broker_window_count', 'configured_exception_rules', 'mismatch_intervals'):
        number(calendar[name], True)
    number(calendar['metadata_age_seconds'])
    boolean(calendar['dated_exceptions_covered'])
    codes(calendar['codes'])
    keys(report['timeframes'], 'M1 M5')
    for entry in report['timeframes'].values():
        keys(entry, 'status requested_count validated_closed_count last_open_utc last_close_utc age_seconds missing_recent_bars unexpected_gap_count scheduled_gap_count codes')
        if entry['status'] not in ('PASS', 'WARN', 'FAIL') or entry['requested_count'] != 100:
            raise ValueError('Invalid timeframe evidence')
        for name in ('validated_closed_count', 'missing_recent_bars', 'unexpected_gap_count', 'scheduled_gap_count'):
            number(entry[name], True)
        number(entry['age_seconds'])
        timestamp(entry['last_open_utc'])
        timestamp(entry['last_close_utc'])
        codes(entry['codes'])
    keys(report['safety'], 'signal execution_allowed orders_requested credentials_requested login_called binding_initialization_attempted binding_initialized shutdown_completed independent_broker_certification')
    safety = report['safety']
    if safety['signal'] != 'WAIT' or any(safety[name] is not False for name in ('execution_allowed', 'credentials_requested', 'login_called', 'independent_broker_certification')) or type(safety['orders_requested']) is not int or safety['orders_requested'] != 0:
        raise ValueError('Unsafe evidence')
    for name in ('binding_initialization_attempted', 'binding_initialized', 'shutdown_completed'):
        boolean(safety[name])
    if report['status'] == 'PASS' and (safety['shutdown_completed'] is not True or
            safety['binding_initialized'] is not True or
            not all(value is True for value in report['terminal'].values()) or
            report['runtime']['mt5_package'] is None or
            report['finished_at_utc'] is None or
            report['calendar']['comparison'] != 'MATCH' or
            any(entry['validated_closed_count'] != 100 or entry['status'] != 'PASS'
                for entry in report['timeframes'].values())):
        raise ValueError('Incomplete checks cannot establish PASS')


def validate_session_summary(value):
    """Strict allowlist for additive v2 diagnostic state; no provenance refs."""
    from datetime import datetime
    from iat.session_v2 import STATES
    fields = {'version','configuration_sha256','provenance_count','evaluated_at_utc','coverage_start_utc','coverage_end_utc','expires_at_utc','verification','reason_codes','provenance_kinds','permissions'}
    if not isinstance(value, dict) or set(value) != fields or value['version'] != 2:
        raise ValueError('Invalid v2 diagnostic schema')
    import re
    if not isinstance(value['configuration_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['configuration_sha256']) or type(value['provenance_count']) is not int or not 1<=value['provenance_count']<=32:
        raise ValueError('Invalid configuration fingerprint')
    for key in ('evaluated_at_utc','coverage_start_utc','coverage_end_utc','expires_at_utc'):
        timestamp = datetime.fromisoformat(value[key])
        if timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
            raise ValueError('Invalid v2 UTC evidence')
    if value['verification'] not in ('BLOCKED','VERIFIED_DECLARATIONS') or any(code not in MESSAGES for code in value['reason_codes']):
        raise ValueError('Invalid v2 verification evidence')
    if any(kind not in ('PUBLISHED','LOCAL_OBSERVATION','SYNTHETIC_TEST') for kind in value['provenance_kinds']):
        raise ValueError('Unredacted provenance')
    permissions = value['permissions']
    if set(permissions) != {'phase','market_data_expected','broker_open_positions','broker_close_positions','broker_permissions_verified','iat_execution_allowed'} or permissions['phase'] not in STATES:
        raise ValueError('Invalid phase evidence')
    if any(type(permissions[key]) not in (bool,type(None)) for key in permissions if key != 'phase') or permissions['iat_execution_allowed'] is not False:
        raise ValueError('Unsafe phase evidence')


def publish_research_preflight_failure(path, code):
    """Atomically publish a new fixed-vocabulary failure without valid config."""
    from datetime import datetime, timezone
    from uuid import uuid4
    code = code if code in MESSAGES else 'CONFIG_INVALID'
    payload = {'report_version':1,'kind':'SESSION_RESEARCH_PREFLIGHT','run_id':str(uuid4()),
               'status':'FAIL','as_of_utc':datetime.now(timezone.utc).isoformat(),
               'diagnostics':[diagnostic(code)],'safety':{'signal':'WAIT','execution_allowed':False}}
    destination=Path(path)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,prefix='.iat-research-',delete=False) as handle:
            temporary=Path(handle.name)
            handle.write((json.dumps(payload,indent=2)+'\n').encode('utf-8'))
            handle.flush();os.fsync(handle.fileno())
        if os.name=='nt':os.rename(temporary,destination)
        else:os.link(temporary,destination)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return payload
