"""
학습 분석 / 채점 / 집중관리(복습) / 통계 로직.
Vercel API(api/index.py)와 Streamlit 관리자(backend/app.py)가 함께 사용합니다.
"""
import json
import os
import random
import re
import secrets
from datetime import datetime, timedelta, timezone

import requests

from _store import Store, StoreError

KST = timezone(timedelta(hours=9))
SUBJECTS = ["수학", "영어", "한자", "기타"]

DEFAULT_SETTINGS = {
    "app_name": "오늘공부 체크",
    "access_code": "1234",
    "gemini_model": "gemini-2.5-flash",
    "questions_per_session": 8,
    "default_pass_score": 80,
    "default_goal_days": 20,
    "mastery_streak": 2,
    "review_intervals": [1, 2, 4, 7],
    "review_policy": "fail_only",  # fail_only: 기준 미달 시에만 / all_wrong: 틀린 문제는 항상
    "max_review_per_day": 15,
    "max_images": 3,
    "service_open": True,
    "notice": "",
}


class AppError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# ====================================================================== 시간
def now_kst():
    return datetime.now(KST)


def today_str():
    return now_kst().strftime("%Y-%m-%d")


def iso_now():
    return now_kst().isoformat(timespec="seconds")


def add_days(date_str, days):
    d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


# ====================================================================== 설정
def get_settings(store: Store):
    data, _ = store.read("settings.json", {})
    s = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        s.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    return normalize_settings(s)


def normalize_settings(s):
    s = dict(s)

    def clamp(v, lo, hi, d):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return d

    s["questions_per_session"] = clamp(s.get("questions_per_session"), 3, 15, 8)
    s["default_pass_score"] = clamp(s.get("default_pass_score"), 0, 100, 80)
    s["default_goal_days"] = clamp(s.get("default_goal_days"), 1, 31, 20)
    s["mastery_streak"] = clamp(s.get("mastery_streak"), 1, 5, 2)
    s["max_review_per_day"] = clamp(s.get("max_review_per_day"), 3, 50, 15)
    s["max_images"] = clamp(s.get("max_images"), 1, 3, 3)
    iv = s.get("review_intervals")
    if not isinstance(iv, list) or not iv:
        iv = [1, 2, 4, 7]
    s["review_intervals"] = [clamp(x, 0, 60, 1) for x in iv][:8]
    if s.get("review_policy") not in ("fail_only", "all_wrong"):
        s["review_policy"] = "fail_only"
    s["access_code"] = str(s.get("access_code") or "1234").strip()
    s["gemini_model"] = str(s.get("gemini_model") or "gemini-2.5-flash").strip()
    s["service_open"] = bool(s.get("service_open", True))
    s["notice"] = str(s.get("notice") or "")[:300]
    s["app_name"] = str(s.get("app_name") or "오늘공부 체크")[:30]
    return s


def save_settings(store: Store, new_values: dict):
    def fn(data):
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: v for k, v in (data or {}).items() if k in DEFAULT_SETTINGS})
        merged.update({k: v for k, v in (new_values or {}).items() if k in DEFAULT_SETTINGS})
        merged = normalize_settings(merged)
        data.clear()
        data.update(merged)
        return merged

    return store.update("settings.json", fn, default={}, message="update settings")


# ====================================================================== 아이
def get_children(store: Store):
    data, _ = store.read("children.json", [])
    return data if isinstance(data, list) else []


def get_child(store: Store, child_id):
    for c in get_children(store):
        if c.get("id") == child_id:
            return c
    raise AppError("아이 정보를 찾을 수 없습니다.", 404)


def _norm_pass_scores(ps, default):
    out = {}
    for s in SUBJECTS:
        try:
            out[s] = max(0, min(100, int((ps or {}).get(s, default))))
        except (TypeError, ValueError):
            out[s] = default
    return out


