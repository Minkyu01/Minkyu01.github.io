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
"""로컬 미리보기: 빌드 → _site 를 no-store 로 서빙 → content/theme/site.yaml 이 바뀌면 다시 빌드.

실행:  uv run --no-project dev.py 4900
"""
import http.server
import importlib
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "_site"
WATCH = [ROOT / "content", ROOT / "theme", ROOT / "site.yaml", ROOT / "build.py"]


def snapshot():
    snap = {}
    for w in WATCH:
        if w.is_file():
            snap[w] = w.stat().st_mtime
        elif w.is_dir():
            for f in w.rglob("*"):
                if f.is_file():
                    snap[f] = f.stat().st_mtime
    return snap


def rebuild():
    try:
        importlib.reload(build)
        n = build.Builder(OUT, "", "", drafts=True).build()
        print(f"[dev] built {n} pages", flush=True)
    except Exception:
        traceback.print_exc()


def watcher():
    last = snapshot()
    while True:
        time.sleep(1)
        cur = snapshot()
        if cur != last:
            last = cur
            rebuild()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(OUT), **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def already_running(port: int) -> bool:
    import socket
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
    print(f"[dev] http://127.0.0.1:{port}/  (초안 포함, 저장하면 자동 재빌드)", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
