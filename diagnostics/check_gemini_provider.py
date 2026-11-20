"""Explicit opt-in paid API smoke test with synthetic contract facts, never market data."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.live_ai_gemini import GeminiResearchProvider,DEFAULT_MODEL
from iat.live_ai_evidence import SECTIONS
from iat.live_commentary import CommentaryFailure
from iat.intelligence.strategy_replay import digest


def smoke_packet():
    cards=[dict(fact_id='SYNTHETIC:'+s,section=s,text='SYNTHETIC CONTRACT TEST ONLY. No market observation. WAIT; execution disabled.',
        evidence_ids=[],timeframe=None,event_type=None,level=None,direction='NEUTRAL',kind='UNCERTAINTY') for s in SECTIONS]
    packet=dict(commentary_version=3,symbol='XAUUSD',cutoffs={},cards=cards,
        required_fact_ids={s:[c['fact_id'] for c in cards if c['section']==s] for s in SECTIONS},changes=[],
        limitations=['SYNTHETIC_NOT_MARKET_OR_TERMINAL_VALIDATION'],scope='SYNTHETIC_PROVIDER_CONTRACT_ONLY')
    packet['bundle_id']=digest(packet);return packet


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--enable-llm',action='store_true',help='Explicit consent to one potentially billable Gemini request.')
    p.add_argument('--model',default=DEFAULT_MODEL);a=p.parse_args(argv);provider=None
    result=dict(status='DISABLED',scope='SYNTHETIC_NOT_MARKET_OR_TERMINAL_VALIDATION',signal='WAIT',execution_allowed=False,
        mode='READ_ONLY_SHADOW',orders_requested=0,exness='BLOCKED',qualification='DATA_NOT_QUALIFIED',historical_validation='PENDING',historical_comparisons='NOT_RUN')
    code=0
    try:
        if a.enable_llm:
            provider=GeminiResearchProvider(os.environ.get('IAT_GEMINI_API_KEY'),a.model)
            out=provider.request(smoke_packet())
            result.update(status='PASS_SYNTHETIC_PROVIDER_SMOKE',provider=provider.provider_name,model=provider.model,
                sections=len(out['sections']),usage=out['usage'],latency_ms=out['latency_ms'])
    except CommentaryFailure as exc:result.update(status='FAIL',reason_code=exc.code);code=1
    except Exception:result.update(status='FAIL',reason_code='AI_PROVIDER_ERROR');code=1
    finally:
        if provider is not None:
            try:provider.close()
            except Exception:result.update(status='FAIL',reason_code='AI_PROVIDER_ERROR');code=1
    print(json.dumps(result,sort_keys=True));return code


if __name__=='__main__':raise SystemExit(main())
