import requests

BINANCE_URL = "https://api.binance.com/api/v3/klines"

def get_closing_prices(symbol, interval, limit=20):
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    response = requests.get(BINANCE_URL, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    # Closing price is index 4
    closes = [float(candle[4]) for candle in data]
    return closes
