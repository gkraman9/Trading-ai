"""Legacy explanation interface without synthetic market observations."""
from iat.analysis import analyze


def explain(symbol, timeframe, rows=None):
    """Explain supplied validated candles, or disclose unavailable data.

    The HTTP endpoint fetches and validates closed candles before analysis.
    Legacy two-argument callers have no market data and receive no trend claim.
    """
    if rows is None:
        return ["No validated market data supplied; analysis unavailable.",
                "Trade proposals are disabled until data and strategy validation."]
    return analyze(symbol, timeframe, rows)["reasoning"]
