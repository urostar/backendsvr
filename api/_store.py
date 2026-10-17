"""
저장소 계층.

- local 모드 : 서버의 임시 폴더(tempfile)에 JSON 파일로 기록합니다.
               (GitHub 설정이 없을 때 자동 사용. 서버 재시작 시 사라질 수 있음)
- github 모드: 별도의 비공개(Private) GitHub 저장소에 JSON 파일로 영구 보관합니다.
               Vercel(학생용 API)과 Streamlit(관리자)이 같은 데이터를 함께 쓰기 위해 필요합니다.

두 모드 모두 같은 인터페이스(read / write / update / list / delete)를 제공합니다.
"""
import base64
import copy
import json
import os
import tempfile
import threading
import time

import requests

GITHUB_API = "https://api.github.com"


class StoreError(Exception):
    pass


class ConflictError(StoreError):
    pass


def _clean_path(path: str) -> str:
    path = (path or "").strip().strip("/")
    if not path or ".." in path.split("/"):
        raise StoreError(f"잘못된 경로: {path!r}")
    return path


class Store:
    def __init__(self, token=None, repo=None, branch=None, base_dir=None):
        self.token = (token if token is not None else os.environ.get("GITHUB_TOKEN", "")).strip()
        self.repo = (repo if repo is not None else os.environ.get("GITHUB_REPO", "")).strip()
        self.branch = (branch or os.environ.get("GITHUB_BRANCH", "") or "main").strip()
        self.mode = "github" if (self.token and self.repo) else "local"
        self.base_dir = base_dir or os.environ.get("LOCAL_DATA_DIR") or os.path.join(
            tempfile.gettempdir(), "study_coach_data"
        )
        self.prefix = "data"
        self._lock = threading.RLock()
        self._session = requests.Session()

    # ------------------------------------------------------------------ 공통
    def describe(self) -> str:
        if self.mode == "github":
            return f"GitHub 저장소 {self.repo} ({self.branch} 브랜치, /{self.prefix} 폴더)"
        return f"임시 폴더 {self.base_dir}"

    def read(self, path, default=None):
        """(data, version) 반환. 파일이 없으면 (default 복사본, None)."""
        path = _clean_path(path)
        if self.mode == "github":
            return self._gh_read(path, default)
        return self._local_read(path, default)

    def write(self, path, data, version=None, message=None):
        path = _clean_path(path)
        if self.mode == "github":
            return self._gh_write(path, data, version, message)
        return self._local_write(path, data)

    def update(self, path, fn, default=None, message=None, retries=6):
        """read → fn(data) 로 수정 → write. 충돌 시 자동 재시도.
        fn 은 data 를 직접 수정하고, 호출자에게 돌려줄 값을 반환합니다."""
        path = _clean_path(path)
        if self.mode == "local":
            with self._lock:
                data, _ = self._local_read(path, default)
                result = fn(data)
                self._local_write(path, data)
                return result
        last_err = None
        for attempt in range(retries):
            data, version = self._gh_read(path, default)
            result = fn(data)
            try:
                self._gh_write(path, data, version, message)
                return result
            except ConflictError as e:
                last_err = e
                time.sleep(0.4 * (attempt + 1))
        raise StoreError(f"동시 저장 충돌이 계속 발생했습니다: {last_err}")

    def list(self, dir_path):
        """폴더 안 파일 이름 목록 (하위 폴더 제외)."""
        dir_path = _clean_path(dir_path)
        if self.mode == "github":
            r = self._session.get(
                self._gh_url(dir_path), headers=self._headers(),
                params={"ref": self.branch, "_": str(time.time())}, timeout=20,
            )
            if r.status_code == 404:
                return []
            self._raise_for(r, "목록 조회")
            items = r.json()
            if not isinstance(items, list):
                return []
            return sorted(i["name"] for i in items if i.get("type") == "file")
        full = os.path.join(self.base_dir, dir_path)
        if not os.path.isdir(full):
            return []
        return sorted(n for n in os.listdir(full) if os.path.isfile(os.path.join(full, n)))

    def delete(self, path):
        path = _clean_path(path)
        if self.mode == "github":
            r = self._session.get(self._gh_url(path), headers=self._headers(),
                                  params={"ref": self.branch}, timeout=20)
            if r.status_code == 404:
                return False
            self._raise_for(r, "삭제 준비")
            sha = r.json().get("sha")
            r = self._session.delete(
                self._gh_url(path), headers=self._headers(), timeout=20,
                json={"message": f"delete {path}", "sha": sha, "branch": self.branch},
            )
            self._raise_for(r, "삭제")
            return True
        full = os.path.join(self.base_dir, path)
        if os.path.isfile(full):
            os.remove(full)
            return True
        return False

    def health(self):
        """저장소 연결 점검. (ok, 메시지)"""
        if self.mode == "local":
            try:
                os.makedirs(self.base_dir, exist_ok=True)
                test = os.path.join(self.base_dir, ".write_test")
                with open(test, "w") as f:
                    f.write("ok")
                os.remove(test)
                return True, f"임시 저장소 사용 중: {self.base_dir} (서버 재시작 시 데이터가 사라질 수 있음)"
            except Exception as e:  # noqa
                return False, f"임시 폴더 쓰기 실패: {e}"
        try:
            r = self._session.get(f"{GITHUB_API}/repos/{self.repo}", headers=self._headers(), timeout=15)
        except requests.RequestException as e:
            return False, f"GitHub 연결 실패: {e}"
        if r.status_code == 401:
            return False, "GitHub 토큰이 올바르지 않거나 만료되었습니다."
        if r.status_code == 404:
            return False, f"저장소 {self.repo} 를 찾을 수 없습니다. 이름과 토큰 접근 권한을 확인하세요."
        if not r.ok:
            return False, f"GitHub 오류 {r.status_code}: {r.text[:200]}"
        info = r.json()
        perms = info.get("permissions") or {}
        if perms and not perms.get("push", False):
            return False, "토큰에 쓰기(Contents: Read and write) 권한이 없습니다."
        private = "비공개" if info.get("private") else "공개(⚠️ 비공개 권장)"
        return True, f"GitHub 저장소 연결 정상: {self.repo} [{private}]"

    # ------------------------------------------------------------------ local
    def _local_full(self, path):
        return os.path.join(self.base_dir, path)

    def _local_read(self, path, default):
        full = self._local_full(path)
        if not os.path.isfile(full):
            return copy.deepcopy(default), None
        with open(full, "r", encoding="utf-8") as f:
            text = f.read()
        if not text.strip():
            return copy.deepcopy(default), None
        return json.loads(text), "local"

    def _local_write(self, path, data):
        full = self._local_full(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(full), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, full)
        return "local"

    # ------------------------------------------------------------------ github
    def _gh_url(self, path):
        return f"{GITHUB_API}/repos/{self.repo}/contents/{self.prefix}/{path}"

    def _headers(self, raw=False):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Cache-Control": "no-cache",
        }

    @staticmethod
    def _raise_for(r, what):
        if r.ok:
            return
        if r.status_code == 401:
            raise StoreError("GitHub 토큰이 올바르지 않거나 만료되었습니다.")
        if r.status_code == 403 and "rate limit" in r.text.lower():
            raise StoreError("GitHub API 사용 한도를 초과했습니다. 잠시 후 다시 시도하세요.")
        raise StoreError(f"GitHub {what} 실패 ({r.status_code}): {r.text[:200]}")

    def _gh_read(self, path, default):
        try:
            r = self._session.get(self._gh_url(path), headers=self._headers(),
                                  params={"ref": self.branch, "_": str(time.time())}, timeout=20)
        except requests.RequestException as e:
            raise StoreError(f"GitHub 연결 실패: {e}")
        if r.status_code == 404:
            return copy.deepcopy(default), None
        self._raise_for(r, "읽기")
        meta = r.json()
        if isinstance(meta, list):
            raise StoreError(f"{path} 는 폴더입니다.")
        sha = meta.get("sha")
        content = meta.get("content")
        if meta.get("encoding") == "base64" and content:
            text = base64.b64decode(content).decode("utf-8")
        elif meta.get("size", 0) == 0:
            text = ""
        else:  # 1MB 이상 파일은 raw 로 다시 받기
            r2 = self._session.get(self._gh_url(path), headers=self._headers(raw=True),
                                   params={"ref": self.branch}, timeout=30)
            self._raise_for(r2, "읽기(raw)")
            text = r2.content.decode("utf-8")
        if not text.strip():
            return copy.deepcopy(default), sha
        return json.loads(text), sha

    def _gh_write(self, path, data, sha, message):
        body = {
            "message": message or f"update {path}",
            "content": base64.b64encode(
                json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
            ).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            body["sha"] = sha
        try:
            r = self._session.put(self._gh_url(path), headers=self._headers(), json=body, timeout=30)
        except requests.RequestException as e:
            raise StoreError(f"GitHub 연결 실패: {e}")
        if r.status_code in (200, 201):
            return r.json()["content"]["sha"]
        if r.status_code in (409, 422):
            raise ConflictError(f"{r.status_code}: {r.text[:150]}")
        self._raise_for(r, "저장")
        return None
