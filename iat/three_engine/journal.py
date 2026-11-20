"""Separate comparison journal. Stage B.2 is opened read-only and never migrated."""

from pathlib import Path
from contextlib import contextmanager
from copy import deepcopy
import sqlite3, json, shutil
from iat.replay_dataset import strict_json
from iat.intelligence.strategy_replay import digest
from iat.live_shadow.store import (
    Journal as B2Journal,
    calendar_identity,
    canonical,
    safe_packet,
)
from iat.three_engine.config import validate_config, PROTOCOL_SHA256
from iat.three_engine import VERSION, ENGINES
from iat.three_engine.reducer import initial, reduce
from iat.three_engine.simulation import metrics


class SourceReader:
    def __init__(self, journal):
        self.journal = journal
        self.binding = journal.binding_sha
        self.source_kind = journal.binding["source_kind"]

    def records(self, after, limit=100):
        with self.journal.connection(readonly=True) as db:
            for row in db.execute(
                "SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?", (after, limit)
            ):
                body = strict_json(row["body"])
                if digest(body) != row["sha256"]:
                    raise ValueError("SOURCE_EVENT_CHECKSUM_MISMATCH")
                p = deepcopy(body["packet"])
                sid = p.pop("source_id")
                source = strict_json(
                    db.execute(
                        "SELECT body FROM sources WHERE id=?", (sid,)
                    ).fetchone()[0]
                )
                if digest(source) != sid:
                    raise ValueError("SOURCE_DATA_CHECKSUM_MISMATCH")
                p.update(source)
                safe_packet(p)
                yield dict(
                    seq=row["seq"],
                    previous_sha256=body["previous_sha256"],
                    source_event_sha256=row["sha256"],
                    candle_source_id=sid,
                    packet=p,
                    correction_detected=any(
                        e.get("code") == "CLOSED_CANDLE_CORRECTION_DETECTED"
                        for e in body["effects"]
                    ),
                )


