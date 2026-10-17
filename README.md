# 오늘공부 체크

아이가 그날 공부한 페이지를 사진으로 올리면 AI가 내용을 정리하고, 잘 이해하고 외웠는지 확인 문제를 내고 채점합니다.
기준점수에 못 미치면 틀린 문제를 **집중 복습**으로 옮겨 매일 다시 풀게 하고, 정해진 횟수만큼 연속으로 맞히면 졸업시킵니다.

## 구성

```
study-coach/
├─ public/              학생 화면 (Vercel 정적 호스팅, 반응형)
│   ├─ index.html
│   ├─ styles.css
│   └─ app.js
├─ api/                 학생 화면용 Python API (Vercel 서버리스 함수)
│   ├─ index.py         요청 처리 (Flask)
│   ├─ _engine.py       사진 분석·채점·집중관리·통계 로직 (관리자와 공용)
│   └─ _store.py        저장소 (임시 파일 / GitHub 비공개 저장소)
├─ backend/             관리자 백엔드 (Streamlit Community Cloud)
│   ├─ app.py           대시보드 · 학습 기록 · 집중관리 · 관리자 기능
│   └─ requirements.txt
├─ requirements.txt     Vercel 함수용 패키지
├─ vercel.json
├─ .streamlit/          Streamlit 테마, secrets 예시
└─ dev_server.py        내 컴퓨터에서 학생 화면+API 함께 띄우는 테스트 서버
```

| 역할 | 어디서 | 비용 |
|---|---|---|
| 학생 화면 + 사진 분석 API(Python) | Vercel Hobby | 무료 |
| 관리자 대시보드 / 설정 (Python) | Streamlit Community Cloud | 무료 |
| 사진 분석 AI | Google Gemini API 무료 등급 | 무료(일일 한도 있음) |
| 데이터 보관 | GitHub 비공개 저장소(JSON 파일) | 무료 |

### 왜 사진 분석 API가 Streamlit이 아니라 Vercel에 있나요?
Streamlit Community Cloud는 화면(웹앱)만 띄울 수 있고, 다른 사이트(Vercel 프론트엔드)가 호출할 수 있는 API 주소를 만들 수 없습니다.
그래서 학생이 쓰는 분석·채점 API는 Vercel의 **Python 서버리스 함수**로 돌리고, Streamlit은 관리자 백엔드(대시보드·설정)를 맡습니다.
두 곳 모두 `api/_engine.py` 의 같은 Python 코드를 사용합니다.

### 왜 임시 파일만으로는 안 되나요?
Vercel과 Streamlit은 서로 다른 서버라 임시 파일을 공유할 수 없고, 두 곳 모두 재시작하면 임시 폴더가 지워집니다.
그래서 GitHub 설정이 없으면 임시 폴더(`/tmp/study_coach_data`)에 기록하고(테스트용), 설정이 있으면 **비공개 GitHub 저장소**에 JSON으로 영구 보관합니다.
데이터 저장소는 코드 저장소와 **반드시 따로** 만드세요. 같은 저장소에 쓰면 저장할 때마다 Vercel이 다시 배포됩니다.

---

## 배포 순서 (약 30분)

### 0. 준비물
- GitHub 계정, Google 계정
- Vercel 계정(GitHub로 가입), Streamlit Community Cloud 계정(GitHub로 가입)

### 1. Gemini API 키 만들기 (무료)
1. https://aistudio.google.com 접속 → 왼쪽 **Get API key** → **Create API key**
2. `AIza...` 로 시작하는 키를 복사해 둡니다.
> 무료 등급은 하루 요청 수에 한도가 있고, Google이 무료 등급 입력 내용을 서비스 개선에 쓸 수 있다고 안내합니다. 아이 얼굴이나 이름이 사진에 나오지 않게 찍는 것을 권장합니다.
> 모델 이름(기본값 `gemini-2.5-flash`)이 바뀌면 관리자 화면 → 서비스 설정에서 고칠 수 있습니다.

### 2. GitHub 저장소 2개 만들기
1. **코드 저장소**: 예) `study-coach` (공개/비공개 모두 가능) → 이 폴더 전체를 올립니다.
   ```bash
   cd study-coach
   git init && git add . && git commit -m "first"
   git branch -M main
   git remote add origin https://github.com/내아이디/study-coach.git
   git push -u origin main
   ```
   (명령어가 어렵다면 GitHub 웹에서 **Add file → Upload files** 로 폴더 내용을 끌어다 놓아도 됩니다. `.streamlit` 처럼 점으로 시작하는 폴더도 올라갔는지 확인하세요.)
2. **데이터 저장소**: 예) `study-coach-data` — 반드시 **Private**, "Add a README file" 체크(main 브랜치가 생겨야 함).

### 3. GitHub 토큰 만들기 (데이터 저장소 전용)
1. GitHub → 오른쪽 위 프로필 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. Repository access: **Only select repositories → study-coach-data**
3. Permissions → Repository permissions → **Contents: Read and write**
4. 만료일을 정하고 생성 → `github_pat_...` 복사. (만료되면 새로 만들어 Vercel·Streamlit 두 곳에 바꿔 넣습니다)

### 4. Vercel 배포 (학생 화면 + 분석 API)
1. https://vercel.com → **Add New… → Project** → `study-coach` 저장소 **Import**
2. Framework Preset: **Other**, Root Directory: 그대로(`./`), Build 설정은 비워 둡니다. (`vercel.json` 이 `public` 폴더와 API를 지정합니다)
3. **Environment Variables** 에 추가:
   | 이름 | 값 |
   |---|---|
   | `GEMINI_API_KEY` | 1번에서 만든 키 |
   | `GITHUB_TOKEN` | 3번 토큰 |
   | `GITHUB_REPO` | `내아이디/study-coach-data` |
   | `GITHUB_BRANCH` | `main` |
