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
"""content/*.md → _site/ 정적 블로그 생성기 (GitBook 스타일 테마).

실행:  uv run --no-project build.py [--out _site] [--base /tech_blog] [--url https://…] [--drafts]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import posixpath
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.lexers.special import TextLexer
from pygments.util import ClassNotFound

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
THEME = ROOT / "theme"

HINT_KINDS = {"NOTE": "info", "TIP": "success", "IMPORTANT": "info", "WARNING": "warning", "CAUTION": "danger"}
HINT_ICONS = {
    "info": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>',
    "success": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>',
    "warning": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z"/><path d="M12 9v4M12 17h.01"/></svg>',
    "danger": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/></svg>',
}
COPY_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'


# ---------- 모델 ----------
@dataclass
class Page:
    src: Path
    rel: str                     # content/ 기준 상대 경로 (posix)
    group: str | None            # 폴더 이름 (루트면 None)
    slug: str
    url: str                     # "/" 또는 "/group/slug/"
    title: str
    description: str = ""
    date: dt.date | None = None
    updated: dt.date | None = None
    tags: list[str] = field(default_factory=list)
    order: int | None = None
    draft: bool = False
    body_md: str = ""
    body_html: str = ""
    toc: list[dict] = field(default_factory=list)
    text: str = ""               # 검색용 평문
    excerpt: str = ""
    is_home: bool = False
    group_title: str = ""
    has_math: bool = False      # 수식이 있으면 KaTeX 를 불러온다
    has_mermaid: bool = False   # mermaid 블록이 있으면 Mermaid 를 불러온다
    folder: str = ""            # content/ 기준 폴더 ("42/webserv"), 루트면 ""
    series: str | None = None   # 머리말 series: 이름
    series_order: int | None = None
    series_description: str = ""
    series_info: dict | None = None
    kind: str = "post"          # post · home · folder · series · special
    crumbs: list = field(default_factory=list)   # 위쪽 폴더들 [{title, url}]
    place: str = ""             # 가장 가까운 폴더 이름 (목록의 보조 정보)
    meta_line: str = ""         # 폴더·시리즈 페이지 머리의 한 줄 (글 n편 …)
    local_only: bool = False    # .gitignore 에 걸린 글 = 이 컴퓨터에만 있고 GitHub 에는 안 올라감

    is_folder = False

    @property
    def is_post(self) -> bool:
        return self.group is not None and self.kind == "post"


@dataclass
class Folder:
    rel: str                    # content/ 기준 경로 "42/webserv"
    url: str                    # "/42/webserv/"
    title: str
    description: str = ""
    order: int | None = None
    intro_md: str = ""          # _index.md 본문
    src: Path | None = None     # _index.md 경로 (없으면 None)
    parent: "Folder | None" = None
    folders: list = field(default_factory=list)
    pages: list = field(default_factory=list)
    items: list = field(default_factory=list)     # 정렬된 하위 폴더 + 글

    is_folder = True

    def all_pages(self) -> list:
        out = []
        for x in self.items:
            out += x.all_pages() if x.is_folder else [x]
        return out

    def ancestors(self) -> list:
        chain, f = [], self.parent
        while f is not None:
            chain.insert(0, f)
            f = f.parent
        return chain


class BuildError(Exception):
    """글 설정이 잘못돼서 빌드를 멈춰야 할 때 (주소 겹침 등)."""


def dir_url(rel_dir: str) -> str:
    """폴더 경로 → 주소. 폴더 이름마다 slugify ("ft_irc" → "ft-irc")."""
    return "/" + "".join(slugify(part) + "/" for part in rel_dir.split("/") if part)


# ---------- 유틸 ----------
def slugify(s: str) -> str:
    s = unicodedata.normalize("NFC", s).strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s.strip("-") or "section"


def split_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
        if m:
            data = yaml.safe_load(m.group(1)) or {}
            return data, text[m.end():]
    return {}, text


def to_date(v) -> dt.date | None:
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def git_date(path: Path, first: bool) -> dt.date | None:
    args = ["git", "log", "--format=%as", "--follow", "--", str(path)]
    try:
        out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    lines = [l for l in out.stdout.splitlines() if l.strip()]
    if out.returncode != 0 or not lines:
        return None
    return dt.date.fromisoformat(lines[-1] if first else lines[0])


def git_ignored(rels: list[str]) -> set[str]:
    """content/ 기준 경로 중 .gitignore 에 걸린 것. git 이 없거나 저장소가 아니면 빈 집합."""
    if not rels:
        return set()
    try:
        out = subprocess.run(["git", "check-ignore", "--stdin", "-z"], cwd=ROOT, capture_output=True, text=True, timeout=10,
                             input="".join(f"content/{r}\0" for r in rels))
    except Exception:
        return set()
    if out.returncode not in (0, 1):      # 1 = 걸린 것 없음, 128 = 저장소 아님
        return set()
    return {x[len("content/"):] for x in out.stdout.split("\0") if x.startswith("content/")}


def file_date(path: Path) -> dt.date:
    return dt.datetime.fromtimestamp(path.stat().st_mtime).date()


def ko_date(d: dt.date | None) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일" if d else ""


def nav_split(items: list, here: str, limit) -> tuple[list, list]:
    """사이드바 한 목록이 limit 줄을 넘으면 "n개 더 보기" 버튼까지 limit 줄이 되게 앞쪽만 남긴다.
    지금 페이지(또는 그 페이지가 든 폴더)는 늘 보이는 쪽에 둔다. limit 이 0 이면 접지 않는다."""
    limit = int(limit or 0)
    if not limit or len(items) <= limit:
        return items, []
    cut = limit - 1
    for i, x in enumerate(items):
        if x.url == here or (x.is_folder and here.startswith(x.url)):
            cut = max(cut, i + 1)
            break
    if len(items) - cut < 2:    # 하나를 숨기려고 버튼 한 줄을 쓰지는 않는다
        cut = len(items)
    return items[:cut], items[cut:]


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def image_size(path: Path) -> tuple[int, int] | None:
    """PNG·JPEG·GIF·SVG 의 가로세로 픽셀 (라이브러리 없이 머리글만 읽음). 모르면 None."""
    try:
        data = path.read_bytes()[:65536] if path.suffix.lower() != ".svg" else path.read_bytes()
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
        return None
    if path.suffix.lower() == ".svg":
        head = data[:2000].decode("utf-8", "ignore")
        m = re.search(r'<svg[^>]*\bviewBox="[\d.\s-]*?([\d.]+)\s+([\d.]+)"', head)
        w = re.search(r'<svg[^>]*\bwidth="([\d.]+)"', head)
        h = re.search(r'<svg[^>]*\bheight="([\d.]+)"', head)
        if w and h:
            return round(float(w.group(1))), round(float(h.group(1)))
        if m:
            return round(float(m.group(1))), round(float(m.group(2)))
    return None


# ---------- 마크다운 ----------
def make_markdown(ctx: "Builder") -> MarkdownIt:
    md = MarkdownIt("gfm-like", {"html": True, "linkify": True, "typographer": False})
    md.use(footnote_plugin).use(tasklists_plugin)
    md.use(dollarmath_plugin, allow_space=False, allow_digits=False, allow_labels=False)

    def resolve(env: dict, target: str) -> str:
        """상대 경로 링크/이미지를 사이트 루트 기준 경로로 바꾼다."""
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith(("/", "#")):
            return target
        path, frag = (target.split("#", 1) + [""])[:2]
        resolved = posixpath.normpath(posixpath.join(env["src_dir"], path)) if path else env["src_rel"]
        page = ctx.pages_by_rel.get(resolved)
        if page is not None:
            return ctx.base + page.url + (f"#{frag}" if frag else "")
        return ctx.base + "/" + resolved.lstrip("./") + (f"#{frag}" if frag else "")

    def render_fence(self, tokens, idx, options, env):
        token = tokens[idx]
        info = token.info.strip()
        lang = info.split()[0] if info else ""
        if lang == "math":            # ```math 도 $$…$$ 와 같게
            env["has_math"] = True
            return f'<div class="math math-display">{html.escape(token.content.strip())}</div>\n'
        if lang == "mermaid":
            env["has_mermaid"] = True
            return f'<div class="mermaid-block"><pre class="mermaid">{html.escape(token.content.rstrip())}</pre></div>\n'
        title = ""
        m = re.search(r'title="([^"]*)"', info)
        if m:
            title = m.group(1)
        try:
            lexer = get_lexer_by_name(lang) if lang else TextLexer()
        except ClassNotFound:
            lexer = TextLexer()
        out = highlight(token.content, lexer, HtmlFormatter(linespans="L", cssclass="hl"))
        inner = re.search(r"<pre>(.*)</pre>", out, re.S).group(1)
        inner = re.sub(r'^<span></span>', "", inner)
        # Pygments 는 줄마다 <span id="L-n">…\n</span> 로 감싼다 → 줄 블록으로 바꾸고 줄 끝 \n 은 뺀다
        chunks = [c for c in re.split(r'(?=<span id="L-\d+">)', inner) if c.strip()]
        lines = [re.sub(r"\n(?=(?:</span>)*\s*$)", "", re.sub(r'^<span id="L-\d+">', '<span class="line">', c).rstrip())
                 for c in chunks]
        head = ""
        if title:
            head = f'<div class="code-title">{html.escape(title)}</div>'
        copy_btn = f'<button type="button" class="code-copy" aria-label="코드 복사">{COPY_ICON}<span>복사</span></button>'
        return (f'<div class="code-block" data-lang="{html.escape(lang)}">{head}'
                f'<div class="code-body">{copy_btn}<pre class="hl"><code>{"".join(lines)}</code></pre></div></div>\n')

    def render_heading_open(self, tokens, idx, options, env):
        return self.renderToken(tokens, idx, options, env)

    def render_heading_close(self, tokens, idx, options, env):
        open_tok = tokens[idx - 2] if idx >= 2 else None
        hid = open_tok.attrGet("id") if open_tok is not None else None
        anchor = f'<a class="heading-anchor" href="#{hid}" aria-label="이 제목으로 링크">#</a>' if hid else ""
        return anchor + self.renderToken(tokens, idx, options, env)

    def dark_twin(env: dict, target: str) -> str | None:
        """그림 옆에 이름.dark.확장자 파일이 있으면 다크 모드용 주소를 돌려준다."""
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("/"):
            return None
        rel = posixpath.normpath(posixpath.join(env["src_dir"], target.split("#")[0]))
        stem, ext = posixpath.splitext(rel)
        if (CONTENT / f"{stem}.dark{ext}").exists():
            return ctx.base + "/" + f"{stem}.dark{ext}".lstrip("./")
        return None

    def render_image(self, tokens, idx, options, env):
        token = tokens[idx]
        raw = token.attrGet("src") or ""
        src = resolve(env, raw)
        alt = html.escape(self.renderInlineAsText(token.children or [], options, env))
        title = token.attrGet("title") or ""
        cap = f"<figcaption>{html.escape(title)}</figcaption>" if title else ""
        dark = dark_twin(env, raw)
        size = ""
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw) and not raw.startswith("/"):
            wh = image_size(CONTENT / posixpath.normpath(posixpath.join(env["src_dir"], raw.split("#")[0])))
            if wh:   # 자리를 미리 잡아 두어 늦게 뜨는 그림이 글을 밀어내지 않게
                size = f' width="{wh[0]}" height="{wh[1]}"'
        def one(url: str, cls: str = "") -> str:   # 누르면 원본 크기로 열린다
            c = f"figure-link {cls}".strip()
            return (f'<a class="{c}" href="{html.escape(url)}" target="_blank" rel="noopener">'
                    f'<img src="{html.escape(url)}" alt="{alt}"{size} loading="lazy"></a>')
        imgs = one(src, "img-light") + one(dark, "img-dark") if dark else one(src)
        return f'<figure class="figure">{imgs}{cap}</figure>'

    def render_link_open(self, tokens, idx, options, env):
        token = tokens[idx]
        href = token.attrGet("href") or ""
        new = resolve(env, href)
        token.attrSet("href", new)
        if re.match(r"^https?://", new) and not new.startswith(ctx.site_url):
            token.attrSet("target", "_blank")
            token.attrSet("rel", "noopener")
        return self.renderToken(tokens, idx, options, env)

    def render_table_open(self, tokens, idx, options, env):
        return '<div class="table-wrap">' + self.renderToken(tokens, idx, options, env)

    def render_table_close(self, tokens, idx, options, env):
        return self.renderToken(tokens, idx, options, env) + "</div>"

    def render_bq_open(self, tokens, idx, options, env):
        token = tokens[idx]
        kind = token.meta.get("hint")
        if kind:
            return f'<div class="hint hint-{kind}" role="note"><div class="hint-icon">{HINT_ICONS[kind]}</div><div class="hint-body">'
        return self.renderToken(tokens, idx, options, env)

    def render_bq_close(self, tokens, idx, options, env):
        if tokens[idx].meta.get("hint"):
            return "</div></div>\n"
        return self.renderToken(tokens, idx, options, env)

    def render_math_inline(self, tokens, idx, options, env):
        env["has_math"] = True
        return f'<span class="math math-inline">{html.escape(tokens[idx].content)}</span>'

    def render_math_block(self, tokens, idx, options, env):
        env["has_math"] = True
        return f'<div class="math math-display">{html.escape(tokens[idx].content.strip())}</div>\n'

    md.add_render_rule("math_inline", render_math_inline)
    md.add_render_rule("math_inline_double", render_math_block)
    md.add_render_rule("math_block", render_math_block)
    md.add_render_rule("math_block_label", render_math_block)
    md.add_render_rule("fence", render_fence)
    md.add_render_rule("heading_open", render_heading_open)
    md.add_render_rule("heading_close", render_heading_close)
    md.add_render_rule("image", render_image)
    md.add_render_rule("link_open", render_link_open)
    md.add_render_rule("table_open", render_table_open)
    md.add_render_rule("table_close", render_table_close)
    md.add_render_rule("blockquote_open", render_bq_open)
    md.add_render_rule("blockquote_close", render_bq_close)
    return md


def postprocess_tokens(tokens: list[Token]) -> list[dict]:
    """제목 id 부여 + 목차 수집, GitHub 식 경고(> [!NOTE]) 변환, 이미지만 있는 문단 풀기."""
    toc: list[dict] = []
    used: dict[str, int] = {}
    stack: list[Token] = []
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            inline = tokens[i + 1]
            text = "".join(c.content for c in (inline.children or []) if c.type in ("text", "code_inline"))
            base = slugify(text)
            n = used.get(base, 0)
            used[base] = n + 1
            hid = base if n == 0 else f"{base}-{n}"
            tok.attrSet("id", hid)
            level = int(tok.tag[1])
            if level in (2, 3):
                toc.append({"level": level, "text": text, "id": hid})
        elif tok.type == "blockquote_open":
            stack.append(tok)
            para = tokens[i + 1] if i + 1 < len(tokens) else None
            inline = tokens[i + 2] if i + 2 < len(tokens) else None
            if para is not None and para.type == "paragraph_open" and inline is not None and inline.type == "inline":
                m = re.match(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*", inline.content)
                if m and inline.children:
                    kind = HINT_KINDS[m.group(1)]
                    tok.meta["hint"] = kind
                    first = inline.children[0]
                    first.content = first.content[len(m.group(0)):].lstrip() if first.type == "text" else first.content
                    inline.content = inline.content[m.end():]
                    if first.type == "text" and not first.content:
                        inline.children.pop(0)
                        if inline.children and inline.children[0].type in ("softbreak", "hardbreak"):
                            inline.children.pop(0)
                    if not inline.children:          # "[!NOTE]" 만 있는 줄이면 문단 자체를 숨긴다
                        para.hidden = True
                        tokens[i + 3].hidden = True
        elif tok.type == "blockquote_close":
            opener = stack.pop()
            if opener.meta.get("hint"):
                tok.meta["hint"] = opener.meta["hint"]
        elif tok.type == "paragraph_open":
            inline = tokens[i + 1]
            kids = inline.children or []
            if kids and all(k.type == "image" or (k.type == "text" and not k.content.strip()) for k in kids):
                tok.hidden = True
                tokens[i + 2].hidden = True
    return toc


# ---------- 빌더 ----------
class Builder:
    def __init__(self, out: Path, base: str, url: str, drafts: bool):
        self.cfg = yaml.safe_load((ROOT / "site.yaml").read_text(encoding="utf-8"))
        self.out = out
        self.site_url = (url or self.cfg.get("url") or "").rstrip("/")
        if base is None:
            base = urlparse(self.site_url).path if self.site_url else ""
        self.base = base.rstrip("/")
        self.drafts = drafts
        self.pages: list[Page] = []
        self.pages_by_rel: dict[str, Page] = {}
        self.groups: list[dict] = []
        self.md = make_markdown(self)
        self.env = Environment(loader=FileSystemLoader(THEME / "templates"), autoescape=select_autoescape(["html"]))
        self.env.filters["ko_date"] = ko_date
        self.env.filters["slug"] = slugify
        self.env.globals["nav_split"] = nav_split

    # 1) 읽기
    def load(self):
        self.folder_meta: dict[str, dict] = {}
        # .gitignore 에 걸린 파일 = 로컬 전용. 미리보기(--drafts)에서는 "로컬" 표시로 보여 주고,
        # 배포용 빌드에서는 빼서 GitHub 에서 빌드한 결과와 같게 만든다.
        self.local_only = git_ignored([f.relative_to(CONTENT).as_posix() for f in CONTENT.rglob("*") if f.is_file()])
        for src in sorted(CONTENT.rglob("*.md")):
            rel = src.relative_to(CONTENT).as_posix()
            parts = Path(rel).parts
            local = rel in self.local_only
            if local and not self.drafts:
                continue
            try:
                fm, body = split_front_matter(src.read_text(encoding="utf-8"))
            except Exception as e:
                raise BuildError(f"content/{rel}: 머리말(맨 위 --- 사이)을 읽지 못했습니다.\n  {e}") from e
            if any(part.startswith(("_", ".")) for part in parts):
                if parts[-1] == "_index.md" and not any(x.startswith(("_", ".")) for x in parts[:-1]) and len(parts) > 1:
                    self.folder_meta["/".join(parts[:-1])] = {**fm, "body": body, "src": src}   # 폴더 소개·이름·순서
                continue
            try:
                self.load_page(src, rel, parts, fm, body, local)
            except BuildError:
                raise
            except Exception as e:
                raise BuildError(f"content/{rel}: 머리말 값을 쓸 수 없습니다.\n  {type(e).__name__}: {e}") from e
        if "index.md" not in self.pages_by_rel:
            home = Page(src=CONTENT / "index.md", rel="index.md", group=None, slug="", url="/",
                        title=self.cfg["title"], description=self.cfg.get("description", ""),
                        body_md="<!-- recent-posts -->", is_home=True, kind="home",
                        date=dt.date.today(), updated=dt.date.today())
            self.pages.insert(0, home)
            self.pages_by_rel["index.md"] = home

    def load_page(self, src: Path, rel: str, parts: tuple, fm: dict, body: str, local: bool):
        """글 파일 하나 → Page."""
        draft = bool(fm.get("draft"))
        if draft and not self.drafts:
            return
        group = parts[0] if len(parts) > 1 else None
        folder = posixpath.dirname(rel)
        is_home = rel == "index.md"
        num, stem = None, src.stem
        m = re.match(r"^(\d+)[-_. ](.+)$", stem)          # "01-소켓.md" → 순서 1, 주소 "소켓"
        if m:
            num, stem = int(m.group(1)), m.group(2)
        slug = str(fm.get("slug") or slugify(stem))
        url = "/" if is_home else dir_url(folder) + slug + "/"
        title = fm.get("title") or (self.cfg["title"] if is_home else stem)
        order = fm.get("order", num)
        page = Page(
            src=src, rel=rel, group=group, slug=slug, url=url, title=str(title),
            description=str(fm.get("description") or ""),
            date=to_date(fm.get("date")) or git_date(src, first=True) or file_date(src),
            updated=to_date(fm.get("updated")) or git_date(src, first=False) or file_date(src),
            tags=[str(t) for t in (fm.get("tags") or [])],
            order=order, draft=draft, body_md=body, is_home=is_home, local_only=local,
            folder=folder, kind="home" if is_home else "post",
            series=str(fm["series"]) if fm.get("series") else None,
            series_order=fm.get("series_order", order),
            series_description=str(fm.get("series_description") or ""),
        )
        self.pages.append(page)
        self.pages_by_rel[rel] = page

    # 2) 폴더 나무 · 순서 · 시리즈
    @staticmethod
    def item_key(x):
        """order 가 있으면 그 순서. 없으면 폴더 먼저(이름순), 글은 최신순."""
        if x.is_folder:
            return (x.order is None, x.order or 0, 0, 0, x.title)
        return (x.order is None, x.order or 0, 1, -(x.date.toordinal() if x.date else 0), x.title)

    def arrange(self):
        titles = {str(g["dir"]): g["title"] for g in self.cfg.get("groups", [])}
        top_order = [str(g["dir"]) for g in self.cfg.get("groups", [])]
        self.folders: dict[str, Folder] = {}

        def get_folder(rel: str) -> Folder:
            if rel in self.folders:
                return self.folders[rel]
            parent = get_folder(posixpath.dirname(rel)) if "/" in rel else None
            meta = self.folder_meta.get(rel, {})
            name = rel.rsplit("/", 1)[-1]
            title = (titles.get(rel) if parent is None else None) or meta.get("title") or name
            f = Folder(rel=rel, url=dir_url(rel), title=str(title), description=str(meta.get("description") or ""),
                       order=meta.get("order"), intro_md=meta.get("body", ""), src=meta.get("src"), parent=parent)
            self.folders[rel] = f
            if parent is not None:
                parent.folders.append(f)
            return f

        for p in self.pages:
            if p.folder:
                get_folder(p.folder).pages.append(p)
        for f in self.folders.values():
            f.items = sorted(f.folders + f.pages, key=self.item_key)

        tops = [f for f in self.folders.values() if f.parent is None]
        rank = {d: i for i, d in enumerate(top_order)}
        self.tree = sorted(tops, key=lambda f: (rank.get(f.rel, len(rank)), f.title))

        for f in self.folders.values():
            chain = f.ancestors() + [f]
            for p in f.pages:
                p.crumbs = [{"title": a.title, "url": a.url} for a in chain]
                p.place = f.title
                p.group_title = chain[0].title

        # 앞뒤 글 순서 = 홈 → 루트 글 → 사이드바를 위에서 아래로 (폴더 페이지는 빼고)
        home = self.pages_by_rel["index.md"]
        self.root_pages = sorted([p for p in self.pages if not p.folder and not p.is_home], key=self.item_key)
        self.nav = [home] + self.root_pages + [p for f in self.tree for p in f.all_pages()]
        self.groups = [{"dir": f.rel, "title": f.title, "pages": f.all_pages()} for f in self.tree]

        # 시리즈: 이름이 같은 글을 series_order(없으면 order·날짜) 순으로
        self.series: dict[str, dict] = {}
        for p in self.pages:
            if p.series:
                entry = self.series.setdefault(p.series, {"title": p.series, "url": f"/series/{slugify(p.series)}/", "parts": [], "description": ""})
                entry["parts"].append(p)
                entry["description"] = entry["description"] or p.series_description
        for s_ in self.series.values():
            parts = sorted(s_["parts"], key=lambda p: (p.series_order is None, p.series_order or 0, p.date or dt.date.min, p.title))
            s_["parts"] = parts
            for i, p in enumerate(parts):
                p.series_info = {"title": s_["title"], "url": s_["url"], "index": i + 1, "total": len(parts), "parts": parts,
                                 "prev": parts[i - 1] if i else None, "next": parts[i + 1] if i + 1 < len(parts) else None}

    # 3) 렌더
    def render_markdown(self, page: Page):
        env = {"src_dir": posixpath.dirname(page.rel), "src_rel": page.rel}
        tokens = self.md.parse(page.body_md, env)
        page.toc = postprocess_tokens(tokens)
        html_out = self.md.renderer.render(tokens, self.md.options, env)
        page.has_math = bool(env.get("has_math"))
        page.has_mermaid = bool(env.get("has_mermaid"))
        if page.is_home:
            html_out = html_out.replace("<!-- recent-posts -->", self.recent_posts_html())
        page.body_html = html_out
        page.text = strip_tags(html_out)
        page.excerpt = page.description or page.text[:140]

    FOLDER_ICON = ('<svg class="folder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                   'stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>')

    def post_item_html(self, p: Page, number: int | None = None, show_place: bool = True) -> str:
        """홈·폴더·시리즈 목록에서 쓰는 글 한 줄 (제목 · 설명 · 날짜 · 위치)."""
        bits = [ko_date(p.date)]
        if show_place and p.place:
            bits.append(p.place)
        if p.series_info and number is None:
            bits.append(f"{p.series_info['title']} {p.series_info['index']}편")
        if p.local_only:
            bits.append("로컬 전용")
        elif p.draft:
            bits.append("초안")
        meta = " · ".join(b for b in bits if b)
        desc = f'<p class="post-card-desc">{html.escape(p.excerpt)}</p>' if p.excerpt else ""
        num = f'<span class="post-card-num">{number}</span>' if number is not None else ""
        return (f'<a class="post-card{" numbered" if num else ""}" href="{self.base}{p.url}">{num}<span class="post-card-body">'
                f'<span class="post-card-title">{html.escape(p.title)}</span>{desc}'
                f'<span class="post-card-meta">{html.escape(meta)}</span></span></a>')

    def recent_posts_html(self) -> str:
        posts = sorted([p for p in self.pages if p.is_post], key=lambda p: (p.date or dt.date.min), reverse=True)
        posts = posts[: int(self.cfg.get("home_recent", 8))]
        return '<div class="post-list">' + "".join(self.post_item_html(p) for p in posts) + "</div>"

    def folder_card_html(self, f: Folder) -> str:
        pages = f.all_pages()
        latest = max((p.date for p in pages if p.date), default=None)
        meta = " · ".join(x for x in [f"글 {len(pages)}편", f"최근 {ko_date(latest)}" if latest else ""] if x)
        desc = f'<span class="folder-card-desc">{html.escape(f.description)}</span>' if f.description else ""
        return (f'<a class="folder-card" href="{self.base}{f.url}"><span class="folder-card-title">{self.FOLDER_ICON}'
                f'{html.escape(f.title)}</span>{desc}<span class="folder-card-meta">{html.escape(meta)}</span></a>')

    @staticmethod
    def section_heading(text: str, hid: str) -> str:
        return f'<h2 id="{hid}">{html.escape(text)}<a class="heading-anchor" href="#{hid}" aria-label="이 제목으로 링크">#</a></h2>'

    def make_folder_page(self, f: Folder) -> Page:
        src = f.src or (ROOT / "_folder_")
        rel = f"{f.rel}/_index.md"
        pg = Page(src=src, rel=rel, group=None, slug=f.url.strip("/").rsplit("/", 1)[-1], url=f.url, title=f.title,
                  description=f.description, kind="folder", body_md=f.intro_md, folder=f.rel,
                  crumbs=[{"title": a.title, "url": a.url} for a in f.ancestors()],
                  date=dt.date.today(), updated=None)
        pages = f.all_pages()
        pg.meta_line = f"글 {len(pages)}편" + (f" · 폴더 {len(f.folders)}개" if f.folders else "")
        return pg

    def folder_listing(self, f: Folder, pg: Page) -> None:
        """폴더 소개(있으면) 아래에 하위 폴더 카드와 글 목록을 붙인다. 사이드바에서 먼저 오는 쪽을 먼저."""
        subs = [x for x in f.items if x.is_folder]
        posts = [x for x in f.items if not x.is_folder]
        blocks = []
        if subs:
            blocks.append(("폴더", '<div class="folder-grid">' + "".join(self.folder_card_html(x) for x in subs) + "</div>"))
        if posts:
            blocks.append(("글 목록", '<div class="post-list">' + "".join(self.post_item_html(x, show_place=False) for x in posts) + "</div>"))
        if len(blocks) == 2 and not f.items[0].is_folder:   # 글이 먼저 오는 폴더는 글 목록을 위로
            blocks.reverse()
        for title, body in blocks:
            hid = slugify(title)
            pg.body_html += self.section_heading(title, hid) + body
            pg.toc.append({"level": 2, "text": title, "id": hid})

    def make_series_pages(self) -> list[Page]:
        out = []
        if not self.series:
            return out
        cards = []
        for s_ in sorted(self.series.values(), key=lambda x: -max((p.date or dt.date.min).toordinal() for p in x["parts"])):
            parts = s_["parts"]
            latest = max((p.date for p in parts if p.date), default=None)
            items = "".join(self.post_item_html(p, number=i + 1) for i, p in enumerate(parts))
            pg = Page(src=ROOT / "_series_", rel=f"series/{slugify(s_['title'])}", group=None, slug=slugify(s_["title"]),
                      url=s_["url"], title=s_["title"], kind="series",
                      description=s_["description"],
                      crumbs=[{"title": "시리즈", "url": "/series/"}], date=dt.date.today(), updated=None)
            pg.meta_line = f"시리즈 · {len(parts)}편" + (f" · 최근 {ko_date(latest)}" if latest else "")
            pg.body_html = '<div class="post-list">' + items + "</div>"
            out.append(pg)
            first = parts[0]
            desc = s_["description"] or f"1편 · {first.title}"
            cards.append(f'<a class="folder-card" href="{self.base}{s_["url"]}"><span class="folder-card-title">{html.escape(s_["title"])}</span>'
                         f'<span class="folder-card-desc">{html.escape(desc)}</span>'
                         f'<span class="folder-card-meta">{len(parts)}편{" · 최근 " + ko_date(latest) if latest else ""}</span></a>')
        index = Page(src=ROOT / "_series_", rel="series", group=None, slug="series", url="/series/", title="시리즈",
                     description="여러 편으로 이어지는 글을 묶어 봅니다.", kind="series",
                     body_html='<div class="folder-grid">' + "".join(cards) + "</div>",
                     date=dt.date.today(), updated=None)
        index.meta_line = f"시리즈 {len(self.series)}개"
        return [index] + out

    def tags_html(self) -> tuple[str, list[dict]]:
        tags: dict[str, list[Page]] = {}
        for p in self.pages:
            for t in p.tags:
                tags.setdefault(t, []).append(p)
        toc = []
        out = []
        for t in sorted(tags, key=lambda s: (-len(tags[s]), s)):
            tid = slugify(t)
            toc.append({"level": 2, "text": f"{t} ({len(tags[t])})", "id": tid})
            lis = "".join(f'<li><a href="{self.base}{p.url}">{html.escape(p.title)}</a> <span class="muted">{ko_date(p.date)}</span></li>'
                          for p in sorted(tags[t], key=lambda p: p.date or dt.date.min, reverse=True))
            out.append(f'<h2 id="{tid}">{html.escape(t)} <span class="muted">{len(tags[t])}</span><a class="heading-anchor" href="#{tid}">#</a></h2><ul>{lis}</ul>')
        return "".join(out) or "<p>아직 태그가 없습니다.</p>", toc

    def write_page(self, page: Page, template="page.html", **extra):
        prev_p = next_p = None
        if page in self.nav:
            i = self.nav.index(page)
            prev_p = self.nav[i - 1] if i > 0 else None
            next_p = self.nav[i + 1] if i + 1 < len(self.nav) else None
        edit_url = ""
        repo = (self.cfg.get("repo") or "").rstrip("/")
        if repo and page.src.exists():
            edit_url = f"{repo}/edit/{self.cfg.get('edit_branch', 'main')}/content/{page.rel}"
        out_html = self.render_tpl(page, prev_p, next_p, edit_url, template, **extra)
        dest = self.out / page.url.strip("/") / "index.html" if page.url != "/" else self.out / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out_html, encoding="utf-8")
        if page.src.exists():
            (dest.parent / "index.md").write_text(f"# {page.title}\n\n{page.body_md}", encoding="utf-8")

    def render_tpl(self, page: Page, prev_p=None, next_p=None, edit_url="", template="page.html", **extra) -> str:
        return self.env.get_template(template).render(
            site=self.cfg, base=self.base, site_url=self.site_url, page=page, groups=self.groups, tree=self.tree,
            root_pages=self.root_pages, home=self.pages_by_rel["index.md"], prev=prev_p, next=next_p,
            edit_url=edit_url, asset_v=self.asset_v, has_series=bool(self.series), **extra,
        )

    def check_urls(self, pages: list[Page]) -> None:
        """같은 주소에 두 페이지가 나오면 하나가 조용히 사라지므로 빌드를 멈춘다."""
        seen: dict[str, Page] = {}
        for p in pages:
            if p.url in seen:
                a, b = seen[p.url], p
                raise BuildError(f"주소가 겹칩니다: {p.url}\n  - {a.rel} ({a.kind})\n  - {b.rel} ({b.kind})\n"
                                 "  한쪽 머리말에 slug: 를 적어 주소를 바꾸세요.")
            seen[p.url] = p

    def copy_static(self):
        assets = self.out / "assets"
        shutil.copytree(THEME / "static", assets, dirs_exist_ok=True)
        for f in CONTENT.rglob("*"):
            rel_f = f.relative_to(CONTENT).as_posix()
            if not self.drafts and rel_f in self.local_only:
                continue
            if f.is_file() and f.suffix.lower() != ".md" and not any(p.startswith((".", "_")) for p in f.relative_to(CONTENT).parts):
                dest = self.out / f.relative_to(CONTENT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)

    def write_extras(self):
        posts = sorted([p for p in self.pages if p.is_post], key=lambda p: p.date or dt.date.min, reverse=True)
        # 검색 색인
        index = []
        for p in self.pages:
            sections = []
            body = re.sub(r"<button.*?</button>", "", p.body_html, flags=re.S)   # 복사 버튼 글자 제외
            body = re.sub(r'<div class="mermaid-block">.*?</div>', "", body, flags=re.S)   # 도표 원문 제외
            parts = re.split(r"(?=<h[23] id=)", body)
            for part in parts:
                m = re.match(r'<h([23]) id="([^"]+)">(.*?)<a class="heading-anchor"[^>]*>#</a></h[23]>', part, re.S)
                heading = strip_tags(m.group(3)) if m else ""
                hid = m.group(2) if m else ""
                text = strip_tags(part[m.end():] if m else part)
                if text or heading:
                    sections.append({"h": heading, "id": hid, "t": text[:2000]})
            index.append({"title": p.title, "url": self.base + p.url, "group": p.group_title, "sections": sections})
        (self.out / "search-index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        # RSS
        items = []
        for p in posts[:30]:
            link = self.site_url + p.url
            pub = dt.datetime.combine(p.date or dt.date.today(), dt.time()).strftime("%a, %d %b %Y 00:00:00 +0900")
            items.append(f"<item><title>{xml_escape(p.title)}</title><link>{link}</link><guid>{link}</guid><pubDate>{pub}</pubDate>"
                         f"<description>{xml_escape(p.excerpt)}</description><content:encoded><![CDATA[{p.body_html}]]></content:encoded></item>")
        rss = (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">'
               f'<channel><title>{xml_escape(self.cfg["title"])}</title><link>{self.site_url}/</link><description>{xml_escape(self.cfg.get("description", ""))}</description>'
               f'<language>{self.cfg.get("lang", "ko")}</language><atom:link href="{self.site_url}/feed.xml" rel="self" type="application/rss+xml"/>{"".join(items)}</channel></rss>')
        (self.out / "feed.xml").write_text(rss, encoding="utf-8")
        # sitemap · robots · llms.txt
        urls = "".join(f"<url><loc>{self.site_url}{p.url}</loc><lastmod>{p.updated}</lastmod></url>" for p in self.pages)
        urls += "".join(f"<url><loc>{self.site_url}{f.url}</loc></url>" for f in self.folders.values())
        (self.out / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', encoding="utf-8")
        (self.out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {self.site_url}/sitemap.xml\n", encoding="utf-8")
        lines = [f"# {self.cfg['title']}", "", f"> {self.cfg.get('description', '')}", ""]
        for g in self.groups:
            lines.append(f"## {g['title']}")
            lines += [f"- [{p.title}]({self.site_url}{p.url}index.md): {p.excerpt[:100]}" for p in g["pages"]]
            lines.append("")
        (self.out / "llms.txt").write_text("\n".join(lines), encoding="utf-8")
        (self.out / ".nojekyll").write_text("", encoding="utf-8")

    def build(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        css = (THEME / "static" / "style.css").read_bytes() + (THEME / "static" / "app.js").read_bytes()
        self.asset_v = hashlib.sha1(css).hexdigest()[:8]
        self.load()
        self.arrange()
        for p in self.pages:
            if not p.is_home:
                self.render_markdown(p)
        self.render_markdown(self.pages_by_rel["index.md"])   # 홈은 다른 글의 요약이 필요하니 마지막에
        folder_pages = []
        for f in self.folders.values():
            pg = self.make_folder_page(f)
            self.render_markdown(pg)          # _index.md 본문(소개)
            self.folder_listing(f, pg)
            folder_pages.append(pg)
        series_pages = self.make_series_pages()
        specials = [Page(src=ROOT / "_tags_", rel="tags", group=None, slug="tags", url="/tags/", title="태그", kind="special")]
        self.check_urls(self.pages + folder_pages + series_pages + specials)
        for p in self.pages:
            self.write_page(p)
        for p in folder_pages + series_pages:
            self.write_page(p)
        # 태그 페이지
        tags_body, tags_toc = self.tags_html()
        tags_page = Page(src=ROOT / "_tags_", rel="tags", group=None, slug="tags", url="/tags/", title="태그",
                         description="글에 붙은 태그를 모아 봅니다.", body_html=tags_body, toc=tags_toc, kind="special",
                         date=dt.date.today(), updated=dt.date.today())
        self.write_page(tags_page)
        # 404
        nf = Page(src=ROOT / "_404_", rel="404", group=None, slug="404", url="/404/", title="페이지를 찾을 수 없습니다",
                  description="주소가 바뀌었거나 지워진 글입니다.", body_html=f'<p><a href="{self.base}/">홈으로 돌아가기</a></p>',
                  date=dt.date.today(), updated=dt.date.today())
        nf.kind = "special"
        (self.out / "404.html").write_text(self.render_tpl(nf), encoding="utf-8")
        self.copy_static()
        self.write_extras()
        return len(self.pages)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "_site"))
    ap.add_argument("--base", default=None, help="하위 경로 배포용 접두어 (예: /tech_blog). 기본값은 site.yaml 의 url 경로")
    ap.add_argument("--url", default=None, help="배포 주소 전체 (RSS·sitemap 용). 기본값은 site.yaml 의 url")
    ap.add_argument("--drafts", action="store_true", help="draft: true 글도 포함")
    args = ap.parse_args(argv)
    b = Builder(Path(args.out), args.base, args.url, args.drafts)
    try:
        n = b.build()
    except BuildError as e:
        print(f"빌드 멈춤: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"built {n} pages → {b.out}  (base='{b.base}')")


if __name__ == "__main__":
    main()