def add_child(store: Store, name, grade="", pass_score=80, goal_days=20):
    name = (name or "").strip()
    if not name:
        raise AppError("이름을 입력하세요.")
    child = {
        "id": "c" + secrets.token_hex(4),
        "name": name[:20],
        "grade": (grade or "").strip()[:20],
        "pass_scores": _norm_pass_scores({}, int(pass_score)),
        "monthly_goal_days": max(1, min(31, int(goal_days))),
        "active": True,
        "created_at": iso_now(),
    }

    def fn(data):
        data.append(child)
        return child

    return store.update("children.json", fn, default=[], message=f"add child {child['id']}")


def update_child(store: Store, child_id, values: dict):
    def fn(data):
        for c in data:
            if c.get("id") == child_id:
                if "name" in values:
                    n = (values["name"] or "").strip()
                    if not n:
                        raise AppError("이름을 입력하세요.")
                    c["name"] = n[:20]
                if "grade" in values:
                    c["grade"] = (values["grade"] or "").strip()[:20]
                if "pass_scores" in values:
                    c["pass_scores"] = _norm_pass_scores(values["pass_scores"], 80)
                if "monthly_goal_days" in values:
                    c["monthly_goal_days"] = max(1, min(31, int(values["monthly_goal_days"])))
                if "active" in values:
                    c["active"] = bool(values["active"])
                return c
        raise AppError("아이 정보를 찾을 수 없습니다.", 404)

    return store.update("children.json", fn, default=[], message=f"update child {child_id}")


def delete_child(store: Store, child_id, delete_data=True):
    def fn(data):
        before = len(data)
        data[:] = [c for c in data if c.get("id") != child_id]
        return before != len(data)

    removed = store.update("children.json", fn, default=[], message=f"delete child {child_id}")
    if delete_data:
        reset_child_data(store, child_id)
    return removed


def reset_child_data(store: Store, child_id):
    count = 0
    for name in store.list(f"sessions/{child_id}"):
        if store.delete(f"sessions/{child_id}/{name}"):
            count += 1
    if store.delete(f"review/{child_id}.json"):
        count += 1
    return count


def pass_score_for(child, subject, settings):
    ps = (child or {}).get("pass_scores") or {}
    try:
        return int(ps.get(subject, settings["default_pass_score"]))
    except (TypeError, ValueError):
        return settings["default_pass_score"]


# ====================================================================== 세션 저장
def _month_key_from_sid(sid):
    m = re.match(r"^(\d{4})(\d{2})-[0-9a-f]{8}$", sid or "")
    if not m:
        raise AppError("잘못된 학습 기록 번호입니다.", 404)
    return f"{m.group(1)}-{m.group(2)}"


def session_path(child_id, month):
    if not re.match(r"^c[0-9a-f]{8}$", child_id or ""):
        raise AppError("잘못된 아이 번호입니다.", 404)
    return f"sessions/{child_id}/{month}.json"


def list_sessions(store: Store, child_id, months=None):
    """최신순 정렬된 세션 목록. months: 읽을 'YYYY-MM.json' 개수 제한(최근 n개월)."""
    names = [n for n in store.list(f"sessions/{child_id}") if n.endswith(".json")]
    names.sort(reverse=True)
    if months:
        names = names[:months]
    out = []
    for n in names:
        data, _ = store.read(f"sessions/{child_id}/{n}", [])
        if isinstance(data, list):
            out.extend(data)
    out.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return out


def get_session(store: Store, child_id, sid, retries=3):
    month = _month_key_from_sid(sid)
    import time

    for i in range(retries):
        data, _ = store.read(session_path(child_id, month), [])
        for s in data or []:
            if s.get("id") == sid:
                return s
        if i < retries - 1:
            time.sleep(1.0)  # GitHub 저장 직후 읽기 지연 대비
    raise AppError("학습 기록을 찾을 수 없습니다.", 404)


def delete_session(store: Store, child_id, sid):
    month = _month_key_from_sid(sid)

    def fn(data):
        before = len(data)
        data[:] = [s for s in data if s.get("id") != sid]
        return before != len(data)

    return store.update(session_path(child_id, month), fn, default=[], message=f"delete session {sid}")