4. **Deploy** → 완료 후 주소(예: `https://study-coach.vercel.app`) 확인
5. 브라우저에서 `https://주소/api/index?action=health` 를 열어 `"storage_mode":"github"`, `"storage_ok":true`, `"ai_configured":true` 인지 확인합니다.
> 환경변수를 나중에 바꿨다면 Vercel → Deployments → 최신 배포 **⋯ → Redeploy** 해야 반영됩니다.

### 5. Streamlit 배포 (관리자 백엔드)
1. https://share.streamlit.io → **Create app → Deploy a public app from GitHub**
2. Repository: `내아이디/study-coach`, Branch: `main`, **Main file path: `backend/app.py`**
3. **Advanced settings** → Python 3.12 선택, Secrets 칸에 `.streamlit/secrets.toml.example` 내용을 붙여넣고 값 수정:
   ```toml
   ADMIN_PASSWORD = "관리자비밀번호"
   GITHUB_TOKEN = "github_pat_..."
   GITHUB_REPO = "내아이디/study-coach-data"
   GITHUB_BRANCH = "main"
   FRONTEND_URL = "https://study-coach.vercel.app"
   GEMINI_API_KEY = "AIza..."   # 선택(키 점검용)
   ```
4. **Deploy** → 관리자 비밀번호로 로그인

### 6. 처음 설정
1. 관리자 → **아이 관리**: 아이 이름, 학년, 월 목표 학습일, 과목별 기준점수 등록
2. 관리자 → **서비스 설정**: 학생 **접속 코드**를 기본값 `1234` 에서 꼭 바꾸기
3. 관리자 → **서버 상태**: "저장소 연결 점검", "학생 화면 API 점검" 이 모두 정상인지 확인
4. 휴대폰으로 Vercel 주소 접속 → 접속 코드 입력 → 아이 선택 → 사진 올리기
   (휴대폰 브라우저의 "홈 화면에 추가"를 하면 앱처럼 쓸 수 있습니다)

---

## 사용 흐름
1. 아이가 공부한 페이지를 찍어 올림(최대 3장, 브라우저에서 자동 압축)
2. AI가 내용 요약·핵심 정리, 사진 속 아이 답 채점, 확인 문제(4지선다) 생성
3. 아이가 문제를 풀면 서버가 채점 → 과목별 기준점수와 비교
4. **기준 미달**이면 틀린 문제를 집중 복습에 등록 (설정에서 "틀린 문제는 항상"으로 바꿀 수 있음)
5. 집중 복습: 맞히면 1·2·4·7일 간격으로 다시 나오고, 정해진 횟수(기본 2번) 연속 정답이면 졸업. 틀리면 그날 다시 나옴
6. 진도율 = 이번 달 공부한 날 수 ÷ 월 목표 학습일

## 무료 운영 시 알아둘 점
- **Streamlit 앱은 오래 접속이 없으면 잠듭니다.** 관리자 화면을 열 때 "Yes, get this app back up" 버튼을 누르면 깨어납니다. 학생 화면(Vercel)은 영향을 받지 않습니다.
- **Gemini 무료 한도**를 넘으면 "오늘 무료 AI 사용량을 다 썼어요" 안내가 나옵니다. 다음 날 다시 됩니다.
- 사진 원본은 저장하지 않고 분석 결과(텍스트)만 저장합니다. 1년치도 수 MB 수준이라 GitHub 무료 용량으로 충분합니다.
- 관리자 → 데이터 관리에서 **백업 파일**을 가끔 내려받아 두세요.
- AI가 만든 문제·해설은 드물게 틀릴 수 있습니다. 관리자 → 학습 기록에서 확인하고 잘못된 집중관리 문제는 삭제할 수 있습니다.

## 내 컴퓨터에서 먼저 시험해 보기
```bash
pip install -r requirements.txt -r backend/requirements.txt
# 학생 화면 + API (체험 모드: AI 키 없이 예시 문제로 동작)
DEMO_MODE=1 python dev_server.py          # → http://localhost:8000 (접속 코드 1234)
# 관리자 (같은 임시 폴더를 보도록 같은 터미널 환경에서)
ADMIN_PASSWORD=admin streamlit run backend/app.py
```
Windows PowerShell은 `$env:DEMO_MODE="1"; python dev_server.py` 처럼 씁니다.
실제 분석을 시험하려면 `DEMO_MODE` 대신 `GEMINI_API_KEY` 를 넣으세요.

## 문제 해결
| 증상 | 확인할 것 |
|---|---|
| 학생 화면에서 "접속 코드가 맞지 않습니다" | 관리자 → 서비스 설정의 접속 코드 (바꾼 뒤 약 20초 후 반영) |
| "GEMINI_API_KEY 가 설정되지 않았습니다" | Vercel 환경변수 추가 후 **Redeploy** 했는지 |
| "AI 모델 … 을 사용할 수 없습니다" | 관리자 → 서비스 설정의 모델 이름(AI Studio에서 사용 가능한 이름으로) |
| 관리자 화면에 학생 기록이 안 보임 | 두 곳의 `GITHUB_REPO` 값이 같은지, 관리자 사이드바가 "임시 저장소 모드"가 아닌지 |
| "GitHub 토큰이 올바르지 않거나 만료" | 새 토큰을 만들어 Vercel·Streamlit 두 곳에 교체 |
| 사진 분석 시간 초과 | 사진 수를 줄이거나 관리자 설정에서 확인 문제 수를 줄이기 |
