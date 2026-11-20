"""Start a local read-only MT5 observer. No login, credentials or execution capability."""
import argparse,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.live_data import ReadOnlyMarketData
from iat.live_observer import LiveObserver,ShadowLog
from iat.live_dashboard import create_dashboard
from iat.live_commentary import CommentaryFailure
from iat.live_ai_provider import OpenAIResearchProvider
from iat.live_ai_runtime import LiveAIReasoning,ResearchCommentary,AIJournal
from iat.mt5_data import MarketDataError
from iat.session_config import load_session_config


class UnavailableProvider:
    raw={}
    def preflight(self):raise MarketDataError('MT5 unavailable','PROVIDER_UNAVAILABLE')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--log-directory',required=True);p.add_argument('--interval',type=int,default=10)
    p.add_argument('--port',type=int,default=8765);p.add_argument('--session-config')
    p.add_argument('--enable-llm',action='store_true',help='Explicit opt-in to send bounded typed research facts to OpenAI, never raw logs.')
    p.add_argument('--llm-model');p.add_argument('--llm-min-seconds',type=int,default=60)
    a=p.parse_args(argv)
    if sys.platform!='win32' or sys.version_info[:2]!=(3,11):
        print('Windows Python 3.11 is required for the real MT5 runner. Offline tests run on Linux/Windows 3.11/3.12.');return 1
    if not 2<=a.interval<=60 or not 1024<=a.port<=65535:
        print('Use interval 2..60 seconds and port 1024..65535.');return 1
    module=None;observer=None;reasoning=None
    try:
        calendar=load_session_config(a.session_config) if a.session_config else None
        log=ShadowLog(a.log_directory)
        try:
            import MetaTrader5 as module
            module.initialize(timeout=10000)  # Attach locally, no login/server/password arguments.
            provider=ReadOnlyMarketData(module)
        except Exception:provider=UnavailableProvider()
        observer=LiveObserver(provider,log,calendar=calendar,interval=a.interval)
        manager=ResearchCommentary()
        if a.enable_llm:
            try:
                provider=OpenAIResearchProvider(os.environ.get('IAT_OPENAI_API_KEY'),a.llm_model or os.environ.get('IAT_REASONING_MODEL'))
                manager=ResearchCommentary(provider,min_seconds=a.llm_min_seconds)
            except CommentaryFailure as exc:manager=ResearchCommentary(error=exc.code)
            except ValueError:manager=ResearchCommentary(error='LLM_CONFIGURATION_INVALID')
        reasoning=LiveAIReasoning(manager,AIJournal(log.root))
        app=create_dashboard(observer,ai_reasoning=reasoning);observer.start();reasoning.start(observer)
        print('Open http://127.0.0.1:'+str(a.port)+' — READ ONLY; WAIT; execution disabled; zero order capability.')
        print('Without verified session coverage, real descriptive observations may appear but the assessment remains WAIT.')
        app.run(host='127.0.0.1',port=a.port,debug=False,use_reloader=False,threaded=True)
    except (ValueError,OSError):
        print('Startup blocked: verify configuration, a NEW log directory outside the repository and local port availability.');return 1
    finally:
        if reasoning is not None:reasoning.close()
        if observer is not None:observer.close()
        if module is not None and (observer is None or observer.thread is None or not observer.thread.is_alive()):
            try:module.shutdown()
            except Exception:pass
    return 0


if __name__=='__main__':raise SystemExit(main())
