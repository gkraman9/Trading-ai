"""Local Windows DEMO evidence runner. No login or execution APIs are used."""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iat.analysis import analyze
from iat.broker_sessions import UNSET, compare_broker_sessions
from iat.evidence import AtomicEvidence, diagnostic, outcome, validate_report
from iat.mt5_data import MarketDataError, get_candle_snapshot
from iat.quality import ClockGuard, ClockValidationError
from iat.sessions import SessionValidationError
from iat.session_config import MAX_BYTES, load_session_bundle, reject_constant, unique_object


def package_version():
    try:
        value = version('MetaTrader5')
        return value if re.fullmatch(r'\d{1,5}(?:\.\d{1,5}){1,3}', value) else None
    except Exception:
        return None


def new_report():
    return {
        'report_version': 1, 'run_id': str(uuid4()), 'started_at_utc': None, 'finished_at_utc': None,
        'status': 'FAIL', 'diagnostics': [diagnostic('RUN_INCOMPLETE')],
        'runtime': {'python': '.'.join(map(str, sys.version_info[:3])), 'mt5_package': None},
        'symbol': {'alias': 'SYMBOL_1', 'requested_asset': 'XAUUSD', 'visible': None,
                   'asset_metadata_match': None, 'digits': None},
        'terminal': {'connected': None, 'demo_account': None, 'algo_trading_disabled': None,
                     'external_api_trading_disabled': None},
        'calendar': {'scope': 'UNAVAILABLE', 'comparison': 'NOT_RUN', 'configured_window_count': None,
                     'broker_window_count': None, 'configured_exception_rules': None,
                     'metadata_age_seconds': None, 'mismatch_intervals': None,
                     'dated_exceptions_covered': False, 'codes': []},
        'timeframes': {tf: {'status': 'FAIL', 'requested_count': 100, 'validated_closed_count': None,
                           'last_open_utc': None, 'last_close_utc': None, 'age_seconds': None,
                           'missing_recent_bars': None, 'unexpected_gap_count': None,
                           'scheduled_gap_count': None, 'codes': ['RUN_INCOMPLETE']}
                       for tf in ('M1', 'M5')},
        'safety': {'signal': 'WAIT', 'execution_allowed': False, 'orders_requested': 0,
                   'credentials_requested': False, 'login_called': False,
                   'binding_initialization_attempted': False, 'binding_initialized': False,
                   'shutdown_completed': None, 'independent_broker_certification': False},
    }


def load_metadata(path):
    with Path(path).open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Metadata exceeds size limit')
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object, parse_constant=reject_constant)


def validate_demo(config_path, *, mt5=None, clock=None, metadata_path=None, terminal_path=None, report=None):
    """Return only allowlisted evidence. Suppress third-party Python stdout/stderr."""
    with open(os.devnull, 'w') as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        return _validate(config_path, mt5, clock, metadata_path, terminal_path, report)


