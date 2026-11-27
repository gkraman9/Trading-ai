"""E4.7 offline preflight and reporting contracts, never a historical/live runner."""

from copy import deepcopy
from dataclasses import fields
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import csv
import io
import re

from iat.replay_dataset import load_dataset, read_bytes, local_file, strict_json, utc
from iat.pilot_qualification import qualify_historical
from iat.intelligence.paper_contracts import (
    report,
    require,
    dec,
    reports_equal,
    financial_context,
    BrokerSpecification,
    SyntheticCosts,
    FillPolicy,
)
from iat.intelligence.paper_account import PaperAccount, PaperExitPolicy
from iat.intelligence.protected_paper import ProtectedPaperAccount
from iat.intelligence.capital_intelligence import CapitalPolicy
from iat.intelligence.protection_contracts import (
    ProtectiveStopPolicy,
    LiquidationPolicy,
)
from iat.intelligence.strategy_replay import digest

EVIDENCE = (
    "usage",
    "source_feed",
    "raw_normalized_lineage",
    "timestamp_availability",
    "bid_ask_sequence_completeness",
    "calendar_holidays_maintenance",
    "bar_finality_corrections",
    "dated_instrument_specifications",
    "dated_costs",
    "independent_qualification",
)
ARTIFACTS = ("raw_m1", "raw_m5", "quote_events", "specification", "costs", "policies")
QUOTE_COLUMNS = [
    "sequence",
    "occurred_at_utc",
    "available_at_utc",
    "bid",
    "ask",
    "revision",
    "finality",
]


def exact(value, names):
    require(type(value) is dict and set(value) == set(names), "PAPER_SCHEMA_INVALID")


def interval(value):
    exact(value, ("start", "end"))
    a, b = utc(value["start"]), utc(value["end"])
    require(a < b, "PAPER_WINDOW_INVALID")
    return a, b


def bound_file(root, ref):
    exact(ref, ("file", "sha256"))
    require(
        type(ref["sha256"]) is str and re.fullmatch("[a-f0-9]{64}", ref["sha256"]),
        "PAPER_CHECKSUM_REQUIRED",
    )
    path = local_file(root, ref["file"])
    # Reuse the existing bounded, local-only reader; no URL fetch or byte normalization.
    content = read_bytes(path)
    require(
        content and sha256(content).hexdigest() == ref["sha256"],
        "PAPER_CHECKSUM_MISMATCH",
    )
    return content


@financial_context
def audit_quote_events(raw, *, start, end, max_rows=1000000):
    """Mechanical receipt-order audit. Does not prove capture completeness or sessions."""
    a, b = utc(start), utc(end)
    require(
        a < b and type(max_rows) is int and 0 < max_rows <= 1000000,
        "PAPER_WINDOW_INVALID",
    )
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
    require(
        reader.fieldnames == QUOTE_COLUMNS, "PAPER_OCCURRENCE_AND_AVAILABILITY_REQUIRED"
    )
    rows, previous = [], None
    for item in reader:
        exact(item, QUOTE_COLUMNS)
        require(all(type(v) is str for v in item.values()), "PAPER_QUOTE_INVALID")
        require(
            re.fullmatch(r"0|[1-9][0-9]*", item["sequence"]), "PAPER_SEQUENCE_INVALID"
        )
        sequence = int(item["sequence"])
        occurred, available = utc(item["occurred_at_utc"]), utc(
            item["available_at_utc"]
        )
        require(occurred <= available, "PAPER_QUOTE_FUTURE")
        require(
            item["finality"] == "FINAL" and item["revision"] == "0",
            "PAPER_CORRECTION_OR_FINALITY_ADAPTER_REQUIRED",
        )
        bid, ask = dec(item["bid"], positive=True), dec(item["ask"], positive=True)
        require(bid <= ask, "PAPER_QUOTE_CROSSED")
        if previous is not None:
            seq, old_occurrence, old_available = previous
            require(sequence == seq + 1, "PAPER_SEQUENCE_GAP_OR_DUPLICATE")
            require(
                occurred >= old_occurrence and available > old_available,
                "PAPER_QUOTE_CLOCK_OR_ORDER_INVALID",
            )
        previous = sequence, occurred, available
        rows.append(dict(item))
        require(len(rows) <= max_rows, "PAPER_QUOTE_ROW_LIMIT")
    require(
        rows
        and utc(rows[0]["available_at_utc"]) <= a
        and utc(rows[-1]["available_at_utc"]) >= b,
        "PAPER_QUOTE_WINDOW_NOT_COVERED",
    )
    gaps = [
        (utc(y["available_at_utc"]) - utc(x["available_at_utc"])).total_seconds()
        for x, y in zip(rows, rows[1:])
    ]
    return dict(
        count=len(rows),
        source_sha256=sha256(raw).hexdigest(),
        normalized_sha256=digest(rows),
        first_available_at_utc=rows[0]["available_at_utc"],
        last_available_at_utc=rows[-1]["available_at_utc"],
        maximum_receipt_gap_seconds=max(gaps, default=0),
        capture_completeness="NOT_ESTABLISHED_BY_SEQUENCE_OR_OHLC_MATCH",
        session_gap_audit="REQUIRES_E5_REVIEWED_QUOTE_CALENDAR_ADAPTER",
        rows=tuple(rows),
    )


