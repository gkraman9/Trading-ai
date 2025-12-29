from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({
        "status": "OK",
        "message": "Trading AI is running"
    })

@app.route("/analyze")
def analyze():
    return jsonify({
        "signal": "BUY",
        "reasoning": [
            "Test route active",
            "Routing is working correctly"
        ]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
