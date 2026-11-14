"""Versioned, causal analytical decisions; no trade proposals or profitability metrics."""
from dataclasses import asdict,dataclass
from datetime import datetime,timedelta
import json
from hashlib import sha256
from iat.intelligence.models import iso


@dataclass(frozen=True)
class Decision:
    decision_version: int
    timestamp_utc: str
    data_quality_status: str
    selected_hypothesis: str
    abstained: bool
    supporting_evidence: tuple[str,...]
    contradictory_evidence: tuple[str,...]
    reason_codes: tuple[str,...]
    abstention_reasons: tuple[str,...]
    evidence_ids: tuple[str,...]
    new_evidence: tuple[str,...]
    evidence_revisions: tuple[dict,...]
    new_events: tuple[str,...]
    unique_event_count: int
    unique_evidence_count: int
    hypothesis_revisions: tuple[str,...]
    withdrawn_hypotheses: tuple[str,...]
    timeframe_context: dict
    context_evidence: tuple[dict,...]
    mode: str = 'READ_ONLY_SHADOW'
    signal: str = 'WAIT'
    execution_allowed: bool = False
    phase: str = 'UNSCOPED'

    def __post_init__(self):
        if type(self.decision_version) is not int or self.decision_version!=1 or self.mode!='READ_ONLY_SHADOW' or self.signal!='WAIT' or self.execution_allowed is not False:
            raise ValueError('Unsafe DecisionLog record')
        if self.phase not in ('UNSCOPED','WARMUP','EVALUATION'):raise ValueError('Invalid DecisionLog phase')
        at=datetime.fromisoformat(self.timestamp_utc)
        iso(at)
        if at.utcoffset()!=timedelta(0):raise ValueError('DecisionLog requires UTC')
        ids={e['id'] for e in self.context_evidence}
        if ids!=set(self.evidence_ids) or not (set(self.supporting_evidence)|set(self.contradictory_evidence)|set(self.new_evidence))<=ids:
            raise ValueError('Unresolved evidence in DecisionLog')
        for revision in self.evidence_revisions:
            if revision['evidence_id'] not in ids:raise ValueError('Unresolved revision in DecisionLog')
        for item in self.context_evidence:
            if datetime.fromisoformat(item['available_at'])>at:
                raise ValueError('Future evidence in DecisionLog')
        for tf in ('m1_as_of','m5_as_of'):
            value=self.timeframe_context.get(tf)
            if value is not None and datetime.fromisoformat(value)>at:
                raise ValueError('Future timeframe context in DecisionLog')


def from_replay(entry):
    report=entry['report']
    selected=report['confluence']['selected_hypothesis']
    blocked=not report['data_quality']['valid']
    abstained=blocked or bool(report['abstention_reasons']) or selected=='NO_CLEAR_DIRECTIONAL_HYPOTHESIS'
    if abstained:selected='NO_CLEAR_DIRECTIONAL_HYPOTHESIS'
    hypothesis=next((h for h in report['hypotheses'] if h['hypothesis_type']==selected),None)
    reasons=set(report['abstention_reasons'])|{d['code'] for d in report['data_quality']['diagnostics'] if d['code']!='DATA_VALID'}
    abstention=set(report['abstention_reasons'])
    if blocked:abstention|={d['code'] for d in report['data_quality']['diagnostics'] if d['severity']=='ERROR' or d['code']=='SESSION_CLOSED'}
    if not abstention and abstained:abstention.add('NO_CLEAR_DIRECTIONAL_HYPOTHESIS')
    reasons|=abstention
    return Decision(1,report['analysis_at'],report['data_quality']['status'],selected,abstained,
        tuple(hypothesis['supporting_evidence']) if hypothesis else (),
        tuple(hypothesis['contradictory_evidence']) if hypothesis else (),tuple(sorted(reasons)),tuple(sorted(abstention)),
        tuple(sorted(e['id'] for e in report['evidence'])),tuple(entry['new_evidence']),
        tuple(entry['event_revisions']),tuple(entry['new_events']),entry['unique_event_count'],
        entry['unique_evidence_count'],tuple(entry['hypothesis_revisions']),tuple(entry['withdrawn_hypotheses']),
        report['context'],tuple(report['evidence']))


@dataclass(frozen=True)
class DecisionLog:
    log_version: int
    configuration_hashes: dict
    entries: tuple[Decision,...]

    def __post_init__(self):
        if type(self.log_version) is not int or self.log_version!=1:raise ValueError('Unsupported DecisionLog')
        if any(b.timestamp_utc<=a.timestamp_utc for a,b in zip(self.entries,self.entries[1:])):
            raise ValueError('DecisionLog must be strictly chronological')

    def to_dict(self):return asdict(self)

    @property
    def sha256(self):
        return sha256(json.dumps(self.to_dict(),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
