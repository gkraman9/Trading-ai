"""Stage-A rehearsal readiness and persistent stop controls. No order-sending adapter."""
import argparse,json,sys
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iat.demo_execution.policy import Config,Blocked,load_config,readiness
from iat.demo_execution.store import Store
from iat.demo_execution.readiness import inspect_terminal


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config');p.add_argument('--state-directory');p.add_argument('--write-template')
    p.add_argument('--initialize-state',action='store_true');p.add_argument('--emergency-stop',action='store_true')
    p.add_argument('--reset-emergency-stop',action='store_true');p.add_argument('--acknowledge-rehearsal-only',action='store_true')
    p.add_argument('--inspect-demo-terminal',action='store_true');p.add_argument('--print-demo-fingerprint',action='store_true')
    p.add_argument('--enable-demo-auto-execution',action='store_true',help='Readiness request only; this Stage-A build cannot activate broker execution.')
    a=p.parse_args(argv);module=None;result=readiness();exit_code=3
    try:
        if a.write_template:
            target=Path(a.write_template);repo=Path(__file__).resolve().parents[1]
            if target.resolve().is_relative_to(repo) or any(x.is_symlink() for x in (target,*target.parents)):raise Blocked('PRIVATE_CONFIG_PATH_REQUIRED')
            with target.open('x',encoding='utf-8',newline='\n') as f:json.dump(asdict(Config()),f,sort_keys=True,indent=2);f.write('\n')
            result['template_created']=True
        config=load_config(Path(a.config)) if a.config else None;result=readiness(config)|{'template_created':bool(a.write_template)}
        if a.initialize_state or a.emergency_stop or a.reset_emergency_stop:
            if config is None or not a.state_directory:raise Blocked('CONFIG_AND_PRIVATE_STATE_REQUIRED')
            state=Store(a.state_directory,config.sha256,create=a.initialize_state)
            if a.emergency_stop:state.emergency_stop()
            if a.reset_emergency_stop:
                if config.enabled:raise Blocked('LIVE_READINESS_NOT_ESTABLISHED')
                state.emergency_stop(reset=True,acknowledge=a.acknowledge_rehearsal_only)
            with state.connection() as db:result['emergency_stop']=state.stop_value(db)=='1'
        if a.inspect_demo_terminal:
            if sys.platform!='win32' or sys.version_info[:2]!=(3,11):raise Blocked('WINDOWS_PYTHON_311_REQUIRED')
            import MetaTrader5 as module
            if module.initialize(timeout=10000) is not True:raise Blocked('TERMINAL_UNAVAILABLE')
            result['terminal']=inspect_terminal(module,config.expected_account_fingerprint if config else '',include_fingerprint=a.print_demo_fingerprint)
        elif a.print_demo_fingerprint:raise Blocked('EXPLICIT_TERMINAL_INSPECTION_REQUIRED')
        if a.enable_demo_auto_execution:result['reason_codes'].append('ACTIVATION_REFUSED_STAGE_A_NO_BROKER_ADAPTER')
    except Blocked as exc:result['reason_codes']=sorted(set(result['reason_codes']+[exc.code]))
    except Exception:result['reason_codes']=sorted(set(result['reason_codes']+['CONFIG_STATE_OR_TERMINAL_UNAVAILABLE']))
    finally:
        if module is not None:
            try:module.shutdown()
            except Exception:pass
    print(json.dumps(result,sort_keys=True,allow_nan=False));return exit_code


if __name__=='__main__':raise SystemExit(main())
