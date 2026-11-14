"""Chronological offline strategy observations and distinct evidence-anchored lifecycles."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
from hashlib import sha256
import json

from iat.intelligence.context import context_at
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig, iso
from iat.intelligence.strategies import evaluate_strategies
from iat.intelligence.strategy_registry import registry
from iat.replay_dataset import utc


POLICY = {'version': 1, 'continuation_anchor': 'CANONICAL_M5_STRUCTURE_PIVOTS',
          'reversal_anchor': 'SELECTED_CANONICAL_SWEEP', 'rearm': 'DISTINCT_ANCHOR_ONLY',
          'blocked': 'SUSPEND_LIFECYCLE', 'reversal_age_minutes': 5}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def setup_identity(strategy, version, symbol, direction, anchor):
    return 'SETUP:' + digest([strategy, version, symbol, direction, anchor['kind'], sorted(set(anchor['references']))])


def _anchor(report, result):
    if result['strategy_id'] == 'M5_TREND_M1_CONFIRMATION':
        if report.context.get('m5_structure') != result['direction']:return None
        evidence = [e for e in report.evidence if e.category == 'STRUCTURE' and e.timeframe == 'M5'
                    and e.direction == result['direction']]
        refs = sorted({r for e in evidence for r in e.references})
        if not refs or any(report.interpretations['source_registry'].get(r, {}).get('kind') != 'CONFIRMED_PIVOT' for r in refs):
            return None
        return {'kind': 'M5_STRUCTURE_PIVOTS', 'references': refs,
                'available_at': max(e.available_at for e in evidence), 'expires_at': None}
    frame = report.interpretations.get('frames', {}).get('M1', {})
    supported = set(result['supporting_evidence'])
    sweeps = [e for e in frame.get('liquidity_events', ()) if e.event_type == 'CONFIRMED_SWEEP' and e.id in supported]
    if not sweeps:return None
    sweep = max(sweeps, key=lambda e: (utc(e.available_at), e.id))
    return {'kind': 'CONFIRMED_M1_SWEEP', 'references': [sweep.id], 'available_at': sweep.available_at,
            'expires_at': iso(utc(sweep.available_at) + timedelta(minutes=5))}


class StrategyReplayLedger:
    """Pure ledger over typed context reports; not an alternative OHLC quality gate."""
    def __init__(self, symbol, *, config=None, intelligence_config=None, session_sha256=None, finality_sha256=None):
        config = ContextConfig() if config is None else config
        intelligence_config = IntelligenceConfig() if intelligence_config is None else intelligence_config
        if not isinstance(config, ContextConfig) or not isinstance(intelligence_config, IntelligenceConfig):
            raise ValueError('Typed analytical configurations required')
        if not isinstance(symbol, str) or not symbol or len(symbol) > 128:
            raise ValueError('Invalid replay symbol')
        self.symbol = symbol
        self.hashes = {'context': config.digest, 'intelligence': intelligence_config.digest,
                       'registry': registry()['sha256'], 'lifecycle_policy': digest(POLICY),
                       'session': session_sha256, 'observed_finality': finality_sha256}
        self.entries, self.setups = [], {}
        self.provenance = None

    def record(self, report):
        snapshot = evaluate_strategies(report)
        at = utc(report.analysis_at)
        if self.entries and at <= utc(self.entries[-1]['timestamp_utc']):
            raise ValueError('Strategy replay must be strictly chronological')
        if (report.symbol != self.symbol or report.configuration_sha256 != self.hashes['context']
                or report.intelligence_configuration_sha256 != self.hashes['intelligence']):
            raise ValueError('Strategy replay identity/configuration changed')
        if self.provenance is not None and report.provenance != self.provenance:
            raise ValueError('Strategy replay provenance changed')
        sources = deepcopy(report.interpretations.get('source_registry', {}))
        evidence = {e.id: asdict(e) for e in report.evidence}
        references = set(sources) | set(evidence)
        if any(utc(item['available_at']) > at for item in list(sources.values()) + list(evidence.values())):
            raise ValueError('Future strategy evidence')
        blocked = not report.data_quality['valid']
        rows, events = [], []
        # Work on a detached state so a rejected snapshot cannot partially advance lifecycles.
        states = deepcopy(self.setups)
        for result in snapshot['evaluations']:
            result = deepcopy(result)
            key = (result['strategy_id'], result['rule_version'], result['direction'])
            anchor = None if blocked else _anchor(report, result)
            if not blocked and result['status'] in ('QUALIFIES', 'INVALIDATED') and anchor is None:
                raise ValueError('Qualification/invalidation requires a canonical anchor')
            sid = setup_identity(*key[:2], self.symbol, key[2], anchor) if anchor else None
            if anchor and (any(r not in references for r in anchor['references']) or utc(anchor['available_at']) > at):
                raise ValueError('Unresolved/future strategy anchor')
            if not (set(result['supporting_evidence']) | set(result['contradictory_evidence'])) <= references:
                raise ValueError('Unresolved strategy evidence')
            if not blocked:
                for old_id, old in states.items():
                    if (old['strategy_id'], old['rule_version'], old['direction']) != key or old['state'] != 'ACTIVE':continue
                    reason = None
                    if old['anchor']['expires_at'] and at > utc(old['anchor']['expires_at']):
                        reason = 'SWEEP_WINDOW_EXPIRED'
                    elif sid is not None and sid != old_id:
                        reason = 'DISTINCT_ANCHOR_SUPERSEDES'
                    elif (result['strategy_id'] == 'M5_TREND_M1_CONFIRMATION' and sid is None
                          and 'M5_TREND_NOT_ALIGNED' in result['reason_codes']):
                        reason = 'M5_TREND_ANCHOR_LOST'
                    if reason:
                        old.update(state='EXPIRED', terminal_at=iso(at))
                        events.append({'setup_id': old_id, 'event': 'EXPIRED', 'reason_codes': [reason]})
                if sid is not None:
                    old = states.get(sid)
                    if old is None and result['status'] in ('QUALIFIES', 'INVALIDATED'):
                        qualified = result['status'] == 'QUALIFIES'
                        states[sid] = {'setup_id': sid, 'strategy_id': key[0], 'rule_version': key[1],
                                       'symbol': self.symbol, 'direction': key[2], 'anchor': deepcopy(anchor),
                                       'qualified_at': iso(at) if qualified else None,
                                       'state': 'ACTIVE' if qualified else 'UNQUALIFIED_INVALIDATED',
                                       'terminal_at': None if qualified else iso(at)}
                        events.append({'setup_id': sid, 'event': 'QUALIFIED' if qualified else 'INVALIDATION_WITHOUT_QUALIFICATION',
                                       'reason_codes': result['reason_codes']})
                    elif old is not None and old['state'] == 'ACTIVE':
                        if result['status'] == 'INVALIDATED':
                            old.update(state='INVALIDATED', terminal_at=iso(at))
                            events.append({'setup_id': sid, 'event': 'INVALIDATED_QUALIFIED_SETUP', 'reason_codes': result['reason_codes']})
                        elif result['status'] == 'QUALIFIES':
                            events.append({'setup_id': sid, 'event': 'REPEATED_QUALIFICATION', 'reason_codes': ['SAME_ANCHOR_COUNTED_ONCE']})
                    elif old is not None and result['status'] == 'QUALIFIES':
                        events.append({'setup_id': sid, 'event': 'ANCHOR_RETIRED_NO_REARM', 'reason_codes': ['DISTINCT_ANCHOR_REQUIRED']})
            result.update(snapshot_outcome='BLOCKED_DATA' if blocked else result['status'], setup_id=sid, anchor=anchor)
            rows.append(result)
        entry = {'timestamp_utc': iso(at), 'configuration_hashes': deepcopy(self.hashes),
                 'data_quality': deepcopy(report.data_quality), 'evaluations': rows,
                 'evidence': evidence, 'source_registry': sources, 'lifecycle_events': events,
                 'signal': 'WAIT', 'execution_allowed': False}
        self.provenance = report.provenance
        self.setups = states
        self.entries.append(deepcopy(entry))
        return deepcopy(entry)

    def to_dict(self):
        result = {'log_version': 1, 'kind': 'STRATEGY_REPLAY_LOG', 'symbol': self.symbol,
                  'provenance': self.provenance, 'configuration_hashes': deepcopy(self.hashes),
                  'lifecycle_policy': deepcopy(POLICY), 'entries': deepcopy(self.entries),
                  'setups': [deepcopy(self.setups[k]) for k in sorted(self.setups)],
                  'summary': _summary(self.entries, self.setups),
                  'historical_validation': 'PENDING', 'historical_comparisons': 'NOT_RUN',
                  'exness': 'BLOCKED', 'signal': 'WAIT', 'execution_allowed': False}
        result['sha256'] = digest(result)
        return result



def _summary(entries, setups):
    groups = []
    for spec in registry()['strategies']:
        for direction in ('BULLISH', 'BEARISH'):
            rows = [r for e in entries for r in e['evaluations']
                    if r['strategy_id'] == spec['strategy_id'] and r['direction'] == direction]
            states = [s for s in setups.values() if s['strategy_id'] == spec['strategy_id'] and s['direction'] == direction]
            qualified = [s for s in states if s['qualified_at'] is not None]
            groups.append({'strategy_id': spec['strategy_id'], 'direction': direction,
                           'snapshot_outcomes': {k: sum(r['snapshot_outcome'] == k for r in rows)
                                                 for k in ('QUALIFIES', 'ABSTAINS', 'INVALIDATED', 'BLOCKED_DATA')},
                           'reason_counts': dict(sorted(Counter(c for r in rows for c in r['reason_codes']).items())),
                           'unique_qualified_setups': len(qualified),
                           'active_qualified_setups': sum(s['state'] == 'ACTIVE' for s in qualified),
                           'invalidated_qualified_setups': sum(s['state'] == 'INVALIDATED' for s in qualified),
                           'expired_qualified_setups': sum(s['state'] == 'EXPIRED' for s in qualified),
                           'unqualified_invalidated_anchors': sum(s['qualified_at'] is None for s in states)})
    return {'timestamps': len(entries), 'directional_snapshots': 4 * len(entries),
            'blocked_timestamps': sum(not e['data_quality']['valid'] for e in entries), 'groups': groups}

def replay_strategies(symbol, m1_history, m5_history, *, as_of=None, **options):
    """Evaluate each supplied M1 close; a missing candle is not a fabricated snapshot.

    No rolling truncation: full supplied warm-up prefixes determine durable anchors.
    as_of bounds acquisition visibility and is excluded from analytical policy hashes.
    """
    if not isinstance(m1_history, (list, tuple)):
        raise ValueError('Replay requires a bounded M1 history')
    cutoff = utc(iso(as_of)) if as_of is not None else None
    calendar = options.get('calendar')
    if calendar is None: session_hash = None
    elif hasattr(calendar, 'configuration_sha256'): session_hash = calendar.configuration_sha256
    else:
        data = asdict(calendar)
        data['coverage_start'], data['coverage_end'] = iso(calendar.coverage_start), iso(calendar.coverage_end)
        data['windows'] = [[iso(a), iso(b)] for a, b in calendar.windows]
        session_hash = digest(data)
    finality = options.get('observed_finality')
    ledger = StrategyReplayLedger(symbol, config=options.get('config'), intelligence_config=options.get('intelligence_config'),
                                  session_sha256=session_hash, finality_sha256=digest(finality) if finality is not None else None)
    previous = None
    for index, row in enumerate(m1_history):
        at = utc(row['timestamp']) + timedelta(minutes=1)
        if cutoff is not None and at > cutoff:break
        if index >= 5000:raise ValueError('Replay visible M1 history limit exceeded')
        if previous is not None and at <= previous:raise ValueError('Strategy replay M1 chronology invalid')
        report = context_at(symbol, m1_history, m5_history, at, **options)
        ledger.record(report)
        previous = at
    return ledger.to_dict()


def validate_strategy_replay_log(log):
    """Validate serialized safety, chronology, references, configuration and checksum."""
    if (type(log['log_version']) is not int or log['log_version'] != 1 or log['kind'] != 'STRATEGY_REPLAY_LOG'
            or log['signal'] != 'WAIT' or log['execution_allowed'] is not False
            or log['exness'] != 'BLOCKED' or log['historical_validation'] != 'PENDING'
            or log['historical_comparisons'] != 'NOT_RUN' or log['lifecycle_policy'] != POLICY
            or type(log['lifecycle_policy']['version']) is not int):
        raise ValueError('Unsafe/unsupported Strategy Replay Log')
    if digest({k: v for k, v in log.items() if k != 'sha256'}) != log['sha256']:
        raise ValueError('Strategy Replay Log checksum mismatch')
    if (log['configuration_hashes']['registry'] != registry()['sha256']
            or log['configuration_hashes']['lifecycle_policy'] != digest(POLICY)):
        raise ValueError('Strategy Replay Log policy/registry mismatch')
    previous = None
    states = {s['setup_id']: s for s in log['setups']}
    ids = set(states)
    if len(ids) != len(log['setups']) or _summary(log['entries'], states) != log['summary']:
        raise ValueError('Strategy Replay Log summary/setup mismatch')
    expected = {}
    pairs = {(s['strategy_id'], d) for s in registry()['strategies'] for d in ('BULLISH', 'BEARISH')}
    for sid, state in states.items():
        if sid != setup_identity(state['strategy_id'], state['rule_version'], log['symbol'], state['direction'], state['anchor']):
            raise ValueError('Strategy setup identity mismatch')
        if state['symbol'] != log['symbol']:raise ValueError('Strategy setup symbol mismatch')
    for e in log['entries']:
        at = utc(e['timestamp_utc'])
        if previous is not None and at <= previous:raise ValueError('Strategy Replay Log chronology invalid')
        previous = at
        if e['configuration_hashes'] != log['configuration_hashes'] or e['signal'] != 'WAIT' or e['execution_allowed'] is not False:
            raise ValueError('Strategy Replay Log configuration/safety changed')
        refs = set(e['evidence']) | set(e['source_registry'])
        for item in list(e['evidence'].values()) + list(e['source_registry'].values()):
            if utc(item['available_at']) > at:raise ValueError('Future strategy evidence')
        if len(e['evaluations']) != 4 or {(r['strategy_id'], r['direction']) for r in e['evaluations']} != pairs:
            raise ValueError('Incomplete strategy snapshot')
        for row in e['evaluations']:
            outcome = 'BLOCKED_DATA' if not e['data_quality']['valid'] else row['status']
            if row['status'] not in ('QUALIFIES','ABSTAINS','INVALIDATED') or row['snapshot_outcome'] != outcome:
                raise ValueError('Invalid strategy snapshot outcome')
            if row['anchor'] and row['setup_id'] != setup_identity(row['strategy_id'], row['rule_version'], log['symbol'], row['direction'], row['anchor']):
                raise ValueError('Strategy snapshot identity mismatch')
            if not (set(row['supporting_evidence']) | set(row['contradictory_evidence'])) <= refs:
                raise ValueError('Unresolved strategy evidence')
            if row['anchor'] and (not set(row['anchor']['references']) <= refs or utc(row['anchor']['available_at']) > at):
                raise ValueError('Unresolved/future strategy anchor')
        if not e['data_quality']['valid'] and e['lifecycle_events']:
            raise ValueError('Blocked data cannot advance lifecycles')
        for event in e['lifecycle_events']:
            sid, kind = event['setup_id'], event['event']
            if sid not in ids:raise ValueError('Unresolved lifecycle setup')
            if kind in ('QUALIFIED','INVALIDATION_WITHOUT_QUALIFICATION'):
                if sid in expected:raise ValueError('Setup rearmed without a distinct anchor')
                expected[sid] = {'state':'ACTIVE' if kind == 'QUALIFIED' else 'UNQUALIFIED_INVALIDATED',
                                 'qualified_at':iso(at) if kind == 'QUALIFIED' else None,
                                 'terminal_at':None if kind == 'QUALIFIED' else iso(at)}
            elif sid not in expected:raise ValueError('Lifecycle event before setup exists')
            elif kind in ('EXPIRED','INVALIDATED_QUALIFIED_SETUP'):
                if expected[sid]['state'] != 'ACTIVE' or expected[sid]['qualified_at'] is None:
                    raise ValueError('Terminal event without qualified active setup')
                expected[sid].update(state='EXPIRED' if kind == 'EXPIRED' else 'INVALIDATED', terminal_at=iso(at))
            elif kind == 'REPEATED_QUALIFICATION':
                if expected[sid]['state'] != 'ACTIVE':raise ValueError('Repeated qualification of retired setup')
            elif kind == 'ANCHOR_RETIRED_NO_REARM':
                if expected[sid]['state'] == 'ACTIVE':raise ValueError('Active setup labeled retired')
            else:raise ValueError('Unknown lifecycle event')
    if set(expected) != ids or any(any(states[sid][k] != v for k,v in state.items()) for sid,state in expected.items()):
        raise ValueError('Strategy lifecycle terminal state mismatch')
    return True


def write_strategy_replay_log(path, log):
    """Publish a validated private log atomically; never overwrite existing evidence."""
    import os
    from pathlib import Path
    import tempfile
    validate_strategy_replay_log(log)
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(b'{"publication_status":"INCOMPLETE"}\n')
        handle.flush()
        os.fsync(handle.fileno())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.iat-strategy-', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write((json.dumps(log, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