class ComparisonJournal:
    def __init__(
        self,
        directory,
        config,
        source_binding,
        *,
        calendar=None,
        source_kind="LIVE_MT5_OBSERVATIONS",
        create=False,
        models=None
    ):
        self.root = Path(directory)
        self.path = self.root / "comparison.sqlite3"
        self.config = validate_config(deepcopy(config))
        self.calendar = calendar
        repo = Path(__file__).resolve().parents[2]
        if self.root.resolve().is_relative_to(repo) or any(
            p.is_symlink() for p in (self.root, *self.root.parents)
        ):
            raise ValueError("PRIVATE_COMPARISON_PATH_REQUIRED")
        self.binding = dict(
            schema_version=1,
            engine_version=VERSION,
            protocol_sha256=PROTOCOL_SHA256,
            configuration=config,
            source_binding=source_binding,
            source_kind=source_kind,
            calendar_sha256=calendar_identity(calendar),
            models=models or {"B_HYBRID": "DISABLED", "C_AI_LED": "DISABLED"},
        )
        self.binding_sha = digest(self.binding)
        if create:
            self.root.mkdir(parents=True, mode=0o700, exist_ok=False)
            with self.connection(create=True) as db:
                db.execute(
                    "CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,sha256 TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE sources (id TEXT PRIMARY KEY,body TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE events (seq INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,body TEXT NOT NULL,sha256 TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE checkpoint (id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,sha256 TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT INTO meta VALUES (1,?,?)",
                    (canonical(self.binding), self.binding_sha),
                )
                s = initial(config, source_binding)
                db.execute(
                    "INSERT INTO checkpoint VALUES (1,?,?)", (canonical(s), digest(s))
                )
        self.verify()

    @contextmanager
    def connection(self, *, create=False, readonly=False):
        db = None
        try:
            if not create and (not self.path.is_file() or self.path.is_symlink()):
                raise ValueError("COMPARISON_DATABASE_MISSING")
            db = sqlite3.connect(
                (
                    str(self.path)
                    if create
                    else self.path.resolve().as_uri()
                    + ("?mode=ro" if readonly else "?mode=rw")
                ),
                uri=not create,
                timeout=3,
                isolation_level=None,
            )
            db.row_factory = sqlite3.Row
            if not readonly:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("BEGIN IMMEDIATE")
            else:
                db.execute("BEGIN")
            yield db
            db.execute("COMMIT")
        except Exception:
            if db is not None and db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            if db is not None:
                db.close()

    def checkpoint(self, db):
        meta = db.execute("SELECT * FROM meta").fetchone()
        if (
            not meta
            or meta["sha256"] != self.binding_sha
            or meta["body"] != canonical(self.binding)
        ):
            raise ValueError("COMPARISON_BINDING_MISMATCH")
        row = db.execute("SELECT * FROM checkpoint").fetchone()
        s = strict_json(row["body"])
        last = db.execute("SELECT * FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        if (
            digest(s) != row["sha256"]
            or last
            and (
                digest(strict_json(last["body"])) != last["sha256"]
                or strict_json(last["body"])["state_sha256"] != row["sha256"]
            )
        ):
            raise ValueError("COMPARISON_CHECKPOINT_CORRUPT")
        if last is None and digest(s) != digest(
            initial(self.config, self.binding["source_binding"])
        ):
            raise ValueError("COMPARISON_EMPTY_STATE_CORRUPT")
        return s, last

    def state(self):
        with self.connection(readonly=True) as db:
            return self.checkpoint(db)[0]

    def _expand(self, db, event):
        e = deepcopy(event)
        if e["kind"] == "SOURCE":
            sid = e["data"]["candle_source_id"]
            source = strict_json(
                db.execute("SELECT body FROM sources WHERE id=?", (sid,)).fetchone()[0]
            )
            if digest(source) != sid:
                raise ValueError("COMPARISON_SOURCE_CORRUPT")
            e["data"]["packet"].update(source)
        return e

    def record(self, event):
        if shutil.disk_usage(self.root).free < 128 * 1024 * 1024:
            raise ValueError("DISK_HEADROOM_REQUIRED")
        e = deepcopy(event)
        source = None
        if e["kind"] == "SOURCE":
            safe_packet(e["data"]["packet"])
            source = {k: e["data"]["packet"].pop(k) for k in ("candles", "raw_candles")}
            if digest(source) != e["data"]["candle_source_id"]:
                raise ValueError("SOURCE_BINDING_INVALID")
        with self.connection() as db:
            s, last = self.checkpoint(db)
            if db.execute("SELECT id FROM events WHERE id=?", (digest(e),)).fetchone():
                return False
            if (
                e["kind"] == "REQUEST"
                and e["data"]["model"] != self.binding["models"][e["data"]["engine"]]
            ):
                raise ValueError("PROVIDER_MODEL_BINDING_MISMATCH")
            if e["kind"] == "RESULT":
                from iat.three_engine.contracts import validate_response

                if set(e["data"]) != {
                    "request_id",
                    "raw",
                    "response_at",
                    "available_at",
                    "code",
                } or e["data"]["code"] not in (
                    None,
                    "PROVIDER_ERROR",
                    "PROVIDER_TIMEOUT",
                    "MODEL_SCHEMA_INVALID",
                ):
                    raise ValueError("RESULT_FIELDS_UNSAFE")
                if e["data"]["raw"] is not None:
                    req = s["requests"][e["data"]["request_id"]]
                    try:
                        e["data"]["raw"] = validate_response(
                            e["data"]["raw"], s["bundles"][req["bundle_id"]]
                        )
                    except Exception:
                        e["data"]["raw"] = None
                        e["data"]["code"] = "MODEL_SCHEMA_INVALID"
            key = digest(e)
            if db.execute("SELECT id FROM events WHERE id=?", (key,)).fetchone():
                return False
            seq = 1 if last is None else last["seq"] + 1
            if seq > 1000000:
                raise ValueError("JOURNAL_CAPACITY_REACHED")
            if source is not None:
                db.execute(
                    "INSERT OR IGNORE INTO sources VALUES (?,?)",
                    (digest(source), canonical(source)),
                )
            state, effects = reduce(s, self._expand(db, e), self.config, self.calendar)
            body = dict(
                seq=seq,
                previous_sha256=last["sha256"] if last else self.binding_sha,
                event=e,
                effects=effects,
                state_sha256=digest(state),
                execution_allowed=False,
                orders_requested=0,
            )
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?)",
                (seq, key, canonical(body), digest(body)),
            )
            db.execute(
                "UPDATE checkpoint SET body=?,sha256=? WHERE id=1",
                (canonical(state), digest(state)),
            )
        return True

    def verify(self, *, replay=False):
        with self.connection(readonly=True) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("COMPARISON_SQLITE_CORRUPT")
            state, last = self.checkpoint(db)
            previous = self.binding_sha
            count = 0
            rebuilt = initial(self.config, self.binding["source_binding"])
            for r in db.execute("SELECT * FROM sources"):
                if digest(strict_json(r["body"])) != r["id"]:
                    raise ValueError("SOURCE_CHECKSUM_MISMATCH")
            for r in db.execute("SELECT * FROM events ORDER BY seq"):
                body = strict_json(r["body"])
                count += 1
                if (
                    r["seq"] != count
                    or body["seq"] != count
                    or body["previous_sha256"] != previous
                    or digest(body) != r["sha256"]
                    or digest(body["event"]) != r["id"]
                ):
                    raise ValueError("COMPARISON_AUDIT_CORRUPT")
                if replay:
                    rebuilt, effects = reduce(
                        rebuilt,
                        self._expand(db, body["event"]),
                        self.config,
                        self.calendar,
                    )
                    if (
                        digest(rebuilt) != body["state_sha256"]
                        or effects != body["effects"]
                    ):
                        raise ValueError("COMPARISON_REPLAY_DIFFERENCE")
                previous = r["sha256"]
            return dict(
                status="MATCH" if replay else "VERIFIED",
                events=count,
                state_sha256=digest(state),
                log_sha256=previous,
                source_kind=self.binding["source_kind"],
                signal="WAIT",
                execution_allowed=False,
                orders_requested=0,
                historical_validation="PENDING",
                historical_comparisons="NOT_RUN",
            )

    def snapshot(self):
        with self.connection(readonly=True) as db:
            s, _ = self.checkpoint(db)
            recent = []
            for row in db.execute(
                "SELECT body FROM events ORDER BY seq DESC LIMIT 100"
            ):
                for effect in strict_json(row["body"])["effects"]:
                    if effect["kind"] in ("ENTRY", "EXIT", "UNRESOLVED"):
                        recent.append(effect)
            latest = deepcopy(s["proposals"])
        for name in ENGINES:
            attempted = [
                r
                for r in s["requests"].values()
                if r["engine"] == name and r["reason"] is None
            ]
            s["engines"][name]["attempted_requests"] = len(attempted)
        b = s["bundles"].get(s["latest_bundle"])
        return dict(
            comparison_version=1,
            engine_version=VERSION,
            status="RESEARCH_ONLY",
            source_kind=self.binding["source_kind"],
            source_cursor=s["source_cursor"],
            source_hash=s["source_hash"],
            market_watermark=s["watermark"],
            current_market_quote=s["last_market_quote"],
            comparison_points=s["points"],
            common_evidence=b,
            proposals=latest,
            engines={
                k: dict(
                    metrics=metrics(v),
                    position=v["position"],
                    research_status=(
                        "BASELINE"
                        if k == "A_RULES"
                        else (
                            "NOT_RUN"
                            if not v["attempted_requests"]
                            else "RESEARCH_ATTEMPTED"
                        )
                    ),
                    attempted_provider_requests=v["attempted_requests"],
                )
                for k, v in s["engines"].items()
            },
            pending_timeline_events=len(s["queue"]),
            provider_requests={
                k: dict(
                    status=v["status"],
                    reason=v["reason"],
                    model=v["model"],
                    actual_ai=v["actual_ai"],
                    actual_ai_success=v.get("actual_ai_success", False),
                )
                for k, v in s["requests"].items()
            },
            budget=s["budget"],
            recent_simulated_activity=recent[:30],
            qualified_performance_metrics=None,
            confidence_calibration="NOT_RUN",
            ai_improvement="UNMEASURED",
            signal="WAIT",
            execution_allowed=False,
            orders_requested=0,
            exness="BLOCKED",
            stage_b_qualification="PENDING",
            stages_c_d="BLOCKED",
            historical_validation="PENDING",
            historical_comparisons="NOT_RUN",
        )
