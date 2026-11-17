"""Private offline export orchestration; existing import/dataset/qualification contracts only."""
import csv
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
import re

from iat.chart_benchmark import hashed, write_new, require
from iat.historical_evidence_manifest import local_path
from iat.historical_replay import alignment_check, safety
from iat.intelligence.models import IntelligenceConfig, iso
from iat.intelligence.strategy_replay import digest
from iat.pilot_preparation import stream_archive, file_fingerprint, window_contract
from iat.pilot_qualification import ITEMS
from iat.provenance_assessment import assess_historical_provenance, validate_provenance_assessment, provenance_text
from iat.qualification_assistant import prepare_package, _write_bytes
from iat.replay_dataset import load_dataset, read_bytes, utc

HEADERS = ['timestamp_utc', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']
LIMIT = 5000  # Unchanged prepared-dataset limit, not an archive-scale importer.


def import_spec(expected, *, retrieved_at, reference, start, end, evaluation_start,
                dataset_kind, authorized_local_use):
    """Existing import v1. Unknown feed/basis/finality remain unknown, never inferred."""
    require(authorized_local_use is True, 'LOCAL_USE_AUTHORIZATION_REQUIRED')
    window = window_contract(start, end, evaluation_start)
    require(utc(retrieved_at) >= utc(end), 'DECLARED_EXPORT_PRECEDES_WINDOW_END')
    require(dataset_kind in ('INDEPENDENT_HISTORICAL', 'SYNTHETIC_FIXTURE'))
    return dict(import_version=1, dataset_kind=dataset_kind, preparer_code='operator_intake',
        authorized_local_use=True,
        source=dict(provider_entity='Exness operator-declared' if dataset_kind=='INDEPENDENT_HISTORICAL' else 'SYNTHETIC Exness-shaped fixture',
            feed_id='UNKNOWN', instrument='XAUUSD', price_basis='UNKNOWN', reference=reference,
            retrieved_at_utc=iso(utc(retrieved_at)), curation_id='intake-'+digest(expected)[:32]),
        timestamp=dict(format='ISO8601', timezone='UTC', convention='INTERVAL_OPEN_UTC'),
        utc_range={k:window[k] for k in ('start','end')},
        evaluation=dict(start=window['evaluation_start'], end=window['end']),
        warmup={tf:dict(start=window['start'], end=window['evaluation_start']) for tf in ('M1','M5')},
        frames={tf:dict(file='source/'+tf.lower()+'.csv',
            columns=dict(timestamp='timestamp_utc', open='open', high='high', low='low', close='close',
                volume='tick_volume', complete=None, symbol=None, price_basis=None, feed_id=None),
            ignored_columns=['spread','real_volume'], price_basis='UNKNOWN', feed_id='UNKNOWN', origin='UNKNOWN',
            volume_kind='TICK', finality=dict(policy='UNKNOWN', provider_contract='UNKNOWN', true_token=None,
                false_token=None, reference=None),
            corrections=dict(status='UNKNOWN', reference=None, previous_source_sha256=None)) for tf in ('M1','M5')},
        calendar=None, evidence={name:dict(file=None, sha256=None, reference=None) for name in ITEMS})


def auxiliary_fields(path):
    """Validate every extra field before import; retain tick-volume for diagnostics only."""
    volumes = {}; count = 0
    with Path(path).open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle, strict=True)
        require(reader.fieldnames == HEADERS, 'EXPORT_HEADER_ORDER_INVALID')
        for row in reader:
            count += 1
            require(count <= LIMIT, 'DATASET_ROW_LIMIT')
            require(set(row) == set(HEADERS) and all(isinstance(v,str) and v.strip() for v in row.values()),
                    'EXPORT_MISSING_OR_EXTRA_FIELDS')
            try:
                values = {k:Decimal(row[k]) for k in ('tick_volume','spread','real_volume')}
                require(all(v.is_finite() and v >= 0 for v in values.values()), 'EXPORT_AUXILIARY_VALUE_INVALID')
            except InvalidOperation as exc:
                raise ValueError('EXPORT_AUXILIARY_VALUE_INVALID') from exc
            stamp = iso(utc(row['timestamp_utc']))
            require(stamp not in volumes, 'TIMESTAMP_DUPLICATE')
            volumes[stamp] = values['tick_volume']
    return count, volumes


