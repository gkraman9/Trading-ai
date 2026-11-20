"""Stage B.2: localhost live DEMO shadow recorder; no broker order capability."""

import argparse, sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.live_shadow.policy import configuration
from iat.live_shadow.feed import ShadowFeed
from iat.live_shadow.store import Journal
from iat.live_shadow.runtime import ShadowRuntime
from iat.live_dashboard import create_dashboard
from iat.session_config import load_session_config


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--journal-directory", required=True)
    p.add_argument("--create", action="store_true")
    p.add_argument("--config")
    p.add_argument("--session-config")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--interval", type=int, default=1)
    p.add_argument("--offline-verify", action="store_true")
    p.add_argument(
        "--synthetic-replay",
        action="store_true",
        help="Only for offline verification of explicitly synthetic examples.",
    )
    a = p.parse_args(argv)
    module = None
    runtime = None
    try:
        config = configuration(a.config)
        calendar = load_session_config(a.session_config) if a.session_config else None
        if a.offline_verify:
            if a.create:
                raise ValueError("Cannot create during read-only verification")
            journal = Journal(
                a.journal_directory,
                config,
                calendar=calendar,
                source_kind=(
                    "SYNTHETIC_FIXTURE"
                    if a.synthetic_replay
                    else "LIVE_MT5_OBSERVATIONS"
                ),
            )
            print(json.dumps(journal.verify(replay=True), sort_keys=True))
            return 0
        if a.synthetic_replay:
            raise ValueError("Synthetic replay cannot be used for live capture")
        if sys.platform != "win32" or sys.version_info[:2] != (3, 11):
            print(
                "Real capture requires Windows Python 3.11; offline replay supports 3.11/3.12."
            )
            return 1
        if not 1024 <= a.port <= 65535 or not 1 <= a.interval <= 10:
            raise ValueError("Invalid port or interval")
        journal = Journal(
            a.journal_directory, config, calendar=calendar, create=a.create
        )
        import MetaTrader5 as module

        if module.initialize(timeout=10000) is not True:
            raise ValueError("Terminal unavailable")
        feed = ShadowFeed(module)
        runtime = ShadowRuntime(feed, journal, calendar=calendar, interval=a.interval)
        app = create_dashboard(runtime, shadow=runtime)
        runtime.start()
        print(
            "http://127.0.0.1:"
            + str(a.port)
            + " — LIVE MARKET DATA / SHADOW SIMULATION / BROKER EXECUTION DISABLED"
        )
        print(
            "This is not historical qualification or broker-confirmed performance. Keep both trading permissions disabled."
        )
        app.run(
            host="127.0.0.1",
            port=a.port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    except Exception:
        print(
            "BLOCKED: verify a private journal path, unchanged config/calendar, and connected DEMO terminal with trading disabled. No order capability."
        )
        return 1
    finally:
        if runtime:
            runtime.close()
        if module is not None and (
            runtime is None or runtime.thread is None or not runtime.thread.is_alive()
        ):
            try:
                module.shutdown()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