def _validate(config_path, mt5, clock, metadata_path, terminal_path, report):
    run_id = report['run_id'] if report is not None else None
    report = new_report()
    if run_id is not None:
        report['run_id'] = run_id
    codes = []
    clock = ClockGuard(clock if clock is not None else lambda: datetime.now(timezone.utc))
    initialized = False

    def add(code):
        safe = diagnostic(code)['code']
        if safe not in codes:
            codes.append(safe)

    try:
        report['started_at_utc'] = clock().isoformat()
        try:
            config, calendar = load_session_bundle(config_path)
        except Exception:
            add('CONFIG_INVALID')
            return _finish(report, codes, clock)
        # A schema-valid research candidate is not an assured broker calendar.
        # Do not even import/initialize MT5 while explicit assurance holds remain.
        if calendar.assurance_codes:
            for code in calendar.assurance_codes:
                add(code)
            for entry in report['timeframes'].values():
                entry.update(status='FAIL', codes=list(calendar.assurance_codes))
            duration = timedelta(minutes=5)
            if any(boundary.timestamp() % duration.total_seconds() for pair in calendar.windows for boundary in pair):
                report['timeframes']['M5']['codes'].append('SESSION_ALIGNMENT_INVALID')
                add('SESSION_ALIGNMENT_INVALID')
            if not calendar.coverage_start <= clock() < calendar.coverage_end:
                add('SESSION_COVERAGE_UNKNOWN')
            return _finish(report, codes, clock)
        metadata = UNSET
        if metadata_path is not None:
            try:
                metadata = load_metadata(metadata_path)
            except Exception:
                add('BROKER_METADATA_INVALID')
                return _finish(report, codes, clock)
        if mt5 is None:
            try:
                import MetaTrader5 as mt5
            except Exception:
                add('MT5_UNAVAILABLE')
                return _finish(report, codes, clock)
        report['runtime']['mt5_package'] = package_version()
        if report['runtime']['mt5_package'] is None:
            add('VERSION_UNAVAILABLE')
        report['safety']['binding_initialization_attempted'] = True
        try:
            initialized = (mt5.initialize() if terminal_path is None else mt5.initialize(str(terminal_path))) is True
        except Exception:
            add('INITIALIZATION_FAILED')
        report['safety']['binding_initialized'] = initialized
        if not initialized:
            add('INITIALIZATION_FAILED')
        else:
            terminal = mt5.terminal_info()
            connected = terminal is not None and getattr(terminal, 'connected', None) is True
            report['terminal']['connected'] = connected
            if not connected:
                add('TERMINAL_DISCONNECTED')
            else:
                # Never serialize terminal/account namedtuples or access any
                # account field other than trade_mode. No account identifier is read.
                disabled = getattr(terminal, 'trade_allowed', None) is False
                api_disabled = getattr(terminal, 'tradeapi_disabled', None) is True
                report['terminal'].update(algo_trading_disabled=disabled,
                                          external_api_trading_disabled=api_disabled)
                if not disabled:
                    add('AUTOTRADING_NOT_DISABLED')
                if not api_disabled:
                    add('EXTERNAL_API_NOT_DISABLED')
                account = mt5.account_info()
                mode = getattr(account, 'trade_mode', None)
                constant = getattr(mt5, 'ACCOUNT_TRADE_MODE_DEMO', None)
                demo = type(mode) is int and type(constant) is int and constant == 0 and mode == constant
                report['terminal']['demo_account'] = demo
                if not demo:
                    add('DEMO_ACCOUNT_REQUIRED')
                if disabled and api_disabled and demo:
                    _inspect_symbol(mt5, config, calendar, metadata, report, add, clock)
    except ClockValidationError as exc:
        add(exc.report.diagnostics[0].code)
    except KeyboardInterrupt:
        add('INTERRUPTED')
    except Exception:
        add('VALIDATION_FAILED')
    finally:
        if report['safety']['binding_initialization_attempted']:
            try:
                mt5.shutdown()
                report['safety']['shutdown_completed'] = True
            except Exception:
                report['safety']['shutdown_completed'] = False
                add('SHUTDOWN_FAILED')
    return _finish(report, codes, clock)


