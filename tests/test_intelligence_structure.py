"""Synthetic pivot/structure/break unit cases plus genuine candle confirmation cases."""
import unittest
from dataclasses import replace
from datetime import timedelta
from iat.intelligence.models import IntelligenceConfig, Pivot
from iat.intelligence.swings import detect
from iat.intelligence.structure import classify
from iat.intelligence.bos_choch import detect as breaks
from test_intelligence_patterns import START, candles


CONFIG=IntelligenceConfig(left_strength=1,right_strength=1)


def pivot(kind,index,price,relation='UNCLASSIFIED',confirmation=None):
    confirmation=index+1 if confirmation is None else confirmation
    return Pivot(f'M1:P:{kind}:{index}',kind,index,(START+timedelta(minutes=index)).isoformat(),
                 confirmation,(START+timedelta(minutes=confirmation+1)).isoformat(),price,relation,
                 (f'M1:C:{index}',),'CONFIRMED')


def structure_pivots(direction='BULLISH'):
    return (pivot('HIGH',1,110),pivot('LOW',2,90),
            pivot('HIGH',3,115 if direction=='BULLISH' else 105,'HH' if direction=='BULLISH' else 'LH'),
            pivot('LOW',4,95 if direction=='BULLISH' else 85,'HL' if direction=='BULLISH' else 'LL'))


class SwingTests(unittest.TestCase):
    def swings(self,values,config=CONFIG):
        cs=candles([(v,v+0.1,v-0.1,v) for v in values])
        return detect(cs,'M1',config,[f'M1:C:{i}' for i in range(len(cs))])

    def test_confirmation_time_not_occurrence(self):
        a,b=self.swings([10,12])
        self.assertFalse(a)
        self.assertEqual(b[0].status,'CANDIDATE')
        self.assertIsNone(b[0].confirmed_at)
        a,b=self.swings([10,12,11])
        self.assertEqual(a[0].index,1)
        self.assertEqual(a[0].confirmation_index,2)
        self.assertEqual(a[0].confirmed_at,(START+timedelta(minutes=3)).isoformat())
        self.assertEqual(a[0].occurred_at,(START+timedelta(minutes=1)).isoformat())

    def test_strength_two_waits_for_two_right_candles(self):
        a,b=self.swings([10,11,15,12],IntelligenceConfig())
        self.assertFalse(a)
        self.assertEqual(b[0].index,2)
        a,b=self.swings([10,11,15,12,11],IntelligenceConfig())
        self.assertEqual(a[0].confirmation_index,4)

    def test_right_invalidation(self):
        a,_=self.swings([10,12,13])
        self.assertFalse(a)

    def test_leftmost_plateau_tie(self):
        confirmed,_=self.swings([10,12,12,11])
        highs=[p for p in confirmed if p.kind=='HIGH']
        self.assertEqual([p.index for p in highs],[1])

    def test_equal_separated_highs_and_lows(self):
        confirmed,_=self.swings([10,12,10,12,10,12])
        self.assertIn('EH',[p.relation for p in confirmed])
        self.assertIn('EL',[p.relation for p in confirmed])

    def test_hh_hl_lh_ll(self):
        for values,relations in (([10,13,9,15,11,14,8,12],{'HH','HL','LH','LL'}),):
            confirmed,_=self.swings(values)
            self.assertTrue(relations<={p.relation for p in confirmed})

    def test_tolerance_controls_equal(self):
        confirmed,_=self.swings([10,12,9,12.01,10],replace(CONFIG,equal_tolerance=.02))
        self.assertEqual([p for p in confirmed if p.kind=='HIGH'][-1].relation,'EH')


