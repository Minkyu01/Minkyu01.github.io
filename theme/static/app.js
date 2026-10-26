// 테마 전환 · 사이드바 시트 · 목차 팝오버/스크롤 스파이 · 검색 · 복사 버튼
(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const base = document.body.dataset.base || "";

  // ---- 테마: 시스템 → 라이트 → 다크 순환 ----
  const themeBtn = $("#theme-btn");
  let lastDark = document.documentElement.classList.contains("dark");
  const names = { system: "시스템", light: "라이트", dark: "다크" };
  function applyTheme(mode) {
    const dark = mode === "dark" || (mode === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.classList.toggle("light", !dark);
    document.documentElement.dataset.theme = mode;
    if (themeBtn) themeBtn.title = "테마: " + names[mode];
    if (dark !== lastDark) { lastDark = dark; document.dispatchEvent(new CustomEvent("themechange", { detail: { dark } })); }
  }
  if (themeBtn) {
    applyTheme(document.documentElement.dataset.theme || "system");
    themeBtn.addEventListener("click", () => {
      const cur = document.documentElement.dataset.theme || "system";
      const next = cur === "system" ? "light" : cur === "light" ? "dark" : "system";
      try { next === "system" ? localStorage.removeItem("theme") : localStorage.setItem("theme", next); } catch (e) {}
      applyTheme(next);
    });
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if ((document.documentElement.dataset.theme || "system") === "system") applyTheme("system");
    });
  }

  // ---- 사이드바 시트 (모바일) ----
  const sidebar = $("#sidebar"), backdrop = $("#sidebar-backdrop"), menuBtn = $("#menu-btn");
  function setSidebar(open) {
    sidebar.classList.toggle("open", open);
    backdrop.classList.toggle("open", open);
    menuBtn.setAttribute("aria-expanded", String(open));
    document.body.style.overflow = open ? "hidden" : "";
  }
  if (menuBtn) {
    menuBtn.addEventListener("click", () => setSidebar(!sidebar.classList.contains("open")));
    backdrop.addEventListener("click", () => setSidebar(false));
  }
  // ---- 폴더·그룹 접기와 긴 목록의 "더 보기" (펼친 것은 이 브라우저에 기억, 되살리기는 page.html 에서) ----
  const remember = (key, k, open) => {
    let keep = [];
    try { keep = JSON.parse(localStorage.getItem(key) || "[]"); } catch (e) { keep = []; }
    keep = keep.filter((x) => x !== k);
    if (open) keep.push(k);
    try { localStorage.setItem(key, JSON.stringify(keep)); } catch (e) {}
  };
  const toggleBox = (box, btn, key) => {
    const open = !box.classList.contains("open");
    box.classList.toggle("open", open);
    btn.setAttribute("aria-expanded", String(open));
    remember(key, box.dataset.folder, open);
  };
  $$(".nav-toggle").forEach((b) => b.addEventListener("click", (e) => {
    e.preventDefault();
    toggleBox(b.closest(".nav-folder"), b, "nav-open");
  }));
  $$(".nav-more").forEach((b) => b.addEventListener("click", () => toggleBox(b.closest(".nav-overflow"), b, "nav-more")));

  // ---- 시리즈 상자: 펼치거나 접은 상태를 기억해서 다음 글에서도 그대로 ----
  const fold = $(".series-fold");
  if (fold) fold.addEventListener("toggle", () => {
    try { localStorage.setItem("series-open", fold.open ? "1" : "0"); } catch (e) {}
  });

  // 현재 글이 보이도록 사이드바 스크롤
  // 현재 글이 사이드바 가운데 오게: 사이드바 목록만 움직이고 페이지는 그대로 (scrollIntoView 는 페이지까지 내려 버림)
  const active = $(".sidebar .nav-link.active, .sidebar .nav-folder-row.active, .sidebar .nav-group-title.active");
  const navList = $(".sidebar-nav");
  if (active && navList) {
    const a = active.getBoundingClientRect(), n = navList.getBoundingClientRect();
    navList.scrollTop += (a.top - n.top) - (navList.clientHeight - a.height) / 2;
  }

  // ---- 목차 ----
  const toc = $("#toc"), tocBtn = $("#toc-btn");
  if (tocBtn) {
    tocBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = !toc.classList.contains("open");
      toc.classList.toggle("open", open);
      tocBtn.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (e) => {
      if (toc.classList.contains("open") && !toc.contains(e.target)) { toc.classList.remove("open"); tocBtn.setAttribute("aria-expanded", "false"); }
    });
  }
  const tocLinks = $$(".toc-list a");
  if (tocLinks.length) {
    const byId = new Map(tocLinks.map((a) => [decodeURIComponent(a.getAttribute("href").slice(1)), a]));
    const headings = [...byId.keys()].map((id) => document.getElementById(id)).filter(Boolean);
    let current = null;
    function update() {
      const line = 64 + 32;
      let pick = headings[0];
      for (const h of headings) { if (h.getBoundingClientRect().top <= line + 8) pick = h; else break; }
      const scrollable = document.documentElement.scrollHeight > innerHeight + 8;
      if (scrollable && scrollY > 0 && innerHeight + scrollY >= document.documentElement.scrollHeight - 4) pick = headings[headings.length - 1];   // 끝까지 내리면 마지막 제목
      if (pick && pick !== current) {
        current = pick;
        tocLinks.forEach((a) => a.classList.remove("active"));
        byId.get(pick.id)?.classList.add("active");
      }
    }
    update();
    addEventListener("scroll", update, { passive: true });
  }

  // ---- 복사 버튼 ----
  function flash(btn, label) {
    const span = btn.querySelector("span"); const old = span ? span.textContent : "";
    btn.classList.add("done"); if (span) span.textContent = label;
    setTimeout(() => { btn.classList.remove("done"); if (span) span.textContent = old; }, 1600);
  }
  $$(".code-copy").forEach((btn) => btn.addEventListener("click", async () => {
    const pre = btn.parentElement.querySelector("pre");
    const text = [...pre.querySelectorAll(".line")].map((l) => l.textContent).join("\n");
    try { await navigator.clipboard.writeText(text); flash(btn, "복사됨"); } catch (e) {}
  }));

  // ---- 수식 (KaTeX) ----
  if (window.katex) {
    $$(".math").forEach((el) => {
      const display = el.classList.contains("math-display");
      try { katex.render(el.textContent, el, { displayMode: display, throwOnError: false, output: "htmlAndMathml" }); }
      catch (e) { el.classList.add("math-error"); }
    });
  }

  // ---- 도표 (Mermaid) — TDS 색, 테마를 바꾸면 다시 그린다 ----
  if (window.mermaid) {
    const blocks = $$("pre.mermaid");
    blocks.forEach((el) => { el.dataset.src = el.textContent; });
    document.documentElement.classList.add("js-mermaid");
    const FONT = '"Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif';
    const LIGHT = {
      background: "#f9fafb", fontFamily: FONT, fontSize: "15px", textColor: "#333d4b", titleColor: "#191f28",
      primaryColor: "#ffffff", primaryBorderColor: "#d1d6db", primaryTextColor: "#191f28",
      secondaryColor: "#e8f3ff", secondaryBorderColor: "#90c2ff", secondaryTextColor: "#191f28",
      tertiaryColor: "#f2f4f6", tertiaryBorderColor: "#d1d6db", tertiaryTextColor: "#191f28",
      mainBkg: "#ffffff", nodeBorder: "#d1d6db", lineColor: "#8b95a1", edgeLabelBackground: "#f9fafb",
      clusterBkg: "#f2f4f6", clusterBorder: "#e5e8eb",
      actorBkg: "#ffffff", actorBorder: "#d1d6db", actorTextColor: "#191f28", actorLineColor: "#b0b8c1",
      signalColor: "#6b7684", signalTextColor: "#191f28", sequenceNumberColor: "#ffffff",
      labelBoxBkgColor: "#f2f4f6", labelBoxBorderColor: "#d1d6db", labelTextColor: "#191f28", loopTextColor: "#4e5968",
      noteBkgColor: "#fff9e7", noteBorderColor: "#ffdd78", noteTextColor: "#333d4b",
      activationBkgColor: "#e8f3ff", activationBorderColor: "#90c2ff",
    };
    const DARK = {
      background: "#202027", fontFamily: FONT, fontSize: "15px", textColor: "#e4e4e5", titleColor: "#ffffff",
      primaryColor: "#2c2c35", primaryBorderColor: "#4d4d59", primaryTextColor: "#ffffff",
      secondaryColor: "#1f2a3d", secondaryBorderColor: "#2c5aa0", secondaryTextColor: "#ffffff",
      tertiaryColor: "#2c2c35", tertiaryBorderColor: "#4d4d59", tertiaryTextColor: "#ffffff",
      mainBkg: "#2c2c35", nodeBorder: "#4d4d59", lineColor: "#7e7e87", edgeLabelBackground: "#202027",
      clusterBkg: "#17171c", clusterBorder: "#3c3c47",
      actorBkg: "#2c2c35", actorBorder: "#4d4d59", actorTextColor: "#ffffff", actorLineColor: "#62626d",
      signalColor: "#9e9ea4", signalTextColor: "#ffffff", sequenceNumberColor: "#17171c",
      labelBoxBkgColor: "#2c2c35", labelBoxBorderColor: "#4d4d59", labelTextColor: "#ffffff", loopTextColor: "#c3c3c6",
      noteBkgColor: "#3a3322", noteBorderColor: "#7a6630", noteTextColor: "#e4e4e5",
      activationBkgColor: "#1f2a3d", activationBorderColor: "#2c5aa0",
    };
    let drawing = Promise.resolve();
    const draw = () => (drawing = drawing.then(async () => {
      const dark = document.documentElement.classList.contains("dark");
      mermaid.initialize({
        startOnLoad: false, securityLevel: "strict", theme: "base", darkMode: dark,
        themeVariables: dark ? DARK : LIGHT, fontFamily: FONT, fontSize: 15,   // 순서도는 이 값이 sequence 설정보다 우선
        deterministicIds: true, deterministicIDSeed: "tech-blog",   // 시계 대신 순번으로 id → 여러 도표가 한 칸에 겹쳐 그려지지 않음
        sequence: { actorFontSize: 15, messageFontSize: 15, noteFontSize: 13, mirrorActors: false },
        // Mermaid 12 기본값(elk 배치, 상자 최소 폭 120px)은 본문 폭에 비해 너무 넓다 → dagre + 촘촘한 간격
        layout: "dagre", flowchart: { minNodeWidth: 0, wrappingWidth: 200, padding: 12, nodeSpacing: 30, rankSpacing: 36, curve: "basis" },   // 120px 에서 줄바꿈하면 한글 낱말이 갈라짐
      });
      blocks.forEach((el) => { el.removeAttribute("data-processed"); el.textContent = el.dataset.src; });
      try { await mermaid.run({ nodes: blocks }); } catch (e) { console.error("mermaid", e); }
      // 칸보다 넓은 도표는 원래 크기의 80% 까지만 줄이고, 그보다 넓으면 옆으로 밀어 보게 한다
      blocks.forEach((el) => {
        const svg = el.querySelector("svg");
        const natural = svg && parseFloat(svg.style.maxWidth);
        if (natural) svg.style.minWidth = Math.round(natural * 0.8) + "px";
      });
    }));
    (document.fonts ? document.fonts.ready : Promise.resolve()).then(draw);   // 글꼴이 뜬 뒤에 재야 글상자 크기가 맞는다
    document.addEventListener("themechange", draw);
  }

  // ---- 검색 ----
  const search = $("#search"), input = $("#search-input"), panel = $("#search-panel"), results = $("#search-results"),
        clearBtn = $(".search-clear"), searchBtn = $("#search-btn");
  if (!input) return;
  let index = null, hits = [], selected = -1, timer = null;
  const PAGE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>';
  const SEC_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/></svg>';
  async function loadIndex() {
    if (index) return index;
    try { index = await (await fetch(base + "/search-index.json")).json(); } catch (e) { index = []; }
    return index;
  }
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function mark(text, terms) {
    let out = esc(text);
    for (const t of terms) out = out.replace(new RegExp(esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), (m) => "<mark>" + m + "</mark>");
    return out;
  }
  function snippet(text, terms) {
    const low = text.toLowerCase();
    let pos = -1;
    for (const t of terms) { const i = low.indexOf(t.toLowerCase()); if (i >= 0 && (pos < 0 || i < pos)) pos = i; }
    const start = Math.max(0, pos - 40);
    return (start > 0 ? "…" : "") + text.slice(start, start + 140) + (start + 140 < text.length ? "…" : "");
  }
  function run(q) {
    const terms = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    hits = []; selected = -1;
    if (!terms.length) { panel.hidden = true; return; }
    for (const p of index) {
      const title = p.title.toLowerCase();
      const titleScore = terms.every((t) => title.includes(t)) ? 10 : 0;
      if (titleScore) hits.push({ score: titleScore + 1, url: p.url, title: p.title, crumb: p.group, text: p.sections[0]?.t || "", icon: PAGE_ICON });
      for (const s of p.sections) {
        const h = s.h.toLowerCase(), t = s.t.toLowerCase();
        if (!terms.every((x) => h.includes(x) || t.includes(x))) continue;
        const score = (terms.every((x) => h.includes(x)) ? 5 : 1) + titleScore / 10;
        hits.push({ score, url: p.url + (s.id ? "#" + s.id : ""), title: s.h || p.title, crumb: s.h ? p.title : p.group, text: s.t, icon: s.h ? SEC_ICON : PAGE_ICON });
      }
    }
    hits.sort((a, b) => b.score - a.score);
    hits = hits.slice(0, 20);
    panel.hidden = false;
    if (!hits.length) { results.innerHTML = `<div class="search-empty">"${esc(q)}" 에 대한 결과가 없습니다.</div>`; return; }
    results.innerHTML = hits.map((h, i) => `<a class="search-hit" role="option" data-i="${i}" href="${h.url}">${h.icon}<span><span class="search-hit-title">${mark(h.title, terms)}</span>${h.crumb ? `<span class="search-hit-crumb">${esc(h.crumb)}</span>` : ""}<span class="search-hit-snippet">${mark(snippet(h.text, terms), terms)}</span></span></a>`).join("");
    select(0);
  }
  function select(i) {
    selected = i;
    $$(".search-hit", results).forEach((el, j) => el.classList.toggle("selected", j === i));
    const el = $(`.search-hit[data-i="${i}"]`, results); if (el) el.scrollIntoView({ block: "nearest" });
  }
  function close() { panel.hidden = true; search.classList.remove("open"); }
  input.addEventListener("input", async () => {
    clearBtn.hidden = !input.value;
    await loadIndex();
    clearTimeout(timer); timer = setTimeout(() => run(input.value), 80);
  });
  input.addEventListener("focus", async () => { await loadIndex(); if (input.value) run(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" && hits.length) { e.preventDefault(); select(Math.min(hits.length - 1, selected + 1)); }
    else if (e.key === "ArrowUp" && hits.length) { e.preventDefault(); select(Math.max(0, selected - 1)); }
    else if (e.key === "Enter" && hits[selected]) { location.href = hits[selected].url; }
    else if (e.key === "Escape") { input.value = ""; clearBtn.hidden = true; close(); input.blur(); }
  });
  clearBtn.addEventListener("click", () => { input.value = ""; clearBtn.hidden = true; panel.hidden = true; input.focus(); });
  document.addEventListener("click", (e) => { if (!search.contains(e.target) && e.target !== searchBtn) close(); });
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); search.classList.add("open"); input.focus(); input.select(); }
  });
  if (searchBtn) searchBtn.addEventListener("click", () => { search.classList.add("open"); input.focus(); });
})();