def _inspect_symbol(mt5, config, calendar, metadata, report, add, clock):
    info = mt5.symbol_info(calendar.symbol)
    visible = info is not None and getattr(info, 'visible', None) is True
    report['symbol']['visible'] = visible
    if not visible:
        add('SYMBOL_NOT_VISIBLE')
        return
    digits = getattr(info, 'digits', None)
    if type(digits) is not int or not 0 <= digits <= 12:
        add('SYMBOL_METADATA_INVALID')
        return
    report['symbol']['digits'] = digits
    base, profit = getattr(info, 'currency_base', None), getattr(info, 'currency_profit', None)
    if base in (None, '') or profit in (None, ''):
        add('SYMBOL_ASSET_UNVERIFIED')
    elif not isinstance(base, str) or not isinstance(profit, str):
        add('SYMBOL_METADATA_INVALID')
        return
    else:
        match = base == 'XAU' and profit == 'USD'
        report['symbol']['asset_metadata_match'] = match
        if not match:
            add('SYMBOL_ASSET_MISMATCH')
            return
    report['calendar'] = compare_broker_sessions(mt5, config, calendar, metadata, now=clock())
    for code in report['calendar']['codes']:
        add(code)
    for timeframe in ('M1', 'M5'):
        entry = report['timeframes'][timeframe]
        try:
            snapshot = get_candle_snapshot(symbol=calendar.symbol, timeframe=timeframe, count=100,
                                           mt5=mt5, clock=clock, session_calendar=calendar)
            if snapshot.quality.valid is not True:
                raise ValueError('Unestablished quality')
            decision = analyze(calendar.symbol, timeframe, snapshot.candles)
            if decision['signal'] != 'WAIT' or decision['execution_allowed'] is not False:
                raise ValueError('Read-only safety invariant')
            safe_codes = [diagnostic(item.code)['code'] for item in snapshot.quality.diagnostics]
            opens = [datetime.fromisoformat(row['timestamp']) for row in snapshot.candles]
            duration = timedelta(minutes=1 if timeframe == 'M1' else 5)
            now = clock()
            # Recheck at evidence time, not just the pre-fetch clock sample.
            calendar.validate_history(opens, now, duration, 2)
            missing = sum(1 for _ in calendar.expected_opens(opens[-1] + duration,
                          now - duration + timedelta(microseconds=1), duration))
            if missing and 'RECENT_BARS_MISSING' not in safe_codes:
                safe_codes.append('RECENT_BARS_MISSING')
            entry.update(status=outcome(safe_codes), validated_closed_count=len(opens),
                         last_open_utc=opens[-1].isoformat(),
                         last_close_utc=(opens[-1] + duration).isoformat(),
                         age_seconds=(now - opens[-1] - duration).total_seconds(),
                         missing_recent_bars=missing, unexpected_gap_count=0,
                         scheduled_gap_count=sum(b - a > duration for a, b in zip(opens, opens[1:])),
                         codes=safe_codes)
            for code in safe_codes:
                add(code)
        except SessionValidationError as exc:
            safe_code = diagnostic(exc.code)["code"]
            entry.update(status=outcome([safe_code]), codes=[safe_code])
            add(safe_code)
        except (MarketDataError, ClockValidationError) as exc:
            safe_codes = [diagnostic(item.code)['code'] for item in exc.report.diagnostics]
            entry.update(status=outcome(safe_codes), codes=safe_codes)
            for code in safe_codes:
                add(code)
        except Exception:
            entry.update(status='FAIL', codes=['QUALITY_UNESTABLISHED'])
            add('QUALITY_UNESTABLISHED')


def _finish(report, codes, clock):
    try:
        report['finished_at_utc'] = clock().isoformat()
    except Exception:
        if 'CLOCK_UNAVAILABLE' not in codes:
            codes.append('CLOCK_UNAVAILABLE')
    # Not-run frames must never masquerade as zero-gap, fresh, validated data.
    if any(entry['validated_closed_count'] is None for entry in report['timeframes'].values()):
        if not codes or outcome(codes) == 'PASS':
            codes.append('QUALITY_UNESTABLISHED')
    if not codes:
        codes.append('CHECKS_PASSED')
    report['diagnostics'] = [diagnostic(code) for code in dict.fromkeys(codes)]
    report['status'] = outcome([item['code'] for item in report['diagnostics']])
    return report


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('Invalid command-line arguments')


def main(argv=None):
    parser = SafeParser(description='Redacted read-only MT5 DEMO validation')
    parser.add_argument('--config', default=os.environ.get('IAT_SESSION_CONFIG'))
    parser.add_argument('--report-path')
    parser.add_argument('--broker-metadata')
    parser.add_argument('--terminal-path')
    try:
        args = parser.parse_args([] if argv is None else argv)
    except ValueError:
        print(json.dumps({'status': 'FAIL', 'code': 'CLI_ARGUMENTS_INVALID'}))
        return 1
    initial = new_report()
    evidence = None
    if args.report_path is not None:
        try:
            evidence = AtomicEvidence(args.report_path, initial)
        except Exception:
            print(json.dumps({'status': 'FAIL', 'code': 'REPORT_PATH_UNAVAILABLE'}))
            return 1
    try:
        report = validate_demo(args.config, metadata_path=args.broker_metadata, terminal_path=args.terminal_path, report=initial)
    except (Exception, KeyboardInterrupt):
        report = new_report()
        report['run_id'] = initial['run_id']
        report['diagnostics'] = [diagnostic('VALIDATION_FAILED')]
    try:
        validate_report(report)
    except Exception:
        print(json.dumps({'status': 'FAIL', 'code': 'REPORT_SCHEMA_INVALID'}))
        return 1
    if evidence is not None:
        try:
            evidence.publish(report)
        except Exception:
            # The reserved file remains RUN_INCOMPLETE/FAIL. Never print PASS.
            print(json.dumps({'status': 'FAIL', 'code': 'REPORT_PUBLICATION_FAILED'}))
            return 1
    print(json.dumps(report, allow_nan=False, indent=2))
    return {'PASS': 0, 'WARN': 2, 'FAIL': 1}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
