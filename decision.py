"""Legacy compatibility: trade signals remain disabled."""


def get_signal(symbol, timeframe):
    """Keep the legacy signature; never fabricate a trading recommendation."""
    return "WAIT"
