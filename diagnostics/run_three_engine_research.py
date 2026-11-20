"""Stage B.3 comparison consumer. Source recorder is read-only; no MT5/order imports."""

import argparse, sys, os, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iat.live_shadow.store import Journal as SourceJournal
from iat.live_shadow.policy import configuration as source_configuration
from iat.three_engine.config import configuration
from iat.three_engine.journal import SourceReader, ComparisonJournal
from iat.three_engine.runtime import ComparisonRuntime
from iat.three_engine.dashboard import create_dashboard
from iat.session_config import load_session_config


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-journal-directory", required=True)
    p.add_argument("--journal-directory", required=True)
    p.add_argument("--create", action="store_true")
    p.add_argument("--source-config")
    p.add_argument("--research-config")
    p.add_argument("--session-config")
    p.add_argument("--port", type=int, default=8767)
    p.add_argument("--verify-only", action="store_true")
    p.add_argument("--synthetic-source", action="store_true")
    p.add_argument("--enable-ai", action="store_true")
    p.add_argument("--provider", choices=("openai", "gemini"))
    p.add_argument("--model")
    a = p.parse_args(argv)
    runtime = None
    providers = {}
    try:
        if not a.verify_only and (
            sys.platform != "win32" or sys.version_info[:2] != (3, 11)
        ):
            raise ValueError("Live follow requires Windows Python 3.11")
        if not 1024 <= a.port <= 65535 or a.verify_only and (a.create or a.enable_ai):
            raise ValueError("Invalid invocation")
        calendar = load_session_config(a.session_config) if a.session_config else None
        config = configuration(a.research_config)
        source = SourceJournal(
            a.source_journal_directory,
            source_configuration(a.source_config),
            calendar=calendar,
            source_kind=(
                "SYNTHETIC_FIXTURE" if a.synthetic_source else "LIVE_MT5_OBSERVATIONS"
            ),
        )
        if not a.verify_only and a.synthetic_source:
            raise ValueError("Synthetic data must not be displayed as live")
        models = {
            name: (
                (a.provider + ":" + a.model)
                if a.enable_ai and a.provider and a.model
                else "DISABLED"
            )
            for name in ("B_HYBRID", "C_AI_LED")
        }
        # Verification needs the original model declarations without reading credentials or loading SDKs.
        if a.verify_only:
            from contextlib import closing
            import sqlite3

            with closing(
                sqlite3.connect(
                    (Path(a.journal_directory) / "comparison.sqlite3")
                    .resolve()
                    .as_uri()
                    + "?mode=ro",
                    uri=True,
                )
            ) as db:
                models = json.loads(db.execute("SELECT body FROM meta").fetchone()[0])[
                    "models"
                ]
        journal = ComparisonJournal(
            a.journal_directory,
            config,
            source.binding_sha,
            calendar=calendar,
            source_kind=source.binding["source_kind"],
            create=a.create,
            models=models,
        )
        if a.verify_only:
            print(json.dumps(journal.verify(replay=True), sort_keys=True))
            return 0
        if a.enable_ai:
            if not a.provider or not a.model:
                raise ValueError("Explicit provider/model required")
            from iat.three_engine.providers import OpenAIReasoner, GeminiReasoner

            cls = OpenAIReasoner if a.provider == "openai" else GeminiReasoner
            key = os.environ.get(
                "IAT_OPENAI_API_KEY" if a.provider == "openai" else "IAT_GEMINI_API_KEY"
            )
            for engine in models:
                providers[engine] = cls(key, a.model)
                providers[engine].model_ref = a.provider + ":" + a.model
                # SDK transport still requires its original vendor model name.
                providers[engine].vendor_model = a.model
        runtime = ComparisonRuntime(SourceReader(source), journal, providers=providers)
        app = create_dashboard(runtime)
        runtime.start()
        print(
            "http://127.0.0.1:"
            + str(a.port)
            + " — THREE-ENGINE SHADOW RESEARCH; WAIT; no broker capability."
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
            "BLOCKED: verify private paths, unchanged source/config/calendar and optional provider/budget configuration. No orders or credentials are logged."
        )
        return 1
    finally:
        if runtime:
            runtime.close()
        elif providers:
            for provider in providers.values():
                try:
                    provider.close()
                except Exception:
                    pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
