/* 오늘공부 체크 — 학생 화면 (Vanilla JS, 빌드 없음) */
(() => {
  "use strict";

  const API = "/api/index";
  const LS = "studycheck.v1";
  const SUBJECTS = ["수학", "영어", "한자", "기타"];
  const MAX_TOTAL_B64 = 4.0 * 1024 * 1024; // Vercel 요청 한도(4.5MB) 여유

  const $view = document.getElementById("view");
  const S = {
    code: "", childId: "", childName: "", appName: "오늘공부 체크", maxImages: 3,
    children: [], photos: [], subject: "", quiz: null, stats: null,
  };

  // ---------------------------------------------------------------- 저장
  function load() {
    try { Object.assign(S, JSON.parse(localStorage.getItem(LS) || "{}")); } catch (_) { /* 무시 */ }
    S.photos = []; S.quiz = null;
  }
  function save() {
    try {
      localStorage.setItem(LS, JSON.stringify({
        code: S.code, childId: S.childId, childName: S.childName, appName: S.appName, maxImages: S.maxImages,
      }));
    } catch (_) { /* 저장 불가 브라우저 */ }
  }

  // ---------------------------------------------------------------- 도우미
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const subjTag = (s) => `<span class="tag subj-${esc(s)}">${esc(s)}</span>`;
  const fmtDate = (d) => {
    if (!d) return "";
    const [y, m, dd] = d.split("-").map(Number);
    const dow = "일월화수목금토"[new Date(y, m - 1, dd).getDay()];
    return `${m}월 ${dd}일 (${dow})`;
  };
  function scorePill(s) {
    if (s.first_score === null || s.first_score === undefined) return `<span class="score-pill wait">풀기 전</span>`;
    return `<span class="score-pill ${s.passed ? "pass" : "fail"}">${s.best_score}점</span>`;
  }
  let toastTimer;
  function toast(msg, isError = false) {
    const t = document.getElementById("toast");
    t.textContent = msg; t.className = "toast" + (isError ? " error" : ""); t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, isError ? 5000 : 2600);
  }
  function render(html) { $view.innerHTML = html; window.scrollTo(0, 0); }
  function loading() { render(`<div class="loading-block"><span class="spinner" aria-label="불러오는 중"></span></div>`); }
  function errorView(msg, retry = true) {
    render(`<div class="sheet empty stack">
      <div class="big-ico" aria-hidden="true">⚠️</div><h2>불러오지 못했어요</h2>
      <p class="muted">${esc(msg)}</p>
      <div class="row" style="justify-content:center">
        ${retry ? `<button class="btn primary" data-act="retry">다시 시도</button>` : ""}
        <a class="btn" href="#/">홈으로</a>
      </div></div>`);
    const b = $view.querySelector('[data-act="retry"]');
    if (b) b.onclick = () => route();
  }
  let overlayTimer;
  function overlay(show, title, subs = []) {
    const o = document.getElementById("overlay");
    clearInterval(overlayTimer);
    if (!show) { o.hidden = true; return; }
    document.getElementById("overlayTitle").textContent = title;
    const sub = document.getElementById("overlaySub");
    let i = 0; sub.textContent = subs[0] || "잠시만 기다려 주세요";
    if (subs.length > 1) overlayTimer = setInterval(() => { i = (i + 1) % subs.length; sub.textContent = subs[i]; }, 3500);
    o.hidden = false;
  }

  async function api(action, { method = "GET", params = {}, body } = {}) {
    const qs = new URLSearchParams({ action, ...params });
    let res;
    try {
      res = await fetch(`${API}?${qs}`, {
        method,
        headers: { "Content-Type": "application/json", "X-Access-Code": S.code || "" },
        body: body ? JSON.stringify(body) : undefined,
        cache: "no-store",
      });
    } catch (_) {
      throw new Error("인터넷 연결을 확인해 주세요.");
    }
    let j = null;
    try { j = await res.json(); } catch (_) { /* HTML 오류 페이지 등 */ }
    if (!j) {
      if (res.status === 504) throw new Error("분석 시간이 너무 오래 걸렸어요. 사진 수를 줄여서 다시 시도해 주세요.");
      if (res.status === 413) throw new Error("사진 용량이 너무 커요. 사진 수를 줄여 주세요.");
      throw new Error(`서버 응답 오류가 발생했어요 (${res.status}). 잠시 후 다시 시도해 주세요.`);
    }
    if (!j.ok) {
      if (res.status === 401 && action !== "login") {
        S.code = ""; save(); location.hash = "#/login";
      }
      const err = new Error(j.error || "알 수 없는 오류가 발생했어요.");
      err.status = res.status;
      throw err;
    }
    return j.data;
  }

  // ---------------------------------------------------------------- 사진 압축
  function readImage(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => { resolve({ img, url }); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("이 사진 형식은 열 수 없어요. JPG나 PNG 사진을 골라 주세요.")); };
      img.src = url;
    });
  }
  async function compress(file, maxSide = 1600, quality = 0.82) {
    const { img, url } = await readImage(file);
    try {
      const w0 = img.naturalWidth, h0 = img.naturalHeight;
      const scale = Math.min(1, maxSide / Math.max(w0, h0));
      const w = Math.max(1, Math.round(w0 * scale)), h = Math.max(1, Math.round(h0 * scale));
      const canvas = document.createElement("canvas");
      canvas.width = w; canvas.height = h;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0, w, h);
      const dataUrl = canvas.toDataURL("image/jpeg", quality);
      return { mime: "image/jpeg", data: dataUrl.split(",")[1], preview: dataUrl, file };
    } finally { URL.revokeObjectURL(url); }
  }

  // ---------------------------------------------------------------- 화면: 접속 코드
  function viewLogin() {
    setChrome(false);
    render(`<section class="gate stack">
      <div class="stack" style="gap:6px">
        <h1>${esc(S.appName)}</h1>
        <p class="muted">오늘 공부한 내용을 사진으로 올리면 잘 이해했는지 문제로 확인해 줘요.</p>
      </div>
      <form class="sheet stack" id="loginForm" autocomplete="off">
        <label class="field"><span>접속 코드</span>
          <input class="input" id="code" name="code" type="password" inputmode="text" required placeholder="부모님께 받은 코드">
        </label>
        <button class="btn primary block" type="submit">들어가기</button>
        <p class="muted small" id="loginMsg"></p>
      </form>
    </section>`);
    const f = document.getElementById("loginForm");
    document.getElementById("code").focus();
    f.onsubmit = async (e) => {
      e.preventDefault();
      const code = document.getElementById("code").value.trim();
      const btn = f.querySelector("button");
      btn.disabled = true;
      try {
        const d = await api("login", { method: "POST", body: { code } });
        S.code = code; S.appName = d.app_name; S.maxImages = d.max_images; S.children = d.children;
        save(); setAppName();
        location.hash = "#/children";
      } catch (err) {
        document.getElementById("loginMsg").textContent = err.message;
        btn.disabled = false;
      }
    };
  }

  // ---------------------------------------------------------------- 화면: 아이 선택
  async function viewChildren() {
    setChrome(false);
    loading();
    let d;
    try { d = await api("login", { method: "POST", body: { code: S.code } }); } catch (err) {
      if (err.status === 401) { S.code = ""; save(); return viewLogin(); }
      return errorView(err.message);
    }
    S.children = d.children; S.appName = d.app_name; S.maxImages = d.max_images; save(); setAppName();
    if (!S.children.length) {
      return render(`<section class="gate sheet empty stack">
        <div class="big-ico" aria-hidden="true">👧</div><h2>등록된 아이가 없어요</h2>
        <p class="muted">관리자 화면에서 아이를 먼저 등록해 주세요.</p>
        <button class="btn" id="relogin">접속 코드 다시 입력</button></section>`), bindRelogin();
    }
    render(`<section class="stack" style="max-width:720px;margin:4vh auto 0">
      <h1>누가 공부했나요?</h1>
      ${d.notice ? `<div class="sheet flat small">📢 ${esc(d.notice)}</div>` : ""}
      <div class="kids">
        ${S.children.map((c) => `<button class="kid" data-id="${esc(c.id)}" data-name="${esc(c.name)}">
          <span class="avatar" aria-hidden="true">${esc(c.name.slice(0, 1))}</span>
          <span class="name">${esc(c.name)}</span><span class="muted small">${esc(c.grade || "")}</span></button>`).join("")}
      </div>
      <button class="btn ghost" id="relogin">접속 코드 다시 입력</button>
    </section>`);
    $view.querySelectorAll(".kid").forEach((b) => b.onclick = () => {
      S.childId = b.dataset.id; S.childName = b.dataset.name; save();
      location.hash = "#/";
    });
    bindRelogin();
  }
  function bindRelogin() {
    const b = document.getElementById("relogin");
    if (b) b.onclick = () => { S.code = ""; S.childId = ""; save(); location.hash = "#/login"; };
  }

  // ---------------------------------------------------------------- 화면: 홈
  function calendarHtml(stats) {
    const [y, m] = stats.month.split("-").map(Number);
    const first = new Date(y, m - 1, 1).getDay();
    const days = new Date(y, m, 0).getDate();
    const done = new Set(stats.study_dates || []);
    let cells = "일월화수목금토".split("").map((d) => `<div class="dow">${d}</div>`).join("");
    for (let i = 0; i < first; i++) cells += `<div></div>`;
    for (let d = 1; d <= days; d++) {
      const key = `${stats.month}-${String(d).padStart(2, "0")}`;
      const cls = ["d", done.has(key) ? "done" : "", key === stats.today ? "today" : ""].join(" ");
      cells += `<div class="${cls}" ${done.has(key) ? 'aria-label="' + d + '일 공부함"' : ""}>${d}</div>`;
    }
    return `<div class="cal">${cells}</div>`;
  }

  async function viewHome() {
    setChrome(true, "home");
    loading();
    let st;
    try { st = await api("stats", { params: { child_id: S.childId } }); } catch (err) {
      if (err.status === 404) { S.childId = ""; save(); location.hash = "#/children"; return; }
      return errorView(err.message);
    }
    S.stats = st; updateBadge(st.review_due);
    const pending = (st.recent || []).find((s) => s.status === "analyzed");
    const subjRows = SUBJECTS.map((sub) => {
      const v = st.by_subject[sub];
      if (!v.count) return "";
      const low = v.avg < v.pass_score;
      return `<div class="subj-row">
        <span>${subjTag(sub)}</span>
        <div class="meter" role="img" aria-label="${sub} 평균 ${v.avg}점, 기준 ${v.pass_score}점">
          <span style="width:${v.avg}%"></span><i style="left:calc(${v.pass_score}% - 1px)"></i></div>
        <span class="val ${low ? "low" : ""}">${v.avg}점 / ${v.pass_score}</span></div>`;
    }).join("");

    render(`<div class="stack">
      <section class="hello stack" style="gap:4px">
        <h1>${st.today_done ? `${esc(st.child.name)}, 오늘도 해냈어요!` : `${esc(st.child.name)}, 오늘 공부를 올려 볼까요?`}</h1>
        <p class="muted">${fmtDate(st.today)}${st.streak ? ` · ${st.streak}일 연속 공부 중` : ""}</p>
      </section>
      ${st.notice ? `<div class="sheet flat small">📢 ${esc(st.notice)}</div>` : ""}
      <div class="home-grid">
        <div class="stack">
          <a class="btn primary big block" href="#/upload">📷 오늘 공부 사진 올리기</a>
          ${st.review_due ? `<section class="sheet red focus-alert">
              <div class="num">${st.review_due}</div>
              <div class="stack" style="gap:8px;flex:1">
                <div><h3>집중 복습할 문제가 있어요</h3>
                <p class="small muted">기준점수에 못 미친 공부의 틀린 문제예요. ${st.mastery_streak}번 연속으로 맞히면 졸업해요.</p></div>
                <a class="btn red" href="#/review">복습 시작</a></div></section>` : ""}
          ${pending ? `<section class="sheet stack" style="gap:10px">
              <h3>아직 확인 문제를 안 풀었어요</h3>
              <p class="muted small">${esc(pending.title)} · ${pending.question_count}문제</p>
              <a class="btn" href="#/quiz/${esc(pending.id)}">지금 풀기</a></section>` : ""}
          <section class="sheet stack">
            <div class="cal-head"><h2>${Number(st.month.split("-")[1])}월 공부 도장</h2>
              <span class="muted small">${st.study_days} / ${st.goal_days}일 · 진도율 ${st.progress}%</span></div>
            <div class="bar yellow" aria-hidden="true"><span style="width:${st.progress}%"></span></div>
            ${calendarHtml(st)}
          </section>
        </div>
        <div class="stack">
          <section class="sheet stack">
            <h2>이번 달 성적</h2>
            <div class="stat-line">
              <div><b>${st.avg_score ?? "-"}${st.avg_score !== null ? "점" : ""}</b><span class="muted small">평균 점수</span></div>
              <div><b>${st.pass_rate ?? "-"}${st.pass_rate !== null ? "%" : ""}</b><span class="muted small">기준 통과</span></div>
              <div><b>${st.review_mastered}</b><span class="muted small">졸업한 문제</span></div>
            </div>
            ${subjRows ? `<div class="subj-rows">${subjRows}</div><p class="muted small">빨간 선이 기준점수예요.</p>`
              : `<p class="muted">문제를 풀면 과목별 점수가 여기에 보여요.</p>`}
          </section>
          <section class="sheet stack" style="gap:6px">
            <div class="cal-head" style="margin:0"><h2>최근 공부</h2><a href="#/history" class="small">전체 보기</a></div>
            ${(st.recent || []).length ? `<div class="list">${st.recent.map(itemHtml).join("")}</div>`
              : `<p class="muted">아직 올린 공부가 없어요. 첫 사진을 올려 보세요!</p>`}
          </section>
        </div>
      </div></div>`);
  }
  function itemHtml(s) {
    return `<a class="item" href="#/s/${esc(s.id)}">${subjTag(s.subject)}
      <div class="grow"><div class="title">${esc(s.title)}</div><div class="muted small">${fmtDate(s.date)}</div></div>
      ${scorePill(s)}</a>`;
  }

  // ---------------------------------------------------------------- 화면: 사진 올리기
  function viewUpload() {
    setChrome(true, "upload");
    const max = S.maxImages || 3;
    const slots = [];
    for (let i = 0; i < max; i++) {
      const p = S.photos[i];
      slots.push(p ? `<div class="photo"><img src="${p.preview}" alt="올린 사진 ${i + 1}"><button type="button" data-rm="${i}" aria-label="사진 ${i + 1} 빼기">✕</button></div>`
        : `<div class="photo slot">사진 ${i + 1}</div>`);
    }
    render(`<div class="stack">
      <h1>오늘 공부 올리기</h1>
      <div class="upload-grid">
        <section class="sheet stack">
          <h2>1. 공부한 페이지를 찍어요</h2>
          <p class="muted small">교재, 학습지, 공책을 밝은 곳에서 글씨가 잘 보이게 찍어 주세요. 최대 ${max}장.</p>
          <div class="pick-row">
            <label class="btn primary">📷 카메라<input type="file" accept="image/*" capture="environment" id="camIn" class="vh"></label>
            <label class="btn">🖼 앨범에서<input type="file" accept="image/*" multiple id="albumIn" class="vh"></label>
          </div>
          <div class="photos">${slots.join("")}</div>
        </section>
        <section class="sheet stack">
          <h2>2. 과목을 골라요</h2>
          <div class="chips" role="group" aria-label="과목">
            ${["", ...SUBJECTS].map((s) => `<button type="button" class="chip" data-subj="${s}" aria-pressed="${S.subject === s}">${s || "자동"}</button>`).join("")}
          </div>
          <label class="field"><span>메모 (선택)</span>
            <textarea class="input" id="note" maxlength="200" placeholder="예: 3단원 받아올림 덧셈, 영어 단어 20개">${esc(S.note || "")}</textarea></label>
          <button class="btn primary big block" id="go" ${S.photos.length ? "" : "disabled"}>확인 문제 만들기</button>
          <p class="muted small">사진을 분석해서 오늘 공부를 정리하고, 잘 외웠는지 확인 문제를 만들어요. 20초~1분쯤 걸려요.</p>
        </section>
      </div></div>`);

    const addFiles = async (files) => {
      const list = Array.from(files || []);
      if (!list.length) return;
      const room = max - S.photos.length;
      if (room <= 0) { toast(`사진은 ${max}장까지 올릴 수 있어요.`, true); return; }
      if (list.length > room) toast(`사진은 ${max}장까지라서 ${room}장만 넣었어요.`);
      for (const f of list.slice(0, room)) {
        try { S.photos.push(await compress(f)); } catch (err) { toast(err.message, true); }
      }
      viewUpload();
    };
    document.getElementById("camIn").onchange = (e) => addFiles(e.target.files);
    document.getElementById("albumIn").onchange = (e) => addFiles(e.target.files);
    $view.querySelectorAll("[data-rm]").forEach((b) => b.onclick = () => { S.photos.splice(Number(b.dataset.rm), 1); viewUpload(); });
    $view.querySelectorAll("[data-subj]").forEach((b) => b.onclick = () => {
      S.subject = b.dataset.subj;
      $view.querySelectorAll("[data-subj]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    });
    const note = document.getElementById("note");
    note.oninput = () => { S.note = note.value; };
    document.getElementById("go").onclick = analyze;
  }

  async function analyze() {
    if (!S.photos.length) return;
    let images = S.photos.map((p) => ({ mime: p.mime, data: p.data }));
    let total = images.reduce((a, i) => a + i.data.length, 0);
    if (total > MAX_TOTAL_B64) { // 더 작게 다시 압축
      const smaller = [];
      for (const p of S.photos) smaller.push(await compress(p.file, 1200, 0.7));
      images = smaller.map((p) => ({ mime: p.mime, data: p.data }));
      total = images.reduce((a, i) => a + i.data.length, 0);
      if (total > MAX_TOTAL_B64) { toast("사진 용량이 너무 커요. 사진 수를 줄여 주세요.", true); return; }
    }
    overlay(true, "사진을 읽고 있어요", ["글씨를 하나하나 읽는 중", "오늘 배운 내용을 정리하는 중", "확인 문제를 만드는 중", "거의 다 됐어요"]);
    try {
      const s = await api("analyze", { method: "POST", body: { child_id: S.childId, subject: S.subject, images, note: S.note || "" } });
      S.photos = []; S.note = ""; S.subject = "";
      S.lastSession = s;
      overlay(false);
      location.hash = `#/s/${s.id}`;
    } catch (err) {
      overlay(false);
      toast(err.message, true);
    }
  }

  // ---------------------------------------------------------------- 화면: 분석 결과
  async function getSession(id) {
    if (S.lastSession && S.lastSession.id === id && !S.lastSession.stale) return S.lastSession;
    const s = await api("session", { params: { child_id: S.childId, id } });
    S.lastSession = s;
    return s;
  }

  async function viewSession(id) {
    setChrome(true, "history");
    loading();
    let s;
    try { s = await getSession(id); } catch (err) { return errorView(err.message); }
    const ws = (s.worksheet && s.worksheet.items) || [];
    const done = s.first_score !== null && s.first_score !== undefined;
    render(`<div class="stack" style="max-width:820px">
      <div class="row">${subjTag(s.subject)}<span class="muted small">${fmtDate(s.date)}</span></div>
      <h1>${esc(s.title)}</h1>
      <section class="sheet stack">
        <h2>오늘 공부한 내용</h2>
        <p>${esc(s.summary)}</p>
        ${s.key_points.length ? `<ul class="highlight-list">${s.key_points.map((k) => `<li>✏️ <span>${esc(k)}</span></li>`).join("")}</ul>` : ""}
        ${s.encouragement ? `<p class="muted">💬 ${esc(s.encouragement)}</p>` : ""}
      </section>
      ${ws.length ? `<section class="sheet stack">
        <h2>사진 속 채점 <span class="muted small">${ws.filter((i) => i.is_correct).length} / ${ws.length}</span></h2>
        <div class="ws">${ws.map((i) => `<div class="ws-item"><span class="mark" aria-label="${i.is_correct ? "맞음" : "틀림"}">${i.is_correct ? "◯" : "✕"}</span>
          <div><div>${esc(i.question)}</div>
          <div class="ans muted">${i.is_correct ? `내 답: ${esc(i.child_answer)}` : `내 답: <s>${esc(i.child_answer || "(빈칸)")}</s> → 정답: <b>${esc(i.correct_answer)}</b>`}</div>
          ${!i.is_correct && i.explanation ? `<div class="small">${esc(i.explanation)}</div>` : ""}</div></div>`).join("")}</div>
      </section>` : ""}
      <section class="sheet stack ${done ? (s.passed ? "green" : "red") : ""}">
        ${done ? `<h2>확인 문제 ${s.passed ? "통과 🎉" : "기준점수 미달"}</h2>
            <p>최고 ${s.best_score}점 · 처음 ${s.first_score}점 · 기준 ${s.pass_score}점 · ${s.attempts_count}번 풀었어요</p>
            <div class="row"><a class="btn primary" href="#/quiz/${esc(s.id)}">다시 풀기</a>
            ${s.last_attempt ? `<button class="btn" id="showLast">지난 채점 보기</button>` : ""}</div>`
          : `<h2>잘 이해했는지 확인해 봐요</h2>
            <p class="muted">${s.questions.length}문제 · 기준점수 ${s.pass_score}점</p>
            <a class="btn primary big block" href="#/quiz/${esc(s.id)}">확인 문제 풀기</a>`}
      </section>
      <div id="lastBox"></div>
    </div>`);
    const b = document.getElementById("showLast");
    if (b) b.onclick = () => {
      document.getElementById("lastBox").innerHTML = `<section class="sheet stack"><h2>지난 채점 (${s.last_attempt.score}점)</h2>
        <div>${s.last_attempt.details.map(reviewQHtml).join("")}</div></section>`;
      b.remove();
    };
  }

  // ---------------------------------------------------------------- 퀴즈 (학습 확인 / 집중 복습 공용)
  async function viewQuiz(id) {
    setChrome(true, "history");
    loading();
    let s;
    try { s = await getSession(id); } catch (err) { return errorView(err.message); }
    S.quiz = { mode: "session", id: s.id, title: s.title, items: s.questions, idx: 0, answers: new Array(s.questions.length).fill(null), passScore: s.pass_score };
    drawQuiz();
  }

  function drawQuiz() {
    const q = S.quiz, item = q.items[q.idx], n = q.items.length;
    const last = q.idx === n - 1;
    render(`<div class="quiz stack">
      <div class="q-progress"><span class="display">${q.idx + 1} / ${n}</span>
        <div class="bar" aria-hidden="true"><span style="width:${((q.idx + 1) / n) * 100}%"></span></div>
        <button class="btn ghost" id="quit" aria-label="그만 풀기">✕</button></div>
      <p class="muted small">${q.mode === "review" ? "🎯 집중 복습" : esc(q.title)}${item.subject ? ` · ${esc(item.subject)}` : ""}${q.mode === "review" && item.streak ? ` · 연속 ${item.streak}번 맞힘` : ""}</p>
      <section class="sheet q-card">
        <div class="q-text">${esc(item.question)}</div>
        <div class="options" role="radiogroup" aria-label="보기">
          ${item.options.map((o, i) => `<button type="button" class="opt" role="radio" aria-checked="${q.answers[q.idx] === i}" data-i="${i}">
            <span class="n">${i + 1}</span><span>${esc(o)}</span></button>`).join("")}
        </div>
        <div class="q-nav">
          <button class="btn" id="prev" ${q.idx === 0 ? "disabled" : ""}>이전</button>
          <button class="btn primary" id="next" ${q.answers[q.idx] === null ? "disabled" : ""}>${last ? "채점하기" : "다음"}</button>
        </div>
      </section></div>`);
    $view.querySelectorAll(".opt").forEach((b) => b.onclick = () => {
      q.answers[q.idx] = Number(b.dataset.i);
      $view.querySelectorAll(".opt").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
      document.getElementById("next").disabled = false;
    });
    document.getElementById("prev").onclick = () => { q.idx = Math.max(0, q.idx - 1); drawQuiz(); };
    document.getElementById("next").onclick = () => {
      if (q.answers[q.idx] === null) return;
      if (!last) { q.idx += 1; drawQuiz(); return; }
      const empty = q.answers.findIndex((a) => a === null);
      if (empty >= 0) { q.idx = empty; drawQuiz(); toast(`${empty + 1}번 문제를 아직 안 풀었어요.`); return; }
      submitQuiz();
    };
    document.getElementById("quit").onclick = () => {
      if (confirm("그만 풀까요? 지금까지 고른 답은 저장되지 않아요.")) history.back();
    };
  }

  async function submitQuiz() {
    const q = S.quiz;
    overlay(true, "채점하고 있어요", ["빨간펜 준비 중"]);
    try {
      if (q.mode === "session") {
        const r = await api("submit", { method: "POST", body: { child_id: S.childId, session_id: q.id, answers: q.answers } });
        if (S.lastSession) S.lastSession.stale = true;
        overlay(false);
        drawSessionResult(r);
      } else {
        const answers = {};
        q.items.forEach((it, i) => { answers[it.id] = q.answers[i]; });
        const r = await api("review_submit", { method: "POST", body: { child_id: S.childId, answers } });
        overlay(false);
        drawReviewResult(r);
      }
    } catch (err) {
      overlay(false);
      toast(err.message, true);
    }
  }

  function stampHtml(score, pass) {
    return `<div class="stamp ${pass ? "" : "fail"}">
      <svg viewBox="0 0 210 160" aria-hidden="true"><path d="M150 22 C 205 40, 210 120, 120 140 C 40 155, 0 110, 12 70 C 22 35, 70 15, 118 16 C 140 17, 160 24, 170 32"/></svg>
      <span class="score">${score}<small>점</small></span></div>`;
  }
  function reviewQHtml(d) {
    const chosen = d.chosen !== null && d.chosen !== undefined ? d.options[d.chosen] : "(안 고름)";
    return `<div class="review-q"><span class="mark" aria-label="${d.correct ? "맞음" : "틀림"}">${d.correct ? "◯" : "✕"}</span>
      <div class="stack" style="gap:4px"><div class="qt">${esc(d.question)}</div>
      ${d.correct ? `<div class="line">내 답: <span class="right-ans">${esc(chosen)}</span></div>`
        : `<div class="line">내 답: <span class="wrong-ans">${esc(chosen)}</span></div>
           <div class="line">정답: <span class="right-ans">${esc(d.options[d.answer_index])}</span></div>`}
      ${d.extra || ""}
      ${d.explanation && !d.correct ? `<div class="exp">💡 ${esc(d.explanation)}</div>` : ""}</div></div>`;
  }

  function drawSessionResult(r) {
    const q = S.quiz;
    const wrong = r.total - r.correct;
    render(`<div class="quiz stack">
      <section class="sheet result-hero ${r.passed ? "green" : "red"}">
        ${stampHtml(r.score, r.passed)}
        <p class="verdict ${r.passed ? "pass" : "fail"}">${r.passed ? "기준 통과! 정말 잘했어요" : "조금만 더 해 볼까요?"}</p>
        <p class="muted">${r.total}문제 중 ${r.correct}문제 맞힘 · 기준점수 ${r.pass_score}점 · ${r.attempt}번째 풀이</p>
        ${r.review_added ? `<p style="margin-top:10px">틀린 문제 ${r.review_added}개를 <b>집중 복습</b>에 넣었어요. 연속으로 맞히면 졸업해요.</p>`
          : (!r.passed && wrong ? `<p style="margin-top:10px">틀린 문제는 이미 집중 복습에 있어요.</p>` : "")}
        <div class="row" style="justify-content:center;margin-top:16px">
          ${!r.passed ? `<button class="btn primary" id="retry">다시 풀기</button>` : ""}
          ${r.review_added ? `<a class="btn red" href="#/review">집중 복습하기</a>` : ""}
          <a class="btn" href="#/">홈으로</a>
        </div>
      </section>
      <section class="sheet stack"><h2>채점 결과</h2><div>${r.details.map(reviewQHtml).join("")}</div></section>
    </div>`);
    const retry = document.getElementById("retry");
    if (retry) retry.onclick = () => {
      S.quiz = { ...q, idx: 0, answers: new Array(q.items.length).fill(null) };
      drawQuiz();
    };
  }

  // ---------------------------------------------------------------- 화면: 집중 복습
  async function viewReview() {
    setChrome(true, "review");
    loading();
    let d;
    try { d = await api("review", { params: { child_id: S.childId } }); } catch (err) { return errorView(err.message); }
    updateBadge(d.items.length);
    if (!d.items.length) {
      return render(`<section class="sheet empty stack" style="max-width:560px;margin:0 auto">
        <div class="big-ico" aria-hidden="true">🌈</div><h2>오늘 복습할 문제가 없어요</h2>
        <p class="muted">기준점수에 못 미친 문제는 여기서 매일 다시 풀어요. 지금은 모두 끝냈어요!</p>
        <a class="btn primary" href="#/">홈으로</a></section>`);
    }
    const subjects = [...new Set(d.items.map((i) => i.subject))];
    render(`<section class="sheet red stack" style="max-width:640px;margin:0 auto">
      <h1>🎯 집중 복습</h1>
      <p>오늘 다시 풀 문제가 <b>${d.items.length}개</b> 있어요.</p>
      <div class="row">${subjects.map(subjTag).join("")}</div>
      <p class="muted small">한 문제를 ${d.mastery_streak}번 연속으로 맞히면 졸업! 틀리면 오늘 다시 나와요.</p>
      <button class="btn red big block" id="start">복습 시작</button></section>`);
    document.getElementById("start").onclick = () => {
      S.quiz = { mode: "review", id: "review", title: "집중 복습", items: d.items, idx: 0, answers: new Array(d.items.length).fill(null), mastery: d.mastery_streak };
      drawQuiz();
    };
  }

  function drawReviewResult(r) {
    const score = r.total ? Math.round((r.correct / r.total) * 100) : 0;
    const allOk = r.correct === r.total;
    const details = r.results.map((x) => ({
      ...x,
      extra: x.mastered ? `<div class="line" style="color:var(--green)">🎓 졸업했어요!</div>`
        : x.correct ? `<div class="line muted small">연속 ${x.streak} / ${r.mastery_streak}번 · 다음 복습 ${fmtDate(x.next_review)}</div>`
          : `<div class="line muted small">오늘 다시 풀어요</div>`,
    }));
    const left = r.total - r.correct;
    render(`<div class="quiz stack">
      <section class="sheet result-hero ${allOk ? "green" : "red"}">
        ${stampHtml(score, allOk)}
        <p class="verdict ${allOk ? "pass" : "fail"}">${allOk ? "모두 맞혔어요!" : `${left}문제는 한 번 더!`}</p>
        <p class="muted">${r.total}문제 중 ${r.correct}문제 맞힘${r.mastered_now ? ` · ${r.mastered_now}문제 졸업 🎓` : ""}</p>
        <div class="row" style="justify-content:center;margin-top:16px">
          ${left ? `<button class="btn red" id="again">틀린 문제 다시 풀기</button>` : ""}
          <a class="btn" href="#/">홈으로</a></div>
      </section>
      <section class="sheet stack"><h2>복습 결과</h2><div>${details.map(reviewQHtml).join("")}</div></section></div>`);
    const again = document.getElementById("again");
    if (again) again.onclick = () => viewReview();
  }

  // ---------------------------------------------------------------- 화면: 기록
  async function viewHistory() {
    setChrome(true, "history");
    loading();
    let list;
    try { list = await api("sessions", { params: { child_id: S.childId } }); } catch (err) { return errorView(err.message); }
    const draw = (filter) => {
      const items = list.filter((s) => !filter || s.subject === filter);
      let html = "", lastDate = "";
      for (const s of items) {
        if (s.date !== lastDate) { html += `<div class="date-head">${fmtDate(s.date)}</div>`; lastDate = s.date; }
        html += itemHtml(s);
      }
      render(`<div class="stack" style="max-width:820px">
        <h1>공부 기록</h1>
        <div class="filters chips" role="group" aria-label="과목 거르기">
          ${["", ...SUBJECTS].map((s) => `<button class="chip" data-f="${s}" aria-pressed="${filter === s}">${s || "전체"}</button>`).join("")}
        </div>
        <section class="sheet">${items.length ? `<div class="list">${html}</div>`
          : `<div class="empty"><p class="muted">기록이 없어요.</p><a class="btn primary" href="#/upload" style="margin-top:12px">공부 올리기</a></div>`}</section>
      </div>`);
      $view.querySelectorAll("[data-f]").forEach((b) => b.onclick = () => draw(b.dataset.f));
    };
    draw("");
  }

  // ---------------------------------------------------------------- 공통 틀
  function setAppName() {
    document.getElementById("appName").textContent = S.appName;
    document.title = S.appName;
  }
  function setChrome(show, active) {
    const nav = document.getElementById("nav");
    const chip = document.getElementById("childChip");
    nav.hidden = !show;
    chip.hidden = !show || !S.childName;
    chip.textContent = S.childName ? `${S.childName} ▾` : "";
    nav.querySelectorAll("a").forEach((a) => a.classList.toggle("active", a.dataset.route === active));
  }
  function updateBadge(n) {
    const b = document.getElementById("reviewBadge");
    b.hidden = !n; b.textContent = n > 99 ? "99+" : String(n || "");
  }
  document.getElementById("childChip").onclick = () => { location.hash = "#/children"; };

  // ---------------------------------------------------------------- 라우터
  function route() {
    overlay(false);
    const h = location.hash.replace(/^#\/?/, "");
    const [page, arg] = h.split("/");
    if (!S.code && page !== "login") { location.hash = "#/login"; return; }
    if (page === "login") return viewLogin();
    if (page === "children") return viewChildren();
    if (!S.childId) { location.hash = "#/children"; return; }
    switch (page) {
      case "": case "home": return viewHome();
      case "upload": return viewUpload();
      case "s": return arg ? viewSession(decodeURIComponent(arg)) : viewHistory();
      case "quiz": return arg ? viewQuiz(decodeURIComponent(arg)) : viewHistory();
      case "review": return viewReview();
      case "history": return viewHistory();
      default: location.hash = "#/";
    }
  }

  load();
  setAppName();
  window.addEventListener("hashchange", route);
  route();
})();
