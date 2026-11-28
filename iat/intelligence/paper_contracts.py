"""Typed synthetic E4 contracts. No broker, credentials, order or live adapter."""

from iat.paper_source_scope import current_source, require_scope
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
import re
from functools import wraps
from iat.replay_dataset import utc
from iat.intelligence.risk_intelligence import ARITHMETIC, number, text_number
from iat.intelligence.market_view import SAFETY, plain
from iat.intelligence.strategy_replay import digest


class PaperError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise PaperError(code)


def at(value):
    return utc(value.isoformat() if isinstance(value, datetime) else value)


def dec(value, *, positive=False):
    # Financial declarations use exact decimal strings/integers, never binary floats.
    require(type(value) in (str, int, Decimal), "EXACT_DECIMAL_REQUIRED")
    v = number(value)
    require(v > 0 if positive else v >= 0, "FINANCIAL_NUMBER_INVALID")
    require(
        abs(v.adjusted()) <= 18 and len(v.as_tuple().digits) <= 28,
        "FINANCIAL_RESOURCE_LIMIT",
    )
    return v


def name(value):
    require(
        type(value) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", value),
        "IDENTIFIER_INVALID",
    )
    return value


def canonical(value):
    return plain(asdict(value))


def report(model, **fields):
    value = dict(
        report_version=1,
        model_version=model,
        provenance="SYNTHETIC_RESEARCH",
        research_only=True,
        **fields,
        **SAFETY
    )
    scope = current_source()
    if scope is not None:
        value["provenance"] = scope.provenance
        value["source_qualification_binding"] = scope.binding
        value["model_version"] = (
            model.replace("SYNTHETIC", "HISTORICAL") if scope.historical else model
        )
        if scope.historical:
            if "result_scope" in value:
                value["result_scope"] = value["result_scope"].replace(
                    "SYNTHETIC", "HISTORICAL_HYPOTHETICAL"
                )
            if "fill_time_basis" in value:
                value["fill_time_basis"] = (
                    "DECLARED_HISTORICAL_RECEIPT_SIDE_PRICE_MODEL"
                )
    return dict(value, sha256=digest(value))


def reports_equal(value, expected):
    """Compare serialized report meaning without bool/int equality coercion."""
    if type(value) is not dict or value != expected:
        return False
    try:
        return digest(value) == digest(expected)
    except (ValueError, TypeError, OverflowError):
        return False


@dataclass(frozen=True)
class SyntheticQuote:
    symbol: str
    feed: str
    sequence: int
    occurred_at_utc: str
    available_at_utc: str
    bid: str
    ask: str
    quotation_eligible: bool
    new_position_eligible: bool
    version: int = 1
    provenance: str = "SYNTHETIC_RESEARCH"

    def __post_init__(self):
        require(
            type(self.version) is int and self.version == 1, "QUOTE_VERSION_INVALID"
        )
        scope = current_source()
        require(
            (
                self.provenance == "SYNTHETIC_RESEARCH"
                if scope is None
                else scope.authenticates_quote(self)
            ),
            "LIVE_PROVENANCE_BLOCKED",
        )
        name(self.symbol)
        name(self.feed)
        require(
            type(self.sequence) is int and self.sequence >= 0, "QUOTE_SEQUENCE_INVALID"
        )
        require(at(self.occurred_at_utc) <= at(self.available_at_utc), "QUOTE_FUTURE")
        require(
            type(self.quotation_eligible) is bool
            and type(self.new_position_eligible) is bool,
            "QUOTE_SESSION_UNKNOWN",
        )
        require(
            not self.new_position_eligible or self.quotation_eligible,
            "QUOTE_SESSION_CONFLICT",
        )
        require(
            dec(self.ask, positive=True) >= dec(self.bid, positive=True),
            "QUOTE_CROSSED",
        )


@dataclass(frozen=True)
class FillPolicy:
    latency_ms: int
    max_age_ms: int
    max_gap_ms: int
    max_analysis_age_ms: int
    version: int = 1

    def __post_init__(self):
        require(
            type(self.version) is int and self.version == 1,
            "FILL_POLICY_VERSION_INVALID",
        )
        for k in ("latency_ms", "max_age_ms", "max_gap_ms", "max_analysis_age_ms"):
            v = getattr(self, k)
            require(type(v) is int and 0 <= v <= 86400000, "FILL_POLICY_INVALID")
        require(
            self.max_age_ms > 0
            and self.max_gap_ms > 0
            and self.max_analysis_age_ms > 0,
            "FILL_POLICY_INVALID",
        )


