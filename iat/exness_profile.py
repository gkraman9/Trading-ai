"""Reproducible installation/inspection of the BLOCKED observed Exness candidate.

This tool writes configuration, never market data or a certification. It has no
MT5 dependency and cannot clear the assurance holds or round session boundaries.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timedelta, timezone

from iat.calendar_assurance import EXNESS_SOURCE, EXNESS_HOLDS
from iat.session_config import load_session_bundle
from iat.sessions import utc

PROFILE = 'exness-xauusd-observed-winter-2026-11'
BUNDLED_DIRECTORY = Path(__file__).resolve().parents[1] / 'config' / 'profiles'


def read_profile(directory=None):
    directory = BUNDLED_DIRECTORY if directory is None else Path(directory)
    path = directory / (PROFILE + '.json')
    raw = path.read_bytes()
    config, calendar = load_session_bundle(path)
    review = json.loads((directory / (PROFILE + '.review.json')).read_text(encoding='utf-8'))
    digest = hashlib.sha256(raw).hexdigest()
    if (review['review_version'] != 1 or review['config_sha256'] != digest or
            review['state'] != 'BLOCKED' or review['broker_certified'] is not False or
            tuple(review['unresolved_codes']) != EXNESS_HOLDS or
            config['verification']['source'] != EXNESS_SOURCE or config['symbol'] != 'XAUUSD' or
            config['timezone'] != 'UTC' or calendar.assurance_codes != EXNESS_HOLDS):
        raise ValueError('Profile consistency checks failed')
    return raw, config, calendar, review


def inspect_profile(*, now=None, directory=None):
    raw, config, calendar, _ = read_profile(directory)
    now = utc(datetime.now(timezone.utc) if now is None else now)
    codes = list(calendar.assurance_codes)
    if not calendar.coverage_start <= now < calendar.coverage_end:
        codes.append('SESSION_COVERAGE_UNKNOWN')
    duration = timedelta(minutes=5)
    misaligned = any(boundary.timestamp() % 300 for pair in calendar.windows for boundary in pair)
    if misaligned:
        codes.append('SESSION_ALIGNMENT_INVALID')
    # Pure calendar grid count is NOT an OHLC availability or quality claim.
    end = min(now - duration + timedelta(microseconds=1), calendar.coverage_end)
    slots = sum(1 for _ in calendar.expected_opens(calendar.coverage_start, end, duration))
    if slots < 100:
        codes.append('HISTORY_INCOMPLETE')
    return {'profile': PROFILE, 'schema_valid': True, 'status': 'BLOCKED', 'runtime_ready': False,
            'profile_sha256': hashlib.sha256(raw).hexdigest(),
            'coverage_start_utc': calendar.coverage_start.isoformat(),
            'coverage_end_utc': calendar.coverage_end.isoformat(),
            'coverage_has_100_potential_m5_slots': slots >= 100,
            'potential_m5_grid_slots_before_test': slots,
            'timeframe_compatibility': {'M1': 'ALIGNED_BUT_ASSURANCE_BLOCKED',
                                       'M5': 'SESSION_ALIGNMENT_INVALID' if misaligned else 'ASSURANCE_BLOCKED'},
            'reason_codes': codes, 'broker_certified': False, 'terminal_tested': False,
            'signal': 'WAIT', 'execution_allowed': False}


def install_profile(destination, *, replace_confirmed=False, expected_current_sha256=None,
                    now=None, directory=None):
    raw, _, _, _ = read_profile(directory)
    assessment = inspect_profile(now=now, directory=directory)
    path = Path(destination)
    source = BUNDLED_DIRECTORY if directory is None else Path(directory)
    if path.suffix.lower() != '.json' or path.is_symlink() or path.resolve() in (
            (source / (PROFILE + '.json')).resolve(), (source / (PROFILE + '.review.json')).resolve()):
        raise ValueError('Unsafe profile destination')
    if replace_confirmed:
        if not isinstance(expected_current_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_current_sha256):
            raise ValueError('Confirmed replacement requires the reviewed current digest')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_current_sha256:
            raise ValueError('Existing configuration changed since confirmation')
    elif expected_current_sha256 is not None:
        raise ValueError('Replacement was not confirmed')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not replace_confirmed:
        # Reserve exclusively. A crash here leaves invalid/incomplete config,
        # never a falsely approved calendar or an overwritten user configuration.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(b'{"status":"INSTALL_INCOMPLETE"}\n')
            handle.flush()
            os.fsync(handle.fileno())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.iat-profile-', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        # Validate the bytes actually staged, not only a source-memory object.
        _, staged = load_session_bundle(temporary)
        if staged.assurance_codes != EXNESS_HOLDS:
            raise ValueError('Staged configuration lost assurance holds')
        if replace_confirmed and hashlib.sha256(path.read_bytes()).hexdigest() != expected_current_sha256:
            raise ValueError('Existing configuration changed during installation')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return dict(assessment, installed=True)