def public_session(s):
    """학생 화면용: 정답 정보 제거."""
    qs = [
        {"id": q["id"], "question": q["question"], "options": q["options"], "concept": q.get("concept", "")}
        for q in s.get("questions", [])
    ]
    return {
        "id": s["id"],
        "date": s.get("date"),
        "created_at": s.get("created_at"),
        "subject": s.get("subject"),
        "title": s.get("title"),
        "summary": s.get("summary"),
        "key_points": s.get("key_points", []),
        "worksheet": s.get("worksheet", {"items": []}),
        "encouragement": s.get("encouragement", ""),
        "questions": qs,
        "status": s.get("status"),
        "first_score": s.get("first_score"),
        "best_score": s.get("best_score"),
        "pass_score": s.get("pass_score"),
        "passed": s.get("passed"),
        "attempts_count": len(s.get("attempts", [])),
    }


def session_brief(s):
    return {
        "id": s["id"],
        "date": s.get("date"),
        "subject": s.get("subject"),
        "title": s.get("title"),
        "status": s.get("status"),
        "first_score": s.get("first_score"),
        "best_score": s.get("best_score"),
        "pass_score": s.get("pass_score"),
        "passed": s.get("passed"),
        "question_count": len(s.get("questions", [])),
    }


# ====================================================================== Gemini 분석
def _gemini_key():
    return os.environ.get("GEMINI_API_KEY", "").strip()


def _demo_mode():
    return os.environ.get("DEMO_MODE", "").strip() in ("1", "true", "yes")


def build_prompt(child, subject, n_questions, note):
    grade = (child or {}).get("grade") or "초등학생"
    subject_hint = subject if subject in SUBJECTS else "자동 판단"
    return f"""당신은 아이의 공부를 점검해 주는 친절하고 정확한 학습 코치입니다.
첨부된 사진은 학습자({grade})가 오늘 공부한 교재, 학습지, 공책입니다. 과목: {subject_hint}
보호자 메모: {note or "없음"}

할 일:
1. 사진 속 학습 내용을 정확히 읽고 오늘 공부한 내용을 정리합니다.
2. 사진에 아이가 직접 쓴 답이 있으면 하나하나 채점합니다(worksheet). 답이 없으면 items 는 빈 배열입니다.
3. 아이가 내용을 이해하고 외웠는지 확인하는 4지선다 문제를 정확히 {n_questions}개 만듭니다.

문제 작성 규칙:
- 반드시 사진 속 학습 내용에서만 출제합니다. 사진에 없는 내용은 출제하지 않습니다.
- 수학: 같은 개념의 유사 문제를 숫자를 바꿔 출제하고, 정답을 직접 다시 계산해 검산합니다.
- 영어: 단어 뜻, 철자, 문장 의미, 빈칸 채우기 등을 섞습니다.
- 한자: 뜻(훈), 소리(음), 한자 고르기, 한자어 뜻을 섞습니다.
- 아이가 틀린 문제가 있다면 문제의 절반 이상을 그 개념으로 출제합니다.
- 보기 4개는 모두 서로 다르고, 그럴듯한 오답이어야 합니다. 정답은 하나뿐이어야 합니다.
- {grade} 수준의 쉬운 한국어로 씁니다. 해설은 1~2문장으로 친절하게 씁니다.

사진이 흐리거나 학습 내용이 아니라면 readable 을 false 로 하고 reason 에 이유를 씁니다.

아래 JSON 형식으로만 답하세요(설명 문장, 마크다운 금지):
{{
  "readable": true,
  "reason": "",
  "subject": "수학|영어|한자|기타 중 하나",
  "title": "오늘 공부 제목 (20자 이내)",
  "summary": "오늘 공부한 내용 요약 2~3문장",
  "key_points": ["꼭 기억할 핵심 내용", "..."],
  "worksheet": {{
    "items": [
      {{"question": "문제", "child_answer": "아이가 쓴 답", "correct_answer": "정답", "is_correct": true, "explanation": "해설"}}
    ]
  }},
  "questions": [
    {{"question": "문제", "options": ["보기1", "보기2", "보기3", "보기4"], "answer_index": 0, "explanation": "해설", "concept": "관련 개념"}}
  ],
  "encouragement": "아이에게 주는 짧은 응원 한 문장"
}}"""