class SyntheticQuoteTape:
    """Append-only bounded invented observations; authentication is in-process only."""

    def __init__(self, symbol, feed, dataset_sha256, *, max_quotes=10000):
        self._historical_source = current_source()
        self.symbol, self.feed = name(symbol), name(feed)
        if self._historical_source is not None:
            require(
                symbol == "XAUUSD"
                and feed == self._historical_source.specification.feed
                and dataset_sha256 == self._historical_source.binding,
                "E5_TAPE_SOURCE_BINDING_INVALID",
            )
        require(
            type(dataset_sha256) is str
            and re.fullmatch("[a-f0-9]{64}", dataset_sha256),
            "DATASET_HASH_REQUIRED",
        )
        require(
            type(max_quotes) is int and 0 < max_quotes <= 100000, "QUOTE_RESOURCE_LIMIT"
        )
        self.dataset_sha256, self.max_quotes = dataset_sha256, max_quotes
        self._rows = []

    def append(self, quote):
        require_scope(self._historical_source)
        require(type(quote) is SyntheticQuote, "TYPED_SYNTHETIC_QUOTE_REQUIRED")
        require(
            quote.symbol == self.symbol and quote.feed == self.feed,
            "QUOTE_FEED_MISMATCH",
        )
        row = report(
            "IAT_SYNTHETIC_QUOTE_V1",
            quote=canonical(quote),
            source=dict(
                dataset_sha256=self.dataset_sha256, symbol=self.symbol, feed=self.feed
            ),
        )
        if self._rows:
            old = self._rows[-1]["quote"]
            if quote.sequence == old["sequence"]:
                require(row == self._rows[-1], "QUOTE_SEQUENCE_CONFLICT")
                return deepcopy(row)
            require(quote.sequence > old["sequence"], "QUOTE_SEQUENCE_BACKWARD")
            require(quote.sequence == old["sequence"] + 1, "QUOTE_SEQUENCE_GAP")
            require(
                at(quote.occurred_at_utc) >= at(old["occurred_at_utc"])
                and at(quote.available_at_utc) > at(old["available_at_utc"]),
                "QUOTE_CLOCK_BACKWARD_OR_AMBIGUOUS_AVAILABILITY",
            )
        require(len(self._rows) < self.max_quotes, "QUOTE_RESOURCE_LIMIT")
        self._rows.append(row)
        return deepcopy(row)

    def authenticate(self, row, *, as_of, policy, decision_at=None, opening=False):
        require_scope(self._historical_source)
        require(type(policy) is FillPolicy, "TYPED_FILL_POLICY_REQUIRED")
        require(
            type(row) is dict and any(row == r for r in self._rows),
            "QUOTE_SOURCE_MISMATCH",
        )
        q, cutoff = row["quote"], at(as_of)
        occurred, available = at(q["occurred_at_utc"]), at(q["available_at_utc"])
        require(occurred <= available <= cutoff, "QUOTE_NOT_AVAILABLE")
        require(
            cutoff - occurred <= timedelta(milliseconds=policy.max_age_ms),
            "QUOTE_STALE",
        )
        require(q["quotation_eligible"], "QUOTATIONS_CLOSED")
        if opening:
            require(q["new_position_eligible"], "NEW_POSITIONS_CLOSED")
        if decision_at is not None:
            d = at(decision_at)
            require(
                occurred >= d + timedelta(milliseconds=policy.latency_ms)
                and available > d,
                "FILL_BEFORE_DECISION_OR_LATENCY",
            )
            eligible = [
                r
                for r in self._rows
                if at(r["quote"]["available_at_utc"]) <= cutoff
                and at(r["quote"]["available_at_utc"]) > d
                and at(r["quote"]["occurred_at_utc"])
                >= d + timedelta(milliseconds=policy.latency_ms)
                and r["quote"]["quotation_eligible"]
                and (not opening or r["quote"]["new_position_eligible"])
            ]
            require(eligible and row == eligible[0], "NOT_FIRST_CAUSAL_QUOTE")
        else:
            available_rows = [
                r for r in self._rows if at(r["quote"]["available_at_utc"]) <= cutoff
            ]
            require(available_rows and row == available_rows[-1], "QUOTE_NOT_CURRENT")
        return deepcopy(q)

    def rows(self):
        return deepcopy(self._rows)


