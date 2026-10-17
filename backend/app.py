"""
오늘공부 체크 - 관리자 백엔드 (Streamlit Community Cloud)

화면
  📊 학습 대시보드  : 기준점수, 진도율, 달성점수, 과목별 현황, 점수 추이
  📚 학습 기록      : 날짜별 분석 내용, 문제/정답, 응시 기록
  🎯 집중관리 현황  : 기준 미달로 등록된 문제의 복습 진행 상태
  ⚙️ 관리자         : 아이 관리, 서비스 설정, 데이터 백업/복원, 서버 상태
"""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import _engine as E  # noqa: E402
from _store import Store, StoreError  # noqa: E402

st.set_page_config(page_title="오늘공부 체크 · 관리자", page_icon="📒", layout="wide")


# ====================================================================== 설정값
def secret(name, default=""):
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # secrets.toml 이 없을 때
        pass
    return os.environ.get(name, default)


if secret("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = secret("GEMINI_API_KEY")


@st.cache_resource
def get_store():
    return Store(token=secret("GITHUB_TOKEN"), repo=secret("GITHUB_REPO"),
                 branch=secret("GITHUB_BRANCH", "main"))


store = get_store()

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; max-width: 1280px;}
    div[data-testid="stMetric"] {background: #F3F7FC; border: 1px solid #DCE6F2;
        border-radius: 12px; padding: 12px 16px;}
    div[data-testid="stMetricValue"] {color: #1F3B73;}
    .focus-box {border-left: 5px solid #E5484D; background: #FFF4F4; padding: 10px 14px;
        border-radius: 6px; margin: 6px 0;}
    @media (max-width: 640px) {.block-container {padding: 1rem 0.6rem;}}
    </style>
    """,
    unsafe_allow_html=True,
)


# ====================================================================== 로그인
def login_gate():
    if st.session_state.get("auth"):
        return True
    admin_pw = secret("ADMIN_PASSWORD")
    st.title("📒 오늘공부 체크 관리자")
    if not admin_pw:
        st.error(
            "관리자 비밀번호(ADMIN_PASSWORD)가 설정되지 않았습니다.\n\n"
            "Streamlit Cloud → 앱 Settings → Secrets 에 `ADMIN_PASSWORD = \"원하는비밀번호\"` 를 추가하세요."
        )
        st.stop()
    with st.form("login"):
        pw = st.text_input("관리자 비밀번호", type="password")
        if st.form_submit_button("로그인", type="primary", use_container_width=True):
            if pw == admin_pw:
                st.session_state.auth = True
                st.rerun()
            else:
                st.error("비밀번호가 맞지 않습니다.")
    st.stop()


login_gate()


# ====================================================================== 데이터 로딩(캐시)
@st.cache_data(ttl=60, show_spinner=False)
def load_settings():
    return E.get_settings(store)


@st.cache_data(ttl=60, show_spinner=False)
def load_children():
    return E.get_children(store)


@st.cache_data(ttl=60, show_spinner=False)
def load_sessions(child_id):
    return E.list_sessions(store, child_id)


@st.cache_data(ttl=60, show_spinner=False)
def load_review(child_id):
    return E.get_review_items(store, child_id)


def refresh(msg=None):
    st.cache_data.clear()
    if msg:
        st.session_state.flash = msg
    st.rerun()


def run_safely(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except E.AppError as e:
        st.error(e.message)
    except StoreError as e:
        st.error(f"저장소 오류: {e}")
    return None


try:
    SETTINGS = load_settings()
    CHILDREN = load_children()
except StoreError as e:
    st.error(f"데이터 저장소에 연결할 수 없습니다: {e}")
    st.info("⚙️ Secrets 의 GITHUB_TOKEN / GITHUB_REPO 값을 확인하세요.")
    st.stop()


# ====================================================================== 사이드바
with st.sidebar:
    st.markdown(f"### 📒 {SETTINGS['app_name']}")
    page = st.radio("메뉴", ["📊 학습 대시보드", "📚 학습 기록", "🎯 집중관리 현황", "⚙️ 관리자"],
                    label_visibility="collapsed")
    st.divider()
    if store.mode == "github":
        st.caption(f"💾 저장소: GitHub `{store.repo}`")
    else:
        st.warning("💾 임시 저장소 모드\n\n학생 화면(Vercel)과 데이터가 공유되지 않으며 재시작 시 사라집니다. "
                   "GitHub 저장소를 설정하세요.")
    if SETTINGS["access_code"] == "1234":
        st.warning("🔑 학생 접속 코드가 기본값(1234)입니다. 관리자 → 서비스 설정에서 바꿔 주세요.")
    if not SETTINGS["service_open"]:
        st.error("⛔ 학생 서비스가 점검 중(닫힘)입니다.")
    c1, c2 = st.columns(2)
    if c1.button("🔄 새로고침", use_container_width=True):
        refresh()
    if c2.button("로그아웃", use_container_width=True):
        st.session_state.auth = False
        st.rerun()

if st.session_state.get("flash"):
    st.success(st.session_state.pop("flash"))


def pick_child(key):
    active = [c for c in CHILDREN]
    if not active:
        st.info("등록된 아이가 없습니다. ⚙️ 관리자 → 아이 관리에서 먼저 등록하세요.")
        st.stop()
    labels = {c["id"]: f"{c['name']} ({c.get('grade') or '학년 미입력'})" + ("" if c.get("active", True) else " · 비활성")
              for c in active}
    cid = st.selectbox("아이 선택", list(labels), format_func=lambda x: labels[x], key=key)
    return next(c for c in active if c["id"] == cid)


def sessions_df(sessions):
    rows = []
    for s in sessions:
        rows.append({
            "날짜": s.get("date"),
            "과목": s.get("subject"),
            "제목": s.get("title"),
            "첫 점수": s.get("first_score"),
            "최고 점수": s.get("best_score"),
            "기준점수": s.get("pass_score"),
            "결과": ("미응시" if s.get("first_score") is None else ("✅ 통과" if s.get("passed") else "❌ 미달")),
            "응시": len(s.get("attempts", [])),
            "문항": len(s.get("questions", [])),
            "id": s["id"],
        })
    return pd.DataFrame(rows)


# ====================================================================== 📊 대시보드
def page_dashboard():
    st.title("📊 학습 대시보드")
    top = st.columns([2, 2, 3])
    with top[0]:
        child = pick_child("dash_child")
    sessions = load_sessions(child["id"])
    review = load_review(child["id"])
    months = sorted({(s.get("date") or "")[:7] for s in sessions if s.get("date")}, reverse=True)
    this_month = E.today_str()[:7]
    if this_month not in months:
        months.insert(0, this_month)
    with top[1]:
        month = st.selectbox("기간(월)", months, key="dash_month")
    stats = E.compute_stats(child, sessions, review, SETTINGS, month=month)

    m = st.columns(5)
    m[0].metric("진도율 (학습일/목표)", f"{stats['progress']}%", f"{stats['study_days']} / {stats['goal_days']}일",
                delta_color="off")
    m[1].metric("평균 달성점수(첫 응시)", "-" if stats["avg_score"] is None else f"{stats['avg_score']}점")
    m[2].metric("기준점수 통과율", "-" if stats["pass_rate"] is None else f"{stats['pass_rate']}%",
                f"미달 {stats['failed_sessions']}회", delta_color="off")
    m[3].metric("집중관리 문제", f"{stats['review_active']}개", f"졸업 {stats['review_mastered']}개", delta_color="off")
    m[4].metric("연속 학습", f"{stats['streak']}일", "오늘 완료" if stats["today_done"] else "오늘 아직", delta_color="off")
    st.progress(stats["progress"] / 100, text=f"{month} 진도율 {stats['progress']}%")

    st.subheader("과목별 기준점수와 달성점수")
    subj_rows = []
    for subj, v in stats["by_subject"].items():
        subj_rows.append({"과목": subj, "기준점수": v["pass_score"], "평균 달성점수": v["avg"],
                          "학습 횟수": v["count"], "통과 횟수": v["passed"],
                          "상태": "-" if v["avg"] is None else ("✅ 달성" if v["avg"] >= v["pass_score"] else "⚠️ 미달")})
    sdf = pd.DataFrame(subj_rows)
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = go.Figure()
        fig.add_bar(x=sdf["과목"], y=sdf["평균 달성점수"].fillna(0), name="평균 달성점수", marker_color="#3B6FD8",
                    text=sdf["평균 달성점수"], textposition="outside")
        fig.add_scatter(x=sdf["과목"], y=sdf["기준점수"], name="기준점수", mode="markers+lines",
                        marker=dict(color="#E5484D", size=12, symbol="line-ew-open", line=dict(width=4)),
                        line=dict(color="rgba(229,72,77,0.35)", dash="dot"))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(range=[0, 110]),
                          legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.dataframe(sdf, hide_index=True, use_container_width=True)

    month_sessions = [s for s in sessions if (s.get("date") or "").startswith(month)]
    done = [s for s in month_sessions if s.get("first_score") is not None]
    st.subheader("점수 추이")
    if done:
        df = pd.DataFrame([{"날짜": s["date"], "시각": s.get("created_at"), "과목": s["subject"],
                            "첫 점수": s["first_score"], "기준점수": s.get("pass_score"), "제목": s.get("title")}
                           for s in done]).sort_values("시각")
        fig = px.line(df, x="시각", y="첫 점수", color="과목", markers=True, hover_data=["제목", "기준점수"],
                      color_discrete_map={"수학": "#3B6FD8", "영어": "#2F9E77", "한자": "#D9822B", "기타": "#7C6BC4"})
        for ps in sorted(df["기준점수"].dropna().unique()):
            fig.add_hline(y=ps, line_dash="dash", line_color="#E5484D", annotation_text=f"기준 {int(ps)}점")
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(range=[0, 105]),
                          xaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("이 기간에 응시한 퀴즈가 없습니다.")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("일별 학습")
        if month_sessions:
            cnt = pd.DataFrame([{"날짜": s["date"], "과목": s["subject"]} for s in month_sessions])
            cnt = cnt.groupby(["날짜", "과목"]).size().reset_index(name="횟수")
            fig = px.bar(cnt, x="날짜", y="횟수", color="과목",
                         color_discrete_map={"수학": "#3B6FD8", "영어": "#2F9E77", "한자": "#D9822B", "기타": "#7C6BC4"})
            fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("학습 기록이 없습니다.")
    with c2:
        st.subheader("기준점수 미달 · 집중관리 필요")
        failed = [s for s in done if not s.get("passed")]
        if not failed and not stats["review_active"]:
            st.success("기준점수 미달 학습이 없습니다. 👏")
        for s in failed[:8]:
            st.markdown(f"<div class='focus-box'><b>{s['date']} · {s['subject']}</b> {s.get('title','')}<br>"
                        f"첫 점수 {s['first_score']}점 / 기준 {s.get('pass_score')}점 · 응시 {len(s.get('attempts', []))}회</div>",
                        unsafe_allow_html=True)
        if stats["review_active"]:
            st.info(f"집중관리 중인 문제 {stats['review_active']}개 (오늘 복습 대상 {stats['review_due']}개)")

    st.subheader("최근 학습")
    if month_sessions:
        st.dataframe(sessions_df(month_sessions).drop(columns=["id"]), hide_index=True, use_container_width=True)
    else:
        st.caption("학습 기록이 없습니다.")


# ====================================================================== 📚 학습 기록
def page_records():
    st.title("📚 학습 기록")
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        child = pick_child("rec_child")
    sessions = load_sessions(child["id"])
    with c2:
        subj = st.selectbox("과목", ["전체"] + E.SUBJECTS)
    with c3:
        result = st.selectbox("결과", ["전체", "미달", "통과", "미응시"])
    if subj != "전체":
        sessions = [s for s in sessions if s.get("subject") == subj]
    if result == "미달":
        sessions = [s for s in sessions if s.get("first_score") is not None and not s.get("passed")]
    elif result == "통과":
        sessions = [s for s in sessions if s.get("passed")]
    elif result == "미응시":
        sessions = [s for s in sessions if s.get("first_score") is None]
    st.caption(f"{len(sessions)}건")
    for s in sessions[:100]:
        badge = "⏳ 미응시" if s.get("first_score") is None else (
            f"✅ {s['best_score']}점" if s.get("passed") else f"❌ {s['first_score']}점(기준 {s.get('pass_score')})")
        with st.expander(f"{s['date']} · {s['subject']} · {s.get('title','')} — {badge}"):
            st.write(s.get("summary", ""))
            if s.get("key_points"):
                st.markdown("**핵심 내용**\n" + "\n".join(f"- {k}" for k in s["key_points"]))
            ws = (s.get("worksheet") or {}).get("items") or []
            if ws:
                st.markdown(f"**사진 속 채점** ({sum(1 for i in ws if i['is_correct'])}/{len(ws)})")
                st.dataframe(pd.DataFrame([{"": "⭕" if i["is_correct"] else "❌", "문제": i["question"],
                                            "아이 답": i["child_answer"], "정답": i["correct_answer"],
                                            "해설": i["explanation"]} for i in ws]),
                             hide_index=True, use_container_width=True)
            last = (s.get("attempts") or [None])[-1]
            st.markdown("**확인 문제**")
            rows = []
            for idx, q in enumerate(s.get("questions", [])):
                chosen = last["answers"][idx] if last and idx < len(last["answers"]) else None
                rows.append({"": "-" if not last else ("⭕" if chosen == q["answer_index"] else "❌"),
                             "문제": q["question"], "정답": q["options"][q["answer_index"]],
                             "마지막 선택": "-" if chosen is None else q["options"][chosen] if 0 <= chosen < len(q["options"]) else "-",
                             "해설": q.get("explanation", "")})
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            if s.get("attempts"):
                st.caption("응시 기록: " + ", ".join(f"{a['at'][5:16].replace('T',' ')} {a['score']}점" for a in s["attempts"]))
            if s.get("note"):
                st.caption(f"메모: {s['note']}")
            if st.checkbox("이 기록 삭제", key=f"del_chk_{s['id']}"):
                if st.button("삭제 확인", key=f"del_{s['id']}", type="primary"):
                    if run_safely(E.delete_session, store, child["id"], s["id"]) is not None:
                        refresh("학습 기록을 삭제했습니다.")


# ====================================================================== 🎯 집중관리
def page_focus():
    st.title("🎯 집중관리 현황")
    st.caption(f"기준점수에 못 미친 학습의 틀린 문제를 매일 복습합니다. {SETTINGS['mastery_streak']}번 연속으로 맞히면 졸업합니다. "
               f"복습 간격: {', '.join(str(x) for x in SETTINGS['review_intervals'])}일")
    child = pick_child("focus_child")
    items = load_review(child["id"])
    today = E.today_str()
    active = [i for i in items if i.get("status") == "active"]
    mastered = [i for i in items if i.get("status") == "mastered"]
    due = [i for i in active if i.get("next_review", today) <= today]
    c = st.columns(3)
    c[0].metric("집중관리 중", f"{len(active)}개")
    c[1].metric("오늘 복습 대상", f"{len(due)}개")
    c[2].metric("졸업한 문제", f"{len(mastered)}개")

    tab1, tab2 = st.tabs(["집중관리 중", "졸업한 문제"])
    for tab, group, actions in ((tab1, active, ("master", "delete")), (tab2, mastered, ("reactivate", "delete"))):
        with tab:
            if not group:
                st.caption("문제가 없습니다.")
                continue
            df = pd.DataFrame([{
                "과목": i.get("subject"), "문제": i["question"], "정답": i["options"][i["answer_index"]],
                "연속정답": f"{i.get('streak', 0)}/{SETTINGS['mastery_streak']}", "틀린 횟수": i.get("wrong_count", 0),
                "다음 복습": i.get("next_review") if i.get("status") == "active" else "-",
                "출처": i.get("source_title", ""), "id": i["id"]} for i in group])
            st.dataframe(df.drop(columns=["id"]), hide_index=True, use_container_width=True)
            labels = {i["id"]: f"[{i.get('subject')}] {i['question'][:50]}" for i in group}
            sel = st.selectbox("문제 선택", list(labels), format_func=lambda x: labels[x], key=f"sel_{tab_key(actions)}")
            bc = st.columns(len(actions))
            names = {"master": "✅ 졸업 처리", "delete": "🗑 삭제", "reactivate": "↩️ 다시 집중관리"}
            for col, act in zip(bc, actions):
                if col.button(names[act], key=f"{act}_{tab_key(actions)}", use_container_width=True):
                    if run_safely(E.set_review_status, store, child["id"], sel, act) is not None:
                        refresh("처리했습니다.")


def tab_key(actions):
    return "_".join(actions)


# ====================================================================== ⚙️ 관리자
def page_admin():
    st.title("⚙️ 관리자")
    t1, t2, t3, t4 = st.tabs(["👧 아이 관리", "🛠 서비스 설정", "💾 데이터 관리", "🩺 서버 상태"])

    with t1:
        st.subheader("아이 등록")
        with st.form("add_child", clear_on_submit=True):
            c = st.columns([2, 2, 1, 1])
            name = c[0].text_input("이름")
            grade = c[1].text_input("학년", placeholder="예: 초3")
            ps = c[2].number_input("기준점수", 0, 100, SETTINGS["default_pass_score"], step=5)
            goal = c[3].number_input("월 목표 학습일", 1, 31, SETTINGS["default_goal_days"])
            if st.form_submit_button("등록", type="primary"):
                if run_safely(E.add_child, store, name, grade, ps, goal):
                    refresh(f"{name} 등록 완료")
        st.subheader("등록된 아이")
        if not CHILDREN:
            st.caption("등록된 아이가 없습니다.")
        for ch in CHILDREN:
            with st.expander(f"{ch['name']} ({ch.get('grade') or '-'})" + ("" if ch.get("active", True) else " · 비활성")):
                with st.form(f"edit_{ch['id']}"):
                    c = st.columns([2, 2, 1, 1])
                    nm = c[0].text_input("이름", ch["name"])
                    gr = c[1].text_input("학년", ch.get("grade", ""))
                    gd = c[2].number_input("월 목표 학습일", 1, 31, int(ch.get("monthly_goal_days", 20)))
                    ac = c[3].checkbox("사용", ch.get("active", True))
                    st.markdown("**과목별 기준점수** (이 점수 미만이면 틀린 문제를 집중관리합니다)")
                    sc = st.columns(len(E.SUBJECTS))
                    pss = {}
                    for col, subj in zip(sc, E.SUBJECTS):
                        pss[subj] = col.number_input(subj, 0, 100,
                                                     int((ch.get("pass_scores") or {}).get(subj, 80)), step=5,
                                                     key=f"ps_{ch['id']}_{subj}")
                    if st.form_submit_button("저장", type="primary"):
                        if run_safely(E.update_child, store, ch["id"],
                                      {"name": nm, "grade": gr, "monthly_goal_days": gd, "active": ac,
                                       "pass_scores": pss}):
                            refresh("저장했습니다.")
                st.caption(f"아이 번호: {ch['id']} · 등록일 {ch.get('created_at', '')[:10]}")
                if st.checkbox("이 아이와 모든 학습 데이터 삭제", key=f"delc_{ch['id']}"):
                    if st.button("영구 삭제", key=f"delc_btn_{ch['id']}", type="primary"):
                        if run_safely(E.delete_child, store, ch["id"]) is not None:
                            refresh("삭제했습니다.")

    with t2:
        with st.form("settings"):
            st.subheader("학생 접속")
            c = st.columns(2)
            app_name = c[0].text_input("서비스 이름", SETTINGS["app_name"])
            code = c[1].text_input("학생 접속 코드", SETTINGS["access_code"],
                                   help="학생 화면에 처음 들어갈 때 입력하는 코드입니다. 다른 사람이 AI 사용량을 쓰지 못하게 막아줍니다.")
            service_open = st.toggle("학생 서비스 열기", SETTINGS["service_open"])
            notice = st.text_input("공지/점검 안내 문구", SETTINGS["notice"])
            st.subheader("AI 분석")
            c = st.columns(3)
            model = c[0].text_input("Gemini 모델 이름", SETTINGS["gemini_model"],
                                    help="Google AI Studio 에서 무료로 쓸 수 있는 모델 이름. 예: gemini-2.5-flash")
            nq = c[1].number_input("확인 문제 수", 3, 15, SETTINGS["questions_per_session"])
            mi = c[2].number_input("한 번에 올릴 사진 수", 1, 3, SETTINGS["max_images"])
            st.subheader("기준점수 · 집중관리")
            c = st.columns(3)
            dps = c[0].number_input("새 아이 기본 기준점수", 0, 100, SETTINGS["default_pass_score"], step=5)
            dgd = c[1].number_input("새 아이 기본 월 목표 학습일", 1, 31, SETTINGS["default_goal_days"])
            policy = c[2].selectbox(
                "집중관리 등록 기준", ["fail_only", "all_wrong"],
                index=0 if SETTINGS["review_policy"] == "fail_only" else 1,
                format_func=lambda x: {"fail_only": "기준점수 미달 시 틀린 문제", "all_wrong": "틀린 문제는 항상"}[x])
            c = st.columns(3)
            ms = c[0].number_input("졸업 기준(연속 정답 횟수)", 1, 5, SETTINGS["mastery_streak"])
            iv = c[1].text_input("복습 간격(일, 쉼표 구분)", ", ".join(str(x) for x in SETTINGS["review_intervals"]))
            mr = c[2].number_input("하루 최대 복습 문제 수", 3, 50, SETTINGS["max_review_per_day"])
            if st.form_submit_button("설정 저장", type="primary"):
                try:
                    intervals = [int(x) for x in iv.replace(" ", "").split(",") if x]
                except ValueError:
                    st.error("복습 간격은 숫자를 쉼표로 구분해 입력하세요. 예: 1, 2, 4, 7")
                    intervals = None
                if intervals is not None and not code.strip():
                    st.error("접속 코드를 입력하세요.")
                elif intervals is not None:
                    if run_safely(E.save_settings, store, {
                        "app_name": app_name, "access_code": code.strip(), "service_open": service_open,
                        "notice": notice, "gemini_model": model.strip(), "questions_per_session": nq,
                        "max_images": mi, "default_pass_score": dps, "default_goal_days": dgd,
                        "review_policy": policy, "mastery_streak": ms, "review_intervals": intervals,
                        "max_review_per_day": mr}):
                        refresh("설정을 저장했습니다. 학생 화면에는 약 20초 안에 반영됩니다.")

    with t3:
        st.subheader("백업")
        if st.button("백업 파일 만들기"):
            data = run_safely(E.export_all, store)
            if data:
                st.download_button("📥 백업 파일 내려받기", json.dumps(data, ensure_ascii=False, indent=1),
                                   file_name=f"study_backup_{E.today_str()}.json", mime="application/json")
        st.subheader("복원")
        up = st.file_uploader("백업 파일(.json)", type=["json"])
        if up is not None:
            st.warning("복원하면 백업 파일에 있는 아이들의 기록이 백업 내용으로 덮어써집니다.")
            if st.button("복원 실행", type="primary"):
                try:
                    data = json.loads(up.getvalue().decode("utf-8"))
                except Exception:
                    st.error("JSON 파일을 읽을 수 없습니다.")
                else:
                    if run_safely(E.import_all, store, data):
                        refresh("복원했습니다.")
        st.subheader("아이 학습 데이터 초기화")
        if CHILDREN:
            labels = {c["id"]: c["name"] for c in CHILDREN}
            cid = st.selectbox("대상", list(labels), format_func=lambda x: labels[x], key="reset_child")
            if st.checkbox(f"{labels[cid]}의 학습 기록과 집중관리 문제를 모두 지웁니다"):
                if st.button("초기화", type="primary"):
                    n = run_safely(E.reset_child_data, store, cid)
                    if n is not None:
                        refresh(f"파일 {n}개를 삭제했습니다.")

    with t4:
        st.subheader("데이터 저장소")
        st.write(store.describe())
        if st.button("저장소 연결 점검"):
            okk, msg = store.health()
            (st.success if okk else st.error)(msg)
        st.subheader("AI 키 점검 (선택)")
        st.caption("Streamlit Secrets 에 GEMINI_API_KEY 를 넣어 두면 여기서 키와 모델을 확인할 수 있습니다. "
                   "실제 분석은 Vercel 의 환경변수 키를 사용합니다.")
        if st.button("Gemini 키/모델 점검"):
            key = secret("GEMINI_API_KEY")
            if not key:
                st.warning("Streamlit Secrets 에 GEMINI_API_KEY 가 없습니다.")
            else:
                try:
                    r = requests.get(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{SETTINGS['gemini_model']}",
                        headers={"x-goog-api-key": key}, timeout=15)
                    if r.ok:
                        st.success(f"정상: {r.json().get('displayName', SETTINGS['gemini_model'])}")
                    else:
                        st.error(f"오류 {r.status_code}: {r.text[:300]}")
                except requests.RequestException as e:
                    st.error(f"연결 실패: {e}")
        st.subheader("학생 화면(Vercel) 점검")
        fe = st.text_input("학생 화면 주소", secret("FRONTEND_URL"), placeholder="https://내앱.vercel.app")
        if st.button("학생 화면 API 점검") and fe:
            try:
                r = requests.get(fe.rstrip("/") + "/api/index?action=health", timeout=20)
                d = r.json().get("data", {})
                if r.ok and d:
                    st.write(d)
                    if d.get("storage_mode") != "github":
                        st.error("학생 화면이 임시 저장소를 쓰고 있습니다. Vercel 환경변수에 GITHUB_TOKEN/GITHUB_REPO 를 넣으세요.")
                    elif not d.get("storage_ok"):
                        st.error("학생 화면의 저장소 연결에 문제가 있습니다.")
                    elif not d.get("ai_configured"):
                        st.warning("Vercel 환경변수에 GEMINI_API_KEY 가 없습니다.")
                    else:
                        st.success("학생 화면 서버 정상")
                else:
                    st.error(f"응답 이상: {r.status_code} {r.text[:200]}")
            except Exception as e:  # noqa
                st.error(f"접속 실패: {e}")
        st.subheader("캐시")
        if st.button("캐시 비우고 새로 읽기"):
            refresh("새로 읽었습니다.")


PAGES = {"📊 학습 대시보드": page_dashboard, "📚 학습 기록": page_records,
         "🎯 집중관리 현황": page_focus, "⚙️ 관리자": page_admin}
PAGES[page]()
