from trend import detect_trend

def explain():
    prices = [100, 105, 110]
    trend = detect_trend(prices)

    if trend == "BULLISH":
        return [
            "Higher highs and higher lows detected",
            "Trend bias is bullish"
        ]

    if trend == "BEARISH":
        return [
            "Lower highs and lower lows detected",
            "Trend bias is bearish"
        ]

    return [
        "No clear trend structure",
        "Market is ranging or unclear"
    ]
