"""Offline operator-file verification. Mechanical reproduction never qualifies data."""

from collections import Counter
from datetime import timedelta
from pathlib import Path
from copy import deepcopy
import csv
import math
import subprocess
import sys

from iat.analysis import validate_candles
from iat.chart_benchmark import check_hash, hashed, write_new
from iat.historical_evidence_manifest import (
    HEADERS,
    MAPPING,
    MAX_FILE_BYTES,
    local_path,
)
from iat.historical_replay import safety
from iat.pilot_preparation import file_fingerprint, _bounded_lines
from iat.replay_dataset import strict_json, utc
from iat.session_config import compile_session_config
from iat.session_v2 import CLASSES, STATES

ROOT = Path(__file__).resolve().parents[1]
START = "2026-11-11T00:00:00Z"
END = "2026-11-14T00:00:00Z"
EXPECTED = dict(
    M1_observations=4074,
    M5_observations=816,
    five_m1_matches=813,
    partial_m5_intervals=3,
    missing_m1_slots=6,
)
CODES = (
    "REOPEN_2300_VS_230030",
    "CLOSE_ONLY_VS_FULL_TRADING",
    "FRIDAY_WEEKEND_SCOPE",
    "NOVEMBER_11_HOLIDAY",
    "REGULAR_VS_SPECIAL_MAINTENANCE",
    "UTC_AND_BID_PROVENANCE",
    "FULL_AND_PARTIAL_FINALITY",
    "CORRECTIONS_AND_CAPTURE_COMPLETENESS",
)