def _dated_document(raw, kind, bundle):
    obj = strict_json(raw)
    exact(
        obj,
        (
            "version",
            "kind",
            "symbol",
            "feed_id",
            "available_at_utc",
            "effective_from_utc",
            "effective_until_utc",
            "values",
        ),
    )
    require(
        type(obj["version"]) is int and obj["version"] == 1 and obj["kind"] == kind,
        "PAPER_DOCUMENT_VERSION_INVALID",
    )
    require(
        obj["symbol"] == "XAUUSD" and obj["feed_id"] == bundle["feed_id"],
        "PAPER_DOCUMENT_FEED_MISMATCH",
    )
    first = min(utc(v["start"]) for v in bundle["windows"]["warmup"].values())
    last = utc(bundle["windows"]["outcome"]["end"])
    require(
        utc(obj["available_at_utc"]) <= first
        and utc(obj["effective_from_utc"]) <= first
        and last < utc(obj["effective_until_utc"]),
        "PAPER_DOCUMENT_NOT_EFFECTIVE",
    )
    require(type(obj["values"]) is dict, "PAPER_SCHEMA_INVALID")
    return obj["values"]


@financial_context
def _financial_documents(contents, bundle):
    spec = _dated_document(
        contents["specification"], "INSTRUMENT_SPECIFICATION", bundle
    )
    # No conversion to BrokerSpecification's explicitly synthetic verification status.
    names = {f.name for f in fields(BrokerSpecification)} - {
        "symbol",
        "feed",
        "source",
        "effective_at_utc",
        "expires_at_utc",
        "verification",
        "version",
        "session_eligible",
    }
    exact(spec, names)
    for key in (
        "contract_size",
        "min_lot",
        "max_lot",
        "volume_step",
        "tick_size",
        "tick_value",
        "point_size",
        "leverage",
    ):
        dec(spec[key], positive=True)
    for key in (
        "min_stop_distance",
        "freeze_level",
        "margin_call_equity_ratio",
        "stop_out_equity_ratio",
    ):
        dec(spec[key])
    require(
        spec["account_currency"]
        == spec["profit_currency"]
        == spec["margin_currency"]
        == "USD"
        and spec["margin_method"] == "LINEAR_NOTIONAL_LEVERAGE",
        "PAPER_CURRENCY_OR_MARGIN_ADAPTER_REQUIRED",
    )
    require(
        spec["commission_convention"] == "ACCOUNT_CURRENCY_PER_LOT_PER_SIDE"
        and spec["financing_convention"] == "ACCOUNT_CURRENCY_PER_LOT_PER_24H",
        "PAPER_COST_CONVENTION_ADAPTER_REQUIRED",
    )
    require(
        dec(spec["min_lot"]) <= dec(spec["max_lot"])
        and dec(spec["min_lot"]) % dec(spec["volume_step"]) == 0
        and dec(spec["max_lot"]) % dec(spec["volume_step"]) == 0
        and dec(spec["tick_value"])
        == dec(spec["tick_size"]) * dec(spec["contract_size"])
        and dec(spec["margin_call_equity_ratio"]) >= dec(spec["stop_out_equity_ratio"]),
        "PAPER_SPECIFICATION_INCONSISTENT",
    )
    costs = _dated_document(contents["costs"], "TRADING_COSTS", bundle)
    exact(
        costs,
        (
            "commission_per_lot_side",
            "slippage_price_per_fill",
            "financing_per_lot_day",
            "other_per_lot_side",
            "conversion_rate",
        ),
    )
    # Same exact arithmetic contract; this does not confer synthetic or broker provenance.
    for key, value in costs.items():
        dec(value, positive=key == "conversion_rate")
    require(
        dec(costs["conversion_rate"]) == 1, "PAPER_CURRENCY_OR_MARGIN_ADAPTER_REQUIRED"
    )
    require(
        dec(costs["slippage_price_per_fill"]) % dec(spec["tick_size"]) == 0,
        "PAPER_SLIPPAGE_OFF_TICK_GRID",
    )
    policies = strict_json(contents["policies"])
    exact(
        policies,
        (
            "version",
            "starting_capital",
            "baseline",
            "fill",
            "capital",
            "exit",
            "stop",
            "liquidation",
        ),
    )
    require(
        type(policies["version"]) is int
        and policies["version"] == 1
        and policies["starting_capital"] == "50"
        and policies["baseline"] == "UNCHANGED_M1_M5",
        "PAPER_USD50_BASELINE_REQUIRED",
    )
    for key, cls in (
        ("fill", FillPolicy),
        ("capital", CapitalPolicy),
        ("exit", PaperExitPolicy),
        ("stop", ProtectiveStopPolicy),
        ("liquidation", LiquidationPolicy),
    ):
        value = cls(**policies[key])
        if key == "capital":
            value.validate()
    return {
        k: sha256(contents[k]).hexdigest()
        for k in ("specification", "costs", "policies")
    }


