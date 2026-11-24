"""Read-only MT5 tick capture; retains only read functions, never a broker adapter."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from math import isfinite
from iat.live_data import ReadOnlyMarketData, scalar
from iat.mt5_data import MarketDataError
from iat.intelligence.strategy_replay import digest
from iat.replay_dataset import utc


def observed_tick(tick, now, *, historical=False):
    def number(key):
        value = tick.get(key) if isinstance(tick, dict) else getattr(tick, key, None)
        if type(value) not in (float, int) or not isfinite(value):
            raise ValueError("QUOTE_" + key.upper() + "_UNAVAILABLE_OR_INVALID")
        return value

    bid, ask = number("bid"), number("ask")
    epoch = number("time")
    msc = number("time_msc")
    if not 0 < bid <= ask:
        raise ValueError("QUOTE_BID_ASK_INVALID")
    if epoch != int(epoch) or msc != int(msc) or int(msc) // 1000 != int(epoch):
        raise ValueError("QUOTE_TIMESTAMP_INVALID")
    at = datetime.fromtimestamp(msc / 1000, timezone.utc)
    age = (now - at).total_seconds()
    if age < 0:
        raise ValueError("QUOTE_FUTURE")
    if age > 2 and not historical:
        raise ValueError("QUOTE_STALE")
    value = dict(
        timestamp=at.isoformat(),
        bid=str(bid),
        ask=str(ask),
        spread=str(Decimal(str(ask)) - Decimal(str(bid))),
        price_basis="OBSERVED_MT5_BID_ASK",
        timestamp_basis="MT5_API_UTC_EPOCH_MILLISECONDS",
    )
    value["id"] = digest(value)
    return value


class ShadowFeed(ReadOnlyMarketData):
    quote_max_age_seconds = 2  # Declare the existing observed_tick policy; no tolerance change.
    def __init__(self, module):
        super().__init__(module)
        self._tick_range = getattr(module, "copy_ticks_range", None)
        self._all_ticks = getattr(module, "COPY_TICKS_ALL", None)
        self.identity = None
        self.specification = None
        self.last_quote = None

    def preflight(self):
        super().preflight()
        company = getattr(self._account(), "company", None)
        if not isinstance(company, str) or "exness" not in company.casefold():
            raise MarketDataError(
                "Company label does not match", "BROKER_IDENTITY_MISMATCH"
            )
        self.identity = dict(
            broker="EXNESS_COMPANY_LABEL_MATCH",
            symbol="XAUUSD",
            account_mode="DEMO",
            assurance="OBSERVED_COMPANY_LABEL_NOT_AUTHENTICATED_ACCOUNT_BINDING",
            trading_permissions_disabled=True,
        )
        info = self._symbol("XAUUSD")
        keys = (
            "trade_contract_size",
            "trade_tick_size",
            "trade_stops_level",
            "point",
            "digits",
            "volume_min",
            "volume_max",
            "volume_step",
        )
        self.specification = {
            k: (v if type(v) in (float, int) and isfinite(v) else None)
            for k in keys
            for v in (getattr(info, k, None),)
        }

        profit_currency = getattr(info, "currency_profit", None)
        self.specification["currency_profit"] = (
            "USD" if profit_currency == "USD" else None
        )
        mode = getattr(info, "trade_calc_mode", None)
        self.specification["trade_calc_mode"] = (
            mode if type(mode) is int and mode in (0, 1) else None
        )

    def quote_observed(self, clock):
        """Read first, then sample UTC; never treat read latency as clock-skew tolerance."""
        if not callable(clock):
            raise ValueError("OBSERVATION_CLOCK_REQUIRED")
        return self.quote(clock)

    def quote(self, now):
        # Datetime callers retain explicit-cutoff validation. Live acquisition opts
        # into a callable clock so a tick arriving during the read is not "future".
        try:
            started = now() if callable(now) else now
            tick = self._tick("XAUUSD")
            observed = now() if callable(now) else now
            if observed < started:
                raise ValueError("CLOCK_MOVED_BACKWARD")
            q = observed_tick(tick, observed)
        except (ValueError, OverflowError, OSError) as exc:
            raise MarketDataError(
                "Bid/Ask unavailable",
                str(exc) if isinstance(exc, ValueError) else "QUOTE_TIMESTAMP_INVALID",
            ) from None
        self.last_quote = q
        return dict(
            bid=float(q["bid"]),
            ask=float(q["ask"]),
            spread=float(q["spread"]),
            observed_at_utc=q["timestamp"],
            epoch_seconds=int(utc(q["timestamp"]).timestamp()),
            epoch_milliseconds=int(utc(q["timestamp"]).timestamp() * 1000),
            age_seconds=(observed - utc(q["timestamp"])).total_seconds(),
            price_basis="OBSERVED_MT5_BID_ASK",
        )

    def capture(self, start, end):
        result = dict(
            start=start.isoformat(),
            end=end.isoformat(),
            status="UNAVAILABLE",
            reason_codes=[],
            ticks=[],
            assurance="TERMINAL_RETURNED_OBSERVATIONS_NOT_PROVIDER_CAPTURE_COMPLETENESS_PROOF",
        )
        if end < start:
            result["reason_codes"] = ["CLOCK_MOVED_BACKWARD"]
            return result
        if end - start > timedelta(seconds=60):
            result["reason_codes"] = ["CAPTURE_INTERVAL_EXCEEDED"]
            return result
        if not callable(self._tick_range) or type(self._all_ticks) is not int:
            result["reason_codes"] = ["TICK_HISTORY_UNAVAILABLE"]
            return result
        try:
            self.preflight()
            query_start = start.replace(microsecond=0)
            query_end = end.replace(microsecond=0) + (
                timedelta(seconds=1) if end.microsecond else timedelta(0)
            )
            result.update(
                requested_start=query_start.isoformat(),
                requested_end=query_end.isoformat(),
                excluded_outside_window=0,
            )
            rows = self._tick_range("XAUUSD", query_start, query_end, self._all_ticks)
            if rows is None:
                raise ValueError("TICK_HISTORY_UNAVAILABLE")
            ticks = []
            seen = set()
            previous = None
            for index, row in enumerate(rows):
                if index >= 20000:
                    raise ValueError("TICK_CAPTURE_LIMIT")
                values = {k: scalar(row[k]) for k in ("bid", "ask", "time", "time_msc")}
                q = observed_tick(values, query_end, historical=True)
                at = utc(q["timestamp"])
                if not query_start <= at <= query_end:
                    raise ValueError("TICK_RANGE_INCONSISTENT")
                if not start <= at <= end:
                    result["excluded_outside_window"] += 1
                    continue
                if q["id"] in seen:
                    continue
                if previous is not None and at <= previous:
                    raise ValueError("TICK_ORDER_OR_SAME_MILLISECOND_AMBIGUOUS")
                ticks.append(q)
                seen.add(q["id"])
                previous = at
            result.update(status="OBSERVED_RANGE", ticks=ticks)
        except Exception as exc:
            code = str(exc)
            allowed = {
                "TICK_HISTORY_UNAVAILABLE",
                "TICK_CAPTURE_LIMIT",
                "TICK_RANGE_INCONSISTENT",
                "TICK_ORDER_OR_SAME_MILLISECOND_AMBIGUOUS",
                "QUOTE_BID_ASK_INVALID",
                "QUOTE_FUTURE",
                "QUOTE_TIMESTAMP_INVALID",
            }
            result["reason_codes"] = [
                code if code in allowed else "TICK_CAPTURE_FAILED"
            ]
        return result
