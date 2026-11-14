"""Deterministic synthetic OHLC, never purported broker observations."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from iat.analysis import Candle
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.patterns import recognize
from iat.intelligence.candles import measure, atr

START = datetime(2026,11,12,8,tzinfo=timezone.utc)


def candles(values,tf='M1'):
    return tuple(Candle(START+timedelta(minutes=i*(1 if tf=='M1' else 5)),*v) for i,v in enumerate(values))


def rows(closes,tf='M1'):
    return [dict(timestamp=(START+timedelta(minutes=i*(1 if tf=='M1' else 5))).isoformat(),
                 open=c,high=c+0.5,low=c-0.5,close=c) for i,c in enumerate(closes)]


class PatternTests(unittest.TestCase):
    def names(self,values,config=None):
        cs=candles(values)
        m,ps=recognize(cs,'M1',config or IntelligenceConfig(),[f'M1:C:{i}' for i in range(len(cs))])
        for p in ps:
            self.assertEqual(p.detected_at,(cs[-1].timestamp+timedelta(minutes=1)).isoformat())
            self.assertTrue(p.evidence)
        return {p.name for p in ps}

    def test_measurements_and_prior_context(self):
        cs=candles([(10,12,9,11),(10,15,8,12)])
        m=measure(cs[-1],cs[:-1],IntelligenceConfig())
        self.assertEqual((m['range'],m['body'],m['upper_wick'],m['lower_wick']),(7,2,3,2))
        self.assertAlmostEqual(m['body_to_range'],2/7)
        self.assertEqual(m['relative_range'],7/3)
        self.assertEqual(m['upper_wick_to_body'],1.5)

    def test_bullish_engulfing(self):
        self.assertIn('BULLISH_ENGULFING',self.names([(12,12,10,10),(9,13,9,13)]))

    def test_bearish_engulfing(self):
        self.assertIn('BEARISH_ENGULFING',self.names([(10,12,10,12),(13,13,9,9)]))

    def test_hammer(self):
        names=self.names([(15,16,14,15),(14,15,13,14),(13,14,12,13),(10,11.1,7,11)])
        self.assertTrue({'HAMMER','BULLISH_PIN_BAR'}<=names)
        self.assertNotIn('HANGING_MAN',names)

    def test_hanging_man(self):
        self.assertIn('HANGING_MAN',self.names([(10,11,9,10),(11,12,10,11),(12,13,11,12),(13,14.1,10,14)]))

    def test_shooting_star(self):
        self.assertIn('SHOOTING_STAR',self.names([(10,11,9,10),(11,12,10,11),(12,13,11,12),(13,17,12.9,14)]))

    def test_inverted_hammer(self):
        self.assertIn('INVERTED_HAMMER',self.names([(15,16,14,15),(14,15,13,14),(13,14,12,13),(10,14,9.9,11)]))

    def test_missing_trend_shape_only(self):
        self.assertEqual(self.names([(10,11.1,7,11)]),{'BULLISH_PIN_BAR'})

    def test_doji(self):
        self.assertIn('DOJI',self.names([(10,11,9,10)]))

    def test_dragonfly(self):
        self.assertIn('DRAGONFLY_DOJI',self.names([(10,10.05,7,10.02)]))

    def test_gravestone(self):
        self.assertIn('GRAVESTONE_DOJI',self.names([(10,13,9.95,10.02)]))

    def test_morning_star(self):
        self.assertIn('MORNING_STAR',self.names([(15,15.1,10,10),(10,10.2,9.8,10.1),(10.2,14,10,14)]))

    def test_evening_star(self):
        self.assertIn('EVENING_STAR',self.names([(10,15.1,9.9,15),(15,15.2,14.8,14.9),(14.8,15,11,11)]))

    def test_inside_bar(self):
        self.assertIn('INSIDE_BAR',self.names([(10,12,8,11),(10,11,9,10.5)]))

    def test_outside_bar(self):
        self.assertIn('OUTSIDE_BAR',self.names([(10,11,9,10.5),(10,12,8,11)]))

    def test_bullish_pin(self):
        self.assertIn('BULLISH_PIN_BAR',self.names([(10,11.1,7,11)]))

    def test_bearish_pin(self):
        self.assertIn('BEARISH_PIN_BAR',self.names([(10,14,9.9,11)]))

    def test_bullish_momentum(self):
        self.assertIn('BULLISH_MOMENTUM_CANDLE',self.names([(10,11,9,10)]*2+[(10,14,10,14)],IntelligenceConfig(range_window=2)))

    def test_bearish_momentum(self):
        self.assertIn('BEARISH_MOMENTUM_CANDLE',self.names([(10,11,9,10)]*2+[(14,14,10,10)],IntelligenceConfig(range_window=2)))

    def test_zero_range_no_division_and_no_contextual_reversal(self):
        cs=candles([(10,10,10,10)])
        m=measure(cs[0],[],IntelligenceConfig())
        self.assertIsNone(m['body_to_range'])
        self.assertIsNone(m['upper_wick_to_body'])
        self.assertIsNone(m['relative_range'])
        self.assertEqual(self.names([(10,10,10,10)]),{'DOJI'})

    def test_equal_boundaries_and_overlap_policy(self):
        self.assertEqual(self.names([(10,11,9,10)]*2),{'DOJI','INSIDE_BAR'})
        self.assertIn('DOJI',self.names([(10,11,9,10.2)]))  # Exact 10% boundary.
        self.assertNotIn('DOJI',self.names([(10,11,9,10.20001)]))

    def test_engulfing_requires_opposite_body_and_strict_expansion(self):
        self.assertNotIn('BULLISH_ENGULFING',self.names([(11,11,10,10),(10,11,10,11)]))

    def test_momentum_requires_full_warmup(self):
        self.assertNotIn('BULLISH_MOMENTUM_CANDLE',self.names([(10,11,9,10),(10,20,10,20)]))

    def test_atr_formula_includes_gap_and_warmup(self):
        cs=candles([(10,11,9,10),(12,14,12,13),(13,15,12,14)])
        self.assertEqual(atr(cs,2),3.5)
        self.assertIsNone(atr(cs,3))

    def test_pin_long_wick_threshold(self):
        self.assertIn('BULLISH_PIN_BAR',self.names([(10,11.1,8,11)]))
        self.assertNotIn('BULLISH_PIN_BAR',self.names([(10,11.1,8.00001,11)]))

    def test_star_recovery_threshold(self):
        base=[(15,15.1,10,10),(10,10.2,9.8,10.1)]
        self.assertIn('MORNING_STAR',self.names(base+[(10,13,10,12.5)]))
        self.assertNotIn('MORNING_STAR',self.names(base+[(10,13,10,12.4999)]))

    def test_momentum_body_and_relative_thresholds(self):
        config=IntelligenceConfig(range_window=2,momentum_relative_range=2.5)
        base=[(10,11,9,10)]*2
        self.assertIn('BULLISH_MOMENTUM_CANDLE',self.names(base+[(10,15,10,13.5)],config))
        self.assertNotIn('BULLISH_MOMENTUM_CANDLE',self.names(base+[(10,15,10,13.4999)],config))
        self.assertNotIn('BULLISH_MOMENTUM_CANDLE',self.names(base+[(10,15,10,13.5)],replace(config,momentum_relative_range=2.5001)))

    def test_tolerance_does_not_make_a_tiny_zero_range_pin(self):
        self.assertEqual(self.names([(10,10.000000001,10,10)]),{'DOJI'})

    def test_configuration_strictness(self):
        for options in ({'version':2},{'version':True},{'right_strength':0},{'epsilon':float('nan')},
                        {'doji_ratio':1},{'break_policy':'AUTO'},{'atr_multiplier':-1},{'range_window':True},
                        {'trend_window':1},{'equal_tolerance':float('inf')},{'long_wick_body':0.1}):
            with self.subTest(options=options), self.assertRaises(ValueError): IntelligenceConfig(**options)
        with self.assertRaises(ValueError): IntelligenceConfig.from_dict({'epsilon':1})
        with self.assertRaises(ValueError): IntelligenceConfig.from_dict({'version':1,'unknown':1})
        self.assertEqual(IntelligenceConfig.from_dict({'version':1}).digest,IntelligenceConfig().digest)
        self.assertNotEqual(IntelligenceConfig().digest,replace(IntelligenceConfig(),epsilon=1e-7).digest)
