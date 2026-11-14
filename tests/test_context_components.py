"""Phase 8 synthetic component fixtures; no broker data or credentials."""
from dataclasses import replace
from datetime import timedelta
import unittest
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.context import analyze_context
from iat.intelligence import support_resistance,supply_demand,liquidity,momentum,volatility
from iat.intelligence.models import FrameReport,Structure
from test_intelligence_patterns import START,candles,rows
from test_intelligence_structure import pivot

CONFIG=ContextConfig(roc_period=2,atr_period=2,range_period=2,base_bars=2)


def frame(cs,pivots=()):
    at=(cs[-1].timestamp+timedelta(minutes=1)).isoformat()
    return FrameReport('M1',at,at,len(cs),(),{},(),tuple(pivots),(),Structure('UNKNOWN',at,(),(),(),True),(),(),())


def price_candles(values):return candles([(v,v+.1,v-.1,v) for v in values])


class SRTests(unittest.TestCase):
    def test_clusters_repeated_confirmed_touches_and_fixed_width(self):
        cs=price_candles([100]*12)
        ps=(pivot('HIGH',1,105),pivot('HIGH',4,105.05),pivot('HIGH',7,105.09))
        zones=support_resistance.detect(cs,frame(cs,ps),'SYNTHETIC',CONFIG)
        self.assertEqual(len(zones),1)
        z=zones[0]
        self.assertAlmostEqual(z.lower,104.95);self.assertAlmostEqual(z.upper,105.1)
        self.assertEqual(z.confirmed_at,ps[1].confirmed_at)
        self.assertEqual(len(z.historical_touches),3)
        self.assertEqual(z.status,'FRESH')

    def test_insufficient_cluster_not_zone(self):
        cs=price_candles([100]*5)
        self.assertFalse(support_resistance.detect(cs,frame(cs,(pivot('HIGH',1,105),)),'X',CONFIG))

    def test_price_clusters_are_same_kind_and_anchor_bounded(self):
        cs=price_candles([100]*12)
        ps=(pivot('HIGH',1,105),pivot('HIGH',3,105.09),pivot('HIGH',5,105.18),pivot('LOW',7,105.01))
        zs=support_resistance.detect(cs,frame(cs,ps),'X',CONFIG)
        self.assertEqual(len(zs),1);self.assertEqual(len(zs[0].supporting_pivots),2)

    def test_retests_count_episodes_not_every_overlapping_bar(self):
        cs=candles([(100,101,99,100)]*3+[(100,100.1,99.9,100)]*2+[(102,103,101,102)]+[(100,100.1,99.9,100)])
        retests,status,*_=support_resistance.lifecycle(cs,'M1',99.8,100.2,2,'SUPPORT',CONFIG)
        self.assertEqual(len(retests),2);self.assertEqual(status,'TESTED')

    def test_support_break_role_reversal_and_invalidation(self):
        cs=candles([(100,101,99,100)]*3+[(98,98.5,97.5,98),(99,100,98,99),(102,103,101,102)])
        _,status,broken,invalid,reversal=support_resistance.lifecycle(cs,'M1',99.8,100.2,2,'SUPPORT',CONFIG)
        self.assertEqual(status,'INVALIDATED');self.assertTrue(broken);self.assertTrue(invalid);self.assertTrue(reversal)

    def test_resistance_break_is_mirrored(self):
        cs=price_candles([100,100,100,102])
        self.assertEqual(support_resistance.lifecycle(cs,'M1',99.8,100.2,2,'RESISTANCE',CONFIG)[1],'BROKEN')


class SupplyDemandTests(unittest.TestCase):
    def base(self,supply=False):
        values=[(100,101,99,100)]*3+[(100,100.2,99.8,100)]*2+[(100,105,99.9,104.5)]
        if supply:values=[(200-o,200-l,200-h,200-c) for o,h,l,c in values]
        return candles(values)

    def test_demand_formation_available_after_departure(self):
        cs=self.base();z=supply_demand.detect(cs,frame(cs),'X',CONFIG)
        self.assertEqual(len(z),1);self.assertEqual(z[0].kind,'DEMAND')
        self.assertEqual(z[0].confirmed_at,(START+timedelta(minutes=6)).isoformat())
        self.assertFalse(supply_demand.detect(cs[:-1],frame(cs[:-1]),'X',CONFIG))

    def test_supply_is_mirrored(self):
        cs=self.base(True);z=supply_demand.detect(cs,frame(cs),'X',CONFIG)
        self.assertEqual(z[0].kind,'SUPPLY')

    def test_retest_then_invalidation(self):
        values=[(c.open,c.high,c.low,c.close) for c in self.base()]+[(100.1,100.3,99.9,100.1),(98,98.5,97.5,98)]
        cs=candles(values);z=supply_demand.detect(cs,frame(cs),'X',CONFIG)[0]
        self.assertEqual(z.status,'INVALIDATED');self.assertTrue(z.retests);self.assertTrue(z.invalidated_at)

    def test_insufficient_warmup_and_small_departure_abstain(self):
        cs=self.base()
        self.assertFalse(supply_demand.detect(cs,frame(cs),'X',replace(CONFIG,range_period=10)))
        self.assertFalse(supply_demand.detect(cs,frame(cs),'X',replace(CONFIG,departure_range_multiple=10)))

    def test_atr_normalization_and_warmup(self):
        cs=self.base()
        self.assertTrue(supply_demand.detect(cs,frame(cs),'X',replace(CONFIG,departure_atr_multiple=1)))
        self.assertFalse(supply_demand.detect(cs,frame(cs),'X',replace(CONFIG,departure_atr_multiple=1,atr_period=20)))