def _extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def call_gemini(model, prompt, images_b64):
    key = _gemini_key()
    if not key:
        raise AppError("서버에 GEMINI_API_KEY 가 설정되지 않았습니다. 관리자에게 알려주세요.", 500)
    parts = [{"text": prompt}]
    for img in images_b64:
        parts.append({"inline_data": {"mime_type": img["mime"], "data": img["data"]}})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        r = requests.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                          json=body, timeout=55)
    except requests.Timeout:
        raise AppError("사진 분석 시간이 너무 오래 걸렸습니다. 사진 수를 줄여서 다시 시도하세요.", 504)
    except requests.RequestException as e:
        raise AppError(f"AI 서버에 연결하지 못했습니다: {e}", 502)
    if r.status_code == 429:
        raise AppError("오늘 무료 AI 사용량을 다 썼거나 요청이 너무 많습니다. 잠시 후(또는 내일) 다시 시도하세요.", 429)
    if r.status_code in (400, 404) and "model" in r.text.lower():
        raise AppError(f"AI 모델 '{model}' 을 사용할 수 없습니다. 관리자 화면에서 모델 이름을 확인하세요.", 502)
    if r.status_code in (401, 403):
        raise AppError("GEMINI_API_KEY 가 올바르지 않습니다. 관리자에게 알려주세요.", 502)
    if not r.ok:
        raise AppError(f"AI 분석 오류 ({r.status_code}): {r.text[:200]}", 502)
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "응답 없음")
        raise AppError(f"AI가 사진을 분석하지 못했습니다 ({reason}). 다른 사진으로 시도하세요.", 502)
    text = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", [])
                   if not p.get("thought"))
    try:
        return _extract_json(text)
    except Exception:
        raise AppError("AI 응답을 해석하지 못했습니다. 다시 시도하세요.", 502)


def demo_result(subject, n):
    subj = subject if subject in SUBJECTS else "한자"
    bank = [
        ("'山'의 뜻은 무엇일까요?", ["메 (산)", "물", "불", "나무"], 0, "山은 '메 산'으로 산을 뜻해요.", "山"),
        ("'水'의 소리(음)는?", ["화", "수", "목", "토"], 1, "水는 '물 수'예요.", "水"),
        ("'불'을 뜻하는 한자는?", ["木", "土", "火", "金"], 2, "火는 '불 화'예요.", "火"),
        ("'木'의 뜻과 음은?", ["쇠 금", "흙 토", "물 수", "나무 목"], 3, "木은 '나무 목'이에요.", "木"),
        ("'日'의 뜻은?", ["달", "해(날)", "별", "구름"], 1, "日은 '날 일'로 해를 뜻해요.", "日"),
        ("'月'의 소리(음)는?", ["월", "일", "화", "산"], 0, "月은 '달 월'이에요.", "月"),
        ("'흙 토'에 해당하는 한자는?", ["土", "上", "工", "十"], 0, "土는 흙 토예요.", "土"),
        ("'金'의 뜻은?", ["쇠(금)", "물", "나무", "해"], 0, "金은 '쇠 금'이에요.", "金"),
        ("'人'의 뜻은?", ["사람", "들어가다", "여덟", "큰"], 0, "人은 '사람 인'이에요.", "人"),
        ("'大'의 뜻은?", ["작다", "크다", "많다", "높다"], 1, "大는 '큰 대'예요.", "大"),
    ]
    qs = [{"question": q, "options": o, "answer_index": a, "explanation": e, "concept": c}
          for q, o, a, e, c in bank[:n]]
    return {
        "readable": True,
        "subject": subj,
        "title": "[체험용] 기초 한자 익히기",
        "summary": "체험 모드 결과입니다. GEMINI_API_KEY 를 설정하면 실제 사진을 분석합니다.",
        "key_points": ["山 메 산, 水 물 수, 火 불 화", "木 나무 목, 土 흙 토, 金 쇠 금"],
        "worksheet": {"items": [
            {"question": "火의 음", "child_answer": "화", "correct_answer": "화", "is_correct": True, "explanation": ""},
            {"question": "木의 뜻", "child_answer": "물", "correct_answer": "나무", "is_correct": False,
             "explanation": "물은 水예요. 木은 나무예요."},
        ]},
        "questions": qs,
        "encouragement": "오늘도 차근차근 잘했어요!",
    }


