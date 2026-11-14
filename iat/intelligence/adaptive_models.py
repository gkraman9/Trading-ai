"""Versioned research policies; no learned weights or automatic threshold changes."""
from dataclasses import asdict,dataclass
from iat.intelligence.strategy_replay import digest


COMPATIBILITY = {
    'version':1,
    'M5_TREND_M1_CONFIRMATION':{
        'TREND_UP':{'BULLISH':'SUPPORTED','BEARISH':'INCOMPATIBLE'},
        'TREND_DOWN':{'BULLISH':'INCOMPATIBLE','BEARISH':'SUPPORTED'},
        'RANGE':{'BULLISH':'INCOMPATIBLE','BEARISH':'INCOMPATIBLE'},
        'TRANSITION':{'BULLISH':'CONDITIONAL','BEARISH':'CONDITIONAL'}},
    'SWEEP_M1_STRUCTURE_CHANGE':{
        'TREND_UP':{'BULLISH':'SUPPORTED','BEARISH':'CONDITIONAL'},
        'TREND_DOWN':{'BULLISH':'CONDITIONAL','BEARISH':'SUPPORTED'},
        'RANGE':{'BULLISH':'SUPPORTED','BEARISH':'SUPPORTED'},
        'TRANSITION':{'BULLISH':'SUPPORTED','BEARISH':'SUPPORTED'}}}
RANKING = {'version':1,'score_kind':'RESEARCH_HEURISTIC_NOT_PROBABILITY',
           'scenario':'EXISTING_CAPPED_DIRECTION_SCORE_MINUS_MAX_OPPOSING_DIRECTION_SCORE',
           'neutral_direction':'RANGING','candidate':'ELIGIBLE_ONLY_SAME_DIRECTION_SCENARIO_NET_SCORE',
           'ties':'DENSE_RANK_KEEP_ALL_EQUAL_SCORES','selection':'ALL_TOP_RANKED_ELIGIBLE_CANDIDATES'}


@dataclass(frozen=True)
class AdaptiveConfig:
    version:int=1
    compatibility_version:int=1
    ranking_version:int=1

    def __post_init__(self):
        if any(type(v) is not int or v!=1 for v in asdict(self).values()):
            raise ValueError('Unsupported adaptive policy version')

    @property
    def digest(self):
        return digest({'configuration':asdict(self),'compatibility':COMPATIBILITY,'ranking':RANKING})