class Failure(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise Failure(code)


def safe_path(value):
    p = local_path(value)
    if sys.platform == "win32":
        import ctypes

        root = p.absolute().anchor
        need(
            ctypes.windll.kernel32.GetDriveTypeW(root) in (2, 3, 5, 6),
            "LOCAL_DRIVE_REQUIRED",
        )
    need(
        not any(x.is_symlink() for x in (p, *p.parents)),
        "SYMLINK_INPUT_OR_OUTPUT_REJECTED",
    )
    resolved = p.resolve()
    need(not str(resolved).startswith(("\\\\", "//")), "LOCAL_PATH_REQUIRED")
    return p


def private_path(path):
    need(
        not path.resolve().is_relative_to(ROOT)
        and not any(
            (parent / ".git").is_file() or (parent / ".git" / "HEAD").is_file()
            for parent in (path, *path.parents)
        ),
        "PRIVATE_PATH_OUTSIDE_GIT_REQUIRED",
    )


def read_report(path):
    need(path.stat().st_size <= 4 * 1024 * 1024, "REPORT_SIZE_LIMIT")
    with path.open("rb") as stream:
        content = stream.read(4 * 1024 * 1024 + 1)
    need(len(content) <= 4 * 1024 * 1024, "REPORT_SIZE_LIMIT")
    value = strict_json(content)
    try:
        check_hash(value)
    except (ValueError, TypeError):
        raise Failure("DIAGNOSTIC_PAYLOAD_CHECKSUM_INVALID") from None
    need(
        value.get("boundary_report_version") == 1
        and value.get("kind") == "HISTORICAL_SESSION_BOUNDARY_RESEARCH"
        and value.get("status") == "RESEARCH_DIAGNOSTICS_ONLY",
        "DIAGNOSTIC_SCHEMA_OR_STATUS_INVALID",
    )
    need(
        value.get("provenance") != "SYNTHETIC_ONLY"
        and value.get("observation_origin") != "SYNTHETIC_ONLY",
        "DECLARED_SYNTHETIC_REPORT_NOT_OPERATOR_EVIDENCE",
    )
    need(
        value.get("safety") == safety()
        and value.get("ordinary_inputs_emitted") is False
        and value.get("qualification") == "DATA_NOT_QUALIFIED"
        and value.get("exness") == "BLOCKED"
        and value.get("historical_validation") == "PENDING"
        and value.get("historical_comparisons") == "NOT_RUN"
        and value.get("signal", "WAIT") == "WAIT"
        and value.get("execution_allowed", False) is False,
        "DIAGNOSTIC_SAFETY_INVARIANT_FAILED",
    )
    return value


def scan(path, timeframe, start, end):
    """Exact declared headers; never infer metadata, UTC, or silently select an archive."""
    rows = []
    counts = Counter()
    gaps = []
    seen = set()
    previous = None
    step = timedelta(minutes=1 if timeframe == "M1" else 5)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(_bounded_lines(handle), strict=True)
        need(reader.fieldnames == HEADERS, "CSV_HEADERS_MUST_MATCH_REVIEWED_EXPORT")
        for line, record in enumerate(reader, 2):
            need(len(rows) < 5000, "CSV_ROW_LIMIT")
            need(
                set(record) == set(HEADERS)
                and all(type(x) is str for x in record.values()),
                "CSV_COLUMNS_INVALID",
            )
            try:
                t = utc(record["timestamp_utc"])
            except ValueError:
                raise Failure("CSV_UTC_TIMESTAMP_REQUIRED") from None
            if t in seen:
                counts["TIMESTAMP_DUPLICATE"] += 1
            if previous is not None:
                if t < previous:
                    counts["TIMESTAMP_OUT_OF_ORDER"] += 1
                elif t - previous > step:
                    if len(gaps) < 64:
                        gaps.append(
                            dict(
                                after_utc=previous.isoformat(),
                                next_open_utc=t.isoformat(),
                                unobserved_grid_slots=int((t - previous) / step) - 1,
                                assessment="NOMINAL_GAP_NOT_AUTOMATICALLY_UNEXPECTED",
                            )
                        )
                    counts["RAW_GAPS"] += 1
            if t.timestamp() % step.total_seconds():
                counts["TIMEFRAME_MISALIGNED"] += 1
            if not start <= t < end:
                counts["OUTSIDE_REQUESTED_WINDOW"] += 1
            try:
                values = {k: float(record[k]) for k in ("open", "high", "low", "close")}
            except ValueError:
                raise Failure("OHLC_INVALID") from None
            need(
                all(math.isfinite(x) and x > 0 for x in values.values())
                and values["high"] >= max(values.values())
                and values["low"] <= min(values.values()),
                "OHLC_INVALID",
            )
            rows.append(dict(timestamp=t.isoformat(), **values))
            seen.add(t)
            previous = t
    need(len(rows) >= 3, "CSV_HISTORY_INSUFFICIENT")
    errors = {k: v for k, v in counts.items() if k != "RAW_GAPS"}
    result = dict(
        headers=HEADERS,
        row_count=len(rows),
        first_open_utc=rows[0]["timestamp"],
        last_open_utc=rows[-1]["timestamp"],
        raw_gap_count=counts["RAW_GAPS"],
        raw_gap_samples=gaps,
        raw_gap_sample_limit=64,
        errors=errors,
        source_identity="UNVERIFIED",
        price_basis="UNVERIFIED",
        finality="UNESTABLISHED",
    )
    if not errors:
        validate_candles(rows)
    return rows, result


def code_counts(value):
    import re

    need(type(value) is dict and len(value) <= 64, "DIAGNOSTIC_COUNTS_INVALID")
    need(
        all(
            type(k) is str
            and re.fullmatch("[A-Z0-9_]{1,80}", k)
            and type(v) is int
            and 0 <= v <= 25000
            for k, v in value.items()
        ),
        "DIAGNOSTIC_COUNTS_INVALID",
    )
    return deepcopy(value)


def projection(report):
    """Whitelisted comparisons; no raw source text, OHLC or account identifiers."""
    frames = {}
    for tf in ("M1", "M5"):
        f = report["frames"][tf]
        need(
            type(f["observed_count"]) is int and 0 <= f["observed_count"] <= 5000,
            "DIAGNOSTIC_COUNTS_INVALID",
        )
        classes, phases = code_counts(f["classifications"]), code_counts(
            f["phase_bar_counts"]
        )
        need(
            set(classes) == set(CLASSES) and set(phases) == set(STATES),
            "DIAGNOSTIC_CLASSES_INVALID",
        )
        missing = {
            k: f[k]
            for k in (
                "nominal_missing_quote_slots",
                "missing_full_under_verified_declarations",
                "missing_unresolved_or_restricted_slots",
            )
        }
        need(
            all(v is None or type(v) is int and v >= 0 for v in missing.values()),
            "DIAGNOSTIC_COUNTS_INVALID",
        )
        frames[tf] = dict(
            observed_count=f["observed_count"],
            classifications=classes,
            phase_bar_counts=phases,
            missing=missing,
        )
    comparisons = code_counts(report["comparison_counts"])
    absent = code_counts(report["m1_slot_absence_counts"])
    import re

    calendar_sha = report["calendar_state"]["configuration_sha256"]
    need(
        type(calendar_sha) is str and re.fullmatch("[a-f0-9]{64}", calendar_sha),
        "DIAGNOSTIC_CALENDAR_HASH_INVALID",
    )
    intervals = {}
    need(
        type(report["m5_intervals"]) is list and len(report["m5_intervals"]) <= 64,
        "DIAGNOSTIC_SAMPLE_INVALID",
    )
    for item in report["m5_intervals"]:
        g = item["geometry"]
        need(
            g["classification"] in CLASSES
            and all(p in STATES for p in g["phase_states"]),
            "DIAGNOSTIC_SAMPLE_INVALID",
        )
        need(
            item["ordinary_eligible"] is False
            and g["ordinary_eligible"] is False
            and g["iat_execution_allowed"] is False,
            "DIAGNOSTIC_SAFETY_INVARIANT_FAILED",
        )
        seconds = g["market_open_seconds"]
        need(
            seconds is None
            or type(seconds) in (int, float)
            and math.isfinite(seconds)
            and 0 <= seconds <= 300,
            "DIAGNOSTIC_SAMPLE_INVALID",
        )
        opening = utc(g["scheduled_open_utc"]).isoformat()
        slots = {}
        need(len(item["m1_slots"]) == 5, "DIAGNOSTIC_SAMPLE_INVALID")
        for slot in item["m1_slots"]:
            state = slot["assessment"]
            need(
                type(state) is str
                and re.fullmatch("[A-Z_]{1,80}", state)
                and type(slot["observed_count"]) is int
                and slot["observed_count"] >= 0,
                "DIAGNOSTIC_SAMPLE_INVALID",
            )
            slots[utc(slot["timestamp_utc"]).isoformat()] = dict(
                assessment=state, observed_count=slot["observed_count"]
            )
        comparison = item["five_m1_comparison"]
        need(
            type(comparison) is str and re.fullmatch("[A-Z0-9_]{1,80}", comparison),
            "DIAGNOSTIC_SAMPLE_INVALID",
        )
        intervals[opening] = dict(
            classification=g["classification"],
            phase_states=g["phase_states"],
            scheduled_end_utc=utc(g["scheduled_end_utc"]).isoformat(),
            nominal_quote_seconds=seconds,
            m1_slots=slots,
            comparison=comparison,
        )
    return dict(
        window={k: utc(report["scope"][k]).isoformat() for k in ("start", "end")},
        frames=frames,
        comparison_counts=comparisons,
        missing_m1_slot_counts=absent,
        calendar_configuration_sha256=calendar_sha,
        sampled_m5_intervals=intervals,
        diagnostic_reason_codes=sorted(
            code_counts({c: 0 for c in report["reason_codes"]})
        ),
        metrics=dict(
            M1_observations=frames["M1"]["observed_count"],
            M5_observations=frames["M5"]["observed_count"],
            five_m1_matches=comparisons.get("FIVE_M1_MATCH", 0),
            partial_m5_intervals=frames["M5"]["classifications"][
                "PARTIAL_SESSION_CLOSE"
            ],
            missing_m1_slots=sum(absent.values()),
        ),
    )


def differences(left, right, path=""):
    if type(left) is dict and type(right) is dict:
        return [
            d
            for k in sorted(set(left) | set(right))
            for d in differences(left.get(k), right.get(k), path + "/" + k)
        ]
    return [] if left == right else [dict(field=path, original=left, recomputed=right)]


def bindings(report, fingerprints):
    supplied = report.get("file_observations", {})
    declared = {
        tf: supplied.get("sources", {}).get(tf, {}).get("fingerprint")
        for tf in ("M1", "M5")
    }
    declared["calendar"] = supplied.get("calendar_file_fingerprint")
    fields = {
        k: (
            "UNAVAILABLE"
            if v is None
            else "MATCH" if v == fingerprints[k] else "DIFFERENT"
        )
        for k, v in declared.items()
    }
    fields["column_mapping"] = (
        "MATCH"
        if supplied.get("columns") == MAPPING
        else "UNAVAILABLE" if "columns" not in supplied else "DIFFERENT"
    )
    return fields


def boundaries(rows, calendar, diagnostic):
    indexes = {tf: {utc(r["timestamp"]) for r in bars} for tf, bars in rows.items()}
    samples = {
        utc(x["geometry"]["scheduled_open_utc"]): x for x in diagnostic["m5_intervals"]
    }
    result = []
    for day, clock in [(d, "21:55:00") for d in (11, 12, 13)] + [
        (d, "23:00:00") for d in (11, 12, 13)
    ]:
        t = utc(f"2026-11-{day}T{clock}Z")
        g = calendar.classify_bar(t, "M5", research=True)
        result.append(
            dict(
                open_utc=t.isoformat(),
                within_requested_window=utc(diagnostic["scope"]["start"])
                <= t
                < utc(diagnostic["scope"]["end"]),
                m5_file_observation_present=t in indexes["M5"],
                m1_observed_slots=[
                    dict(
                        open_utc=(t + timedelta(minutes=i)).isoformat(),
                        observed=t + timedelta(minutes=i) in indexes["M1"],
                    )
                    for i in range(5)
                ],
                nominal_geometry={
                    k: g[k]
                    for k in (
                        "classification",
                        "phase_states",
                        "market_open_seconds",
                        "scheduled_end_utc",
                        "schedule_verified",
                    )
                },
                diagnostic_comparison=(
                    samples[t]["five_m1_comparison"]
                    if t in samples
                    else "NOT_IN_BOUNDED_SAMPLE"
                ),
                interval_open_is_first_tick_time=False,
                actual_first_tick_utc=None,
                trading_permission_proven=False,
                finality="UNESTABLISHED",
                ordinary_eligible=False,
            )
        )
    return result


def verify(
    m1, m5, original_report, calendar_path, output_directory, *, start=START, end=END
):
    """Consume only explicit files. No generation/fallback, MT5, network or approval."""
    out = safe_path(output_directory)
    private_path(out)
    need(
        not out.resolve().is_relative_to(ROOT) and not out.exists(),
        "NEW_PRIVATE_OUTPUT_DIRECTORY_REQUIRED",
    )
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    result = dict(
        evidence_version=1,
        kind="LOCAL_BOUNDARY_REPRODUCTION",
        status="BLOCKED",
        input_provenance="UNVERIFIED_OPERATOR_SELECTED_BYTES",
        required_csv_headers=HEADERS,
        expected_operator_counts=dict(EXPECTED),
        input_integrity={},
        scans={},
        diagnostic=dict(status="NOT_RUN", exit_code=None),
        comparison=dict(status="NOT_RUN"),
        qualification="DATA_NOT_QUALIFIED",
        exness="BLOCKED",
        signal="WAIT",
        execution_allowed=False,
        historical_validation="PENDING",
        historical_comparisons="NOT_RUN",
        safety=safety(),
        conflicts=[
            dict(code=c, status="UNRESOLVED", resolved_by_ohlc_match=False)
            for c in CODES
        ],
        reason_codes=[],
    )
    paths = {}
    before = {}
    try:
        a, b = utc(start), utc(end)
        need(a < b and (b - a).total_seconds() / 60 <= 20000, "WINDOW_INVALID")
        result["window"] = dict(start=a.isoformat(), end=b.isoformat())
        for key, value in dict(
            M1=m1, M5=m5, original_report=original_report, calendar=calendar_path
        ).items():
            try:
                p = safe_path(value)
                need(p.is_file(), "REQUIRED_INPUT_UNAVAILABLE_" + key.upper())
                need(
                    0
                    < p.stat().st_size
                    <= (MAX_FILE_BYTES if key in ("M1", "M5") else 4 * 1024 * 1024),
                    "INPUT_SIZE_LIMIT",
                )
                if key != "calendar":
                    private_path(p)
                before[key] = file_fingerprint(p)
                paths[key] = p
                result["input_integrity"][key] = dict(
                    status="READABLE", before=before[key], after=None, unchanged=None
                )
            except (OSError, ValueError) as exc:
                code = (
                    str(exc)
                    if isinstance(exc, Failure)
                    else "INPUT_UNAVAILABLE_OR_UNSAFE"
                )
                result["input_integrity"][key] = dict(
                    status="UNAVAILABLE_OR_UNSAFE",
                    before=None,
                    after=None,
                    unchanged=None,
                    code=code,
                )
                result["reason_codes"].append(code)
        need(len(paths) == 4, "REQUIRED_INPUTS_UNAVAILABLE_OR_UNSAFE")
        need(
            len({p.resolve() for p in paths.values()}) == 4, "DISTINCT_INPUTS_REQUIRED"
        )
        raw = strict_json(paths["calendar"].read_bytes())
        calendar = compile_session_config(raw)
        need(
            calendar.version == 2
            and all(
                raw["verification"][k] is False
                for k in (
                    "quote_schedule_verified",
                    "trade_schedule_verified",
                    "holidays_verified",
                    "maintenance_verified",
                )
            )
            and raw["candle_finality"]["verified"] is False,
            "BLOCKED_CANDIDATE_REQUIRED",
        )
        original = read_report(paths["original_report"])
        old = projection(original)
        result["original_report_payload_sha256"] = original["sha256"]
        rows = {}
        for tf in ("M1", "M5"):
            rows[tf], result["scans"][tf] = scan(paths[tf], tf, a, b)
        need(
            not any(x["errors"] for x in result["scans"].values()),
            "CSV_INTEGRITY_INVALID",
        )
        diagnostic_path = out / "recomputed-boundaries.json"
        command = [
            sys.executable,
            str(ROOT / "diagnostics/historical_session_boundaries.py"),
            "--m1",
            str(paths["M1"].resolve()),
            "--m5",
            str(paths["M5"].resolve()),
            "--calendar",
            str(paths["calendar"].resolve()),
            "--timestamp-column",
            "timestamp_utc",
            "--start-utc",
            start,
            "--end-utc",
            end,
            "--report-path",
            str(diagnostic_path),
        ]
        child = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        result["diagnostic"]["exit_code"] = child.returncode
        need(child.returncode == 3, "DIAGNOSTIC_EXIT_CODE_UNEXPECTED")
        recomputed = read_report(diagnostic_path)
        new = projection(recomputed)
        result["diagnostic"].update(
            status="RESEARCH_DIAGNOSTICS_ONLY",
            file_fingerprint=file_fingerprint(diagnostic_path),
            payload_sha256=recomputed["sha256"],
        )
        need(new["window"] == result["window"], "RECOMPUTED_WINDOW_INCONSISTENT")
        need(
            all(
                new["frames"][tf]["observed_count"] == result["scans"][tf]["row_count"]
                for tf in ("M1", "M5")
            ),
            "RECOMPUTED_COUNTS_INCONSISTENT",
        )
        need(
            all(v == "MATCH" for v in bindings(recomputed, before).values()),
            "RECOMPUTED_BINDINGS_INCONSISTENT",
        )
        changes = differences(old, new)
        if original["sha256"] != recomputed["sha256"]:
            changes.append(
                dict(
                    field="/diagnostic_payload_sha256",
                    original=original["sha256"],
                    recomputed=recomputed["sha256"],
                )
            )
        original_bindings = bindings(original, before)
        expected = {
            k: dict(
                reported=v,
                original=old["metrics"][k],
                recomputed=new["metrics"][k],
                matches=new["metrics"][k] == v,
            )
            for k, v in EXPECTED.items()
        }
        declared_fingerprints = {}
        f = original.get("file_observations", {})
        for key in ("M1", "M5", "calendar"):
            value = (
                f.get("calendar_file_fingerprint")
                if key == "calendar"
                else f.get("sources", {}).get(key, {}).get("fingerprint")
            )
            if value is not None:
                import re

                need(
                    type(value) is dict
                    and set(value) == {"sha256", "byte_count"}
                    and type(value["sha256"]) is str
                    and re.fullmatch("[a-f0-9]{64}", value["sha256"])
                    and type(value["byte_count"]) is int
                    and value["byte_count"] >= 0,
                    "ORIGINAL_FINGERPRINT_INVALID",
                )
            declared_fingerprints[key] = value
        result["comparison"] = dict(
            original_declared_input_fingerprints=declared_fingerprints,
            status="MATCH" if not changes else "DIFFERENT",
            original=old,
            recomputed=new,
            difference_count=len(changes),
            differences=changes[:128],
            difference_sample_limit=128,
            original_input_bindings=original_bindings,
            expected_operator_counts=expected,
            payload_hash_equal=original["sha256"] == recomputed["sha256"],
            exact_report_bytes_equal=before["original_report"]
            == result["diagnostic"]["file_fingerprint"],
        )
        result["boundaries"] = boundaries(rows, calendar, recomputed)
        same = (
            not changes
            and all(v == "MATCH" for v in original_bindings.values())
            and all(v["matches"] for v in expected.values())
        )
        result["status"] = "LOCAL_MECHANICAL_MATCH" if same else "DIFFERENCES_FOUND"
        if changes:
            result["reason_codes"].append("ORIGINAL_RECOMPUTED_FINDINGS_DIFFER")
        if not all(v == "MATCH" for v in original_bindings.values()):
            result["reason_codes"].append(
                "ORIGINAL_SOURCE_BINDING_UNAVAILABLE_OR_DIFFERENT"
            )
        if not all(v["matches"] for v in expected.values()):
            result["reason_codes"].append("REPORTED_COUNTS_DIFFER")
    except Failure as exc:
        result["reason_codes"].append(str(exc))
    except subprocess.TimeoutExpired:
        result["reason_codes"].append("DIAGNOSTIC_TIMEOUT")
    except (OSError, ValueError, TypeError, KeyError, OverflowError, csv.Error):
        result["reason_codes"].append("INPUT_OR_DIAGNOSTIC_INVALID")
    finally:
        for key, p in paths.items():
            try:
                after = file_fingerprint(p)
                unchanged = after == before[key]
            except OSError:
                after, unchanged = None, False
            result["input_integrity"][key].update(after=after, unchanged=unchanged)
            if not unchanged:
                result["status"] = "BLOCKED"
                result["comparison"]["status"] = "NOT_ESTABLISHED_INPUT_CHANGED"
                result["reason_codes"].append("INPUT_CHANGED_DURING_VERIFICATION")
    result["reason_codes"] = sorted(set(result["reason_codes"]))
    result["code_fingerprints"] = {
        p: file_fingerprint(ROOT / p)
        for p in (
            "iat/boundary_reproduction.py",
            "iat/historical_session_boundaries.py",
            "iat/session_v2.py",
            "diagnostics/historical_session_boundaries.py",
            "diagnostics/Verify-IATBoundaryEvidence.ps1",
        )
    }
    result = hashed(result)
    write_new(out / "evidence-summary.json", result)
    return result