def input_contract():
    """Versioned acquisition checklist, not a template that grants approval."""
    return dict(
        contract_version=1,
        symbol="XAUUSD",
        starting_capital="50",
        baseline="UNCHANGED_M1_M5",
        required_artifacts=list(ARTIFACTS),
        required_evidence=list(EVIDENCE),
        quote_columns=list(QUOTE_COLUMNS),
        unsupported=[
            "OHLC_INFERRED_TICKS",
            "SYNTHETIC_AS_HISTORICAL",
            "CORRECTIONS_WITHOUT_AS_OF_REVISION_ADAPTER",
            "UNREVIEWED_QUOTE_SESSION_OR_COST_ADAPTER",
        ],
    )


@financial_context
def historical_paper_preflight(manifest_path=None, review_path=None, bundle_path=None):
    """Read-only readiness review. It cannot activate or qualify a paper replay."""
    result = dict(
        status="BLOCKED",
        input_checks_status="NOT_RUN",
        source_qualification=None,
        dataset_hashes=None,
        bundle_sha256=None,
        artifacts=None,
        quote_audit=None,
        windows=None,
        configuration_hashes=None,
        evidence_hashes=None,
        historical_metrics=None,
        replay_status="NOT_RUN",
        contract=input_contract(),
        reason_codes=[],
        assurance="FILE_BOUND_DECLARATIONS_NOT_PROVIDER_AUTHENTICATION",
    )
    try:
        gate = qualify_historical(manifest_path, review_path)
    except (ValueError, TypeError, KeyError, OSError):
        gate = dict(
            status="DATA_NOT_QUALIFIED",
            reason_codes=["PAPER_SOURCE_INPUT_INVALID"],
            dataset_id=None,
        )
    result["source_qualification"] = gate
    result["reason_codes"].extend(gate["reason_codes"])
    if gate["status"] != "HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED":
        result["reason_codes"].append("PAPER_SOURCE_QUALIFICATION_REQUIRED")
    if bundle_path is None:
        result["reason_codes"].extend(
            [
                "PAPER_EVIDENCE_BUNDLE_REQUIRED",
                "PAPER_BID_ASK_AVAILABILITY_REQUIRED",
                "PAPER_DATED_SPECIFICATION_AND_COSTS_REQUIRED",
            ]
        )
    elif gate["status"] == "HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED":
        try:
            dataset = load_dataset(manifest_path)
            m = dataset.metadata
            require(
                m["dataset_kind"] == "INDEPENDENT_HISTORICAL"
                and digest(m) == gate["dataset_id"],
                "PAPER_SOURCE_CHANGED_OR_SYNTHETIC",
            )
            raw = read_bytes(bundle_path)
            bundle = strict_json(raw)
            exact(
                bundle,
                (
                    "version",
                    "symbol",
                    "feed_id",
                    "dataset_id",
                    "preparer_code",
                    "reviewer_code",
                    "independently_reviewed",
                    "reviewed_at_utc",
                    "windows",
                    "artifacts",
                    "evidence",
                ),
            )
            require(
                type(bundle["version"]) is int and bundle["version"] == 1,
                "PAPER_BUNDLE_VERSION_INVALID",
            )
            require(
                bundle["symbol"] == "XAUUSD"
                and bundle["feed_id"] == m["lineage"]["feed_id"]
                and bundle["dataset_id"] == gate["dataset_id"],
                "PAPER_BUNDLE_LINEAGE_MISMATCH",
            )
            require(
                all(
                    type(bundle[k]) is str
                    and re.fullmatch("[A-Za-z0-9_-]{1,64}", bundle[k])
                    for k in ("preparer_code", "reviewer_code")
                )
                and bundle["preparer_code"] != bundle["reviewer_code"]
                and bundle["independently_reviewed"] is True,
                "PAPER_INDEPENDENT_REVIEW_REQUIRED",
            )
            require(
                utc(bundle["reviewed_at_utc"]) >= utc(m["source"]["retrieved_at_utc"]),
                "PAPER_REVIEW_CLOCK_INVALID",
            )
            exact(bundle["windows"], ("warmup", "evaluation", "outcome"))
            require(
                bundle["windows"]["warmup"] == m["warmup"]
                and bundle["windows"]["evaluation"] == m["evaluation"],
                "PAPER_WINDOW_BINDING_MISMATCH",
            )
            a, b = interval(bundle["windows"]["outcome"])
            require(a == utc(m["evaluation"]["end"]), "PAPER_OUTCOME_WINDOW_INVALID")
            exact(bundle["artifacts"], ARTIFACTS)
            root = Path(bundle_path).resolve().parent
            contents = {k: bound_file(root, v) for k, v in bundle["artifacts"].items()}
            exact(bundle["evidence"], EVIDENCE)
            evidence_hashes = {}
            for key, item in bundle["evidence"].items():
                exact(
                    item,
                    ("status", "file", "sha256", "scope", "reference", "explanation"),
                )
                require(
                    item["status"] == "VERIFIED"
                    and type(item["reference"]) is str
                    and item["reference"].strip()
                    and type(item["explanation"]) is str
                    and item["explanation"].strip(),
                    "PAPER_EVIDENCE_" + key.upper() + "_REQUIRED",
                )
                start, end = interval(item["scope"])
                first = min(utc(v["start"]) for v in m["warmup"].values())
                require(
                    start <= first and b <= end, "PAPER_EVIDENCE_COVERAGE_INCOMPLETE"
                )
                bound_file(root, {k: item[k] for k in ("file", "sha256")})
                evidence_hashes[key] = item["sha256"]
            quotes = audit_quote_events(
                contents["quote_events"],
                start=min(v["start"] for v in m["warmup"].values()),
                end=bundle["windows"]["outcome"]["end"],
            )
            config_hashes = _financial_documents(contents, bundle)
            fill = strict_json(contents["policies"])["fill"]
            if quotes["maximum_receipt_gap_seconds"] * 1000 > fill["max_gap_ms"]:
                result["reason_codes"].append("PAPER_QUOTE_GAPS_UNRESOLVED")
            # Raw-to-normalized mapping must be reviewed separately, not guessed from matching OHLC.
            result.update(
                input_checks_status="DOCUMENT_AND_MECHANICAL_CHECKS_PASSED",
                dataset_hashes=deepcopy(m["checksums"]),
                bundle_sha256=sha256(raw).hexdigest(),
                artifacts={k: sha256(v).hexdigest() for k, v in contents.items()},
                quote_audit={k: v for k, v in quotes.items() if k != "rows"},
                windows=deepcopy(bundle["windows"]),
                configuration_hashes=config_hashes,
                evidence_hashes=evidence_hashes,
            )
            result["reason_codes"].extend(
                [
                    "E5_REVIEWED_RECEIPT_AND_SESSION_ADAPTER_REQUIRED",
                    "E5_OUTCOME_CANDLE_COVERAGE_ADAPTER_REQUIRED",
                    "E5_RAW_NORMALIZED_LINEAGE_ADAPTER_REQUIRED",
                ]
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
            ArithmeticError,
            csv.Error,
            UnicodeError,
        ) as exc:
            code = str(exc)
            result["input_checks_status"] = "FAILED"
            result["reason_codes"].append(
                code
                if re.fullmatch("PAPER_[A-Z0-9_]{1,100}", code)
                else "PAPER_INPUT_OR_EVIDENCE_INVALID"
            )
    else:
        result["reason_codes"].append(
            "PAPER_BUNDLE_NOT_ADMITTED_BEFORE_SOURCE_QUALIFICATION"
        )
    result["reason_codes"] = sorted(set(result["reason_codes"]))
    value = report("IAT_HISTORICAL_PAPER_READINESS_V1", **result)
    value.pop("sha256")
    value["provenance"] = "OFFLINE_EVIDENCE_REVIEW_NOT_MARKET_VALIDATION"
    return dict(value, sha256=digest(value))


