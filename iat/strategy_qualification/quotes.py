"""Private bid/ask quote import and file-bound human evidence, never self-approval."""

from dataclasses import dataclass, asdict
from decimal import Decimal
from pathlib import Path
from hashlib import sha256
import csv, json
from iat.replay_dataset import strict_json, utc, read_bytes, local_file
from iat.intelligence.strategy_replay import digest


@dataclass(frozen=True)
class Quote:
    timestamp: str
    bid: str
    ask: str

    def __post_init__(self):
        utc(self.timestamp)
        if type(self.bid) is not str or type(self.ask) is not str:
            raise ValueError("Decimal quote strings required")
        b, a = Decimal(self.bid), Decimal(self.ask)
        if not b.is_finite() or not a.is_finite() or not 0 < b <= a:
            raise ValueError("Invalid bid/ask")

    @property
    def identity(self):
        return digest(asdict(self))


def read_quotes(path, expected_sha256, *, max_rows=1000000):
    """Streaming read, exact source-byte hash; strict timestamp order, no normalization repair."""
    p = Path(path)
    before = sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            before.update(chunk)
    if before.hexdigest() != expected_sha256:
        raise ValueError("QUOTE_CHECKSUM_MISMATCH")
    rows = []
    previous = None
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, strict=True)
        if reader.fieldnames != ["timestamp", "bid", "ask"]:
            raise ValueError("QUOTE_COLUMNS_INVALID")
        for row in reader:
            if set(row) != {"timestamp", "bid", "ask"} or any(
                v is None for v in row.values()
            ):
                raise ValueError("QUOTE_COLUMNS_INVALID")
            q = Quote(**row)
            at = utc(q.timestamp)
            if previous is not None and at <= previous:
                raise ValueError("QUOTE_ORDER_OR_DUPLICATE_AMBIGUOUS")
            previous = at
            rows.append(q)
            if len(rows) > max_rows:
                raise ValueError("QUOTE_ROW_LIMIT")
    after = sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            after.update(chunk)
    if before.digest() != after.digest():
        raise ValueError("QUOTE_SOURCE_CHANGED")
    if not rows:
        raise ValueError("QUOTE_DATA_UNAVAILABLE")
    return tuple(rows), dict(
        source_sha256=before.hexdigest(),
        normalized_sha256=digest([asdict(q) for q in rows]),
        count=len(rows),
        start=rows[0].timestamp,
        end=rows[-1].timestamp,
        ordering="STRICT_UTC_UNIQUE_TIMESTAMP_NO_INFERRED_WITHIN_TIMESTAMP_SEQUENCE",
    )


ITEMS = (
    "usage",
    "source_feed",
    "timestamp",
    "price_basis",
    "dated_calendar",
    "capture_completeness",
    "finality_corrections",
    "costs_symbol",
)


def qualify_quotes(manifest_path, dataset):
    result = dict(
        status="DATA_NOT_QUALIFIED", reason_codes=[], metadata=None, quotes=None
    )
    if manifest_path is None:
        result["reason_codes"] = ["QUALIFIED_BID_ASK_QUOTES_UNAVAILABLE"]
        return result
    try:
        path = Path(manifest_path)
        raw = read_bytes(path)
        m = strict_json(raw)
        if (
            set(m)
            != {
                "version",
                "symbol",
                "feed_id",
                "timestamp_convention",
                "price_basis",
                "interval",
                "file",
                "sha256",
                "preparer_code",
                "reviewer_code",
                "reviewed_at_utc",
                "costs_config_sha256",
                "evidence",
            }
            or type(m["version"]) is not int
            or m["version"] != 1
        ):
            raise ValueError("QUOTE_MANIFEST_INVALID")
        if (
            m["symbol"] != "XAUUSD"
            or m["price_basis"] != "BID_ASK"
            or m["timestamp_convention"] != "OBSERVATION_UTC"
            or m["feed_id"] != dataset.metadata["lineage"]["feed_id"]
            or m["interval"] != dataset.metadata["utc_range"]
        ):
            raise ValueError("QUOTE_LINEAGE_OR_COVERAGE_MISMATCH")
        if (
            not all(
                isinstance(m[k], str) and m[k].strip()
                for k in ("preparer_code", "reviewer_code")
            )
            or m["preparer_code"] == m["reviewer_code"]
        ):
            raise ValueError("INDEPENDENT_QUOTE_REVIEW_REQUIRED")
        utc(m["reviewed_at_utc"])
        if set(m["evidence"]) != set(ITEMS):
            raise ValueError("QUOTE_EVIDENCE_INCOMPLETE")
        for key, e in m["evidence"].items():
            if (
                set(e) != {"status", "file", "sha256", "reference", "interval"}
                or e["status"] != "VERIFIED"
                or not isinstance(e["reference"], str)
                or not e["reference"]
                or e["interval"] != m["interval"]
            ):
                raise ValueError("QUOTE_EVIDENCE_" + key.upper() + "_PENDING")
            content = read_bytes(local_file(path.parent, e["file"]))
            if not content or sha256(content).hexdigest() != e["sha256"]:
                raise ValueError("QUOTE_EVIDENCE_CHECKSUM_MISMATCH")
        rows, meta = read_quotes(local_file(path.parent, m["file"]), m["sha256"])
        start, end = map(utc, (m["interval"]["start"], m["interval"]["end"]))
        if utc(rows[0].timestamp) > start or utc(rows[-1].timestamp) < end:
            raise ValueError("QUOTE_INTERVAL_NOT_COVERED")
        # This is an explicit attestation/document gate, not external provider authentication.
        meta.update(
            manifest_sha256=sha256(raw).hexdigest(),
            feed_id=m["feed_id"],
            interval=m["interval"],
            evidence_sha256=digest(m["evidence"]),
            cost_document_sha256=m["evidence"]["costs_symbol"]["sha256"],
            reviewed_costs_config_sha256=m["costs_config_sha256"],
            assurance="FILE_BOUND_INDEPENDENT_REVIEW_DECLARATIONS_NOT_PROVIDER_AUTHENTICATION",
        )
        result.update(
            status="QUOTE_PRECHECKS_PASSED",
            metadata=meta,
            quotes=tuple(q for q in rows if start <= utc(q.timestamp) <= end),
        )
    except Exception as exc:
        code = str(exc)
        allowed = {
            "QUOTE_CHECKSUM_MISMATCH",
            "QUOTE_ORDER_OR_DUPLICATE_AMBIGUOUS",
            "QUOTE_COLUMNS_INVALID",
            "QUOTE_ROW_LIMIT",
            "QUOTE_SOURCE_CHANGED",
            "QUOTE_DATA_UNAVAILABLE",
            "QUOTE_MANIFEST_INVALID",
            "QUOTE_LINEAGE_OR_COVERAGE_MISMATCH",
            "INDEPENDENT_QUOTE_REVIEW_REQUIRED",
            "QUOTE_EVIDENCE_INCOMPLETE",
            "QUOTE_EVIDENCE_CHECKSUM_MISMATCH",
            "QUOTE_INTERVAL_NOT_COVERED",
        } | {"QUOTE_EVIDENCE_" + k.upper() + "_PENDING" for k in ITEMS}
        result["reason_codes"] = [
            code if code in allowed else "QUOTE_INPUT_OR_REVIEW_INVALID"
        ]
    return result
