from flask import Flask, jsonify, request
from decision import get_signal
from reasoning import explain

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({
        "status": "OK",
        "message": "Trading AI is running"
    })

@app.route("/analyze")
def analyze():
    # 1. Read inputs from URL
    symbol = request.args.get("symbol", "UNKNOWN")
    timeframe = request.args.get("timeframe", "UNKNOWN")

    # 2. Get AI decision
    signal = get_signal(symbol, timeframe)
    reasons = explain(symbol, timeframe)

    return jsonify({
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": signal,
        "reasoning": reasons
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
