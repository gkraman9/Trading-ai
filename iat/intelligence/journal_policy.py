"""Original IAT reasoning-review policy; no returns, trade outcomes or fitted levels."""
from dataclasses import asdict,dataclass
from iat.intelligence.strategy_replay import digest

CRITERIA = {'version':1,'kind':'OBSERVATION_REVIEW_NOT_TRADE_RESULT',
            'clock':'ELAPSED_UTC_MINUTES_CONTINUOUS_M1_REQUIRED',
            'reference':'ORIGINAL_M1_BAR_AND_CITED_CONFIRMED_M1_PIVOT_ENVELOPE',
            'event':'FIRST_STRICT_HIGH_OR_LOW_ENVELOPE_BREACH',
            'ambiguity':'BOTH_BOUNDARIES_IN_FIRST_BREACH_BAR_UNRESOLVED',
            'quality':'COMPLETE_TIMELY_UNBLOCKED_REVIEW_WINDOW_REQUIRED',
            'ties':'REVIEW_EACH_MEMBER_NEVER_PICK_A_RETROSPECTIVE_WINNER',
            'completion':'FIRST_EVALUATED_CLOSE_AT_OR_AFTER_DUE_THEN_FREEZE'}

@dataclass(frozen=True)
class ReviewPolicy:
    version:int=1
    horizons_minutes:tuple[int,...]=(5,15)
    criteria_version:int=1

    def __post_init__(self):
        if type(self.version) is not int or self.version!=1 or type(self.criteria_version) is not int or self.criteria_version!=1:
            raise ValueError('Unsupported reasoning review version')
        h=self.horizons_minutes
        if (not isinstance(h,tuple) or not h or len(h)>8 or any(type(v) is not int or not 1<=v<=240 for v in h)
                or h!=tuple(sorted(set(h)))):
            raise ValueError('Explicit sorted unique integer review horizons required')

    @property
    def sha256(self):return digest({'policy':asdict(self),'criteria':CRITERIA})

    @classmethod
    def from_dict(cls,raw):
        if not isinstance(raw,dict) or set(raw)!={'version','horizons_minutes','criteria_version'}:
            raise ValueError('Strict review policy fields required')
        h=raw['horizons_minutes']
        if not isinstance(h,(tuple,list)):raise ValueError('Review horizon array required')
        return cls(raw['version'],tuple(h),raw['criteria_version'])
