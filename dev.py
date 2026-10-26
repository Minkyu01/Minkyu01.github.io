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
"""로컬 미리보기 서버.

- content/ · theme/ · site.yaml · build.py 가 바뀌면 다시 빌드하고 _site 를 캐시 없이 보여 준다 (초안·로컬 전용 글 포함).
- 열려 있는 미리보기 창은 저장할 때마다 저절로 새로고침된다. 스크롤 위치는 그대로.
- 다른 글을 고쳐 저장하면 미리보기가 그 글로 따라간다.
- 머리말 오류 등으로 빌드가 멈추면 이전 화면을 그대로 두고, 화면 아래 상자에 이유를 보여 준다.

실행:  uv run --no-project dev.py 4900
"""
import html
import http.server
import importlib
import json
import shutil
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
OUT = ROOT / "_site"
NEXT = ROOT / "_site.next"      # 새 빌드는 여기에 만든 뒤 한 번에 바꿔 끼운다 (실패해도 이전 화면 유지)
OLD = ROOT / "_site.old"
WATCH = [CONTENT, ROOT / "theme", ROOT / "site.yaml", ROOT / "build.py"]

START = str(int(time.time()))
STATE = {"v": f"{START}-0", "error": "", "url": None}   # 미리보기 창이 0.6초마다 읽어 간다
LOCK = threading.Lock()
builds = 0


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


def swap():
    if OLD.exists():
        shutil.rmtree(OLD)
    if OUT.exists():
        OUT.rename(OLD)
    NEXT.rename(OUT)
    shutil.rmtree(OLD, ignore_errors=True)


def report(msg: str):
    with LOCK:
        STATE["error"] = msg
    print(f"[dev] 빌드 멈춤 (이전 화면 유지)\n{msg}", flush=True)


def rebuild(changed=()):
    global builds
    t0 = time.time()
    try:
        importlib.reload(build)
        b = build.Builder(NEXT, "", "", drafts=True)
        n = b.build()
        swap()
        url = next((u for u in (url_for(b, f) for f in changed) if u), None)
        builds += 1
        with LOCK:
            STATE.update(v=f"{START}-{builds}", error="", url=url)
        print(f"[dev] {n}쪽 빌드 {time.time() - t0:.1f}초" + (f"  → {url}" if url else ""), flush=True)
    except build.BuildError as e:
        report(str(e))
    except Exception as e:
        report(f"{type(e).__name__}: {e}\n\n{traceback.format_exc(limit=4)}")


def watcher():
    last = snapshot()
    while True:
        time.sleep(0.5)
        cur = snapshot()
        if cur != last:
            changed = changed_files(last, cur)
            last = cur
            rebuild(changed)


# 미리보기 창에 끼워 넣는 작은 스크립트 (배포 사이트에는 들어가지 않는다)
RELOAD_JS = r"""
(() => {
  const key = "dev-scroll:" + location.pathname;
  let version = null, fails = 0, box = null;
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
      if (s.error) show("빌드가 멈췄습니다. 고치고 저장하면 이 상자는 저절로 사라집니다.\n\n" + s.error, "#f04452"); else hide();
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
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(OUT), **kw)

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

    def do_GET(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/__dev/version":
            with LOCK:
                body = json.dumps(STATE, ensure_ascii=False).encode()
            return self.send_bytes(200, body, "application/json; charset=utf-8")
        if path == "/__dev/reload.js":
            return self.send_bytes(200, RELOAD_JS.encode(), "text/javascript; charset=utf-8")
        if not (OUT / "index.html").exists():        # 첫 빌드부터 멈춘 경우: 이유와 자동 새로고침만 있는 쪽
            with LOCK:
                msg = STATE["error"] or "빌드하는 중…"
            page = f"<!doctype html><meta charset=utf-8><title>빌드 멈춤</title><body><pre>{html.escape(msg)}</pre></body>".encode()
            return self.send_bytes(503, page.replace(b"</body>", INJECT + b"</body>"), "text/html; charset=utf-8")
        file = Path(self.translate_path(self.path))
        if file.is_dir():
            if not path.endswith("/"):
                self.send_response(301)
                self.send_header("Location", path + "/")
                self.end_headers()
                return
            file = file / "index.html"
        if file.suffix == ".html" and file.is_file():
            return self.send_html(200, file)
        if not file.exists() and (OUT / "404.html").is_file():   # GitHub Pages 처럼 없는 주소는 404 쪽
            return self.send_html(404, OUT / "404.html")
        return super().do_GET()


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return                                   # 브라우저가 먼저 끊은 것, 문제 아님
        super().handle_error(request, client_address)


def already_running(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4900
    if already_running(port):   # 두 번 실행해도 오류 없이 주소만 알려 준다
        print(f"[dev] 이미 실행 중: http://127.0.0.1:{port}/", flush=True)
        sys.exit(0)
    rebuild()
    threading.Thread(target=watcher, daemon=True).start()
    print(f"[dev] http://127.0.0.1:{port}/  (초안·로컬 전용 포함, 저장하면 미리보기가 저절로 새로고침)", flush=True)
    Server(("127.0.0.1", port), Handler).serve_forever()