def comparison(dataset, volumes, broker):
    """Existing OHLC tolerance; exact decimal tick sums, without replacing native M5."""
    result = alignment_check(dataset, IntelligenceConfig().epsilon)
    one = {utc(row['timestamp']):row for row in dataset.rows['M1']}
    observations = {(o['timeframe'],o['open_utc']):o for o in broker['observations']}
    rows = []; volume_mismatch = 0; partial = 0
    for bar in dataset.rows['M5']:
        opened = utc(bar['timestamp']); stamp = iso(opened)
        times = [opened+timedelta(minutes=i) for i in range(5)]
        available = [t for t in times if t in one]
        boundary = observations.get(('M5',stamp))
        label = boundary['classification'] if boundary else 'NO_SPECIFIC_BOUNDARY_OBSERVATION'
        possible_partial = label == 'PARTIAL_QUOTE_INTERVAL'
        partial += possible_partial
        if len(available) < 5:
            rows.append(dict(open_utc=stamp, m1_count=len(available), ohlc_match=None, tick_volume_match=None,
                classification='RELAYED_PARTIAL_OR_SESSION_UNCERTAIN' if possible_partial else 'INCOMPLETE_M1_GROUP',
                broker_boundary=label))
            continue
        group = [one[t] for t in times]
        derived = dict(open=group[0]['open'], high=max(r['high'] for r in group),
                       low=min(r['low'] for r in group), close=group[-1]['close'])
        matches = all(abs(derived[k]-bar[k]) <= result['tolerance'] for k in derived)
        same_volume = sum((volumes['M1'][iso(t)] for t in times), Decimal(0)) == volumes['M5'][stamp]
        volume_mismatch += not same_volume
        rows.append(dict(open_utc=stamp, m1_count=5, ohlc_match=matches, tick_volume_match=same_volume,
            classification='COMPLETE_FIVE_M1_GROUP', broker_boundary=label))
    result.update(tick_volume_policy='EXACT_DECIMAL_SUM_OF_FIVE_SUPPLIED_M1_TICK_COUNTS',
        tick_volume_mismatch_count=volume_mismatch, relayed_partial_m5_count=partial, comparisons=rows,
        role='DIAGNOSTIC_ONLY_SUPPLIED_M5_NEVER_REPLACED', finality_eligibility='UNESTABLISHED',
        missing_session_candle_count=None, calendar_assurance='DATED_INDEPENDENT_CALENDAR_UNAVAILABLE',
        source_assurance='OPERATOR_SUPPLIED_PAIR_NOT_AUTHENTICATED_NATIVE_SAME_FEED',
        operator_reported_counts={'complete_matches':813,'partial_or_session_uncertain':3},
        observed_complete_ohlc_and_tick_matches=sum(r['ohlc_match'] is True and r['tick_volume_match'] is True for r in rows))
    # This assertion is meaningful only for the reported real interval, not synthetic cases.
    result['operator_count_assertion_status'] = 'NOT_APPLICABLE'
    if dataset.metadata['dataset_kind']=='INDEPENDENT_HISTORICAL' and dataset.metadata['utc_range']=={
            'start':'2026-11-11T00:00:00+00:00','end':'2026-11-14T00:00:00+00:00'}:
        result['operator_count_assertion_status'] = 'MATCH' if (result['observed_complete_ohlc_and_tick_matches'],partial)==(813,3) else 'DIFFERS'
    return result


