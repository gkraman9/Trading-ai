"""Dedicated loopback read-only UI; does not register or alter production APIs."""
from pathlib import Path
from flask import Flask,jsonify,request,send_from_directory,abort


def create_dashboard(observer):
    app=Flask(__name__,static_folder=None)
    assets=Path(__file__).resolve().parent/'live_web'
    @app.before_request
    def loopback_only():
        if request.remote_addr not in ('127.0.0.1','::1') or request.host.split(':')[0].lower() not in ('127.0.0.1','localhost'):
            abort(403)
        if request.args:abort(400)
    @app.after_request
    def headers(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response
    @app.get('/')
    def home():return send_from_directory(assets,'index.html')
    @app.get('/live.js')
    def js():return send_from_directory(assets,'live.js')
    @app.get('/live.css')
    def css():return send_from_directory(assets,'live.css')
    @app.get('/live/v1/snapshot')
    def snapshot():return jsonify(observer.latest())
    @app.get('/live/v1/settings')
    def settings():return jsonify(dict(symbol='XAUUSD',refresh_seconds=observer.interval,execution_allowed=False,signal='WAIT'))
    return app
