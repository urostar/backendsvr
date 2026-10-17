"""
학생용 API (Vercel Python Serverless Function)

모든 요청은 /api/index?action=<이름> 으로 들어옵니다.
  GET  health                      서버 상태
  POST login        {code}          접속 코드 확인 + 아이 목록
  GET  stats        child_id        홈 화면 통계
  POST analyze      {child_id, subject, images:[{mime,data}], note}
  GET  sessions     child_id        학습 기록 목록
  GET  session      child_id, id    학습 기록 1건 (정답 제외)
  POST submit       {child_id, session_id, answers:[...]}
  GET  review       child_id        오늘 복습할 집중관리 문제
  POST review_submit {child_id, answers:{item_id: index}}
인증: 헤더 X-Access-Code (관리자가 설정한 접속 코드)
"""
import base64
import hmac
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request  # noqa: E402

import _engine as E  # noqa: E402
from _store import Store, StoreError  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # Vercel 요청 본문 한도(4.5MB) 근처

_store = None
_cache = {}


def store():
    global _store
    if _store is None:
        _store = Store()
    return _store


def cached(key, loader, ttl=20):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = loader()
    _cache[key] = (time.time(), val)
    return val


def settings(fresh=False):
    if fresh:
        _cache.pop("settings", None)
    return cached("settings", lambda: E.get_settings(store()))


def children(fresh=False):
    if fresh:
        _cache.pop("children", None)
    return cached("children", lambda: E.get_children(store()))


def ok(data=None, **kw):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    body.update(kw)
    return jsonify(body)


