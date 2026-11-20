"""Separate loopback-only comparison dashboard; no order controls or writable routes."""

from pathlib import Path
from flask import Flask, jsonify, request, abort, send_from_directory


def create_dashboard(runtime):
    app = Flask(__name__, static_folder=None)
    assets = Path(__file__).parent / "web"

    @app.before_request
    def local():
        if request.remote_addr not in ("127.0.0.1", "::1") or request.host.split(":")[
            0
        ].lower() not in ("127.0.0.1", "localhost"):
            abort(403)
        if request.args:
            abort(400)

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.get("/")
    def home():
        return send_from_directory(assets, "index.html")

    @app.get("/compare.js")
    def js():
        return send_from_directory(assets, "compare.js")

    @app.get("/compare.css")
    def css():
        return send_from_directory(assets, "compare.css")

    @app.get("/research/v1/comparison")
    def snapshot():
        return jsonify(runtime.latest())

    return app
