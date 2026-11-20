"""Private SQLite v1: immutable inputs/effects plus an atomically bound recovery checkpoint."""

from contextlib import contextmanager
from pathlib import Path
from copy import deepcopy
import sqlite3, json, shutil
from iat.intelligence.strategy_replay import digest
from iat.replay_dataset import strict_json
from iat.live_shadow.processor import initial_state, reduce_packet
from iat.live_shadow.engine import summary
from iat.live_shadow import LABEL


def calendar_identity(calendar):
    if calendar is None:
        return None
    value = getattr(calendar, "configuration_sha256", None)
    if value:
        return value
    return digest(
        dict(
            symbol=calendar.symbol,
            start=calendar.coverage_start.isoformat(),
            end=calendar.coverage_end.isoformat(),
            windows=[[a.isoformat(), b.isoformat()] for a, b in calendar.windows],
            assurance=list(calendar.assurance_codes),
        )
    )


def safe_packet(packet):
    # Reject arbitrary keys/strings instead of attempting to redact unknown secrets.
    from math import isfinite
    import re
    from iat.live_data import FIELDS

    def scalar(v):
        return (
            v is None
            or type(v) in (int, float)
            and isfinite(v)
            or v in ({"invalid_numeric": True}, {"unsupported_type": True})
        )

    expected = {
        "received_at",
        "quote",
        "capture",
        "candles",
        "raw_candles",
        "identity",
        "symbol_specification",
        "errors",
        "observer_snapshot_id",
        "observer_reason_codes",
    }
    if set(packet) != expected:
        raise ValueError("PACKET_SCHEMA_INVALID")

    def quote(q):
        if q is None:
            return
        if (
            set(q)
            != {
                "timestamp",
                "bid",
                "ask",
                "spread",
                "price_basis",
                "timestamp_basis",
                "id",
            }
            or q["price_basis"] != "OBSERVED_MT5_BID_ASK"
            or q["timestamp_basis"] != "MT5_API_UTC_EPOCH_MILLISECONDS"
        ):
            raise ValueError("QUOTE_SCHEMA_INVALID")
        utc(q["timestamp"])
        from decimal import Decimal

        for key in ("bid", "ask", "spread"):
            if type(q[key]) is not str or not Decimal(q[key]).is_finite():
                raise ValueError("QUOTE_SCHEMA_INVALID")
        if not re.fullmatch("[a-f0-9]{64}", q["id"]):
            raise ValueError("QUOTE_ID_INVALID")

    from iat.replay_dataset import utc

    utc(packet["received_at"])
    quote(packet["quote"])
    c = packet["capture"]
    if (
        set(c)
        not in (
            {"start", "end", "status", "reason_codes", "ticks", "assurance"},
            {
                "start",
                "end",
                "status",
                "reason_codes",
                "ticks",
                "assurance",
                "requested_start",
                "requested_end",
                "excluded_outside_window",
            },
        )
        or c["status"] not in ("OBSERVED_RANGE", "UNAVAILABLE")
        or c["assurance"]
        != "TERMINAL_RETURNED_OBSERVATIONS_NOT_PROVIDER_CAPTURE_COMPLETENESS_PROOF"
    ):
        raise ValueError("CAPTURE_SCHEMA_INVALID")
    utc(c["start"])
    utc(c["end"])
    if "requested_start" in c:
        from datetime import timedelta

        a, b = utc(c["requested_start"]), utc(c["requested_end"])
        if (
            a.microsecond
            or b.microsecond
            or not a <= utc(c["start"]) <= utc(c["end"]) <= b
            or utc(c["start"]) - a >= timedelta(seconds=1)
            or b - utc(c["end"]) >= timedelta(seconds=1)
            or type(c["excluded_outside_window"]) is not int
            or not 0 <= c["excluded_outside_window"] <= 20000
        ):
            raise ValueError("CAPTURE_QUERY_BOUNDARIES_INVALID")
    if len(c["ticks"]) > 20000:
        raise ValueError("CAPTURE_LIMIT")
    for q in c["ticks"]:
        quote(q)
    for codes in (packet["errors"], c["reason_codes"], packet["observer_reason_codes"]):
        if not isinstance(codes, list) or any(
            not isinstance(v, str) or not re.fullmatch("[A-Z][A-Z0-9_]{0,95}", v)
            for v in codes
        ):
            raise ValueError("ERROR_CODES_INVALID")
    i = packet["identity"]
    if i is not None and i != dict(
        broker="EXNESS_COMPANY_LABEL_MATCH",
        symbol="XAUUSD",
        account_mode="DEMO",
        assurance="OBSERVED_COMPANY_LABEL_NOT_AUTHENTICATED_ACCOUNT_BINDING",
        trading_permissions_disabled=True,
    ):
        raise ValueError("IDENTITY_FIELDS_UNSAFE")
    if i is not None and i["trading_permissions_disabled"] is not True:
        raise ValueError("IDENTITY_FIELDS_UNSAFE")
    allowed = {
        "trade_contract_size",
        "trade_tick_size",
        "trade_stops_level",
        "point",
        "digits",
        "volume_min",
        "volume_max",
        "volume_step",
        "currency_profit",
        "trade_calc_mode",
    }
    if set(packet["symbol_specification"]) - allowed or any(
        not scalar(v)
        for k, v in packet["symbol_specification"].items()
        if k != "currency_profit"
    ):
        raise ValueError("SYMBOL_FIELDS_UNSAFE")
    if packet["symbol_specification"].get("currency_profit") not in (None, "USD"):
        raise ValueError("SYMBOL_CURRENCY_UNSUPPORTED")
    if set(packet["candles"]) != {"M1", "M5"}:
        raise ValueError("CANDLE_SCHEMA_INVALID")
    for tf, rows in packet["candles"].items():
        if len(rows) > 500:
            raise ValueError("CANDLE_CAPACITY")
        for row in rows:
            if set(row) != {"timestamp", "open", "high", "low", "close"} or any(
                not scalar(row[k]) for k in ("open", "high", "low", "close")
            ):
                raise ValueError("CANDLE_FIELDS_UNSAFE")
            utc(row["timestamp"])
    if set(packet["raw_candles"]) - {"M1", "M5"}:
        raise ValueError("RAW_FIELDS_UNSAFE")
    for frame in packet["raw_candles"].values():
        if (
            set(frame) != {"position", "requested_count", "rates"}
            or frame["position"] != 1
            or type(frame["requested_count"]) is not int
            or len(frame["rates"]) > 501
        ):
            raise ValueError("RAW_FIELDS_UNSAFE")
        for row in frame["rates"]:
            if set(row) - set(FIELDS) or any(not scalar(v) for v in row.values()):
                raise ValueError("RAW_FIELDS_UNSAFE")
    if not re.fullmatch("[a-f0-9]{64}", packet["observer_snapshot_id"]):
        raise ValueError("OBSERVER_ID_INVALID")


