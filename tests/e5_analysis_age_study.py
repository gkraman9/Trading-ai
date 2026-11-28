"""Labeled invented E5 cadence study; no historical admission or market claims."""
from datetime import timedelta
from e5_fixtures import source
from risk_fixtures import START
from iat.e5_protocol import protocol
from iat.e5_replay import replay_source
from iat.intelligence.strategy_replay import digest


def study():
    offsets = [1, 30, 30.001, 60, 61]
    def fixture():
        return source(quote_seconds=offsets, prices=[('2099.9', '2100.1')] * len(offsets))
    full = replay_source(fixture())
    boundary = replay_source(
        fixture(), cutoff=(START + timedelta(minutes=36, seconds=30)).isoformat()
    )
    changes = [e for e in full['opportunity_events'] if e['outcome'] == 'UNRESOLVED']
    policy = protocol()
    report = dict(
        review_version=1, kind='E5_ANALYSIS_AGE_SYNTHETIC_STUDY',
        provenance='SYNTHETIC_FIXTURE_NOT_HISTORICAL',
        protocol_sha256=policy['sha256'],
        analysis_age_limit_ms=policy['policies']['fill']['max_analysis_age_ms'],
        m1_closed_update_interval_ms=60000,
        idealized_continuous_time=dict(
            interval='[0,60000)ms after logical close; zero publication delay',
            stale_interval='(30000,60000)ms', stale_duration_ms=30000,
            interval_duration_ms=60000,
            meaning='CLOCK_GEOMETRY_NOT_MARKET_FREQUENCY_OR_PROBABILITY',
        ),
        invented_quote_offsets_seconds=offsets,
        invented_quote_receipt_delay_ms=0,
        at_30_seconds=dict(
            open_count=len(boundary['journal']['account']['open_positions']),
            states=[p['state'] for p in boundary['journal']['account']['open_positions']],
            stale_transition_count=sum('STRUCTURAL_ANALYSIS_STALE' in e['reason_codes'] for e in boundary['opportunity_events']),
        ),
        first_unresolved=[dict(at_utc=e['at_utc'], reason_codes=e['reason_codes']) for e in changes],
        after_next_m1=dict(
            unresolved=full['setup_summary']['unresolved'],
            states=[p['state'] for p in full['journal']['account']['open_positions']],
            closed_count=len(full['journal']['account']['closed_positions']),
        ),
        historical_validation='PENDING', historical_comparisons='NOT_RUN',
        historical_performance='UNMEASURED', qualification='DATA_NOT_QUALIFIED',
        exness='BLOCKED', mode='READ_ONLY_SHADOW', signal='WAIT', execution_allowed=False,
    )
    return dict(report, sha256=digest(report))
