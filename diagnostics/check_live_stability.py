"""Sample only the local read-only observer; write a new redacted metadata report."""
import argparse,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from iat.live_stability import StabilitySampler
from iat.chart_benchmark import write_new


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds',type=int,default=360);p.add_argument('--interval',type=int,default=5)
    p.add_argument('--port',type=int,default=8765);p.add_argument('--report-path',required=True);a=p.parse_args(argv)
    target=Path(a.report_path);repo=Path(__file__).resolve().parents[1]
    if (not 30<=a.seconds<=3600 or not 1<=a.interval<=60 or not 1024<=a.port<=65535
        or target.exists() or target.resolve().is_relative_to(repo) or target.suffix.lower()!='.json'
        or not target.parent.is_dir() or any(p.is_symlink() for p in (target,*target.parents))):
        print('Use a NEW .json path outside the repository, seconds 30..3600 and interval 1..60.');return 1
    sampler=StabilitySampler();session=requests.Session();session.trust_env=False;end=time.monotonic()+a.seconds
    try:
        while True:
            try:
                response=session.get('http://127.0.0.1:'+str(a.port)+'/live/v1/snapshot',timeout=4,allow_redirects=False)
                if response.status_code!=200:raise ValueError('Unavailable')
                sampler.add(response.json());response.close()
            except Exception:sampler.add({'diagnostic_error':'LOCAL_OBSERVER_UNAVAILABLE'})
            remaining=end-time.monotonic()
            if remaining<=0:break
            time.sleep(min(a.interval,remaining))
        report=sampler.report();write_new(target,report)
    except (ValueError,OSError):print('Report not published. Preserve existing evidence and use a fresh output path.');return 1
    finally:session.close()
    print('Local observer sampling: '+report['status']+'. Historical validation remains PENDING; execution disabled.')
    return 0 if report['status']=='PASS' else 3


if __name__=='__main__':raise SystemExit(main())
