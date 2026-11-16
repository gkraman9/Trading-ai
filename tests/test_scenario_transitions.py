"""Labeled synthetic OHLC; adversarial copies are never market-validation evidence."""
import json,unittest
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from datetime import timedelta
from iat.intelligence.scenario_assessment import scenario_at,assess_scenarios,validate_scenario_assessment
from iat.intelligence.scenario_transitions import assess_scenario_transition,validate_scenario_transition,replay_scenario_transitions,STATES
from iat.intelligence.strategy_replay import digest
from test_context_engine import two_frames,CONFIG,P7
from test_intelligence_patterns import START,rows
from test_intelligence_engine import WAVE

def s(a,b,t):return scenario_at('SYNTHETIC_XAUUSD',a,b,t,config=CONFIG,intelligence_config=P7)
def fixtures():
 a,b,t=two_frames();p=s(a,b,t)
 a.append(dict(timestamp=t.isoformat(),open=111.7,high=112.85,low=111.65,close=112.8));q=s(a,b,t+timedelta(minutes=1))
 a.append(dict(timestamp=(t+timedelta(minutes=1)).isoformat(),open=112.,high=112.9,low=111.95,close=112.));r=s(a,b,t+timedelta(minutes=2))
 yield 'support',[p,q,r]
 a,b,t=two_frames();a[-1].update(open=112,high=113.05,low=110.95,close=112);p=s(a,b,t)
 for n,price in enumerate((113.2,113.3)):
  a.append(dict(timestamp=(t+timedelta(minutes=n)).isoformat(),open=price,high=price+.05,low=price-.05,close=price))
  if n==0:q=s(a,b,t+timedelta(minutes=1))
 r=s(a,b,t+timedelta(minutes=2));yield 'new',[p,q,r]
 for name,high,low in [('replace',121.,103.),('invalidate',120.,102.)]:
  a=rows(WAVE+[112.1+i*.1 for i in range(7)]+[112,112]);b=rows(WAVE+[112,112],'M5')
  for frame in (a,b):
   for bar in frame:bar.update(high=bar['close']+5,low=bar['close']-5)
  for i,bar in enumerate(b):bar['timestamp']=(START+timedelta(minutes=5*i-85)).isoformat()
  a[28].update(high=high,low=low);b[21].update(high=high,low=low)
  yield name,[s(a,b,START+timedelta(minutes=n)) for n in (29,30)]

@lru_cache(maxsize=1)
def cases():
    return dict(fixtures())


def rehash(report):
    report['sha256']=digest({k:v for k,v in report.items() if k!='sha256'})
    return report


def audit():
    result={}
    for name,sequence in cases().items():
        events=list(replay_scenario_transitions(sequence))
        result[name]=[dict(transition_id=r['transition_id'],classification=r['classification'],
            reason_codes=r['reason_codes'],sha256=r['sha256'],assessment_ids=r['assessment_ids'],
            invalidation_evidence=r['invalidation_evidence']) for r in events]
    p=cases()['support'][0]
    extras={'missing':[p,None,p], 'duplicate':[p,p], 'reversed':list(reversed(cases()['support'])),
        'blocked':[p,assess_scenarios(None)]}
    for name,seq in extras.items():
        result[name]=[dict(classification=r['classification'],reason_codes=r['reason_codes'],
            transition_id=r['transition_id'],sha256=r['sha256']) for r in replay_scenario_transitions(seq)]
    counts={k:sum(e['classification']==k for seq in result.values() for e in seq) for k in sorted(STATES)}
    return dict(audit_version=1,provenance='LABELED_SYNTHETIC_OHLC_ONLY',cases=result,counts=counts,
        historical_validation='PENDING',historical_comparisons='NOT_RUN',exness='BLOCKED',
        mode='READ_ONLY_SHADOW',signal='WAIT',execution_allowed=False)