def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Journal:
    def __init__(
        self,
        directory,
        config,
        *,
        calendar=None,
        create=False,
        source_kind="LIVE_MT5_OBSERVATIONS"
    ):
        self.root = Path(directory)
        self.path = self.root / "shadow.sqlite3"
        self.config = config
        self.calendar = calendar
        repo = Path(__file__).resolve().parents[2]
        if self.root.resolve().is_relative_to(repo) or any(
            p.is_symlink() for p in (self.root, *self.root.parents)
        ):
            raise ValueError("PRIVATE_JOURNAL_DIRECTORY_REQUIRED")
        if source_kind not in ("LIVE_MT5_OBSERVATIONS", "SYNTHETIC_FIXTURE"):
            raise ValueError("SOURCE_KIND_INVALID")
        from iat.strategy_qualification.specs import specifications, PROTOCOL_SHA256
        from iat.intelligence.context_models import ContextConfig
        from iat.intelligence.models import IntelligenceConfig

        self.binding = dict(
            schema_version=1,
            engine_version="live-shadow-1.0.2",
            research_specifications=[v.description() for v in specifications()],
            context_sha256=ContextConfig().digest,
            intelligence_sha256=IntelligenceConfig().digest,
            stage_b_protocol_sha256=PROTOCOL_SHA256,
            configuration=config,
            calendar_sha256=calendar_identity(calendar),
            source_kind=source_kind,
        )
        self.binding_sha = digest(self.binding)
        if create:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
            with self.connection(create=True) as db:
                db.execute(
                    "CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,sha256 TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE sources (id TEXT PRIMARY KEY,body TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE events (seq INTEGER PRIMARY KEY,id TEXT NOT NULL UNIQUE,body TEXT NOT NULL,sha256 TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE checkpoint (id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,sha256 TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE artifacts (kind TEXT NOT NULL,id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(kind,id))"
                )
                db.execute(
                    "INSERT INTO meta VALUES (1,?,?)",
                    (canonical(self.binding), self.binding_sha),
                )
                s = initial_state()
                db.execute(
                    "INSERT INTO checkpoint VALUES (1,?,?)", (canonical(s), digest(s))
                )
        self.verify()

    @contextmanager
    def connection(self, *, create=False, readonly=False):
        db = None
        try:
            if not create and (not self.path.is_file() or self.path.is_symlink()):
                raise ValueError("JOURNAL_MISSING_OR_UNSAFE")
            db = sqlite3.connect(
                (
                    self.path.resolve().as_uri()
                    + ("?mode=ro" if readonly else "?mode=rw")
                    if not create
                    else str(self.path)
                ),
                uri=not create,
                timeout=3,
                isolation_level=None,
            )
            db.row_factory = sqlite3.Row
            if not readonly:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("PRAGMA foreign_keys=ON")
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

    def _checkpoint(self, db):
        meta = db.execute("SELECT * FROM meta").fetchone()
        if (
            not meta
            or meta["body"] != canonical(self.binding)
            or meta["sha256"] != self.binding_sha
        ):
            raise ValueError("JOURNAL_CONFIG_OR_SOURCE_MISMATCH")
        row = db.execute("SELECT * FROM checkpoint").fetchone()
        s = strict_json(row["body"])
        last = db.execute(
            "SELECT body,sha256 FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if last and digest(strict_json(last["body"])) != last["sha256"]:
            raise ValueError("JOURNAL_LAST_EVENT_CORRUPT")
        expected = (
            strict_json(last["body"])["state_sha256"]
            if last
            else digest(initial_state())
        )
        if digest(s) != row["sha256"] or row["sha256"] != expected:
            raise ValueError("JOURNAL_CHECKPOINT_CORRUPT")
        return s, last

    def verify(self, *, replay=False):
        with self.connection(readonly=True) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLITE_INTEGRITY_FAILED")
            state, last = self._checkpoint(db)
            previous = self.binding_sha
            count = 0
            projections = {}
            reduced = initial_state()
            previous_source = None
            for source in db.execute("SELECT * FROM sources"):
                if digest(strict_json(source["body"])) != source["id"]:
                    raise ValueError("SOURCE_CHECKSUM_MISMATCH")
            for row in db.execute("SELECT * FROM events ORDER BY seq"):
                body = strict_json(row["body"])
                count += 1
                if (
                    row["seq"] != count
                    or body["seq"] != count
                    or body["previous_sha256"] != previous
                    or digest(body) != row["sha256"]
                    or row["id"] != digest(body["packet"])
                ):
                    raise ValueError("JOURNAL_AUDIT_CORRUPT")
                raw = db.execute(
                    "SELECT body FROM sources WHERE id=?",
                    (body["packet"]["source_id"],),
                ).fetchone()
                if raw is None:
                    raise ValueError("JOURNAL_SOURCE_MISSING")
                if replay:
                    source = strict_json(raw["body"])
                    packet = deepcopy(body["packet"])
                    packet.update(source)
                    reduced, effects = reduce_packet(
                        reduced,
                        packet,
                        self.config,
                        self.calendar,
                        previous_candles=previous_source,
                    )
                    reduced["last_source"] = packet["source_id"]
                    previous_source = source["candles"]
                    if (
                        effects != body["effects"]
                        or digest(reduced) != body["state_sha256"]
                    ):
                        raise ValueError("OFFLINE_REPLAY_DIFFERENCE")
                for index, effect in enumerate(body["effects"]):
                    if effect["kind"] in (
                        "DECISION",
                        "INTENT",
                        "FILL",
                        "EXIT",
                        "UNRESOLVED",
                    ):
                        projections[(effect["kind"], effect["id"])] = canonical(effect)
                previous = row["sha256"]
            actual = {
                (r["kind"], r["id"]): r["body"]
                for r in db.execute("SELECT * FROM artifacts")
            }
            if projections != actual:
                raise ValueError("JOURNAL_PROJECTION_CORRUPT")
            return dict(
                status="MATCH" if replay else "VERIFIED",
                event_count=count,
                last_event_sha256=previous,
                checkpoint_sha256=digest(state),
                source_kind=self.binding["source_kind"],
                summary=summary(state["engine"]),
                signal="WAIT",
                execution_allowed=False,
                orders_requested=0,
            )

    def state(self):
        with self.connection(readonly=True) as db:
            return self._checkpoint(db)[0]

    def record(self, packet):
        if shutil.disk_usage(self.root).free < 128 * 1024 * 1024:
            raise ValueError("JOURNAL_DISK_HEADROOM_REQUIRED")
        safe_packet(packet)
        packet = deepcopy(packet)
        # Only fixed non-identifying fields from the read-only adapter are accepted.
        if packet["identity"] is not None and set(packet["identity"]) != {
            "broker",
            "symbol",
            "account_mode",
            "assurance",
            "trading_permissions_disabled",
        }:
            raise ValueError("IDENTITY_FIELDS_UNSAFE")
        source = {k: packet.pop(k) for k in ("candles", "raw_candles")}
        source_id = digest(source)
        packet["source_id"] = source_id
        event_id = digest(packet)
        with self.connection() as db:
            state, last = self._checkpoint(db)
            duplicate = db.execute(
                "SELECT id FROM events WHERE id=?", (event_id,)
            ).fetchone()
            if duplicate:
                return False
            seq = 1 if last is None else strict_json(last["body"])["seq"] + 1
            if seq > 1000000:
                raise ValueError("JOURNAL_CAPACITY_REQUIRES_NEW_REVIEWED_SEGMENT")
            previous = None
            if state["last_source"]:
                previous = strict_json(
                    db.execute(
                        "SELECT body FROM sources WHERE id=?", (state["last_source"],)
                    ).fetchone()[0]
                )["candles"]
            expanded = deepcopy(packet)
            expanded.update(source)
            state, effects = reduce_packet(
                state, expanded, self.config, self.calendar, previous_candles=previous
            )
            state["last_source"] = source_id
            body = dict(
                seq=seq,
                previous_sha256=last["sha256"] if last else self.binding_sha,
                packet=packet,
                effects=effects,
                state_sha256=digest(state),
                label=LABEL,
                execution_allowed=False,
                orders_requested=0,
            )
            db.execute(
                "INSERT OR IGNORE INTO sources VALUES (?,?)",
                (source_id, canonical(source)),
            )
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?)",
                (seq, event_id, canonical(body), digest(body)),
            )
            for effect in effects:
                if effect["kind"] in (
                    "DECISION",
                    "INTENT",
                    "FILL",
                    "EXIT",
                    "UNRESOLVED",
                ):
                    db.execute(
                        "INSERT OR REPLACE INTO artifacts VALUES (?,?,?)",
                        (effect["kind"], effect["id"], canonical(effect)),
                    )
            db.execute(
                "UPDATE checkpoint SET body=?,sha256=? WHERE id=1",
                (canonical(state), digest(state)),
            )
        return True

    def snapshot(self):
        with self.connection(readonly=True) as db:
            state, last = self._checkpoint(db)
            closed = [
                strict_json(r["body"])["trade"]
                for r in db.execute(
                    "SELECT body FROM artifacts WHERE kind='EXIT' ORDER BY rowid DESC LIMIT 20"
                )
            ]
        packet = strict_json(last["body"])["packet"] if last else None
        return dict(
            shadow_version=1,
            feed_status=(
                "CONNECTED"
                if packet
                and packet["identity"]
                and packet["quote"]
                and not packet["errors"]
                else "DATA_UNAVAILABLE"
            ),
            data_quality_warnings=sorted(
                set(
                    (
                        packet["errors"] + packet["capture"]["reason_codes"]
                        if packet
                        else []
                    )
                    + (state["session"]["reason_codes"] if state["session"] else [])
                )
            ),
            original_observer_reason_codes=(
                packet["observer_reason_codes"] if packet else []
            ),
            label=LABEL,
            status="RECORDING",
            source_kind=self.binding["source_kind"],
            identity=strict_json(last["body"])["packet"]["identity"] if last else None,
            symbol_specification=(
                strict_json(last["body"])["packet"]["symbol_specification"]
                if last
                else None
            ),
            research_candidate=(
                state["last_decision"].get("candidate", "BLOCKED")
                if state["last_decision"]
                else "BLOCKED"
            ),
            safety_gate_outcome="BROKER_EXECUTION_DISABLED_UNQUALIFIED_SHADOW_ONLY",
            quote=strict_json(last["body"])["packet"]["quote"] if last else None,
            research=state["last_decision"],
            session=state["session"],
            open_position=state["engine"]["position"],
            closed_trades=closed,
            performance=summary(state["engine"]),
            observations=state["polls"],
            data_completeness=dict(
                valid_quotes=state["valid_quotes"],
                valid_candles=state["valid_candles"],
                denominator=state["polls"],
            ),
            last_successful_observation=state["last_successful_observation"],
            last_received=state["last_received"],
            configuration_sha256=self.binding_sha,
            signal="WAIT",
            execution_allowed=False,
            orders_requested=0,
            broker_execution="DISABLED_NO_ADAPTER",
            exness="BLOCKED",
            historical_validation="PENDING",
            historical_comparisons="NOT_RUN",
            stage_b_qualification="PENDING",
            stages_c_d="BLOCKED",
            qualified_performance_metrics=None,
        )
