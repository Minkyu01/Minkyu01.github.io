# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "markdown-it-py>=3.0",
#   "mdit-py-plugins>=0.4",
#   "linkify-it-py>=2.0",
#   "pygments>=2.17",
#   "jinja2>=3.1",
#   "pyyaml>=6",
# ]
# ///
"""로컬 미리보기 서버. 한 번 켜면 미리보기 두 개가 뜬다.

작업 미리보기 (4900) — 지금 폴더의 파일 그대로 (초안·로컬 전용 글 포함).
- content/ · theme/ · site.yaml · build.py · .gitignore 가 바뀌면 다시 빌드하고 _site 를 캐시 없이 보여 준다.
- 열려 있는 미리보기 창은 저장할 때마다 저절로 새로고침된다. 스크롤 위치는 그대로.
- 다른 글을 고쳐 저장하면 미리보기가 그 글로 따라간다.
- 머리말 오류 등으로 빌드가 멈추면 이전 화면을 그대로 두고, 화면 아래 상자에 이유를 보여 준다.

배포 미리보기 (4901) — main 브랜치에 커밋된 것만, GitHub Actions 와 같은 방법으로 빌드한 모습.
- 초안·로컬 전용 글·main 에 아직 안 합친 것은 빠진다. 주소도 실제 사이트처럼 /tech_blog/ 아래.
- main 이 바뀌면 (커밋·합치기) 다시 빌드한다.

실행:  uv run --no-project dev.py 4900      (배포 미리보기는 그다음 번호)
"""
import html
import http.server
import importlib
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
WATCH = [CONTENT, ROOT / "theme", ROOT / "site.yaml", ROOT / "build.py", ROOT / ".gitignore"]   # .gitignore 는 로컬 전용 목록이라 바뀌면 다시 빌드
START = str(int(time.time()))


class Preview:
    """미리보기 하나. 새 빌드는 <out>.next 에 만든 뒤 한 번에 바꿔 끼운다 (실패해도 이전 화면 유지)."""

    def __init__(self, out: Path, name: str, hint: str):
        self.out, self.name = out, name
        self.next = out.with_name(out.name + ".next")
        self.old = out.with_name(out.name + ".old")
        self.base = ""              # 사이트가 놓이는 하위 경로. 배포 미리보기만 "/tech_blog"
        self.builds = 0
        self.lock = threading.Lock()
        # 미리보기 창이 0.6초마다 읽어 간다. hint 는 빌드가 멈췄을 때 상자 첫 줄
        self.state = {"v": f"{START}-0", "error": "", "url": None, "badge": "", "hint": hint}

    def swap(self):
        if self.old.exists():
            shutil.rmtree(self.old)
        if self.out.exists():
            self.out.rename(self.old)
        self.next.rename(self.out)
        shutil.rmtree(self.old, ignore_errors=True)

    def done(self, url=None, badge=""):
        self.builds += 1
        with self.lock:
            self.state.update(v=f"{START}-{self.builds}", error="", url=url, badge=badge)

    def report(self, msg: str):
        with self.lock:
            self.state["error"] = msg
        print(f"[dev] {self.name} 빌드 멈춤 (이전 화면 유지)\n{msg}", flush=True)


WORK = Preview(ROOT / "_site", "작업 미리보기", "빌드가 멈췄습니다. 고치고 저장하면 이 상자는 저절로 사라집니다.")
MAIN = Preview(ROOT / "_site.main", "배포 미리보기",
               "main 의 빌드가 멈췄습니다. 이대로 올리면 GitHub 에서도 같은 이유로 멈춥니다. 고쳐서 main 에 합치면 이 상자는 사라집니다.")


def snapshot() -> dict:
    snap = {}
    for w in WATCH:
        if w.is_file():
            snap[w] = w.stat().st_mtime
        elif w.is_dir():
            for f in w.rglob("*"):
                if f.is_file():
                    snap[f] = f.stat().st_mtime
    return snap


def changed_files(before: dict, after: dict) -> list:
    """새로 생기거나 바뀐 파일, 가장 최근 것부터."""
    changed = [f for f, t in after.items() if before.get(f) != t]
    return sorted(changed, key=lambda f: after[f], reverse=True)


def url_for(b, path: Path):
    """content/ 의 글 파일 → 그 글의 주소 (폴더 소개면 폴더 주소)."""
    try:
        rel = path.relative_to(CONTENT).as_posix()
    except ValueError:
        return None
    if not rel.endswith(".md"):
        return None
    if rel.endswith("/_index.md"):
        f = b.folders.get(rel.rsplit("/", 1)[0])
        return f.url if f else None
    p = b.pages_by_rel.get(rel)
    return p.url if p else None