def fail(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def check_code(code):
    s = settings()
    expected = s["access_code"]
    return bool(code) and hmac.compare_digest(str(code).strip().encode(), expected.encode())


def require_auth():
    code = request.headers.get("X-Access-Code", "")
    if not check_code(code):
        # 관리자가 코드를 막 바꿨을 수 있으니 한 번 새로 읽어서 확인
        settings(fresh=True)
        if not check_code(code):
            raise E.AppError("접속 코드가 맞지 않습니다. 다시 입력해 주세요.", 401)
    s = settings()
    if not s["service_open"]:
        raise E.AppError(s["notice"] or "지금은 서비스 점검 중입니다. 잠시 후 이용해 주세요.", 503)


def require_child(child_id):
    for c in children():
        if c.get("id") == child_id and c.get("active", True):
            return c
    for c in children(fresh=True):
        if c.get("id") == child_id and c.get("active", True):
            return c
    raise E.AppError("아이 정보를 찾을 수 없습니다. 처음 화면에서 다시 선택해 주세요.", 404)


def body():
    return request.get_json(silent=True) or {}


def public_children():
    return [{"id": c["id"], "name": c["name"], "grade": c.get("grade", "")}
            for c in children() if c.get("active", True)]


# --------------------------------------------------------------------- 핸들러
def h_health():
    st = store()
    healthy, msg = st.health()
    return ok({
        "storage_mode": st.mode,
        "storage_ok": healthy,
        "storage_message": msg,
        "ai_configured": bool(os.environ.get("GEMINI_API_KEY")),
        "demo_mode": E._demo_mode(),
        "time": E.iso_now(),
    })


def h_login():
    code = body().get("code", "")
    settings(fresh=True)
    if not check_code(code):
        return fail("접속 코드가 맞지 않습니다.", 401)
    s = settings()
    if not s["service_open"]:
        return fail(s["notice"] or "지금은 서비스 점검 중입니다.", 503)
    children(fresh=True)
    return ok({
        "app_name": s["app_name"],
        "notice": s["notice"],
        "max_images": s["max_images"],
        "subjects": E.SUBJECTS,
        "children": public_children(),
    })


def h_stats():
    require_auth()
    child = require_child(request.args.get("child_id"))
    st = store()
    s = settings()
    sessions = E.list_sessions(st, child["id"], months=3)
    review = E.get_review_items(st, child["id"])
    stats = E.compute_stats(child, sessions, review, s)
    stats["child"] = {"id": child["id"], "name": child["name"], "grade": child.get("grade", ""),
                      "pass_scores": child.get("pass_scores", {})}
    stats["recent"] = [E.session_brief(x) for x in sessions[:6]]
    stats["notice"] = s["notice"]
    stats["mastery_streak"] = s["mastery_streak"]
    return ok(stats)


def h_analyze():
    require_auth()
    b = body()
    child = require_child(b.get("child_id"))
    images = []
    for img in b.get("images") or []:
        if not isinstance(img, dict):
            continue
        mime = str(img.get("mime") or "image/jpeg")
        data = str(img.get("data") or "")
        if "," in data[:100]:
            data = data.split(",", 1)[1]
        if mime not in ("image/jpeg", "image/png", "image/webp"):
            raise E.AppError("JPG, PNG, WEBP 사진만 올릴 수 있습니다.")
        try:
            base64.b64decode(data[:1000] + "=" * (-len(data[:1000]) % 4), validate=False)
        except Exception:
            raise E.AppError("사진 데이터가 올바르지 않습니다.")
        images.append({"mime": mime, "data": data})
    session = E.analyze_and_save(store(), settings(), child, b.get("subject", ""), images,
                                 str(b.get("note") or "")[:200])
    return ok(E.public_session(session))


def h_sessions():
    require_auth()
    child = require_child(request.args.get("child_id"))
    sessions = E.list_sessions(store(), child["id"], months=6)
    return ok([E.session_brief(s) for s in sessions])


def h_session():
    require_auth()
    child = require_child(request.args.get("child_id"))
    s = E.get_session(store(), child["id"], request.args.get("id", ""))
    data = E.public_session(s)
    if s.get("attempts"):
        last = s["attempts"][-1]
        data["last_attempt"] = {
            "score": last["score"], "correct": last["correct"], "total": last["total"],
            "details": [
                {"id": q["id"], "question": q["question"], "options": q["options"],
                 "chosen": a, "answer_index": q["answer_index"], "correct": a == q["answer_index"],
                 "explanation": q.get("explanation", "")}
                for q, a in zip(s["questions"], last["answers"])
            ],
        }
    return ok(data)


def h_submit():
    require_auth()
    b = body()
    child = require_child(b.get("child_id"))
    return ok(E.submit_quiz(store(), settings(), child, str(b.get("session_id") or ""), b.get("answers") or []))


def h_review():
    require_auth()
    child = require_child(request.args.get("child_id"))
    s = settings()
    return ok({"items": E.due_review(store(), s, child["id"]), "mastery_streak": s["mastery_streak"]})


def h_review_submit():
    require_auth()
    b = body()
    child = require_child(b.get("child_id"))
    answers = b.get("answers") or {}
    if not isinstance(answers, dict) or not answers:
        raise E.AppError("제출할 답이 없습니다.")
    return ok(E.submit_review(store(), settings(), child["id"], answers))


ROUTES = {
    ("GET", "health"): h_health,
    ("POST", "login"): h_login,
    ("GET", "stats"): h_stats,
    ("POST", "analyze"): h_analyze,
    ("GET", "sessions"): h_sessions,
    ("GET", "session"): h_session,
    ("POST", "submit"): h_submit,
    ("GET", "review"): h_review,
    ("POST", "review_submit"): h_review_submit,
}


@app.after_request
def add_headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Access-Code"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.errorhandler(413)
def too_large(_e):
    return fail("사진 용량이 너무 큽니다. 사진 수를 줄여 주세요.", 413)


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "OPTIONS"])
def dispatch(path):
    if request.method == "OPTIONS":
        return "", 204
    action = request.args.get("action") or path.rstrip("/").rsplit("/", 1)[-1]
    handler = ROUTES.get((request.method, action))
    if not handler:
        return fail(f"알 수 없는 요청입니다: {request.method} {action}", 404)
    try:
        return handler()
    except E.AppError as e:
        return fail(e.message, e.status)
    except StoreError as e:
        return fail(f"데이터 저장소 오류: {e}", 503)
    except Exception as e:  # noqa
        traceback.print_exc()
        return fail(f"서버 오류가 발생했습니다: {type(e).__name__}", 500)


if __name__ == "__main__":  # 로컬 테스트: python api/index.py
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=True)
