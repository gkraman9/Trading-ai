"""Live read-only observation, with descriptive facts separate from eligibility gates."""
from dataclasses import asdict,is_dataclass
from datetime import datetime,timedelta,timezone
from pathlib import Path
from threading import Lock,Event,Thread
from types import SimpleNamespace
import json,os
from copy import deepcopy
from time import perf_counter
from iat.live_market_view import calendar_signature,gate_fingerprint,session_state,formal_artifact,envelope as live_view_envelope,unavailable as live_view_unavailable,seal_presentation
from iat.analysis import validate_candles
from iat.mt5_data import get_candle_snapshot,MarketDataError
from iat.quality import ClockGuard,assess_candles
from iat.intelligence.models import IntelligenceConfig,iso
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.engine import frame_report,_finite_tree
from iat.intelligence.context import context_at,derive
from iat.intelligence import confluence
from iat.intelligence.multi_timeframe import align
from iat.intelligence.candles import prefix
from iat.intelligence.scenario_assessment import assess_scenarios,validate_scenario_assessment
from iat.intelligence.scenario_transitions import assess_scenario_transition
from iat.intelligence.strategy_replay import digest
from iat.historical_replay import safety


def _report_tree(value):
    """Preserve typed research fields as JSON primitives; never stringify unknown objects."""
    if is_dataclass(value) and not isinstance(value,type):
        return _report_tree(asdict(value))
    if isinstance(value,dict):
        if not all(isinstance(k,str) for k in value):raise TypeError('Non-string report key')
        return {k:_report_tree(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [_report_tree(v) for v in value]
    if value is None or type(value) in (str,bool,int,float):
        return value
    raise TypeError('Unsupported report value')


class ShadowLog:
    """Single observer writer, new private directory outside repository, append-only JSONL."""
    def __init__(self,directory):
        root=Path(directory)
        repo=Path(__file__).resolve().parents[1]
        if root.resolve().is_relative_to(repo) or root.exists() or root.is_symlink() or any(p.is_symlink() for p in root.parents):
            raise ValueError('New log directory outside repository required')
        root.mkdir(parents=True,exist_ok=False);self.root=root;self.last_source=None;self.previous=None
        for name in ('raw-candles.jsonl','research.jsonl'):(root/name).open('xb').close()

    def append(self,report,raw):
        source_id=digest(raw)
        if source_id!=self.last_source:
            self._append('raw-candles.jsonl',dict(log_version=1,source_id=source_id,raw=raw))
            self.last_source=source_id
        entry=dict(log_version=1,previous_entry_sha256=self.previous,source_id=source_id,report=report)
        entry['sha256']=digest(entry);self._append('research.jsonl',entry);self.previous=entry['sha256']

    def _append(self,name,value):
        data=(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        with (self.root/name).open('ab') as f:f.write(data);f.flush();os.fsync(f.fileno())


def base(at=None,code='OBSERVER_STARTING'):
    result=dict(report_version=1,model_version='IAT_LIVE_OBSERVER_V1',symbol='XAUUSD',
        acquired_at_utc=at,acquired_at_local=datetime.fromisoformat(at).astimezone().isoformat() if at else None,feed_status='DATA_UNAVAILABLE',research_assessment='DATA_UNAVAILABLE',
        source='LOCAL_MT5_READ_ONLY_NOT_HISTORICAL_EXPORT_BINDING',read_only_market_data_access=True,
        timestamp_basis='MT5_API_DOCUMENTED_UTC_EPOCH_NOT_BROKER_WALL_CLOCK',broker_server_wall_clock=None,
        quote=None,cutoffs={},observations={},scenario=assess_scenarios(None),transition=None,
        reasoning=['Validated observations unavailable; do not infer market direction.'],reason_codes=[code],
        ai_model={'status':'DISABLED','mode':'DETERMINISTIC_EXPLANATION','reason_codes':[]},
        qualification='DATA_NOT_QUALIFIED',exness='BLOCKED',historical_validation='PENDING',
        historical_comparisons='NOT_RUN',signal='WAIT',execution_allowed=False,broker_access=False,
        orders_requested=0,profitability_tested=False,mode='READ_ONLY_SHADOW',safety=safety(),
        limitations=['SESSION_ASSURANCE_SEPARATE_FROM_DESCRIPTIVE_OBSERVATIONS','NO_FORECAST_PROBABILITY_OR_EXECUTION',
            'LIVE_FEED_NOT_BOUND_TO_HISTORICAL_EXPORT','BROKER_SERVER_WALL_CLOCK_UNAVAILABLE'])
    result['snapshot_id']=digest(result)
    return result


def research_label(scenario):
    validate_scenario_assessment(scenario)
    if scenario['status']!='ASSESSED':return 'WAIT'
    selected=scenario['selected_hypothesis']
    if selected.startswith('BULLISH_'):return 'BUY_SCENARIO'
    if selected.startswith('BEARISH_'):return 'SELL_SCENARIO'
    return 'WAIT'


def presentation_adapter(adapter,report):
    """Optional in-process formatter. No bundled LLM/network client or credential configuration.

    Only selects existing statements/IDs; free text, new evidence or a changed
    assessment is rejected. Default is honestly DISABLED, not simulated AI.
    """
    if adapter is None:return
    allowed=sorted({e['id'] for e in report['scenario']['evidence_index']})
    payload=dict(assessment=report['research_assessment'],evidence_ids=allowed,statements=report['reasoning'])
    try:
        out=adapter(json.loads(json.dumps(payload)))
        if (not isinstance(out,dict) or set(out)!={'assessment','evidence_ids','statements'}
            or out['assessment']!=payload['assessment'] or not isinstance(out['evidence_ids'],list)
            or not all(isinstance(e,str) for e in out['evidence_ids']) or not set(out['evidence_ids'])<=set(allowed)
            or not isinstance(out['statements'],list) or not out['statements'] or not all(s in payload['statements'] for s in out['statements'])):
            raise ValueError('Interpretation rejected')
        report['ai_model']=dict(status='ACTIVE',mode='VALIDATED_PRESENTATION_ONLY',reason_codes=[],presentation=out)
    except Exception:
        report['ai_model']=dict(status='UNAVAILABLE',mode='DETERMINISTIC_EXPLANATION',reason_codes=['MODEL_UNAVAILABLE_OR_INTERPRETATION_REJECTED'])


class LiveObserver:
    def __init__(self,provider,log,*,calendar=None,clock=None,interval=10,model_adapter=None):
        if type(interval) is not int or not 2<=interval<=60:raise ValueError('Refresh must be 2..60 seconds')
        self.provider=provider;self.log=log;self.calendar=calendar;self.interval=interval;self.model_adapter=model_adapter
        self.clock=ClockGuard(clock or (lambda:datetime.now(timezone.utc)))
        self.lock=Lock();self.poll_lock=Lock();self.cached=base();self.previous=None;self.stop=Event();self.thread=None;self.lifecycle_lock=Lock()
        self._closed_cache=None;self._live_publication=None
        self.analysis_computations=0;self.analysis_cache_hits=0;self.analysis_invalidations=0

    def _quote(self, cutoff):
        # Optional read-completion protocol; legacy provider APIs stay compatible.
        observe = getattr(self.provider, 'quote_observed', None)
        return observe(self.clock) if callable(observe) else self.provider.quote(cutoff)

    def step(self):
        with self.poll_lock:
            began=perf_counter();cache_hit=False
            r=base();raw={}
            try:
                started=self.clock();r=base(iso(started));self.provider.preflight()
                quote=self._quote(started);r['quote']=quote
                shots={tf:get_candle_snapshot('XAUUSD',tf,count,mt5=self.provider,clock=self.clock)
                       for tf,count in (('M1',500),('M5',100))}
                now=self.clock();r['quote']=self._quote(now)
                if callable(getattr(self.provider,'quote_observed',None)):now=self.clock()
                r['acquired_at_utc']=iso(now);r['acquired_at_local']=now.astimezone().isoformat();r['acquisition_started_at_utc']=iso(started)
                # Recheck both frames at one clock after both fetches.
                for tf,s in shots.items():
                    q=assess_candles(s.candles,tf,now,observed_finality=True)
                    if not q.valid:raise MarketDataError('Snapshot invalid',report=q)
                if (now-started).total_seconds()>10:raise MarketDataError('Acquisition too slow','ACQUISITION_LATENCY_EXCEEDED')
                at=datetime.fromisoformat(shots['M1'].candles[-1]['timestamp'])+timedelta(minutes=1)
                rows={tf:prefix(s.candles,tf,at) for tf,s in shots.items()}
                for tf in rows:
                    q=assess_candles(rows[tf],tf,at,observed_finality=True)
                    if not q.valid:raise MarketDataError('Causal snapshot invalid',report=q)
                config=IntelligenceConfig();ctx_config=ContextConfig()
                gate=gate_fingerprint(self.calendar,now)
                cache_key=digest([rows,iso(at),asdict(config),asdict(ctx_config),
                    calendar_signature(self.calendar),gate,getattr(self.provider,'timestamp_basis',None),'VALIDATED_LIVE'])
                if self._closed_cache is not None and self._closed_cache.get('cacheable',True) and self._closed_cache['key']==cache_key:
                    cache_hit=True;self.analysis_cache_hits+=1
                    r.update(deepcopy(self._closed_cache['payload']))
                else:
                    self.analysis_computations+=1
                    # Existing pure detectors provide observations, not a forged eligible ContextReport.
                    frames={tf:frame_report(tuple(validate_candles(rs)),tf,at,config) for tf,rs in rows.items()}
                    alignment=align(frames,iso(at))
                    descriptive=SimpleNamespace(symbol='XAUUSD',frames=frames,alignment=alignment,configuration_sha256=config.digest)
                    evidence,registry,interpretations,facts,zones=derive(descriptive,{tf:tuple(validate_candles(rs)) for tf,rs in rows.items()},ctx_config)
                    interpretations=_report_tree(interpretations)
                    _finite_tree(dict(frames={tf:asdict(f) for tf,f in frames.items()},context=interpretations,facts=facts))
                    # Matching overlapping complete groups is a diagnostic; never replace native M5.
                    one={bar['timestamp']:bar for bar in rows['M1']};compared=0
                    for five in rows['M5']:
                        t=datetime.fromisoformat(five['timestamp']);group=[one.get(iso(t+timedelta(minutes=i))) for i in range(5)]
                        if not all(group):continue
                        compared+=1;expected=dict(open=group[0]['open'],high=max(b['high'] for b in group),low=min(b['low'] for b in group),close=group[-1]['close'])
                        if any(abs(expected[k]-five[k])>config.epsilon for k in expected):raise MarketDataError('Frame mismatch','M1_M5_OHLC_MISMATCH')
                    if not compared:raise MarketDataError('No overlapping complete groups','M1_M5_COMPARISON_UNAVAILABLE')
                    context=context_at('XAUUSD',rows['M1'],rows['M5'],at,provenance='VALIDATED_LIVE',calendar=self.calendar,observed_finality=True)
                    if context.symbol!='XAUUSD' or context.provenance!='VALIDATED_LIVE':raise MarketDataError('Unexpected context source','CONTEXT_SOURCE_INCONSISTENT')
                    scenario=assess_scenarios(context,as_of=at);validate_scenario_assessment(scenario)
                    r.update(feed_status='CONNECTED',research_assessment=research_label(scenario),scenario=scenario,
                        reason_codes=scenario['reason_codes'],reasoning=list(scenario['source_explanation'] or scenario['explanation']),
                        cutoffs={tf:f.data_as_of for tf,f in frames.items()},analysis_at_utc=iso(at),
                        acquisition_seconds=(now-started).total_seconds(),
                        analysis_scope='SESSION_GATED_CONTEXT' if context.data_quality['valid'] else 'DESCRIPTIVE_UNVERIFIED_SESSION',
                        observations=dict(frames={tf:asdict(f) for tf,f in frames.items()},context=interpretations,
                            evidence=[asdict(e) for e in evidence],source_registry=registry,facts=facts,
                            alignment=asdict(alignment),comparison=dict(complete_groups=compared,ohlc_mismatches=0),
                            configuration_hashes=dict(intelligence=config.digest,context=ctx_config.digest)),
                        candle_quality={tf:s.quality.to_dict() for tf,s in shots.items()},
                        forming_candles=dict(requested=False,position_zero_excluded=True),
                        candle_age_seconds={tf:(now-datetime.fromisoformat(f.data_as_of)).total_seconds() for tf,f in frames.items()})
                    r['observations']['confluence']=context.confluence if context.data_quality['valid'] else confluence.evaluate(evidence,ctx_config,context.context)
                    r['reasoning']=[f"{tf}: {f.structure.classification} structure; {len(f.confirmed_pivots)} confirmed swings; "
                        f"momentum {interpretations[tf]['momentum']['regime']}; volatility {interpretations[tf]['volatility']['regime']}; last closed candle {f.data_as_of}."
                        for tf,f in frames.items()]+r['reasoning']
                    if not context.data_quality['valid']:
                        r['reasoning']=['WAIT: session/data eligibility is not established. Descriptive observations are not eligible directional scenarios.']+r['reasoning']
                    self._closed_cache=dict(key=cache_key,gate=gate,rows=deepcopy(rows),
                        payload={k:deepcopy(r[k]) for k in ['feed_status', 'research_assessment', 'scenario', 'reason_codes', 'reasoning', 'cutoffs', 'analysis_at_utc', 'analysis_scope', 'observations', 'forming_candles']},
                        formal=formal_artifact(r,context,self.calendar))
                    self._closed_cache['cacheable']='LIVE_CONTEXT_BINDING_INVALID' not in self._closed_cache['formal']['formal_context']['reason_codes']
                complete=getattr(self.provider,'acquisition_complete',None)
                if callable(complete):
                    complete(started_at=started,quote_at=r['quote']['observed_at_utc'])
                    completed=self.clock();r['acquired_at_utc']=iso(completed);r['acquired_at_local']=completed.astimezone().isoformat()
                scenario=r['scenario']
                r['acquisition_seconds']=(now-started).total_seconds()
                r['candle_quality']={tf:s.quality.to_dict() for tf,s in shots.items()}
                r['candle_age_seconds']={tf:(now-datetime.fromisoformat(stamp)).total_seconds() for tf,stamp in r['cutoffs'].items()}
                if self.previous and self.previous['analysis_at']==scenario['analysis_at'] and self.previous['sha256']!=scenario['sha256']:
                    raise MarketDataError('Closed evidence revised','CLOSED_CANDLE_REVISION_DETECTED')
                r['transition']=assess_scenario_transition(self.previous,scenario) if self.previous is None or self.previous['analysis_at']!=scenario['analysis_at'] else None
                presentation_adapter(self.model_adapter,r)
                self.previous=scenario
            except Exception as exc:
                code=getattr(exc,'code',None)
                if code is None and hasattr(exc,'report'):code=exc.report.diagnostics[0].code
                code=code if isinstance(code,str) and code.replace('_','').isalnum() and code.upper()==code else 'LIVE_OBSERVATION_UNAVAILABLE'
                # Do not keep an old directional interpretation after failure.
                complete=getattr(self.provider,'acquisition_complete',None)
                if callable(complete):
                    try:complete(code)
                    except Exception:pass
                r=base(r['acquired_at_utc'],code)
                if code!='CLOSED_CANDLE_REVISION_DETECTED':self.previous=None
                presentation_adapter(self.model_adapter,r)
            connection=getattr(self.provider,'snapshot',None)
            if callable(connection):r['connection']=connection()
            raw=dict(getattr(self.provider,'raw',{}))
            try:
                r=_report_tree(r)
                _finite_tree(r)
                r['snapshot_id']=digest({k:v for k,v in r.items() if k!='snapshot_id'})
            except (ValueError,TypeError,OverflowError,RecursionError):
                r=base(r['acquired_at_utc'],'SNAPSHOT_SERIALIZATION_FAILED');self.previous=None
            try:self.log.append(r,raw)
            except Exception:
                r=base(r['acquired_at_utc'],'SHADOW_LOG_FAILED');r['snapshot_id']=digest({k:v for k,v in r.items() if k!='snapshot_id'});self.previous=None
            if r['feed_status']!='CONNECTED':
                if self._closed_cache is not None:self.analysis_invalidations+=1
                self._closed_cache=None
            publication=dict(snapshot_id=r['snapshot_id'],cache_key=self._closed_cache['key'] if self._closed_cache else None,
                gate=self._closed_cache['gate'] if self._closed_cache else None,
                formal=deepcopy(self._closed_cache['formal']) if self._closed_cache else None,
                rows=deepcopy(self._closed_cache['rows']) if self._closed_cache else None,
                runtime=dict(closed_source_fingerprint=self._closed_cache['key'] if self._closed_cache else None,quote_max_age_seconds=getattr(self.provider,'quote_max_age_seconds',2),
                    broker_point=getattr(self.provider,'_point',None),processing_ms=round((perf_counter()-began)*1000,3),cache_hit=cache_hit,
                    analysis_computations=self.analysis_computations,cache_hits=self.analysis_cache_hits,
                    cache_invalidations=self.analysis_invalidations,
                    demo_checks=deepcopy(getattr(self.provider,'diagnostics',{})),
                    connection=deepcopy(r.get('connection'))))
            with self.lock:
                self.cached=json.loads(json.dumps(r,allow_nan=False));self._live_publication=publication
            return json.loads(json.dumps(r,allow_nan=False))

    def latest(self):
        with self.lock:
            result=json.loads(json.dumps(self.cached))
            if self.stop.is_set():return base(result['acquired_at_utc'],'OBSERVER_STOPPING_OR_STOPPED')
            connection=getattr(self.provider,'snapshot',None)
            if callable(connection):
                status=connection()  # Memory-only; HTTP never calls the SDK.
                old=result.get('connection',{})
                if status['state']!='CONNECTED' or old.get('connection_generation')!=status['connection_generation']:
                    result=base(result['acquired_at_utc'],'CONNECTION_FRESH_ACQUISITION_REQUIRED' if status['state']=='CONNECTED' else (status.get('status_reason_code') or 'LIVE_CONNECTION_NOT_CURRENT'))
                    result['connection']=status
                    result['snapshot_id']=digest({k:v for k,v in result.items() if k!='snapshot_id'})
                    return result
            try:
                now=self.clock();at=result['acquired_at_utc']
                if at is not None and (now-datetime.fromisoformat(at)).total_seconds()>max(30,self.interval*2):
                    return base(iso(now),'OBSERVER_STALLED')
                if result['quote'] is not None and (now-datetime.fromisoformat(result['quote']['observed_at_utc'])).total_seconds()>30:
                    return base(iso(now),'TICK_STALE')
            except Exception:return base(None,'CLOCK_UNAVAILABLE_OR_BACKWARD')
            return result

    def market_intelligence(self):
        # HTTP reads never touch the provider or rebuild analytical reports.
        snapshot=self.latest()
        with self.lock:publication=deepcopy(self._live_publication)
        try:
            now=self.clock();state=session_state(self.calendar,now)
            if publication is None or publication['snapshot_id']!=snapshot['snapshot_id']:
                result=live_view_unavailable((snapshot.get('reason_codes') or ['LIVE_SOURCE_NOT_CURRENT'])[0])
                if publication is not None:result['runtime']=publication['runtime']
                if 'connection' in snapshot:
                    c=snapshot['connection'];result['runtime']['connection']=c
                    result['runtime']['demo_checks']={k:c.get(k) for k in ('connected','demo_verified','terminal_trading_disabled','python_api_trading_disabled','symbol_visible')}
                    result['runtime']['broker_point']=None
                return seal_presentation(result)
            if publication['rows'] is not None:
                for tf,rows in publication['rows'].items():
                    quality=assess_candles(rows,tf,now,observed_finality=True)
                    if not quality.valid:
                        result=live_view_unavailable(quality.diagnostics[0].code);result['runtime']=publication['runtime']
                        return seal_presentation(result)
            if publication['gate'] is not None and gate_fingerprint(self.calendar,now)!=publication['gate']:
                result=live_view_unavailable('SESSION_STATE_CHANGED')
                result['session']=state;result['runtime']=publication['runtime'];return seal_presentation(result)
            result=live_view_envelope(snapshot,publication['formal'],publication['runtime'],state,now)
            return seal_presentation(result)
        except Exception:return seal_presentation(live_view_unavailable('LIVE_PRESENTATION_UNAVAILABLE'))

    def start(self):
        with self.lifecycle_lock:
            if self.thread is not None and self.thread.is_alive():raise ValueError('Observer already started')
            with self.poll_lock:
                if self._closed_cache is not None:self.analysis_invalidations+=1
                self._closed_cache=None;self.previous=None
                with self.lock:self.cached=base();self._live_publication=None
            self.stop.clear()
            def run():
                try:
                    while not self.stop.is_set():
                        try:self.step()
                        except Exception:
                            failure=base(None,'OBSERVER_POLL_FAILED');self.previous=None
                            try:self.log.append(failure,{})
                            except Exception:failure=base(None,'SHADOW_LOG_FAILED')
                            if self._closed_cache is not None:self.analysis_invalidations+=1
                            self._closed_cache=None
                            with self.lock:self.cached=failure;self._live_publication=None
                        delay=getattr(self.provider,'retry_delay',None)
                        self.stop.wait(delay(self.interval) if callable(delay) else self.interval)
                finally:
                    close=getattr(self.provider,'close_owner',None)
                    if callable(close):close()
            self.thread=Thread(target=run,name='iat-read-only-observer',daemon=True);self.thread.start()

    def close(self):
        with self.lifecycle_lock:
            self.stop.set();thread=self.thread
        if thread is not None:thread.join(timeout=12)
        # Never call native shutdown from the joining thread. A blocked native call
        # retains ownership; start() refuses overlap until the old worker exits.