class LiquidityTests(unittest.TestCase):
    def detect(self,last,extra=(),pivots=None):
        cs=candles([(100,101,99,100)]*4+[last]+list(extra))
        return liquidity.detect(cs,frame(cs,pivots or (pivot('HIGH',1,105),)),'X',CONFIG)

    def test_single_and_equal_high_pools(self):
        ps=(pivot('HIGH',0,105),pivot('HIGH',2,105.05))
        pools,_=self.detect((100,101,99,100),pivots=ps)
        self.assertEqual({p.kind for p in pools},{'SWING_HIGHS','EQUAL_HIGHS'})

    def test_equal_lows(self):
        cs=price_candles([100]*8)
        pools,_=liquidity.detect(cs,frame(cs,(pivot('LOW',1,95),pivot('LOW',3,95.05))),'X',CONFIG)
        self.assertIn('EQUAL_LOWS',{p.kind for p in pools})

    def test_wick_rejection_confirms_sweep_at_close(self):
        _,events=self.detect((104,106,103,104))
        self.assertEqual([e.event_type for e in events],['LEVEL_PENETRATION','CONFIRMED_SWEEP'])
        self.assertEqual(events[-1].available_at,(START+timedelta(minutes=5)).isoformat())

    def test_close_beyond_needs_sustained_confirmation(self):
        _,events=self.detect((106,107,105.5,106),((107,108,106,107),))
        self.assertEqual([e.event_type for e in events],['LEVEL_PENETRATION','SUSTAINED_BREAKOUT'])
        _,events=self.detect((106,107,105.5,106))
        self.assertNotIn('SUSTAINED_BREAKOUT',[e.event_type for e in events])

    def test_failed_close_through_is_ambiguous_not_sweep(self):
        _,events=self.detect((106,107,105.5,106),((104,104.5,103,104),))
        self.assertEqual(events[-1].event_type,'AMBIGUOUS_EVENT')
        self.assertNotIn('CONFIRMED_SWEEP',[e.event_type for e in events])

    def test_boundary_rejection_is_ambiguous(self):
        _,events=self.detect((105,106,104,105))
        self.assertEqual(events[-1].event_type,'AMBIGUOUS_EVENT')

    def test_low_sweep_is_mirrored(self):
        _,events=self.detect((96,97,94,96),pivots=(pivot('LOW',1,95),))
        self.assertEqual(events[-1].event_type,'CONFIRMED_SWEEP')


class MomentumVolatilityTests(unittest.TestCase):
    def test_roc_and_acceleration_math(self):
        cs=candles([(10,11,9,10),(11,12,10,11),(12,13,11,12),(13,14,12,13)])
        result=momentum.measure(cs,CONFIG)
        self.assertAlmostEqual(result['roc'],13/11-1)
        self.assertAlmostEqual(result['previous_roc'],12/10-1)
        self.assertAlmostEqual(result['acceleration'],13/11-12/10)

    def test_signed_body_momentum_and_direction(self):
        up=candles([(v-.5,v+1,v-1,v+.5) for v in (10,11,12,13)])
        down=candles([(v+.5,v+1,v-1,v-.5) for v in (13,12,11,10)])
        self.assertEqual(momentum.measure(up,CONFIG)['regime'],'POSITIVE_MOMENTUM')
        self.assertEqual(momentum.measure(down,CONFIG)['regime'],'NEGATIVE_MOMENTUM')
        self.assertEqual(momentum.measure(price_candles([10,11,12,13]),CONFIG)['regime'],'WEAK_OR_MIXED_MOMENTUM')

    def test_warmup(self):
        self.assertEqual(momentum.measure(price_candles([10,11,12]),CONFIG)['status'],'INSUFFICIENT_EVIDENCE')
        self.assertEqual(volatility.measure(price_candles([10,11,12]),CONFIG)['status'],'INSUFFICIENT_EVIDENCE')

    def test_atr_and_range_expansion(self):
        cs=candles([(10,11,9,10)]*2+[(10,13,7,10)]*2)
        result=volatility.measure(cs,CONFIG)
        self.assertEqual(result['atr'],6);self.assertEqual(result['relative_volatility'],3)
        self.assertEqual(result['change'],'VOLATILITY_EXPANSION')
        self.assertEqual(result['regime'],'HIGH_VOLATILITY')

    def test_contraction(self):
        cs=candles([(10,13,7,10)]*2+[(10,11,9,10)]*2)
        result=volatility.measure(cs,CONFIG)
        self.assertAlmostEqual(result['relative_volatility'],1/3)
        self.assertEqual(result['change'],'VOLATILITY_CONTRACTION')

    def test_zero_baselines_and_zero_body_no_divide_by_zero(self):
        cs=candles([(10,10,10,10)]*4)
        self.assertIsNone(volatility.measure(cs,CONFIG)['relative_volatility'])
        self.assertEqual(momentum.measure(cs,CONFIG)['body_momentum'],0)

    def test_config_validation(self):
        for changes in ({'version':True},{'version':2},{'cluster_tolerance':-1},{'base_bars':1},
                        {'roc_period':True},{'volatility_low':1},{'minimum_score':0},
                        {'structure_weight':float('inf')},{'zone_half_width':0}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):ContextConfig(**changes)
        with self.assertRaises(ValueError):ContextConfig.from_dict({'unknown':1,'version':1})
        with self.assertRaises(ValueError):ContextConfig.from_dict({})
