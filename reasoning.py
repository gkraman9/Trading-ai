from trend import detect_trend

def explain(symbol, timeframe):
    prices = [100, 105, 110]
    trend = detect_trend(prices)

    reasons = [
        f"Market analyzed: {symbol}",
        f"Timeframe selected: {timeframe}"
    ]

    if trend == "BULLISH":
        reasons.append("Higher highs and higher lows detected")
        reasons.append("Trend bias is bullish")

    elif trend == "BEARISH":
        reasons.append("Lower highs and lower lows detected")
        reasons.append("Trend bias is bearish")

    else:
        reasons.append("No clear trend structure")
        reasons.append("Market is ranging or unclear")

    return reasons