def _s(v, limit=500):
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        v = json.dumps(v, ensure_ascii=False)
    return str(v).strip()[:limit]


def sanitize_analysis(raw, subject, n):
    if not isinstance(raw, dict):
        raise AppError("AI 응답 형식이 올바르지 않습니다. 다시 시도하세요.", 502)
    if raw.get("readable") is False:
        reason = _s(raw.get("reason")) or "사진에서 학습 내용을 읽을 수 없습니다."
        raise AppError(f"{reason} 밝은 곳에서 글씨가 잘 보이게 다시 찍어 주세요.", 422)

    subj = _s(raw.get("subject"), 10)
    if subject in SUBJECTS and subject != "기타":
        subj = subject
    if subj not in SUBJECTS:
        subj = subject if subject in SUBJECTS else "기타"

    ws_items = []
    for it in ((raw.get("worksheet") or {}).get("items") or [])[:40]:
        if not isinstance(it, dict) or not _s(it.get("question")):
            continue
        ws_items.append({
            "question": _s(it.get("question"), 300),
            "child_answer": _s(it.get("child_answer"), 200),
            "correct_answer": _s(it.get("correct_answer"), 200),
            "is_correct": bool(it.get("is_correct")),
            "explanation": _s(it.get("explanation"), 300),
        })

    questions = []
    seen = set()
    for q in raw.get("questions") or []:
        if not isinstance(q, dict):
            continue
        text = _s(q.get("question"), 400)
        opts_raw = q.get("options") or []
        if not text or not isinstance(opts_raw, list) or text in seen:
            continue
        try:
            ai = int(q.get("answer_index"))
        except (TypeError, ValueError):
            continue
        if not (0 <= ai < len(opts_raw)):
            continue
        correct = _s(opts_raw[ai], 200)
        opts = []
        for o in opts_raw:
            o = _s(o, 200)
            if o and o not in opts:
                opts.append(o)
        if not correct or correct not in opts or len(opts) < 2:
            continue
        # 정답 외 보기를 최대 3개로 맞춘 뒤 섞기
        wrong = [o for o in opts if o != correct][:3]
        opts = wrong + [correct]
        random.shuffle(opts)
        seen.add(text)
        questions.append({
            "id": f"q{len(questions) + 1}",
            "question": text,
            "options": opts,
            "answer_index": opts.index(correct),
            "explanation": _s(q.get("explanation"), 400),
            "concept": _s(q.get("concept"), 60),
        })
        if len(questions) >= n:
            break
    if not questions:
        raise AppError("사진에서 확인 문제를 만들지 못했습니다. 학습 내용이 잘 보이게 다시 찍어 주세요.", 422)

    return {
        "subject": subj,
        "title": _s(raw.get("title"), 40) or f"{subj} 공부",
        "summary": _s(raw.get("summary"), 600),
        "key_points": [_s(k, 200) for k in (raw.get("key_points") or []) if _s(k)][:10],
        "worksheet": {
            "items": ws_items,
            "graded": len(ws_items),
            "correct": sum(1 for i in ws_items if i["is_correct"]),
        },
        "questions": questions,
        "encouragement": _s(raw.get("encouragement"), 120),
    }


