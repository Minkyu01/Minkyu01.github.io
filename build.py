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

    @property
    def is_post(self) -> bool:
        return self.group is not None


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


def file_date(path: Path) -> dt.date:
    return dt.datetime.fromtimestamp(path.stat().st_mtime).date()


def ko_date(d: dt.date | None) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일" if d else ""


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

    # 1) 읽기
    def load(self):
        for src in sorted(CONTENT.rglob("*.md")):
            rel = src.relative_to(CONTENT).as_posix()
            if any(part.startswith(("_", ".")) for part in Path(rel).parts):
                continue
            fm, body = split_front_matter(src.read_text(encoding="utf-8"))
            draft = bool(fm.get("draft"))
            if draft and not self.drafts:
                continue
            parts = Path(rel).parts
            group = parts[0] if len(parts) > 1 else None
            stem = src.stem
            is_home = rel == "index.md"
            slug = fm.get("slug") or slugify(stem)
            if is_home:
                url = "/"
            elif group:
                url = f"/{group}/{slug}/"
            else:
                url = f"/{slug}/"
            title = fm.get("title") or (self.cfg["title"] if is_home else stem)
            page = Page(
                src=src, rel=rel, group=group, slug=slug, url=url, title=str(title),
                description=str(fm.get("description") or ""),
                date=to_date(fm.get("date")) or git_date(src, first=True) or file_date(src),
                updated=to_date(fm.get("updated")) or git_date(src, first=False) or file_date(src),
                tags=[str(t) for t in (fm.get("tags") or [])],
                order=fm.get("order"), draft=draft, body_md=body, is_home=is_home,
            )
            self.pages.append(page)
            self.pages_by_rel[rel] = page
        if "index.md" not in self.pages_by_rel:
            home = Page(src=CONTENT / "index.md", rel="index.md", group=None, slug="", url="/",
                        title=self.cfg["title"], description=self.cfg.get("description", ""),
                        body_md="<!-- recent-posts -->", is_home=True, date=dt.date.today(), updated=dt.date.today())
            self.pages.insert(0, home)
            self.pages_by_rel["index.md"] = home

    # 2) 사이드바 순서
    def arrange(self):
        titles = {g["dir"]: g["title"] for g in self.cfg.get("groups", [])}
        order = [g["dir"] for g in self.cfg.get("groups", [])]
        dirs = sorted({p.group for p in self.pages if p.group})
        for d in dirs:
            if d not in order:
                order.append(d)

        def key(p: Page):
            return (p.order is None, p.order if p.order is not None else 0,
                    -(p.date.toordinal() if p.date else 0), p.title)

        self.groups = []
        for d in order:
            members = sorted([p for p in self.pages if p.group == d], key=key)
            if not members:
                continue
            for p in members:
                p.group_title = titles.get(d, d)
            self.groups.append({"dir": d, "title": titles.get(d, d), "pages": members})
        root_pages = sorted([p for p in self.pages if p.group is None and not p.is_home], key=key)
        home = self.pages_by_rel["index.md"]
        self.nav = [home] + root_pages + [p for g in self.groups for p in g["pages"]]
        self.root_pages = root_pages

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

    def recent_posts_html(self) -> str:
        posts = sorted([p for p in self.pages if p.is_post], key=lambda p: (p.date or dt.date.min), reverse=True)
        posts = posts[: int(self.cfg.get("home_recent", 8))]
        items = []
        for p in posts:
            meta = " · ".join(x for x in [ko_date(p.date), p.group_title] if x)
            desc = f'<p class="post-card-desc">{html.escape(p.excerpt)}</p>' if p.excerpt else ""
            items.append(f'<a class="post-card" href="{self.base}{p.url}"><span class="post-card-title">{html.escape(p.title)}</span>'
                         f'{desc}<span class="post-card-meta">{html.escape(meta)}</span></a>')
        return '<div class="post-list">' + "".join(items) + "</div>"

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
        tpl = self.env.get_template(template)
        out_html = tpl.render(
            site=self.cfg, base=self.base, site_url=self.site_url, page=page, groups=self.groups,
            root_pages=self.root_pages, home=self.pages_by_rel["index.md"], prev=prev_p, next=next_p,
            edit_url=edit_url, asset_v=self.asset_v, **extra,
        )
        dest = self.out / page.url.strip("/") / "index.html" if page.url != "/" else self.out / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out_html, encoding="utf-8")
        if page.src.exists():
            (dest.parent / "index.md").write_text(f"# {page.title}\n\n{page.body_md}", encoding="utf-8")

    def copy_static(self):
        assets = self.out / "assets"
        shutil.copytree(THEME / "static", assets, dirs_exist_ok=True)
        for f in CONTENT.rglob("*"):
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
        for p in self.pages:
            self.write_page(p)
        # 태그 페이지
        tags_body, tags_toc = self.tags_html()
        tags_page = Page(src=ROOT / "_tags_", rel="tags", group=None, slug="tags", url="/tags/", title="태그",
                         description="글에 붙은 태그를 모아 봅니다.", body_html=tags_body, toc=tags_toc,
                         date=dt.date.today(), updated=dt.date.today())
        self.write_page(tags_page)
        # 404
        nf = Page(src=ROOT / "_404_", rel="404", group=None, slug="404", url="/404/", title="페이지를 찾을 수 없습니다",
                  description="주소가 바뀌었거나 지워진 글입니다.", body_html=f'<p><a href="{self.base}/">홈으로 돌아가기</a></p>',
                  date=dt.date.today(), updated=dt.date.today())
        tpl = self.env.get_template("page.html")
        (self.out / "404.html").write_text(tpl.render(site=self.cfg, base=self.base, site_url=self.site_url, page=nf, groups=self.groups,
                                                      root_pages=self.root_pages, home=self.pages_by_rel["index.md"], prev=None, next=None,
                                                      edit_url="", asset_v=self.asset_v), encoding="utf-8")
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
    n = b.build()
    print(f"built {n} pages → {b.out}  (base='{b.base}')")


if __name__ == "__main__":
    main()
