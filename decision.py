from trend import detect_trend

def get_signal():
    # fake price data for now (latest last)
    prices = [100, 105, 110]

    trend = detect_trend(prices)

    if trend == "BULLISH":
        return "BUY"
    elif trend == "BEARISH":
        return "SELL"
    else:
        return "WAIT"