@dataclass(frozen=True)
class BrokerSpecification:
    symbol: str
    feed: str
    contract_size: str | None
    min_lot: str | None
    max_lot: str | None
    volume_step: str | None
    tick_size: str | None
    tick_value: str | None
    point_size: str | None
    account_currency: str | None
    profit_currency: str | None
    margin_currency: str | None
    margin_method: str | None
    leverage: str | None
    min_stop_distance: str | None
    freeze_level: str | None
    commission_convention: str | None
    financing_convention: str | None
    margin_call_equity_ratio: str | None
    stop_out_equity_ratio: str | None
    session_eligible: bool | None
    source: str
    effective_at_utc: str
    expires_at_utc: str
    verification: str = "DECLARED_SYNTHETIC_NOT_BROKER_VERIFIED"
    version: int = 1

    def validate(self, quote, cutoff):
        require(type(self.version) is int and self.version == 1, "SPEC_VERSION_INVALID")
        require(
            (
                self.verification == "DECLARED_SYNTHETIC_NOT_BROKER_VERIFIED"
                if current_source() is None
                else current_source().authenticates_specification(self)
            ),
            "UNVERIFIED_BROKER_SPEC_BLOCKED",
        )
        require(
            self.symbol == quote["symbol"] and self.feed == quote["feed"],
            "SPEC_FEED_MISMATCH",
        )
        name(self.source)
        require(
            at(self.effective_at_utc) <= at(cutoff) < at(self.expires_at_utc),
            "SPEC_NOT_EFFECTIVE",
        )
        require(self.session_eligible is True, "SPEC_SESSION_UNAVAILABLE")
        require(
            self.account_currency
            == self.profit_currency
            == self.margin_currency
            == "USD",
            "CURRENCY_MODEL_UNSUPPORTED",
        )
        require(
            self.margin_method == "LINEAR_NOTIONAL_LEVERAGE",
            "MARGIN_METHOD_UNSUPPORTED",
        )
        require(
            self.commission_convention == "ACCOUNT_CURRENCY_PER_LOT_PER_SIDE"
            and self.financing_convention == "ACCOUNT_CURRENCY_PER_LOT_PER_24H",
            "COST_CONVENTION_UNSUPPORTED",
        )
        values = {
            k: dec(getattr(self, k), positive=True)
            for k in (
                "contract_size",
                "min_lot",
                "max_lot",
                "volume_step",
                "tick_size",
                "tick_value",
                "point_size",
                "leverage",
            )
        }
        values.update(
            {
                k: dec(getattr(self, k))
                for k in (
                    "min_stop_distance",
                    "freeze_level",
                    "margin_call_equity_ratio",
                    "stop_out_equity_ratio",
                )
            }
        )
        with localcontext(ARITHMETIC):
            require(
                values["min_lot"] <= values["max_lot"]
                and values["min_lot"] % values["volume_step"] == 0
                and values["max_lot"] % values["volume_step"] == 0,
                "VOLUME_GRID_UNSUPPORTED",
            )
            require(
                values["tick_value"] == values["tick_size"] * values["contract_size"],
                "TICK_VALUE_INCONSISTENT",
            )
            require(
                all(
                    dec(quote[k], positive=True) % values["tick_size"] == 0
                    for k in ("bid", "ask")
                ),
                "QUOTE_OFF_TICK_GRID",
            )
        require(
            values["margin_call_equity_ratio"] >= values["stop_out_equity_ratio"],
            "MARGIN_THRESHOLDS_INVALID",
        )
        return values