def rebuild(changed=()):
    t0 = time.time()
    try:
        importlib.reload(build)
        b = build.Builder(WORK.next, "", "", drafts=True)
        n = b.build()
        WORK.swap()
        url = next((u for u in (url_for(b, f) for f in changed) if u), None)
        WORK.done(url=url)
        print(f"[dev] {n}쪽 빌드 {time.time() - t0:.1f}초" + (f"  → {url}" if url else ""), flush=True)
    except build.BuildError as e:
        WORK.report(str(e))
    except Exception as e:
        WORK.report(f"{type(e).__name__}: {e}\n\n{traceback.format_exc(limit=4)}")


def watcher():
    last = snapshot()
    while True:
        time.sleep(0.5)
        cur = snapshot()
        if cur != last:
            changed = changed_files(last, cur)
            last = cur
            rebuild(changed)


def git(*args, cwd=ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def rebuild_main(sha: str):
    """main 을 임시 폴더에 따로 받아 그 안의 build.py 로 빌드한다 (GitHub Actions 가 하는 일과 같다).
    그래서 이 폴더에서 고치는 중인 파일이나 로컬 전용 파일은 섞이지 않는다."""
    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="tech_blog-main-"))
    try:
        src = tmp / "src"
        r = git("clone", "--quiet", "--shared", "--no-tags", "--single-branch", "--branch", "main", str(ROOT), str(src))
        if r.returncode:
            return MAIN.report(r.stderr.strip())
        shutil.rmtree(MAIN.next, ignore_errors=True)
        r = subprocess.run([sys.executable, str(src / "build.py"), "--out", str(MAIN.next)],
                           cwd=src, capture_output=True, text=True, timeout=300)
        if r.returncode:
            return MAIN.report((r.stderr or r.stdout).strip())
        cfg = yaml.safe_load((src / "site.yaml").read_text(encoding="utf-8")) or {}
        MAIN.base = urlparse((cfg.get("url") or "").rstrip("/")).path.rstrip("/")   # build.py 의 기본 base 와 같은 계산
        MAIN.swap()
        MAIN.done(badge=f"배포 미리보기 · main {sha[:7]}")
        print(f"[dev] 배포 미리보기: main {sha[:7]} 빌드 {time.time() - t0:.1f}초", flush=True)
    except Exception as e:
        MAIN.report(f"{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main_watcher():
    """main 이 가리키는 커밋이 바뀌면 (커밋·합치기) 배포 미리보기를 다시 빌드."""
    last = None
    while True:
        sha = git("rev-parse", "--verify", "--quiet", "refs/heads/main").stdout.strip()
        if sha != last:
            last = sha
            if sha:
                rebuild_main(sha)
            else:
                MAIN.report("main 브랜치가 없습니다.")
        time.sleep(1)


# 미리보기 창에 끼워 넣는 작은 스크립트 (배포 사이트에는 들어가지 않는다)
RELOAD_JS = r"""
(() => {
  const key = "dev-scroll:" + location.pathname;
  let version = null, fails = 0, box = null, tag = null;
  try { history.scrollRestoration = "manual"; } catch (e) {}
  try {                                   // 새로고침 전 스크롤 위치로 돌아가기
    const y = sessionStorage.getItem(key);
    if (y !== null) {
      sessionStorage.removeItem(key);
      const go = () => scrollTo(0, +y);
      go(); addEventListener("load", go);
      if (document.fonts) document.fonts.ready.then(go);
    }
  } catch (e) {}
  const show = (text, color) => {
    if (!box) {
      box = document.createElement("div");
      box.setAttribute("role", "alert");
      box.style.cssText = "position:fixed;left:16px;right:16px;bottom:16px;z-index:9999;max-width:760px;margin:0 auto;" +
        "max-height:45vh;overflow:auto;padding:14px 16px;border-radius:12px;background:#fff;color:#191f28;" +
        "box-shadow:0 0 0 1px rgba(0,27,55,.1),0 16px 32px -8px rgba(0,25,54,.25);" +
        "font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;border-left:4px solid";
      document.body.appendChild(box);
    }
    box.style.borderLeftColor = color;
    box.textContent = text;
  };
  const hide = () => { if (box) { box.remove(); box = null; } };
  const label = (text) => {               // 배포 미리보기 표시 (작업 미리보기에는 없음)
    if (!text) { if (tag) { tag.remove(); tag = null; } return; }
    if (!tag) {
      tag = document.createElement("div");
      tag.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:9998;padding:6px 12px;border-radius:999px;" +
        "background:rgba(25,31,40,.88);color:#fff;font:13px/20px Pretendard,system-ui,sans-serif;pointer-events:none";
      document.body.appendChild(tag);
    }
    tag.textContent = text;
  };
  async function tick() {
    try {
      const s = await (await fetch("/__dev/version", { cache: "no-store" })).json();
      fails = 0;
      if (version !== null && s.v !== version) {
        if (s.url && s.url !== decodeURI(location.pathname)) { location.href = s.url; return; }   // 다른 글을 고쳤으면 그 글로
        try { sessionStorage.setItem(key, String(scrollY)); } catch (e) {}
        location.reload(); return;
      }
      version = s.v;
      label(s.badge);
      if (s.error) show(s.hint + "\n\n" + s.error, "#f04452"); else hide();
    } catch (e) {
      if (++fails === 3) show("미리보기 서버가 꺼졌습니다. VS Code 에서 '블로그 미리보기' 작업을 다시 실행하세요.", "#8b95a1");
    }
    setTimeout(tick, 600);
  }
  tick();
})();
"""
INJECT = b'<script src="/__dev/reload.js"></script>'


class Handler(http.server.SimpleHTTPRequestHandler):
    pv: Preview                     # 이 포트가 보여 줄 미리보기 (serve() 가 정한다)

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(self.pv.out), **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass

    def send_bytes(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, code: int, file: Path):
        html = file.read_bytes()
        i = html.rfind(b"</body>")
        html = html[:i] + INJECT + html[i:] if i >= 0 else html + INJECT
        self.send_bytes(code, html, "text/html; charset=utf-8")

    def redirect(self, to: str):
        self.send_response(301)
        self.send_header("Location", to)
        self.end_headers()

    def not_found(self):
        page = self.pv.out / "404.html"
        if page.is_file():                           # GitHub Pages 처럼 없는 주소는 404 쪽
            return self.send_html(404, page)
        self.send_error(404)

    def do_GET(self):
        pv = self.pv
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/__dev/version":
            with pv.lock:
                body = json.dumps(pv.state, ensure_ascii=False).encode()
            return self.send_bytes(200, body, "application/json; charset=utf-8")
        if path == "/__dev/reload.js":
            return self.send_bytes(200, RELOAD_JS.encode(), "text/javascript; charset=utf-8")
        if not (pv.out / "index.html").exists():     # 첫 빌드부터 멈춘 경우: 이유와 자동 새로고침만 있는 쪽
            with pv.lock:
                msg = pv.state["error"] or "빌드하는 중…"
            page = f"<!doctype html><meta charset=utf-8><title>빌드 멈춤</title><body><pre>{html.escape(msg)}</pre></body>".encode()
            return self.send_bytes(503, page.replace(b"</body>", INJECT + b"</body>"), "text/html; charset=utf-8")
        if pv.base:                                  # 배포 미리보기는 실제 사이트처럼 /tech_blog/ 아래에 있다
            if path in ("/", pv.base):
                return self.redirect(pv.base + "/")
            if not path.startswith(pv.base + "/"):
                return self.not_found()
            self.path = self.path[len(pv.base):]
            path = path[len(pv.base):]
        file = Path(self.translate_path(self.path))
        if file.is_dir():
            if not path.endswith("/"):
                return self.redirect(pv.base + path + "/")
            file = file / "index.html"
        if file.suffix == ".html" and file.is_file():
            return self.send_html(200, file)
        if not file.exists():
            return self.not_found()
        return super().do_GET()


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return                                   # 브라우저가 먼저 끊은 것, 문제 아님
        super().handle_error(request, client_address)


def serve(port: int, pv: Preview) -> Server:
    return Server(("127.0.0.1", port), type("Handler", (Handler,), {"pv": pv}))


def already_running(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4900
    if already_running(port):   # 두 번 실행해도 오류 없이 주소만 알려 준다
        print(f"[dev] 이미 실행 중: http://127.0.0.1:{port}/  (배포 미리보기 http://127.0.0.1:{port + 1}/)", flush=True)
        sys.exit(0)
    rebuild()
    threading.Thread(target=watcher, daemon=True).start()
    work = serve(port, WORK)
    print(f"[dev] http://127.0.0.1:{port}/  작업 미리보기 (초안·로컬 전용 포함, 저장하면 저절로 새로고침)", flush=True)
    try:
        main = serve(port + 1, MAIN)
    except OSError:
        print(f"[dev] {port + 1} 번을 다른 프로그램이 쓰고 있어 배포 미리보기는 건너뜀", flush=True)
    else:
        threading.Thread(target=main_watcher, daemon=True).start()
        threading.Thread(target=main.serve_forever, daemon=True).start()
        print(f"[dev] http://127.0.0.1:{port + 1}/  배포 미리보기 (main 에 커밋된 것만, GitHub 에 올라갈 모습)", flush=True)
    work.serve_forever()