@financial_context
def performance_readiness(account):
    """Source-bound synthetic descriptive contract; historical metrics stay unmeasured."""
    require(
        type(account) in (PaperAccount, ProtectedPaperAccount),
        "PAPER_ACCOUNT_PRODUCER_REQUIRED",
    )
    journal, state = account.journal(), account.snapshot()
    closed, opened = state["closed_positions"], state["open_positions"]
    values = [Decimal(p["net_hypothetical_pnl"]) for p in closed]
    gross = sum((Decimal(p["gross_hypothetical_pnl"]) for p in closed), Decimal(0))
    losses, wins = [v for v in values if v < 0], [v for v in values if v > 0]
    n = len(closed)
    out = dict(
        source_journal_sha256=journal["sha256"],
        original_metrics=deepcopy(journal["metrics"]),
        scope="SYNTHETIC_ACCOUNTING_NOT_TRADING_EFFECTIVENESS",
        starting_balance=state["starting_balance"],
        ending_balance=state["balance"],
        equity=state["equity"],
        closed_gross_pnl=str(gross),
        closed_net_pnl=str(sum(values, Decimal(0))),
        total_trades=n + len(opened),
        resolved_trades=n,
        winning_trades=len(wins),
        losing_trades=len(losses),
        flat_trades=sum(v == 0 for v in values),
        win_rate=str(Decimal(len(wins)) / n) if n else None,
        profit_factor=str(sum(wins, Decimal(0)) / -sum(losses)) if losses else None,
        profit_factor_reason=None if losses else "NO_LOSING_TRADES_DENOMINATOR",
        net_expectancy=str(sum(values, Decimal(0)) / n) if n else None,
        average_holding_seconds=(
            str(sum(Decimal(p["holding_seconds"]) for p in closed) / n) if n else None
        ),
        trading_costs=state["transaction_costs"],
        closed_trade_costs=str(gross - sum(values, Decimal(0))),
        maximum_drawdown=state["max_drawdown"],
        capital_survival=state["account_lifecycle"],
        accepted_opportunities=n + len(opened),
        rejected_opportunities=len(state["rejected_opportunities"]),
        unresolved_outcomes=sum(
            p["state"] in ("UNRESOLVED", "EXIT_PENDING") for p in opened
        ),
        open_unreviewed_positions=sum(
            p["state"] not in ("UNRESOLVED", "EXIT_PENDING") for p in opened
        ),
        denominator_policy="RATES_USE_CLOSED_TRADES_ONLY_OPEN_AND_UNRESOLVED_SEPARATE",
        entry_efficiency=None,
        exit_efficiency=None,
        efficiency_reason="NO_REVIEWED_CAUSAL_REFERENCE_AND_COMPLETE_QUOTE_COVERAGE",
        individual_trade_journal=deepcopy(closed + opened),
        equity_curve=deepcopy(journal["metrics"]["equity_curve"]),
        historical_metrics=None,
    )
    return report("IAT_PAPER_PERFORMANCE_READINESS_V1", **out)


def validate_performance_readiness(value, *, account):
    require(
        reports_equal(value, performance_readiness(account)),
        "PAPER_PERFORMANCE_SOURCE_MISMATCH",
    )
    return True
