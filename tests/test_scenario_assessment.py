"""Labeled synthetic context/OHLC only; no broker data or historical qualification."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import json,unittest
from iat.intelligence.context import analyze_context,context_at,replay_context
from iat.intelligence.scenario_assessment import assess_scenarios,scenario_at,replay_scenarios,validate_scenario_assessment,NO_DIRECTION,SCORE_KIND
from iat.intelligence.context_evidence import identity,ReplayLedger
from iat.intelligence.decision_log import DecisionLog,from_replay
from iat.intelligence.strategy_replay import digest
from test_context_engine import two_frames,CONFIG,P7
from test_intelligence_patterns import rows,START
from test_intelligence_engine import WAVE


def context(mirror=False,choch=False):
    a,b,at=two_frames(mirror,choch)
    return analyze_context('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)


class ScenarioAssessmentTests(unittest.TestCase):
    def safe(self,s):
        self.assertTrue(validate_scenario_assessment(s))
        self.assertEqual(s['sha256'],digest({k:v for k,v in s.items() if k!='sha256'}))
        self.assertEqual(s['mode'],'READ_ONLY_SHADOW');self.assertEqual(s['signal'],'WAIT');self.assertFalse(s['execution_allowed'])
        self.assertFalse(s['broker_access']);self.assertEqual(s['orders_requested'],0);self.assertFalse(s['profitability_tested'])
        self.assertEqual(s['exness'],'BLOCKED');self.assertEqual(s['qualification'],'DATA_NOT_QUALIFIED')
        self.assertEqual(s['historical_validation'],'PENDING');self.assertEqual(s['historical_comparisons'],'NOT_RUN')
        self.assertEqual(s['score_kind'],SCORE_KIND);json.dumps(s,allow_nan=False)
    def blocked(self,r,code=None,**options):
        s=assess_scenarios(r,**options);self.assertEqual(s['status'],'BLOCKED',s['reason_codes']);self.assertEqual(s['ranked_hypotheses'],[]);self.assertEqual(s['evidence_index'],[]);self.safe(s)
        if code:self.assertIn(code,s['reason_codes'])
        return s
    def test_normal_context_is_presented_with_original_selected_hypothesis(self):
        for mirror in (False,True):
            r=context(mirror);s=assess_scenarios(r);self.assertEqual(s['status'],'ASSESSED');self.safe(s)
            self.assertEqual(s['selected_hypothesis'],r.confluence['selected_hypothesis']);self.assertEqual(s['market_regime'],r.context['classification'])
            self.assertEqual(s['m1_m5_alignment'],r.context);self.assertEqual(len(s['ranked_hypotheses']),6)
    def test_original_assumptions_invalidations_scores_and_references_are_reused(self):
        r=context();s=assess_scenarios(r)
        for old in r.hypotheses:
            h=next(v for v in s['ranked_hypotheses'] if v['hypothesis_type']==old.hypothesis_type)
            self.assertEqual(h['heuristic_score'],old.heuristic_score);self.assertEqual(h['assumptions'],list(old.assumptions));self.assertEqual(h['invalidation_conditions'],list(old.invalidation_conditions))
            self.assertEqual(h['supporting_evidence'],sorted(set(old.supporting_evidence)));self.assertEqual(h['contradictory_evidence'],sorted(set(old.contradictory_evidence)))
    def test_scores_are_not_normalized_probabilities_or_execution_levels(self):
        s=assess_scenarios(context());self.assertGreater(max(h['heuristic_score'] for h in s['ranked_hypotheses']),1)
        forbidden={'probability','confidence','entry','entry_price','stop_loss','take_profit'}
        def inspect(value):
            if isinstance(value,dict):
                self.assertFalse(forbidden & set(value))
                for v in value.values():inspect(v)
            elif isinstance(value,list):
                for v in value:inspect(v)
        inspect(s);self.safe(s)
    def test_ties_have_equal_dense_ranks_without_arbitrary_selection(self):
        r=context();s=assess_scenarios(r);groups={}
        for h in s['ranked_hypotheses']:groups.setdefault(h['heuristic_score'],set()).add(h['rank'])
        self.assertTrue(all(len(ranks)==1 for ranks in groups.values()));self.assertEqual(s['selected_hypothesis'],r.confluence['selected_hypothesis'])
        self.assertEqual(s['ranked_hypotheses'],sorted(s['ranked_hypotheses'],key=lambda h:(-h['heuristic_score'],h['hypothesis_type'])))
    def test_fresh_opposing_choch_remains_visible_despite_matching_alignment(self):
        for mirror in (False,True):
            r=context(mirror,True);s=assess_scenarios(r);self.assertEqual(s['status'],'ABSTAINED',s['reason_codes']);self.safe(s)
            self.assertEqual(s['selected_hypothesis'],NO_DIRECTION);self.assertEqual(s['m1_m5_alignment']['phase7_alignment'],r.context['phase7_alignment'])
            self.assertIn('FRESH_OPPOSING_M1_CHOCH',s['abstention_reasons']);self.assertTrue(s['fresh_opposing_m1_choch'])
            direction='BEARISH' if mirror else 'BULLISH';h=next(h for h in s['ranked_hypotheses'] if h['hypothesis_type']==direction+'_CONTINUATION_POSSIBILITY')
            self.assertTrue(set(s['fresh_opposing_m1_choch'])<=set(h['contradictory_evidence']))
    def test_legacy_choch_hash_multiplicity_and_stable_event_ids_are_preserved(self):
        r=context(choch=True);s=assess_scenarios(r);self.assertNotEqual(s['status'],'BLOCKED')
        expected={e.id:e.event_id for e in r.evidence if e.event_id}
        self.assertEqual({e['id']:e['event_id'] for e in s['evidence_index'] if e['event_id']},expected)
    def test_conflicting_m1_m5_structures_abstain(self):
        a,b,at=two_frames()
        for row in b:
            o,h,l,c=(row[k] for k in ('open','high','low','close'));row.update(open=200-o,high=200-l,low=200-h,close=200-c)
        r=analyze_context('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7);s=assess_scenarios(r)
        self.assertEqual(s['status'],'ABSTAINED',s['reason_codes']);self.assertEqual(s['selected_hypothesis'],r.confluence['selected_hypothesis']);self.assertIn('CONFLICTING_TIMEFRAME_STRUCTURE',s['abstention_reasons'])
    def test_insufficient_structure_reuses_upstream_abstention(self):
        r=analyze_context('SYNTHETIC_XAUUSD',rows([100]*3),None,START+timedelta(minutes=3));s=assess_scenarios(r)
        self.assertEqual(s['status'],'ABSTAINED',s['reason_codes']);self.assertEqual(s['abstention_reasons'],list(r.abstention_reasons));self.safe(s)
    def test_quality_blocked_context_emits_no_ranked_directions(self):
        a,b,t=two_frames();a[0]['high']=0;r=analyze_context('SYNTHETIC_XAUUSD',a,b,t,config=CONFIG,intelligence_config=P7)
        s=self.blocked(r,'BLOCKED_DATA_QUALITY');self.assertEqual(s['selected_hypothesis'],r.confluence['selected_hypothesis'])
    def test_none_and_malformed_reports_are_blocked_not_exceptions(self):
        for r in (None,{},[],{'signal':'BUY'},object(),'market context'):self.blocked(r)
    def test_unknown_or_missing_top_level_fields_are_blocked(self):
        for name,value in (('unknown_approval',True),('report_version',2),('report_version',True),('model_version','NEW_MODEL')):
            r=context().to_dict();r[name]=value;self.blocked(r)
        r=context().to_dict();r.pop('hypotheses');self.blocked(r)
    def test_wrong_configuration_hash_is_blocked(self):
        r=context().to_dict();r['configuration_sha256']='a'*64;self.blocked(r,'CONTEXT_CONFIGURATION_MISMATCH')
    def test_invalid_context_configuration_is_blocked(self):
        r=context().to_dict();r['configuration']['minimum_score']=float('nan');self.blocked(r)
    def test_quality_flag_cannot_override_error_diagnostics(self):
        r=context().to_dict();r['data_quality']['diagnostics'].append({'code':'OHLC_MALFORMED','severity':'ERROR','message':'Synthetic failure'})
        self.blocked(r,'CONTEXT_QUALITY_INCONSISTENT')
    def test_safety_downgrades_are_blocked(self):
        for field,value in (('signal','BUY'),('execution_allowed',True),('mode','LIVE')):
            r=context().to_dict();r[field]=value;self.blocked(r,'UNSAFE_CONTEXT_CONTRACT')
    def test_future_analysis_timestamp_is_blocked(self):
        r=context();self.blocked(r,'FUTURE_CONTEXT_REPORT',as_of=START)
    def test_old_report_cannot_be_reused_at_a_later_cutoff(self):
        r=context();self.blocked(r,'CONTEXT_ASSESSMENT_CUTOFF_MISMATCH',as_of=START+timedelta(days=1))
    def test_malformed_cutoff_is_blocked(self):
        for cutoff in ('not-a-date','2026-11-12T08:00:00',123,object()):self.blocked(context(),as_of=cutoff)
    def test_future_evidence_or_frame_timestamp_is_blocked(self):
        for kind in ('evidence','frame','source','hypothesis'):
            r=context().to_dict();future=(START+timedelta(days=1)).isoformat()
            if kind=='evidence':r['evidence'][0]['available_at']=future
            elif kind=='frame':r['observed_facts']['M5']['data_as_of']=future
            elif kind=='source':next(iter(r['interpretations']['source_registry'].values()))['available_at']=future
            else:r['hypotheses'][0]['generated_at']=future
            self.blocked(r,'FUTURE_CONTEXT_OBSERVATION')
    def test_observed_after_available_is_blocked(self):
        r=context().to_dict();e=r['evidence'][0];e['observed_at']=r['analysis_at'];e['available_at']=START.isoformat();self.blocked(r)
    def test_forged_canonical_evidence_id_is_blocked(self):
        r=context().to_dict();r['evidence'][0]['id']='M1:STRUCTURE:'+'a'*64;self.blocked(r,'CANONICAL_EVIDENCE_IDENTITY_MISMATCH')
    def test_changed_evidence_details_without_new_identity_are_blocked(self):
        r=context().to_dict();r['evidence'][0]['details']['forged']='value';self.blocked(r,'CANONICAL_EVIDENCE_IDENTITY_MISMATCH')
    def test_window_relative_ids_are_not_accepted_as_canonical(self):
        r=context().to_dict();r['evidence'][0]['id']='M1:E:window:1';self.blocked(r,'NONCANONICAL_EVIDENCE_IDENTITY')
    def test_identical_duplicate_evidence_does_not_change_scores_counts_or_hash(self):
        r=context().to_dict();expected=assess_scenarios(r);r['evidence']=list(r['evidence'])+[deepcopy(r['evidence'][0])]*3
        self.assertEqual(assess_scenarios(r),expected)
    def test_conflicting_duplicate_evidence_is_blocked(self):
        r=context().to_dict();copy=deepcopy(r['evidence'][0]);copy['direction']='BEARISH' if copy['direction']=='BULLISH' else 'BULLISH';r['evidence']=list(r['evidence'])+[copy];self.blocked(r)
    def test_duplicate_supporting_references_cannot_inflate_scores(self):
        r=context().to_dict();expected=assess_scenarios(r)
        for h in r['hypotheses']:h['supporting_evidence']=list(h['supporting_evidence'])*2
        self.assertEqual(assess_scenarios(r),expected)
    def test_inflated_scores_are_rejected_instead_of_repaired(self):
        r=context().to_dict();r['confluence']['scores']['BULLISH']+=100;self.blocked(r,'CONFLUENCE_INCONSISTENT')
    def test_changed_hypothesis_score_assumption_or_invalidation_is_blocked(self):
        for field,value in (('heuristic_score',100),('assumptions',['PROMISE_RETURN']),('invalidation_conditions',[])):
            r=context().to_dict();r['hypotheses'][0][field]=value;self.blocked(r,'CONTEXT_HYPOTHESIS_INCONSISTENT')
    def test_unknown_or_duplicate_hypothesis_is_blocked(self):
        r=context().to_dict();r['hypotheses'][0]['hypothesis_type']='BUY_NOW';self.blocked(r,'CONTEXT_HYPOTHESES_INVALID')
        r=context().to_dict();r['hypotheses']=list(r['hypotheses']);r['hypotheses'][1]=deepcopy(r['hypotheses'][0]);self.blocked(r,'CONTEXT_HYPOTHESES_INVALID')
    def test_forced_selection_is_rejected_and_never_reauthorized(self):
        r=context(choch=True).to_dict();r['confluence']['selected_hypothesis']='BULLISH_CONTINUATION_POSSIBILITY'
        s=self.blocked(r,'CONFLUENCE_INCONSISTENT');self.assertEqual(s['selected_hypothesis'],r['confluence']['selected_hypothesis'])
    def test_missing_hypothesis_evidence_and_source_reference_are_blocked(self):
        r=context().to_dict();r['hypotheses'][0]['supporting_evidence']=['missing'];self.blocked(r)
        r=context().to_dict();key=r['evidence'][0]['references'][0];del r['interpretations']['source_registry'][key];self.blocked(r)
    def test_source_candle_changes_without_new_identity_are_blocked(self):
        r=context().to_dict();s=next(v for v in r['interpretations']['source_registry'].values() if v['kind']=='CANDLE');s['ohlc']['close']+=0.1;self.blocked(r,'SOURCE_IDENTITY_MISMATCH')
    def test_cycles_and_wrong_timeframe_references_are_blocked(self):
        r=context().to_dict();k=next(iter(r['interpretations']['source_registry']));r['interpretations']['source_registry'][k]['references']=[k];self.blocked(r)
        r=context().to_dict();r['evidence'][0]['timeframe']='M15';self.blocked(r)
    def test_frame_coverage_or_structure_inconsistency_is_blocked(self):
        for field,value in (('candle_count',1),('data_as_of',START.isoformat())):
            r=context().to_dict();r['observed_facts']['M1'][field]=value;self.blocked(r)
        r=context().to_dict();r['context']['m1_structure']='BEARISH';self.blocked(r)
    def test_event_identity_change_and_stale_fresh_flag_are_blocked(self):
        r=context(choch=True).to_dict();e=next(e for e in r['evidence'] if e['event_id']);e['event_id']='M1:CHOCH_EVENT:'+'a'*64;self.blocked(r)
        r=context(choch=True).to_dict();e=next(e for e in r['evidence'] if e['event_id']);e['details']['fresh']=False;self.blocked(r)
    def test_input_objects_and_json_schema_remain_unchanged(self):
        r=context();before=r.to_dict();expected=deepcopy(before);assess_scenarios(r);assess_scenarios(before)
        self.assertEqual(r.to_dict(),expected);self.assertEqual(before,expected)
    def test_typed_and_serialized_context_outputs_and_hashes_are_identical(self):
        r=context();self.assertEqual(assess_scenarios(r),assess_scenarios(json.loads(json.dumps(r.to_dict()))))
    def test_deterministic_evidence_and_hypothesis_ordering(self):
        r=context().to_dict();expected=assess_scenarios(r)
        r['evidence']=list(reversed(r['evidence']));r['hypotheses']=list(reversed(r['hypotheses']));r['confluence']['weighted_evidence'].reverse()
        self.assertEqual(assess_scenarios(r),expected)
    def test_repeatability_and_hash_contract(self):
        a=assess_scenarios(context());b=assess_scenarios(context());self.assertEqual(a,b);self.safe(a)
    def test_no_network_mt5_or_order_dependency(self):
        r=context()
        with patch('socket.create_connection',side_effect=AssertionError('Network forbidden')),patch.dict('sys.modules',{'MetaTrader5':None}):s=assess_scenarios(r)
        self.safe(s)
    def test_exness_candidate_is_blocked_by_inherited_context_gate(self):
        from iat.session_config import load_session_config
        a,b,t=two_frames();r=analyze_context('XAUUSD',a,b,t,calendar=load_session_config('config/profiles/exness-xauusd-v2.candidate.json'),config=CONFIG,intelligence_config=P7)
        self.blocked(r,'BLOCKED_DATA_QUALITY')
    def test_no_phase7_or_session_configuration_change(self):
        from iat.intelligence.context_models import ContextConfig
        from iat.intelligence.models import IntelligenceConfig
        self.assertEqual(ContextConfig().digest,'d8bda7da1af47cc1f1f349682b71ca75f39bef89b7fb5d5873bc0bba5510d424');self.assertEqual(IntelligenceConfig().digest,'0b1db8f78abc3801b23a2aec62ee6057a1b0b711a8244405bc5f77ff582653ff')
    def test_invalid_resource_limit_and_nonfinite_inputs_fail_closed(self):
        r=context().to_dict();r['explanation']=['X'*(8*1024*1024)];self.blocked(r,'CONTEXT_RESOURCE_LIMIT')
        r=context().to_dict();r['hypotheses'][0]['heuristic_score']=float('nan');self.blocked(r)


    def test_measurement_representations_must_agree(self):
        r=context().to_dict();r['observed_facts']['M1']['momentum']['regime']='NEGATIVE_MOMENTUM';self.blocked(r,'CONTEXT_MEASUREMENTS_INCONSISTENT')
    def test_rehashed_output_cannot_enable_execution_or_claim_history(self):
        for field,value in (('execution_allowed',True),('signal','BUY'),('qualification','DATA_QUALIFIED'),('historical_comparisons','PASS')):
            s=assess_scenarios(context());s.pop('sha256');s[field]=value;s['sha256']=digest(s)
            with self.assertRaises(ValueError):validate_scenario_assessment(s)
    def test_output_hash_and_rank_are_checked(self):
        s=assess_scenarios(context());s['sha256']='a'*64
        with self.assertRaises(ValueError):validate_scenario_assessment(s)
        s=assess_scenarios(context());s.pop('sha256');s['ranked_hypotheses'][0]['rank']=99;s['sha256']=digest(s)
        with self.assertRaises(ValueError):validate_scenario_assessment(s)
    def test_inherited_synthetic_scenarios_preserve_existing_outcomes(self):
        from test_adaptive_intelligence import synthetic_cases
        for name,(a,b,t,method) in synthetic_cases().items():
            report=analyze_context('SYNTHETIC_XAUUSD',a,b,t,config=CONFIG,intelligence_config=P7) if method.startswith('DIRECT') else context_at('SYNTHETIC_XAUUSD',a,b,t,config=CONFIG,intelligence_config=P7)
            s=assess_scenarios(report);self.safe(s);self.assertEqual(s['selected_hypothesis'],report.confluence['selected_hypothesis'])
            self.assertEqual(s['status']=='BLOCKED',not report.data_quality['valid'],(name,s['reason_codes']))


    def test_zone_source_and_interpretation_cannot_disagree(self):
        from test_adaptive_intelligence import actual_range
        a,b,t=actual_range();r=context_at('SYNTHETIC_XAUUSD',a,b,t,config=CONFIG,intelligence_config=P7).to_dict()
        zone=next(s for s in r['interpretations']['source_registry'].values() if s['kind']=='ZONE');zone['lower']+=1
        self.blocked(r,'CONTEXT_ZONE_INCONSISTENT')


    def test_published_synthetic_audit_and_output_hashes_are_reproducible(self):
        path=Path('docs/research_audits/scenario-assessment-synthetic-v1/audit.json')
        self.assertEqual(json.loads(path.read_text()),synthetic_audit())


    def test_transition_alignment_cannot_disagree_with_snapshot_context(self):
        r=context(choch=True).to_dict();e=next(e for e in r['evidence'] if e['event_id']);e['details']['phase7_alignment']='BEARISH_ALIGNMENT'
        self.blocked(r,'EVENT_CONTEXT_INCONSISTENT')
    def test_distinct_revisions_of_one_event_cannot_inflate_a_single_snapshot(self):
        r=context(choch=True).to_dict();e=next(e for e in r['evidence'] if e['event_id']);new=deepcopy(e)
        pivot=r['interpretations']['source_registry'][e['event_id']]['references'][0]
        identity_refs=sorted(e['references'])
        def key(item):return identity(r['symbol'],item['timeframe'],item['category'],item['observed_at'],item['available_at'],identity_refs,item['direction'],sorted(item['reason_codes']),item['details'],r['configuration_sha256'],r['intelligence_configuration_sha256'])
        if key(e)!=e['id']:identity_refs=sorted(list(e['references'])+[pivot])
        self.assertEqual(key(e),e['id']);new['details']['threshold']+=.1;new['id']=key(new);r['evidence']=list(r['evidence'])+[new]
        self.blocked(r,'CONFLICTING_EVENT_REVISIONS')


    def test_rehashed_assessed_report_with_null_selection_and_cleared_flags_is_rejected(self):
        s=assess_scenarios(context());self.assertEqual(s['status'],'ASSESSED')
        s.pop('sha256');s['selected_hypothesis']=None
        for h in s['ranked_hypotheses']:h['selected_by_context']=False
        s['sha256']=digest(s)
        with self.assertRaisesRegex(ValueError,'SCENARIO_SELECTION_INVALID'):validate_scenario_assessment(s)
    def test_rehashed_abstained_report_cannot_have_null_selection(self):
        s=assess_scenarios(context(choch=True));self.assertEqual(s['status'],'ABSTAINED')
        s.pop('sha256');s['selected_hypothesis']=None
        for h in s['ranked_hypotheses']:h['selected_by_context']=False
        s['sha256']=digest(s)
        with self.assertRaisesRegex(ValueError,'SCENARIO_SELECTION_INVALID'):validate_scenario_assessment(s)
    def test_assessed_report_requires_a_non_abstention_hypothesis(self):
        s=assess_scenarios(context());s.pop('sha256');s['selected_hypothesis']=NO_DIRECTION
        for h in s['ranked_hypotheses']:h['selected_by_context']=h['hypothesis_type']==NO_DIRECTION
        s['sha256']=digest(s)
        with self.assertRaisesRegex(ValueError,'SCENARIO_SELECTION_INVALID'):validate_scenario_assessment(s)
    def test_assessed_selection_requires_exactly_one_matching_boolean_flag(self):
        original=assess_scenarios(context())
        for defect in ('none','multiple','wrong','nonboolean'):
            s=deepcopy(original);s.pop('sha256');selected=next(h for h in s['ranked_hypotheses'] if h['selected_by_context'])
            other=next(h for h in s['ranked_hypotheses'] if not h['selected_by_context'])
            if defect=='none':selected['selected_by_context']=False
            elif defect=='multiple':other['selected_by_context']=True
            elif defect=='wrong':selected['selected_by_context']=False;other['selected_by_context']=True
            else:selected['selected_by_context']=1
            s['sha256']=digest(s)
            with self.subTest(defect=defect),self.assertRaises(ValueError):validate_scenario_assessment(s)
    def test_genuine_assessed_abstained_and_unavailable_blocked_still_validate(self):
        cases={'ASSESSED':assess_scenarios(context()),'ABSTAINED':assess_scenarios(context(choch=True)),'BLOCKED':assess_scenarios(None)}
        for status,s in cases.items():
            with self.subTest(status=status):self.assertEqual(s['status'],status);self.assertTrue(validate_scenario_assessment(s))
        self.assertIsNone(cases['BLOCKED']['selected_hypothesis'])
    def test_blocked_report_still_accepts_a_recognized_recorded_selection(self):
        s=assess_scenarios(None);s.pop('sha256');s['selected_hypothesis']='BULLISH_CONTINUATION_POSSIBILITY';s['sha256']=digest(s)
        self.assertTrue(validate_scenario_assessment(s))


class ScenarioReplayTests(unittest.TestCase):
    def history(self):
        a,b,t=two_frames();tail=rows(WAVE)
        for c in tail:c['timestamp']=(START+timedelta(minutes=len(a))+ (utc_dt(c['timestamp'])-START)).isoformat()
        return a+tail,b
    def test_replay_matches_existing_context_replay_and_preserves_decisionlog(self):
        a,b=self.history();entries=list(replay_context('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7))
        before=DecisionLog(1,{},tuple(from_replay(e) for e in entries)).sha256
        expected=[assess_scenarios(e['report']) for e in entries]
        actual=list(replay_scenarios('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7));self.assertEqual(actual,expected)
        self.assertEqual(before,DecisionLog(1,{},tuple(from_replay(e) for e in entries)).sha256)
        self.assertTrue(any(s['status']!='BLOCKED' for s in actual))
    def test_prefix_replay_future_append_and_snapshot_equivalence(self):
        a,b=self.history();cut=25;short=list(replay_scenarios('SYNTHETIC_XAUUSD',a[:cut],b,config=CONFIG,intelligence_config=P7))
        full=list(replay_scenarios('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7));self.assertEqual(short,full[:cut])
        at=START+timedelta(minutes=cut);self.assertEqual(short[-1],scenario_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7))
    def test_future_candle_prices_and_unfinished_m5_do_not_leak(self):
        a,b=self.history();at=START+timedelta(minutes=19)
        expected=scenario_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        aa,bb=deepcopy(a),deepcopy(b)
        for row in aa[19:]:row.update(open=500,high=501,low=499,close=500)
        # M5 here starts before M1; select future rows explicitly by scheduled close.
        for row in bb:
            if utc_dt(row['timestamp'])+timedelta(minutes=5)>at:row.update(open=1,high=999,low=.5,close=998)
        self.assertEqual(expected,scenario_at('SYNTHETIC_XAUUSD',aa,bb,at,config=CONFIG,intelligence_config=P7))
        s=scenario_at('SYNTHETIC_XAUUSD',rows([100]*19),rows([100]*4,'M5'),at,config=CONFIG)
        self.assertEqual(s['m1_m5_alignment']['m5_as_of'],(START+timedelta(minutes=15)).isoformat())
    def test_rolling_snapshot_scores_do_not_accumulate_or_relabel_ids(self):
        a,b=self.history();entries=list(replay_context('SYNTHETIC_XAUUSD',a,b,window=18,config=CONFIG,intelligence_config=P7))
        actual=list(replay_scenarios('SYNTHETIC_XAUUSD',a,b,window=18,config=CONFIG,intelligence_config=P7))
        for e,s in zip(entries,actual):
            self.assertEqual(s,assess_scenarios(e['report']))
            if s['status']!='BLOCKED':self.assertEqual({x['id'] for x in s['evidence_index']},{x['id'] for x in e['report']['evidence']})
    def test_invalid_raw_inputs_are_blocked_or_upstream_abstained(self):
        self.assertEqual(scenario_at('X',None,None,START)['status'],'BLOCKED')
        self.assertEqual(list(replay_scenarios('X',[{'timestamp':'bad'}],None))[-1]['status'],'BLOCKED')


    def test_raw_adapters_cannot_use_provenance_labels_as_historical_qualification(self):
        a,b=self.history()
        for provenance in ('HISTORICAL_RESEARCH','VALIDATED_LIVE'):
            s=scenario_at('SYNTHETIC_XAUUSD',a,b,START+timedelta(minutes=25),provenance=provenance)
            self.assertEqual(s['status'],'BLOCKED');self.assertEqual(s['reason_codes'],['UPSTREAM_GATED_CONTEXT_REQUIRED'])
            self.assertEqual(list(replay_scenarios('SYNTHETIC_XAUUSD',a,b,provenance=provenance)),[s])


def utc_dt(value):
    from datetime import datetime
    return datetime.fromisoformat(value)


def synthetic_audit():
    from test_adaptive_intelligence import synthetic_cases
    cases={};counts={}
    for name,(a,b,t,method) in synthetic_cases().items():
        source=analyze_context('SYNTHETIC_XAUUSD',a,b,t,config=CONFIG,intelligence_config=P7) if method.startswith('DIRECT') else context_at('SYNTHETIC_XAUUSD',a,b,t,config=CONFIG,intelligence_config=P7)
        s=assess_scenarios(source);validate_scenario_assessment(s);counts[s['status']]=counts.get(s['status'],0)+1
        cases[name]={'status':s['status'],'market_regime':s['market_regime'],'upstream_selected_hypothesis':source.confluence['selected_hypothesis'],
            'selected_hypothesis':s['selected_hypothesis'],'leading_hypotheses':s['leading_hypotheses'],
            'evidence_count':len(s['evidence_index']),'ranked_hypothesis_count':len(s['ranked_hypotheses']),
            'reason_codes':s['reason_codes'],'assessment_payload_sha256':s['sha256']}
    body={'audit_version':1,'kind':'SYNTHETIC_ONLY_NOT_REAL_MARKET_VALIDATION','case_count':len(cases),'status_counts':counts,'cases':cases,
        'score_kind':SCORE_KIND,'historical_validation':'PENDING','historical_comparisons':'NOT_RUN','exness':'BLOCKED','signal':'WAIT','execution_allowed':False}
    return dict(body,sha256=digest(body))