def analyze_and_save(store: Store, settings, child, subject, images, note=""):
    if not images:
        raise AppError("사진을 1장 이상 올려 주세요.")
    if len(images) > settings["max_images"]:
        raise AppError(f"사진은 최대 {settings['max_images']}장까지 올릴 수 있습니다.")
    n = settings["questions_per_session"]
    if _gemini_key():
        raw = call_gemini(settings["gemini_model"], build_prompt(child, subject, n, note), images)
    elif _demo_mode():
        raw = demo_result(subject, n)
    else:
        raise AppError("서버에 GEMINI_API_KEY 가 설정되지 않았습니다. 관리자에게 알려주세요.", 500)
    a = sanitize_analysis(raw, subject, n)

    now = now_kst()
    sid = f"{now.strftime('%Y%m')}-{secrets.token_hex(4)}"
    session = {
        "id": sid,
        "child_id": child["id"],
        "date": now.strftime("%Y-%m-%d"),
        "created_at": now.isoformat(timespec="seconds"),
        "subject": a["subject"],
        "title": a["title"],
        "summary": a["summary"],
        "key_points": a["key_points"],
        "worksheet": a["worksheet"],
        "questions": a["questions"],
        "encouragement": a["encouragement"],
        "note": (note or "")[:200],
        "image_count": len(images),
        "status": "analyzed",
        "pass_score": pass_score_for(child, a["subject"], settings),
        "first_score": None,
        "best_score": None,
        "passed": None,
        "attempts": [],
    }

    def fn(data):
        data.append(session)
        return True

    store.update(session_path(child["id"], now.strftime("%Y-%m")), fn, default=[],
                 message=f"new session {sid}")
    return session


# ====================================================================== 채점
def _norm_answers(answers, n):
    out = []
    for i in range(n):
        v = answers[i] if isinstance(answers, list) and i < len(answers) else None
        try:
            v = int(v)
        except (TypeError, ValueError):
            v = None
        out.append(v)
    return out


def submit_quiz(store: Store, settings, child, sid, answers):
    get_session(store, child["id"], sid)  # 존재 확인(저장 지연 대비 재시도 포함)
    month = _month_key_from_sid(sid)
    holder = {}

    def fn(data):
        for s in data:
            if s.get("id") != sid:
                continue
            qs = s["questions"]
            ans = _norm_answers(answers, len(qs))
            details = []
            correct = 0
            for q, a in zip(qs, ans):
                ok = a == q["answer_index"]
                correct += 1 if ok else 0
                details.append({
                    "id": q["id"], "question": q["question"], "options": q["options"],
                    "chosen": a, "answer_index": q["answer_index"], "correct": ok,
                    "explanation": q.get("explanation", ""),
                })
            total = len(qs)
            score = round(correct / total * 100) if total else 0
            pass_score = s.get("pass_score")
            if pass_score is None:
                pass_score = pass_score_for(child, s.get("subject"), settings)
                s["pass_score"] = pass_score
            s.setdefault("attempts", []).append({
                "at": iso_now(), "answers": ans, "score": score, "correct": correct, "total": total,
            })
            if s.get("first_score") is None:
                s["first_score"] = score
            s["best_score"] = max(score, s.get("best_score") or 0)
            s["passed"] = s["best_score"] >= pass_score
            s["status"] = "completed"
            holder.update({
                "score": score, "correct": correct, "total": total, "pass_score": pass_score,
                "passed": score >= pass_score, "session_passed": s["passed"],
                "attempt": len(s["attempts"]), "details": details,
                "subject": s.get("subject"), "title": s.get("title"),
            })
            return True
        raise AppError("학습 기록을 찾을 수 없습니다.", 404)

    store.update(session_path(child["id"], month), fn, default=[], message=f"quiz {sid}")

    wrong = [d for d in holder["details"] if not d["correct"]]
    add_review = wrong and (not holder["passed"] or settings["review_policy"] == "all_wrong")
    added = 0
    if add_review:
        session = get_session(store, child["id"], sid)
        qmap = {q["id"]: q for q in session["questions"]}
        added = add_review_items(store, child["id"], [
            {**qmap[d["id"]], "subject": holder["subject"], "source_session": sid,
             "source_title": holder["title"]} for d in wrong if d["id"] in qmap
        ])
    holder["review_added"] = added
    holder["focus"] = not holder["passed"]
    return holder