class StructureTests(unittest.TestCase):
    def test_bullish(self): self.assertEqual(classify(structure_pivots(),'t').classification,'BULLISH')
    def test_bearish(self): self.assertEqual(classify(structure_pivots('BEARISH'),'t').classification,'BEARISH')
    def test_ranging(self):
        ps=list(structure_pivots());ps[-2]=replace(ps[-2],relation='EH');ps[-1]=replace(ps[-1],relation='EL')
        self.assertEqual(classify(ps,'t').classification,'RANGING')
    def test_transitional(self):
        ps=list(structure_pivots());ps[-1]=replace(ps[-1],relation='LL')
        report=classify(ps,'t')
        self.assertEqual(report.classification,'TRANSITIONAL');self.assertTrue(report.contradictory_observations)
    def test_unknown_requires_two_each(self):
        report=classify(structure_pivots()[:3],'t')
        self.assertEqual(report.classification,'UNKNOWN');self.assertTrue(report.insufficient_evidence)
    def test_candidates_never_define_direction(self):
        ps=[replace(p,status='CANDIDATE') for p in structure_pivots()]
        self.assertEqual(classify(ps,'t').classification,'UNKNOWN')


class BreakTests(unittest.TestCase):
    def events(self,direction='BULLISH',last=(116,117,115,116),config=CONFIG,extra=()):
        cs=candles([(100,101,99,100)]*7+[last]+list(extra))
        return breaks(cs,'M1',structure_pivots(direction),config,[f'M1:C:{i}' for i in range(len(cs))])

    def test_bullish_bos(self):
        self.assertIn('BULLISH_BOS',[e.event_type for e in self.events()])
    def test_bearish_bos(self):
        self.assertIn('BEARISH_BOS',[e.event_type for e in self.events('BEARISH',(84,85,83,84))])
    def test_bullish_choch(self):
        self.assertIn('BULLISH_CHOCH',[e.event_type for e in self.events('BEARISH')])
    def test_bearish_choch(self):
        self.assertIn('BEARISH_CHOCH',[e.event_type for e in self.events(last=(94,95,93,94))])
    def test_wick_rejection_sweep_proxy(self):
        kinds={e.event_type for e in self.events(last=(114,116,113,114)) if e.level==115}
        self.assertEqual(kinds,{'WICK_PENETRATION','POTENTIAL_LIQUIDITY_SWEEP'})
    def test_duplicate_suppression(self):
        es=self.events(extra=((117,118,116,117),)*4)
        self.assertEqual(len([e for e in es if e.event_type=='BULLISH_BOS' and e.level==115]),1)
    def test_failed_break_without_rearming(self):
        es=self.events(extra=((114,115,113,114),(116,117,115,116)))
        self.assertEqual(len([e for e in es if e.event_type=='FAILED_STRUCTURAL_BREAK' and e.level==115]),1)
        self.assertEqual(len([e for e in es if e.event_type=='BULLISH_BOS' and e.level==115]),1)
    def test_unknown_prior_not_choch(self):
        cs=candles([(100,101,99,100)]*4+[(120,121,119,120)])
        es=breaks(cs,'M1',[pivot('HIGH',1,110)],CONFIG,[str(i) for i in range(len(cs))])
        self.assertEqual(es[0].event_type,'AMBIGUOUS_STRUCTURAL_EVENT')
    def test_level_must_precede_break_open(self):
        cs=candles([(100,101,99,100)]*3+[(120,121,119,120)])
        es=breaks(cs,'M1',[pivot('HIGH',1,110,confirmation=3)],CONFIG,[str(i) for i in range(len(cs))])
        self.assertFalse(es)
    def test_absolute_threshold_boundary_strict(self):
        es=self.events(config=replace(CONFIG,min_break_distance=1))
        self.assertFalse(any(e.event_type=='BULLISH_BOS' and e.level==115 for e in es))
    def test_wick_confirmation_policy_labeled(self):
        es=self.events(last=(114,116,113,114),config=replace(CONFIG,break_policy='WICK'))
        self.assertTrue(any(e.event_type=='BULLISH_BOS' and e.level==115 and e.policy=='WICK' for e in es))
    def test_atr_warmup_no_qualifying_events(self):
        self.assertFalse(self.events(config=replace(CONFIG,atr_multiplier=1)))
    def test_atr_threshold(self):
        es=self.events(config=replace(CONFIG,atr_multiplier=1,atr_period=2))
        self.assertFalse(any(e.event_type=='BULLISH_BOS' and e.level==115 for e in es))