def intake_exports(m1_path, m5_path, destination, *, expected, retrieved_at, reference,
                   start, end, evaluation_start, authorized_local_use=False,
                   dataset_kind='INDEPENDENT_HISTORICAL'):
    """Publish a new private evidence package; never replay, qualify or touch prior evidence."""
    require(set(expected)=={'M1','M5'}, 'EXPECTED_FILE_ASSERTIONS_REQUIRED')
    for item in expected.values():
        require(set(item)=={'sha256','byte_count','row_count'} and isinstance(item['sha256'],str)
            and re.fullmatch('[a-f0-9]{64}',item['sha256']) and type(item['byte_count']) is int
            and 0<item['byte_count']<=4*1024*1024 and type(item['row_count']) is int
            and 3<=item['row_count']<=LIMIT, 'EXPECTED_FILE_ASSERTIONS_INVALID')
    spec = import_spec(expected, retrieved_at=retrieved_at, reference=reference, start=start, end=end,
        evaluation_start=evaluation_start, dataset_kind=dataset_kind, authorized_local_use=authorized_local_use)
    paths = {tf:local_path(p) for tf,p in (('M1',m1_path),('M5',m5_path))}
    root = local_path(destination)
    require(not root.exists() and not root.is_symlink() and all(not p.is_symlink() for p in root.parents), 'NEW_PRIVATE_OUTPUT_REQUIRED')
    root.mkdir(exist_ok=False)
    report = dict(intake_version=1, kind='EXNESS_HISTORICAL_INTAKE_V1', status='BLOCKED',
        dataset_kind=dataset_kind, reason_codes=[], sources={}, dataset_id=None, dataset_manifest=None,
        alignment=None, provenance_sha256=None, qualification='DATA_NOT_QUALIFIED', historical_validation='PENDING',
        historical_comparisons='NOT_RUN', exness='BLOCKED', signal='WAIT', execution_allowed=False, safety=safety())
    try:
        volumes = {}; originals = {}
        for tf,path in paths.items():
            require(path.is_file() and not path.is_symlink() and all(not p.is_symlink() for p in path.parents), 'SOURCE_UNAVAILABLE_OR_UNSAFE')
            before = file_fingerprint(path)
            require(before == {k:expected[tf][k] for k in ('sha256','byte_count')}, 'SOURCE_FINGERPRINT_MISMATCH')
            scan = stream_archive(path, timeframe=tf, frame_spec=spec['frames'][tf], source=spec['source'])
            count,volumes[tf] = auxiliary_fields(path)
            report['sources'][tf] = dict(expected=expected[tf], observed=before, row_count=count, scan=scan,
                acquisition='OPERATOR_SUPPLIED_LOCAL_EXPORT_NOT_AUTHENTICATED', timestamp_basis='PARSED_UTC_NOT_PROVIDER_VERIFIED')
            require(count==expected[tf]['row_count'] and scan['row_count']==count, 'SOURCE_ROW_COUNT_MISMATCH')
            require(scan['status']=='PASS', 'SOURCE_CANDLE_INTEGRITY_FAILED')
            require(file_fingerprint(path)==before, 'SOURCE_CHANGED_DURING_INTAKE')
            originals[tf] = before
        # Snapshot exact originals in a new private directory; existing importer stays unchanged.
        (root/'source').mkdir()
        for tf,path in paths.items():
            raw = read_bytes(path)
            require(sha256(raw).hexdigest()==originals[tf]['sha256'] and len(raw)==originals[tf]['byte_count'], 'SOURCE_CHANGED_DURING_INTAKE')
            _write_bytes(root/'source'/(tf.lower()+'.csv'), raw)
        write_new(root/'import-spec.json', spec)
        imported = prepare_package(root/'import-spec.json', root/'candidate-package')
        require(imported['candidate_available'], 'NORMALIZED_CANDIDATE_UNAVAILABLE')
        manifest = root/'candidate-package/candidate-manifest.json'
        dataset = load_dataset(manifest)
        binding = dict(binding_version=1, dataset_id=digest(dataset.metadata),
                       manifest_sha256=dataset.metadata['manifest_sha256'], broker='EXNESS')
        write_new(root/'broker-binding.json', binding)
        inputs = dict(import_spec_path=root/'candidate-package/import-spec.json', broker_binding_path=root/'broker-binding.json')
        provenance = assess_historical_provenance(manifest, **inputs)
        validate_provenance_assessment(provenance, manifest, **inputs)
        require(not provenance['input_errors'], 'PREPARED_EVIDENCE_REFERENCE_INVALID')
        audit = comparison(dataset, volumes, provenance['broker_comparison'])
        write_new(root/'alignment-audit.json', hashed(audit))
        write_new(root/'provenance-assessment.json', provenance)
        write_new(root/'provenance-assessment.txt', provenance_text(provenance))
        for tf,path in paths.items():
            require(file_fingerprint(path)==originals[tf], 'SOURCE_CHANGED_DURING_INTAKE')
        report.update(status='EVIDENCE_PREPARED', dataset_id=digest(dataset.metadata),
            dataset_manifest='candidate-package/candidate-manifest.json', alignment=hashed(audit)['sha256'],
            provenance_sha256=provenance['sha256'],
            mechanical_status='CONFLICTS' if audit['mismatch_count'] or audit['tick_volume_mismatch_count'] or provenance['broker_comparison']['closed_quote_conflicts'] else
                'INCOMPLETE_COMPARISON' if audit['uncovered_m5_bars'] else 'LOCAL_COMPARISONS_REPRODUCED',
            reason_codes=['INDEPENDENT_QUALIFICATION_REQUIRED','CALENDAR_FINALITY_FEED_BASIS_CORRECTIONS_UNRESOLVED'])
        # Existing assistant issues and qualification gates remain visible, including legitimate contradictions.
        report['import_issue_codes'] = sorted({i['code'] for i in imported['issues']})
        artifacts = {p.relative_to(root).as_posix():file_fingerprint(p)['sha256'] for p in sorted(root.rglob('*')) if p.is_file()}
        report['artifact_hashes'] = artifacts
    except (ValueError, OSError, KeyError, TypeError, OverflowError, csv.Error) as exc:
        report['reason_codes'] = sorted(set(report['reason_codes']) | {getattr(exc,'code','INTAKE_INPUT_OR_ARTIFACT_INVALID')})
        report['error_detail'] = str(exc) if isinstance(exc,ValueError) and re.fullmatch('[A-Z0-9_]+',str(exc)) else 'INPUT_UNAVAILABLE_OR_CHANGED'
        report['status'] = 'BLOCKED'
    result = hashed(report)
    write_new(root/'intake-report.json', result)  # Completion record published last; no result means incomplete.
    return result
