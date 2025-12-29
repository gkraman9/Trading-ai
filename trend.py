def detect_trend(prices):
    if len(prices) < 3:
        return "RANGE"

    if prices[-1] > prices[-2] > prices[-3]:
        return "BULLISH"

    if prices[-1] < prices[-2] < prices[-3]:
        return "BEARISH"

    return "RANGE"