@dataclass(frozen=True)
class SyntheticCosts:
    commission_per_lot_side: str | None
    slippage_price_per_fill: str | None
    financing_per_lot_day: str | None
    other_per_lot_side: str | None
    conversion_rate: str | None
    version: int = 1
    provenance: str = "DECLARED_SYNTHETIC"

    def validate(self):
        require(
            type(self.version) is int
            and self.version == 1
            and (
                self.provenance == "DECLARED_SYNTHETIC"
                if current_source() is None
                else current_source().authenticates_costs(self)
            ),
            "COST_POLICY_INVALID",
        )
        values = {
            k: dec(getattr(self, k))
            for k in (
                "commission_per_lot_side",
                "slippage_price_per_fill",
                "financing_per_lot_day",
                "other_per_lot_side",
            )
        }
        require(
            dec(self.conversion_rate, positive=True) == 1, "CURRENCY_MODEL_UNSUPPORTED"
        )
        return values


def quote_fill(
    quote_report, *, tape, direction, phase, decision_at, as_of, policy, costs
):
    require(type(tape) is SyntheticQuoteTape, "QUOTE_PRODUCER_REQUIRED")
    require(
        direction in ("BULLISH", "BEARISH") and phase in ("ENTRY", "EXIT"),
        "FILL_SIDE_INVALID",
    )
    require(type(costs) is SyntheticCosts, "COST_ASSUMPTIONS_REQUIRED")
    c = costs.validate()
    q = tape.authenticate(
        quote_report,
        as_of=as_of,
        policy=policy,
        decision_at=decision_at,
        opening=phase == "ENTRY",
    )
    buy = (direction == "BULLISH") == (phase == "ENTRY")
    side = "ASK" if buy else "BID"
    with localcontext(ARITHMETIC):
        price = dec(q[side.lower()], positive=True) + (
            c["slippage_price_per_fill"] if buy else -c["slippage_price_per_fill"]
        )
        require(price > 0, "FILL_PRICE_INVALID")
        return report(
            "IAT_SYNTHETIC_FILL_V1",
            direction=direction,
            phase=phase,
            side=side,
            price=text_number(price),
            quote_sha256=quote_report["sha256"],
            occurred_at_utc=q["occurred_at_utc"],
            available_at_utc=q["available_at_utc"],
            filled_at_utc=q["available_at_utc"],
            fill_time_basis="SYNTHETIC_RECEIPT_TIME_PRICE_ASSUMPTION",
            decision_at_utc=at(decision_at).isoformat(),
            cutoff_utc=at(as_of).isoformat(),
            fill_policy=canonical(policy),
            cost_policy=canonical(costs),
            slippage_is_declared=True,
            spread_already_in_side_prices=True,
            limitations=[
                "INVENTED_QUOTE_FIXTURE_NOT_EXECUTABLE_LIQUIDITY",
                "NO_REAL_BROKER_SPECIFICATION",
            ],
        )


def financial_context(fn):
    @wraps(fn)
    def wrapped(*args, **kw):
        with localcontext(ARITHMETIC):
            return fn(*args, **kw)

    return wrapped


def specification_collection_plan(symbol):
    """Future read-only collection requirements, NOT an MT5 connection or approval."""
    name(symbol)
    return report(
        "IAT_SPECIFICATION_COLLECTION_PLAN_V1",
        symbol=symbol,
        status="NOT_RUN",
        allowed_future_operation="READ_ONLY_SYMBOL_INFO_WITH_SEPARATE_OPERATOR_AUTHORIZATION",
        metadata_fields=[
            "trade_contract_size",
            "volume_min",
            "volume_max",
            "volume_step",
            "trade_tick_size",
            "trade_tick_value",
            "point",
            "currency_profit",
            "currency_margin",
            "trade_calc_mode",
            "trade_stops_level",
            "trade_freeze_level",
        ],
        missing_evidence=[
            "FEED_AND_EFFECTIVE_DATE",
            "ACCOUNT_CURRENCY_WITHOUT_ACCOUNT_READ",
            "LEVERAGE_AND_MARGIN_RULES",
            "COMMISSION_FINANCING_AND_CONVERSION",
            "DATED_SESSION_ELIGIBILITY",
            "INDEPENDENT_VERIFICATION",
        ],
        verification="UNVERIFIED",
        spec_conversion="NOT_IMPLEMENTED_REQUIRES_REVIEWED_METHOD_AND_UNITS",
    )


def validate_fill_report(value, quote_report, **inputs):
    require(value == quote_fill(quote_report, **inputs), "FILL_SOURCE_BINDING_INVALID")
    return True