class ScenarioTransitionTests(unittest.TestCase):
    def pair(self,name='support',index=0):return deepcopy(cases()[name][index:index+2])
    def safe(self,r):
        self.assertTrue(validate_scenario_transition(r))
        self.assertEqual(r['sha256'],digest({k:v for k,v in r.items() if k!='sha256'}))
        self.assertEqual(r['mode'],'READ_ONLY_SHADOW');self.assertEqual(r['signal'],'WAIT')
        for key in ('execution_allowed','broker_access','profitability_tested'):self.assertIs(r[key],False)
        self.assertEqual(r['orders_requested'],0);self.assertEqual(r['exness'],'BLOCKED')
        self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED')
        self.assertEqual(r['historical_validation'],'PENDING');self.assertEqual(r['historical_comparisons'],'NOT_RUN')
    def test_all_eight_states_from_upstream_generated_reports(self):
        found=set()
        for sequence in cases().values():
            for r in replay_scenario_transitions(sequence):self.safe(r);found.add(r['classification'])
        for r in (assess_scenario_transition(None,None),):self.safe(r);found.add(r['classification'])
        self.assertEqual(found,STATES)
    def test_unchanged_upstream_validation_and_inputs(self):
        p,c=self.pair();before=deepcopy([p,c]);r=assess_scenario_transition(p,c)
        self.assertEqual([p,c],before)
        for snapshot in (p,c):self.assertTrue(validate_scenario_assessment(snapshot))
        self.assertEqual(r['inputs']['previous']['assessment'],p)
    def test_new_then_persisting(self):
        seq=cases()['new'];self.assertEqual([r['classification'] for r in replay_scenario_transitions(seq)],['ABSTAINED','NEW','PERSISTING'])
    def test_support_increase_then_decrease_is_not_invalidation(self):
        events=list(replay_scenario_transitions(cases()['support']))
        self.assertEqual([r['classification'] for r in events],['ABSTAINED','STRENGTHENING','WEAKENING'])
        for r in events:self.assertEqual(r['invalidation_evidence'],[])
    def test_invalidation_requires_traceable_new_confirmed_m5_pivots(self):
        p,c=self.pair('invalidate');r=assess_scenario_transition(p,c);self.safe(r)
        self.assertEqual(r['classification'],'INVALIDATED');proof=r['invalidation_evidence'][0]
        self.assertGreater(proof['available_at'],p['analysis_at']);self.assertLessEqual(proof['available_at'],c['analysis_at'])
        self.assertGreaterEqual(len(proof['source_references']),4)
        self.assertTrue(all(x.startswith('M5:PIVOT:') for x in proof['source_references']))
    def test_selection_change_without_opposing_structure_is_replacement(self):
        p,c=self.pair('replace');r=assess_scenario_transition(p,c)
        self.assertEqual(r['classification'],'REPLACED');self.assertFalse(r['invalidation_evidence'])
        self.assertNotEqual(r['scenario_identifiers']['previous'],r['scenario_identifiers']['current'])
    def test_scenario_identity_does_not_include_time_or_score(self):
        r=assess_scenario_transition(*self.pair());self.assertEqual(r['scenario_identifiers']['previous'],r['scenario_identifiers']['current'])
    def test_current_abstention_does_not_imply_invalidation(self):
        p,c=self.pair('new');r=assess_scenario_transition(c,p)
        self.assertEqual(r['classification'],'BLOCKED')
        # Same causal history can return to abstention on an adverse incomplete frame.
        a,b,t=two_frames();p=s(a,b,t)
        a.append(dict(timestamp=t.isoformat(),open=112,high=160,low=60,close=112))
        c=s(a,b,t+timedelta(minutes=1));r=assess_scenario_transition(p,c)
        self.assertEqual(c['status'],'ABSTAINED');self.assertEqual(r['classification'],'ABSTAINED');self.assertFalse(r['invalidation_evidence'])
    def test_quality_failure_is_blocked(self):
        a,b,t=two_frames();p=s(a,b,t);a[0]['high']=0;c=s(a,b,t+timedelta(minutes=1))
        self.assertEqual(c['status'],'BLOCKED');r=assess_scenario_transition(p,c);self.assertEqual(r['classification'],'BLOCKED');self.safe(r)
    def test_missing_previous_is_not_new(self):
        r=assess_scenario_transition(None,cases()['support'][0]);self.assertEqual(r['classification'],'ABSTAINED');self.safe(r)
    def test_missing_current_blocks(self):
        r=assess_scenario_transition(cases()['support'][0],None);self.assertEqual(r['classification'],'BLOCKED');self.safe(r)
    def test_duplicate_timestamp_blocks(self):
        p=cases()['support'][0];r=assess_scenario_transition(p,p);self.assertEqual(r['reason_codes'],['DUPLICATE_OBSERVATION_TIMESTAMP']);self.safe(r)
    def test_reversed_timestamp_blocks(self):
        p,c=self.pair();r=assess_scenario_transition(c,p);self.assertEqual(r['classification'],'BLOCKED');self.safe(r)
    def test_observation_gap_abstains(self):
        seq=cases()['support'];r=assess_scenario_transition(seq[0],seq[2]);self.assertEqual(r['reason_codes'],['OBSERVATION_GAP'])
    def test_missing_observation_resets_continuity(self):
        p,c=self.pair();out=list(replay_scenario_transitions([p,None,c]));self.assertEqual([r['classification'] for r in out],['ABSTAINED','BLOCKED','ABSTAINED'])
    def test_repeatability_and_prefix_equivalence(self):
        for seq in cases().values():
            full=list(replay_scenario_transitions(seq));self.assertEqual(full,list(replay_scenario_transitions(deepcopy(seq))))
            for n in range(len(seq)+1):self.assertEqual(full[:n],list(replay_scenario_transitions(seq[:n])))
    def test_future_append_cannot_change_previous_events(self):
        seq=cases()['support'];prefix=list(replay_scenario_transitions(seq[:2]));full=list(replay_scenario_transitions(seq));self.assertEqual(prefix,full[:2])
    def test_json_roundtrip_and_key_order(self):
        p,c=self.pair();r=assess_scenario_transition(p,c);self.safe(json.loads(json.dumps(r)))
        self.assertEqual(r,assess_scenario_transition(dict(reversed(list(p.items()))),dict(reversed(list(c.items())))))
    def test_no_network_broker_or_wall_clock_dependencies(self):
        import ast
        tree=ast.parse(Path('iat/intelligence/scenario_transitions.py').read_text())
        names=[node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        names += [a.name for node in ast.walk(tree) if isinstance(node,ast.Import) for a in node.names]
        self.assertFalse(any(x and any(bad in x.lower() for bad in ('metatrader','socket','requests','random','broker')) for x in names))
    def test_audit_matches_checked_in_golden(self):
        path=Path('docs/research_audits/scenario-transitions-synthetic-v1/audit.json')
        self.assertEqual(json.loads(path.read_text()),audit())
    def test_historical_label_cannot_enable_synthetic_replay(self):
        p,c=self.pair();c['provenance']='HISTORICAL_RESEARCH';rehash(c)
        self.assertEqual(list(replay_scenario_transitions([p,c]))[-1]['classification'],'BLOCKED')
    def test_upstream_insufficient_history_abstains(self):
        p=assess_scenarios(None);r=assess_scenario_transition(p,cases()['support'][0]);self.assertEqual(r['classification'],'BLOCKED')
        p=scenario_at('SYNTHETIC_XAUUSD',rows([100]*3),None,START+timedelta(minutes=3))
        r=assess_scenario_transition(p,cases()['support'][0]);self.assertEqual(r['classification'],'ABSTAINED')
    def test_malformed_inputs_fail_closed(self):
        for value in ({},[],object(),'invalid',{'sha256':'a'*64}):
            r=assess_scenario_transition(value,cases()['support'][0]);self.assertEqual(r['classification'],'BLOCKED');self.safe(r)
    def test_invalidation_not_available_without_condition(self):
        p,c=self.pair('invalidate')
        for h in p['ranked_hypotheses']:h['invalidation_conditions']=[]
        rehash(p);r=assess_scenario_transition(p,c);self.assertEqual(r['classification'],'REPLACED')
    def test_missing_configuration_abstains(self):
        p,c=self.pair();c['configuration_hashes']={};rehash(c)
        self.assertEqual(assess_scenario_transition(p,c)['classification'],'ABSTAINED')
    def test_duplicate_evidence_cannot_inflate_support(self):
        p,c=self.pair();c['evidence_index'].append(deepcopy(c['evidence_index'][0]));rehash(c)
        self.assertEqual(assess_scenario_transition(p,c)['classification'],'BLOCKED')


    def test_fresh_opposing_m1_choch_abstains_without_m5_invalidation(self):
        for mirror in (False,True):
            a,b,t=two_frames(mirror,True)
            p=s(a,b,t-timedelta(minutes=1));c=s(a,b,t)
            self.assertTrue(c['fresh_opposing_m1_choch'])
            r=assess_scenario_transition(p,c);self.safe(r)
            self.assertEqual(r['classification'],'ABSTAINED');self.assertEqual(r['invalidation_evidence'],[])
    def test_future_ohlc_is_not_in_earlier_assessment(self):
        a,b,t=two_frames();before=s(a,b,t)
        a.append(dict(timestamp=t.isoformat(),open=112,high=1000,low=1,close=900))
        self.assertEqual(before,s(a,b,t))
        self.assertEqual(assess_scenario_transition(None,before),assess_scenario_transition(None,s(a,b,t)))
    def test_unfinished_m5_cannot_invalidate_earlier_assessment(self):
        a,b,t=two_frames();before=s(a,b,t)
        # This M5 candle closes after t; even extreme prices are unavailable at t.
        b.append(dict(timestamp=(START+timedelta(minutes=20)).isoformat(),open=112,high=1000,low=1,close=2))
        self.assertEqual(before,s(a,b,t))
    def test_changed_scoring_version_abstains(self):
        p,c=self.pair()
        for h in c['ranked_hypotheses']:h['configuration_version']+=1
        rehash(c);r=assess_scenario_transition(p,c)
        self.assertEqual(r['classification'],'ABSTAINED');self.assertEqual(r['comparability']['status'],'INCOMPATIBLE')
    def test_changed_model_abstains(self):
        p,c=self.pair()
        for h in c['ranked_hypotheses']:h['model_version']='ANOTHER_RESEARCH_MODEL'
        rehash(c);self.assertEqual(assess_scenario_transition(p,c)['classification'],'ABSTAINED')
    def test_lost_invalidation_source_refs_cannot_prove_invalidation(self):
        p,c=self.pair('invalidate')
        for e in c['evidence_index']:
            if e['category']=='STRUCTURE' and e['timeframe']=='M5':e['references']=[]
        rehash(c);self.assertEqual(assess_scenario_transition(p,c)['classification'],'REPLACED')
    def test_old_structure_revision_does_not_establish_new_invalidation(self):
        p,c=self.pair('invalidate')
        for e in c['evidence_index']:
            if e['category']=='STRUCTURE' and e['timeframe']=='M5':e['available_at']=p['m1_m5_alignment']['m5_as_of']
        rehash(c);r=assess_scenario_transition(p,c)
        self.assertEqual(r['classification'],'ABSTAINED');self.assertFalse(r['invalidation_evidence'])
    def test_unknown_serialized_fields_rejected(self):
        r=assess_scenario_transition(None,None);r['approved']=False;rehash(r)
        with self.assertRaises(ValueError):validate_scenario_transition(r)
    def test_bad_checksum_rejected(self):
        r=assess_scenario_transition(*self.pair());r['sha256']='a'*64
        with self.assertRaises(ValueError):validate_scenario_transition(r)
    def test_tie_ranking_is_preserved(self):
        p,c=self.pair();r=assess_scenario_transition(p,c)
        self.assertEqual(r['inputs']['current']['assessment']['ranked_hypotheses'],c['ranked_hypotheses'])
        self.assertEqual(r['inputs']['current']['assessment']['selected_hypothesis'],c['selected_hypothesis'])


def add_output_tamper(name,change,case='support'):
    def test(self):
        r=assess_scenario_transition(*self.pair(case));change(r);rehash(r)
        with self.assertRaises((ValueError,TypeError,KeyError)):validate_scenario_transition(r)
    setattr(ScenarioTransitionTests,'test_rechecksummed_output_'+name,test)

for name,change in {
    'invalidated_without_proof':lambda r:r.update(classification='INVALIDATED'),
    'persisting_without_equal_support':lambda r:r.update(classification='PERSISTING'),
    'replaced_without_scenario_change':lambda r:r.update(classification='REPLACED'),
    'weakened_when_increasing':lambda r:r.update(classification='WEAKENING'),
    'unknown_state':lambda r:r.update(classification='TRADE'),
    'blocked_claiming_transition':lambda r:r.update(classification='BLOCKED'),
    'missing_evidence':lambda r:r['evidence_references'].update(current=[]),
    'wrong_reason':lambda r:r.update(reason_codes=['APPROVED']),
    'wrong_explanation':lambda r:r.update(explanation=['Guaranteed profit']),
    'authorization_flag':lambda r:r.update(approved=True),
    'unsafe_execution':lambda r:r.update(execution_allowed=True),
    'unsafe_signal':lambda r:r.update(signal='BUY'),
    'wrong_scenario_identity':lambda r:r['scenario_identifiers']['current'].update(scenario_id='a'*64),
    'wrong_timestamp':lambda r:r['observation_timestamps'].update(current=START.isoformat()),
    'wrong_digest':lambda r:r['assessment_ids'].update(current='a'*64),
    'wrong_event_id':lambda r:r.update(transition_id='SCENARIO_TRANSITION:'+'a'*64),
    'wrong_score':lambda r:r['support_comparison'].update(current_score=999),
    'wrong_configuration':lambda r:r['comparability']['method']['configuration_hashes'].update(context='a'*64),
    'wrong_input_digest':lambda r:r['inputs']['current'].update(input_digest='a'*64),
    'wrong_version':lambda r:r.update(transition_version=2),
}.items():add_output_tamper(name,change)
for name,change in {
    'missing_proof':lambda r:r.update(invalidation_evidence=[]),
    'future_proof':lambda r:r['invalidation_evidence'][0].update(available_at='2099-01-01T00:00:00+00:00'),
    'wrong_proof_references':lambda r:r['invalidation_evidence'][0].update(source_references=[]),
    'wrong_proof_condition':lambda r:r['invalidation_evidence'][0].update(condition='score fell'),
}.items():add_output_tamper(name,change,'invalidate')


def add_input_mutation(name,change,expected):
    def test(self):
        p,c=self.pair();change(c);rehash(c);r=assess_scenario_transition(p,c)
        self.assertEqual(r['classification'],expected,r['reason_codes']);self.safe(r)
    setattr(ScenarioTransitionTests,'test_input_'+name,test)

for name,change,expected in [
    ('schema_version',lambda c:c.update(scenario_assessment_version=2),'BLOCKED'),
    ('null_selection',lambda c:c.update(selected_hypothesis=None),'BLOCKED'),
    ('bad_selection_flag',lambda c:c['ranked_hypotheses'][0].update(selected_by_context=False),'BLOCKED'),
    ('different_symbol',lambda c:c.update(symbol='OTHER_SYNTHETIC'),'ABSTAINED'),
    ('different_configuration',lambda c:c['configuration_hashes'].update(context='a'*64),'ABSTAINED'),
    ('different_provenance',lambda c:c.update(provenance='HISTORICAL_RESEARCH'),'ABSTAINED'),
    ('future_evidence',lambda c:c['evidence_index'][0].update(available_at='2099-01-01T00:00:00+00:00'),'BLOCKED'),
    ('future_frame',lambda c:c['m1_m5_alignment'].update(m5_as_of='2099-01-01T00:00:00+00:00'),'BLOCKED'),
    ('unrecognized_structure',lambda c:c['m1_m5_alignment'].update(m1_structure='BUY'),'BLOCKED'),
    ('unsafe',lambda c:c.update(execution_allowed=True),'BLOCKED'),
    ('malformed_reference',lambda c:c['evidence_index'][0].update(references=['missing']),'BLOCKED'),
    ('negative_score',lambda c:c['ranked_hypotheses'][0].update(heuristic_score=-1),'BLOCKED'),
]:add_input_mutation(name,change,expected)