# ====================================================================== 집중관리(복습)
def review_path(child_id):
    if not re.match(r"^c[0-9a-f]{8}$", child_id or ""):
        raise AppError("잘못된 아이 번호입니다.", 404)
    return f"review/{child_id}.json"


def get_review_items(store: Store, child_id):
    data, _ = store.read(review_path(child_id), [])
    return data if isinstance(data, list) else []


def add_review_items(store: Store, child_id, questions):
    today = today_str()

    def fn(data):
        keys = {i.get("key") for i in data}
        added = 0
        for q in questions:
            key = f"{q['source_session']}:{q['id']}"
            if key in keys:
                for i in data:  # 이미 있는 문제를 또 틀림 → 다시 집중관리
                    if i.get("key") == key:
                        i["status"] = "active"
                        i["streak"] = 0
                        i["next_review"] = today
                        i["wrong_count"] = i.get("wrong_count", 0) + 1
                continue
            data.append({
                "id": "r" + secrets.token_hex(5),
                "key": key,
                "subject": q.get("subject", "기타"),
                "question": q["question"],
                "options": q["options"],
                "answer_index": q["answer_index"],
                "explanation": q.get("explanation", ""),
                "concept": q.get("concept", ""),
                "source_session": q["source_session"],
                "source_title": q.get("source_title", ""),
                "added_at": iso_now(),
                "next_review": today,
                "streak": 0,
                "wrong_count": 1,
                "correct_count": 0,
                "status": "active",
                "mastered_at": None,
            })
            keys.add(key)
            added += 1
        return added

    return store.update(review_path(child_id), fn, default=[], message=f"review add {child_id}")


def due_review(store: Store, settings, child_id):
    today = today_str()
    items = [i for i in get_review_items(store, child_id)
             if i.get("status") == "active" and i.get("next_review", today) <= today]
    items.sort(key=lambda i: (i.get("next_review", ""), -i.get("wrong_count", 0)))
    items = items[: settings["max_review_per_day"]]
    return [{"id": i["id"], "question": i["question"], "options": i["options"],
             "subject": i.get("subject"), "concept": i.get("concept", ""),
             "streak": i.get("streak", 0), "source_title": i.get("source_title", "")} for i in items]


def submit_review(store: Store, settings, child_id, answers: dict):
    today = today_str()
    need = settings["mastery_streak"]
    intervals = settings["review_intervals"]

    def fn(data):
        results = []
        for item in data:
            if item["id"] not in answers or item.get("status") != "active":
                continue
            try:
                chosen = int(answers[item["id"]])
            except (TypeError, ValueError):
                chosen = None
            ok = chosen == item["answer_index"]
            item["last_reviewed"] = iso_now()
            if ok:
                item["streak"] = item.get("streak", 0) + 1
                item["correct_count"] = item.get("correct_count", 0) + 1
                if item["streak"] >= need:
                    item["status"] = "mastered"
                    item["mastered_at"] = iso_now()
                else:
                    gap = intervals[min(item["streak"] - 1, len(intervals) - 1)]
                    item["next_review"] = add_days(today, gap)
            else:
                item["streak"] = 0
                item["wrong_count"] = item.get("wrong_count", 0) + 1
                item["next_review"] = today
            results.append({
                "id": item["id"], "question": item["question"], "options": item["options"],
                "chosen": chosen, "answer_index": item["answer_index"], "correct": ok,
                "explanation": item.get("explanation", ""), "streak": item["streak"],
                "mastered": item["status"] == "mastered", "next_review": item.get("next_review"),
            })
        return results

    results = store.update(review_path(child_id), fn, default=[], message=f"review {child_id}")
    correct = sum(1 for r in results if r["correct"])
    return {
        "results": results, "correct": correct, "total": len(results),
        "mastered_now": sum(1 for r in results if r["mastered"]), "mastery_streak": need,
    }


