"""로컬 테스트용 서버: python dev_server.py → http://localhost:8000
public/ 정적 파일 + /api (Vercel 함수와 같은 코드)를 함께 띄웁니다."""
import os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "api"))
from flask import Flask, send_from_directory
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple
import index

PUBLIC = os.path.join(ROOT, "public")
static = Flask(__name__, static_folder=None)

@static.route("/")
def root():
    return send_from_directory(PUBLIC, "index.html")

@static.route("/<path:name>")
def files(name):
    return send_from_directory(PUBLIC, name)

app = DispatcherMiddleware(static, {"/api": index.app})

if __name__ == "__main__":
    run_simple("0.0.0.0", int(os.environ.get("PORT", 8000)), app, threaded=True)
