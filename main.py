from flask import Flask, jsonify
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
    signal = get_signal()
    reasons = explain()

    return jsonify({
        "signal": signal,
        "reasoning": reasons
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