def set_review_status(store: Store, child_id, item_id, action):
    today = today_str()

    def fn(data):
        for i, item in enumerate(data):
            if item["id"] == item_id:
                if action == "delete":
                    data.pop(i)
                elif action == "master":
                    item["status"] = "mastered"
                    item["mastered_at"] = iso_now()
                elif action == "reactivate":
                    item["status"] = "active"
                    item["streak"] = 0
                    item["next_review"] = today
                return True
        return False

    return store.update(review_path(child_id), fn, default=[], message=f"review {action} {item_id}")


# ====================================================================== 통계
def compute_stats(child, sessions, review_items, settings, month=None):
    today = today_str()
    month = month or today[:7]
    month_sessions = [s for s in sessions if (s.get("date") or "").startswith(month)]
    study_days = sorted({s["date"] for s in month_sessions if s.get("date")})
    goal = int(child.get("monthly_goal_days") or settings["default_goal_days"])
    completed = [s for s in month_sessions if s.get("first_score") is not None]
    all_dates = {s["date"] for s in sessions if s.get("date")}

    streak = 0
    d = today if today in all_dates else add_days(today, -1)
    while d in all_dates:
        streak += 1
        d = add_days(d, -1)

    by_subject = {}
    for subj in SUBJECTS:
        ss = [s for s in completed if s.get("subject") == subj]
        by_subject[subj] = {
            "count": len(ss),
            "avg": round(sum(s["first_score"] for s in ss) / len(ss)) if ss else None,
            "pass_score": pass_score_for(child, subj, settings),
            "passed": sum(1 for s in ss if s.get("passed")),
        }

    active = [i for i in review_items if i.get("status") == "active"]
    due = [i for i in active if i.get("next_review", today) <= today]
    return {
        "month": month,
        "today": today,
        "today_done": today in all_dates,
        "study_days": len(study_days),
        "study_dates": study_days,
        "goal_days": goal,
        "progress": min(100, round(len(study_days) / goal * 100)) if goal else 0,
        "streak": streak,
        "sessions": len(month_sessions),
        "completed": len(completed),
        "avg_score": round(sum(s["first_score"] for s in completed) / len(completed)) if completed else None,
        "pass_rate": round(sum(1 for s in completed if s.get("passed")) / len(completed) * 100) if completed else None,
        "pending_quiz": sum(1 for s in month_sessions if s.get("status") == "analyzed"),
        "failed_sessions": sum(1 for s in completed if not s.get("passed")),
        "by_subject": by_subject,
        "review_due": min(len(due), settings["max_review_per_day"]),
        "review_active": len(active),
        "review_mastered": sum(1 for i in review_items if i.get("status") == "mastered"),
    }


# ====================================================================== 백업/복원
def export_all(store: Store):
    out = {"exported_at": iso_now(), "settings": get_settings(store),
           "children": get_children(store), "sessions": {}, "review": {}}
    for c in out["children"]:
        out["sessions"][c["id"]] = list_sessions(store, c["id"])
        out["review"][c["id"]] = get_review_items(store, c["id"])
    return out


def import_all(store: Store, data: dict):
    if not isinstance(data, dict) or "children" not in data:
        raise AppError("백업 파일 형식이 올바르지 않습니다.")
    save_settings(store, data.get("settings") or {})
    store.update("children.json", lambda d: (d.clear(), d.extend(data["children"]))[0],
                 default=[], message="restore children")
    for cid, sessions in (data.get("sessions") or {}).items():
        by_month = {}
        for s in sessions:
            by_month.setdefault((s.get("date") or today_str())[:7], []).append(s)
        for month, items in by_month.items():
            items.sort(key=lambda s: s.get("created_at", ""))
            store.update(session_path(cid, month), lambda d, items=items: (d.clear(), d.extend(items))[0],
                         default=[], message=f"restore {cid} {month}")
    for cid, items in (data.get("review") or {}).items():
        store.update(review_path(cid), lambda d, items=items: (d.clear(), d.extend(items))[0],
                     default=[], message=f"restore review {cid}")
    return True
