(() => {
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const M = D.meta, S = M.summary;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = n => (n == null ? "-" : Number(n).toLocaleString("en-US"));
const pct = (x, d = 0) => (x == null ? "-" : (x * 100).toFixed(d) + "%");
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const root = document.documentElement;
const PAL = ["#4477aa", "#2a9d8f", "#8a63d2", "#c9a227", "#d1558f", "#29a9c9", "#7f9a3a", "#a0715a", "#6c7a96", "#55b05d"];
const authColor = i => (i == null ? css("--cold") : i < PAL.length ? PAL[i] : "#8e8a99");
const authName = i => (i == null ? "-" : D.authors[i] ? D.authors[i].n : "?");

/* ---------- colour ---------- */
let RAMP = [];
function readRamp() {
  RAMP = ["--h0", "--h1", "--h2", "--h3", "--h4"].map(v => {
    const c = css(v).replace("#", "");
    const x = c.length === 3 ? c.split("").map(q => q + q).join("") : c;
    return [parseInt(x.slice(0, 2), 16), parseInt(x.slice(2, 4), 16), parseInt(x.slice(4, 6), 16)];
  });
}
function heat(t) {
  t = clamp(t) * (RAMP.length - 1);
  const i = Math.min(RAMP.length - 2, Math.floor(t)), f = t - i, a = RAMP[i], b = RAMP[i + 1];
  return [0, 1, 2].map(k => Math.round(a[k] + (b[k] - a[k]) * f));
}
const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;
const lum = c => (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255;
function parseColor(s) {
  if (s.startsWith("#")) { const x = s.length === 4 ? s.slice(1).split("").map(q => q + q).join("") : s.slice(1); return [0, 2, 4].map(i => parseInt(x.slice(i, i + 2), 16)); }
  const m = s.match(/\d+/g); return m ? m.slice(0, 3).map(Number) : [128, 128, 128];
}
const heatCss = t => rgb(heat(t));

/* ---------- state ---------- */
const isTest = p => /(^|\/)(tests?|spec|__tests__)\/|(^|\/)test_[^/]*$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$/i.test(p);
const FILES = D.files;
const byPath = new Map(FILES.map((f, i) => [f.p, i]));
const maxCcn = Math.max(1, ...FILES.map(f => f.c));
const maxN = Math.max(1, ...FILES.map(f => f.n));
const st = { tests: true, mode: "hotspot", zoom: "", sel: null, tabAll: false, sort: { k: "r", dir: 1 }, filter: "", cpl: "all" };

const MODES = [
  { id: "hotspot", label: "Hotspot score" },
  { id: "cx", label: "Complexity" },
  { id: "freq", label: "Change frequency" },
  { id: "owner", label: "Main author" },
  { id: "bus", label: "Bus factor" },
  { id: "gone", label: "Owner left" },
];
function fileColor(f) {
  switch (st.mode) {
    case "hotspot": return f.n ? heat(Math.pow(f.s, 0.85)) : parseColor(css("--cold"));
    case "cx": return heat(Math.log1p(f.c) / Math.log1p(maxCcn));
    case "freq": return f.n ? heat(Math.log1p(f.n) / Math.log1p(maxN)) : parseColor(css("--cold"));
    case "owner": return f.ma == null ? parseColor(css("--cold")) : parseColor(authColor(f.ma));
    case "bus": return !f.n ? parseColor(css("--cold")) : f.bf <= 1 ? heat(0.92) : f.bf === 2 ? heat(0.55) : heat(0.12);
    case "gone": return !f.n ? parseColor(css("--cold")) : f.gone ? heat(0.92) : heat(0.12);
  }
}
function fileSub(f) {
  switch (st.mode) {
    case "hotspot": return f.n ? f.s.toFixed(2) : "";
    case "cx": return (f.px ? "~" : "") + f.c;
    case "freq": return f.n ? f.n + "×" : "";
    case "owner": return f.ma == null ? "" : authName(f.ma).split(" ")[0];
    case "bus": return f.n ? "bus " + f.bf : "";
    case "gone": return f.gone ? "owner left" : "";
  }
}

/* ---------- tree ---------- */
function buildTree() {
  const rootN = { name: "", path: "", kids: new Map(), parent: null, dir: true };
  for (let i = 0; i < FILES.length; i++) {
    const f = FILES[i]; if (!st.tests && isTest(f.p)) continue; const parts = f.p.split("/"); let n = rootN;
    for (let k = 0; k < parts.length - 1; k++) {
      let c = n.kids.get(parts[k]);
      if (!c) { c = { name: parts[k], path: parts.slice(0, k + 1).join("/"), kids: new Map(), parent: n, dir: true }; n.kids.set(parts[k], c); }
      n = c;
    }
    n.kids.set(parts[parts.length - 1], { name: parts[parts.length - 1], path: f.p, fi: i, parent: n, value: Math.max(f.l, 1), dir: false });
  }
  const fin = n => {
    if (!n.dir) return n;
    n.kids = Array.from(n.kids.values()).map(fin);
    while (n.parent && n.kids.length === 1 && n.kids[0].dir) { // collapse a/b/c chains
      const c = n.kids[0]; n.name += "/" + c.name; n.path = c.path; n.kids = c.kids; n.kids.forEach(k => (k.parent = n));
    }
    n.kids.sort((a, b) => b.value - a.value);
    return n;
  };
  const val = n => { if (!n.dir) return n.value; n.value = n.kids.reduce((s, k) => s + val(k), 0); return n.value; };
  fin(rootN); val(rootN); rootN.kids.sort((a, b) => b.value - a.value);
  const sortRec = n => { if (n.dir) { n.kids.sort((a, b) => b.value - a.value); n.kids.forEach(sortRec); } };
  sortRec(rootN);
  const rep = n => {
    if (!n.dir) { n.rep = n; n.big = n; n.nf = 1; return n; }
    let best = null, big = null; n.nf = 0;
    for (const k of n.kids) { rep(k); n.nf += k.nf; const a = k.rep; if (!best || FILES[a.fi].s > FILES[best.fi].s) best = a; if (!big || k.big.value > big.value) big = k.big; }
    n.rep = best; n.big = big; return n;
  };
  rep(rootN);
  const idx = new Map(); const walk = n => { if (n.dir) { idx.set(n.path, n); n.kids.forEach(walk); } }; walk(rootN);
  return { rootN, idx };
}
let TREE = buildTree();

function squarify(items, x, y, w, h) {
  const out = []; const total = items.reduce((a, b) => a + b.value, 0);
  if (!total || w <= 0 || h <= 0) return out;
  const k = (w * h) / total; let i = 0;
  while (i < items.length) {
    const short = Math.min(w, h); let sum = 0, mn = Infinity, mx = 0, j = i, worst = Infinity;
    for (; j < items.length; j++) {
      const a = items[j].value * k, s2 = sum + a, mn2 = Math.min(mn, a), mx2 = Math.max(mx, a);
      const wr = Math.max((short * short * mx2) / (s2 * s2), (s2 * s2) / (short * short * mn2));
      if (wr > worst && j > i) break;
      worst = wr; sum = s2; mn = mn2; mx = mx2;
    }
    const row = items.slice(i, j);
    if (w >= h) { const cw = sum / h; let cy = y; for (const it of row) { const ch = (it.value * k) / cw; out.push({ n: it, x, y: cy, w: cw, h: ch }); cy += ch; } x += cw; w -= cw; }
    else { const rh = sum / w; let cx = x; for (const it of row) { const cw2 = (it.value * k) / rh; out.push({ n: it, x: cx, y, w: cw2, h: rh }); cx += cw2; } y += rh; h -= rh; }
    i = j;
  }
  return out;
}

/* ---------- map render ---------- */
let mapEl;
let drawn = [];
function drawMap() {
  const W = mapEl.clientWidth || 900, H = mapEl.clientHeight || 600;
  mapEl.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const node = TREE.idx.get(st.zoom) || TREE.rootN;
  const parts = [];
  drawn = [];
  const textFill = c => (lum(c) > 0.58 ? "#1b1613" : "#fffaf3");
  const place = (n, x, y, w, h, depth) => {
    if (!n.dir) {
      const f = FILES[n.fi], c = fileColor(f), r = { t: "f", fi: n.fi, x, y, w, h };
      drawn.push(r);
      let s = `<rect class="file${st.sel === n.fi ? " sel" : ""}" data-f="${n.fi}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(0, w).toFixed(1)}" height="${Math.max(0, h).toFixed(1)}" rx="${w > 12 && h > 12 ? 3 : 1}" fill="${rgb(c)}"/>`;
      if (w >= 46 && h >= 17) {
        const maxc = Math.floor((w - 10) / 6.3);
        let name = n.name; if (name.length > maxc) name = name.slice(0, Math.max(1, maxc - 1)) + "…";
        s += `<text class="lbl" x="${(x + 6).toFixed(1)}" y="${(y + 14).toFixed(1)}" fill="${textFill(c)}">${esc(name)}</text>`;
        const sub = fileSub(f);
        if (h >= 32 && sub && w >= 40) s += `<text class="lbl2" x="${(x + 6).toFixed(1)}" y="${(y + 27).toFixed(1)}" fill="${textFill(c)}">${esc(sub)}</text>`;
      }
      parts.push(s); return;
    }
    // directory
    const showHead = w > 64 && h > 40 && depth >= 0;
    const head = showHead ? 17 : 0;
    parts.push(`<rect class="dir-bg" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="5"/>`);
    drawn.push({ t: "d", path: n.path, x, y, w, h });
    parts.push(`<rect class="dir-hit" data-d="${esc(n.path)}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="5"/>`);
    if (w < 16 || h < 16) { // too small to subdivide: paint the representative file
      const c = fileColor(FILES[(st.mode === "owner" || st.mode === "bus" || st.mode === "gone" ? n.big : n.rep).fi]);
      parts.push(`<rect data-d="${esc(n.path)}" class="dir-hit" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" fill="${rgb(c)}" style="fill:${rgb(c)}"/>`);
      return;
    }
    if (showHead) {
      const maxc = Math.floor((w - 12) / 6.4); let name = n.name;
      if (name.length > maxc) name = "…" + name.slice(-(maxc - 1));
      parts.push(`<text class="dir-head" x="${(x + 6).toFixed(1)}" y="${(y + 12.5).toFixed(1)}">${esc(name)}</text>`);
    }
    const pad = w > 30 && h > 30 ? 2.5 : 1;
    const kids = squarify(n.kids, x + pad, y + head + pad - (head ? 1 : 0), w - 2 * pad, h - head - 2 * pad + (head ? 1 : 0));
    for (const k of kids) place(k.n, k.x, k.y, k.w, k.h, depth + 1);
  };
  const kids = squarify(node.kids, 4, 4, W - 8, H - 8);
  for (const k of kids) place(k.n, k.x, k.y, k.w, k.h, 0);
  mapEl.innerHTML = `<g class="enter">${parts.join("")}</g>`;
  renderCrumbs(node);
}
function renderCrumbs(node) {
  const chain = []; for (let n = node; n; n = n.parent) chain.unshift(n);
  $("#crumbs").innerHTML = chain.map((n, i) => `<button data-z="${esc(n.path)}">${esc(i === 0 ? M.repo : n.name)}</button>`).join('<span>/</span>');
}

/* ---------- legend ---------- */
function drawLegend() {
  const L = $("#legend");
  const ramp = (a, b) => `<span class="sw">${a}<span class="ramp"></span>${b}</span>`;
  const sw = (c, t) => `<span class="sw"><i style="background:${c}"></i>${t}</span>`;
  let h = "";
  switch (st.mode) {
    case "hotspot": h = ramp("low", "high") + sw(css("--cold"), "not changed in window") + `<span class="muted">size = lines of code &middot; colour = change frequency &times; complexity</span>`; break;
    case "cx": h = ramp("simple", `complex (CCN ${maxCcn})`) + `<span class="muted">sum of cyclomatic complexity, log scale</span>`; break;
    case "freq": h = ramp("1 commit", `${maxN} commits`) + sw(css("--cold"), "unchanged"); break;
    case "owner": h = D.authors.slice(0, PAL.length).filter(a => a.own > 0).map((a, i) => sw(PAL[i], esc(a.n))).join("") + sw("#8e8a99", "others") + sw(css("--cold"), "unchanged"); break;
    case "bus": h = sw(rgb(heat(0.92)), "1 &mdash; single owner") + sw(rgb(heat(0.55)), "2") + sw(rgb(heat(0.12)), "3+") + sw(css("--cold"), "unchanged"); break;
    case "gone": h = sw(rgb(heat(0.92)), `main author inactive &gt; ${M.inactive_months} months`) + sw(rgb(heat(0.12)), "main author active") + sw(css("--cold"), "unchanged"); break;
  }
  L.innerHTML = h + `<span class="hint">click a folder to zoom &middot; click a file for details</span>`;
}

/* ---------- tooltip & detail ---------- */
const tip = document.createElement("div"); tip.id = "tip"; document.body.appendChild(tip);
function tipHtml(el) {
  if (el.dataset.f != null) {
    const f = FILES[+el.dataset.f];
    return `<b>${esc(f.p)}</b><div class="r"><span>LOC</span><span>${fmt(f.l)}</span></div>` +
      (f.n ? `<div class="r"><span>Commits</span><span>${f.n} by ${f.a}</span></div><div class="r"><span>Complexity</span><span>${f.c}${f.px ? " (indent proxy)" : ""}${f.px ? "" : " / max fn " + f.m}</span></div><div class="r"><span>Hotspot</span><span>${f.s.toFixed(2)}${f.r ? " (#" + f.r + ")" : ""}</span></div><div class="r"><span>Owner</span><span>${esc(authName(f.ma))} ${pct(f.ms)}</span></div>` : `<div class="r"><span>Unchanged in this window</span><span></span></div>`);
  }
  if (el.dataset.d != null) { const n = TREE.idx.get(el.dataset.d); return `<b>${esc(n.path || M.repo)}/</b><div class="r"><span>Files</span><span>${n.nf}</span></div><div class="r"><span>LOC</span><span>${fmt(n.value)}</span></div><div class="r"><span>Click to zoom in</span><span></span></div>`; }
  return "";
}
function moveTip(e, html) {
  if (!html) { tip.classList.remove("on"); return; }
  tip.innerHTML = html; tip.classList.add("on");
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let x = e.clientX + 16, y = e.clientY + 16;
  if (x + w > innerWidth - 8) x = e.clientX - w - 14;
  if (y + h > innerHeight - 8) y = e.clientY - h - 14;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function wireMap() {
mapEl.addEventListener("mousemove", e => { const t = e.target.closest("[data-f],[data-d]"); moveTip(e, t ? tipHtml(t) : ""); });
mapEl.addEventListener("mouseleave", () => tip.classList.remove("on"));
mapEl.addEventListener("click", e => {
  const t = e.target.closest("[data-f],[data-d]"); if (!t) return;
  if (t.dataset.f != null) { select(+t.dataset.f); } else { zoomTo(t.dataset.d); }
});
$("#crumbs").addEventListener("click", e => { const b = e.target.closest("[data-z]"); if (b) zoomTo(b.dataset.z); });
addEventListener("keydown", e => { if (e.key === "Escape" && st.zoom) { const n = TREE.idx.get(st.zoom); zoomTo(n && n.parent ? n.parent.path : ""); } });
}
function zoomTo(path) { st.zoom = path; drawMap(); }

function ownBar(owners, h) {
  if (!owners || !owners.length) return "";
  let rest = 1, s = "";
  for (const [i, sh] of owners) { s += `<i style="width:${(sh * 100).toFixed(1)}%;background:${authColor(i)}" title="${esc(authName(i))} ${pct(sh)}"></i>`; rest -= sh; }
  return `<div class="own" style="${h ? "height:" + h + "px" : ""}">${s}</div>`;
}
function select(fi, noZoom) {
  st.sel = fi; const f = FILES[fi];
  $$("#treemap .file.sel").forEach(e => e.classList.remove("sel"));
  const el = $(`#treemap [data-f="${fi}"]`); if (el) el.classList.add("sel");
  const i = f.p.lastIndexOf("/");
  const pairs = D.coupling.pairs.filter(p => p.a === f.p || p.b === f.p).slice(0, 4);
  const fmax = Math.max(1, ...f.tf.map(x => x[1]));
  $("#detail").innerHTML = `
    <div class="dir">${esc(i >= 0 ? f.p.slice(0, i + 1) : "")}</div>
    <h3>${esc(f.p.slice(i + 1))}</h3>
    ${f.n ? `<div class="ring"><div class="big" style="color:${heatCss(Math.pow(f.s, .85))}">${f.s.toFixed(2)}<small>hotspot score</small></div>
      <div class="big">${f.r ? "#" + f.r : "-"}<small>rank</small></div>
      <div class="big">${f.t ? (f.t < 1.5 ? "1" : Math.round(f.t)) + "%" : "-"}<small>top complexity</small></div></div>` : `<div class="placeholder">Not changed in this window.</div>`}
    <div class="grid2">
      <div><span>Commits</span><b>${f.n}</b></div><div><span>Authors</span><b>${f.a}</b></div>
      <div><span>Lines +/−</span><b>+${fmt(f.ad)} / −${fmt(f.de)}</b></div><div><span>LOC</span><b>${fmt(f.l)}</b></div>
      <div><span>${f.px ? "Indent complexity" : "Sum CCN"}</span><b>${fmt(f.c)}</b></div><div><span>${f.px ? "Functions" : "Max fn CCN"}</span><b>${f.px ? "n/a" : f.m}</b></div>
    </div>
    ${f.tf.length ? `<h4>Most complex functions</h4>${f.tf.slice(0, 5).map(x => `<div class="fnrow"><code title="${esc(x[0])}">${esc(x[0])}</code><b class="${x[1] > 30 ? "num-hot" : x[1] > M.ccn_threshold ? "num-warm" : ""}">${x[1]}</b><div class="b"><i style="width:${(x[1] / fmax * 100).toFixed(0)}%"></i></div></div>`).join("")}` : ""}
    ${f.n ? `<h4>Knowledge</h4>
      <div class="owner-line"><span class="dot" style="background:${authColor(f.ma)}"></span><b>${esc(authName(f.ma))}</b><span class="muted">${pct(f.ms)} of added lines, ${pct(f.mc)} of commits</span></div>
      ${ownBar(f.ow, 9)}
      <div class="grid2" style="margin-top:10px"><div><span>Bus factor</span><b>${f.bf}</b></div><div><span>Main author last seen</span><b class="${f.gone ? "warn" : ""}">${esc(f.ml ? f.ml.slice(0, 10) : "-")}${f.gone ? " (left)" : ""}</b></div></div>` : ""}
    ${pairs.length ? `<h4>Changes together with</h4>${pairs.map(p => { const o = p.a === f.p ? p.b : p.a; return `<div class="coupled"><code title="${esc(o)}">${esc(o)}</code><b>${pct(p.degree)}</b></div>`; }).join("")}` : ""}
  `;
  if (!noZoom) {
    const n = TREE.idx.get(st.zoom) || TREE.rootN;
    if (!(f.p === st.zoom || f.p.startsWith(st.zoom ? st.zoom + "/" : ""))) { zoomTo(""); select(fi, true); }
  }
}
function focusFile(path) {
  const fi = byPath.get(path); if (fi == null) return;
  // zoom to the parent folder so the file is large enough to read
  const par = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  let n = TREE.rootN, target = "";
  const segs = (() => { const out = []; let q = TREE.rootN; (function find(x) { if (x.dir) { if (path.startsWith(x.path ? x.path + "/" : "")) { out.push(x); x.kids.forEach(find); } } })(q); return out; })();
  if (segs.length) target = segs[segs.length - 1].path;
  st.zoom = target; drawMap(); select(fi, true);
  $("#map").scrollIntoView({ behavior: "smooth", block: "center" });
}

/* ---------- sections ---------- */
const days = Math.max(1, Math.round((Date.parse(M.until) - Date.parse(M.since)) / 864e5));
const changedFiles = FILES.filter(f => f.n);
const hot = FILES.filter(f => f.r);
function kpis() {
  const goneN = S.inactive_main_author_files, ch = S.code_files_changed || 1;
  return [
    { v: fmt(S.commits), k: "Commits", n: `${days} days · ${(S.commits / days * 7).toFixed(1)}/week` },
    { v: fmt(S.authors), k: "Authors", n: S.bots ? `${S.bots} bot${S.bots > 1 ? "s" : ""} excluded` : "distinct people" },
    { v: fmt(S.code_files), k: "Files", n: `${fmt(S.code_files_changed)} changed · ${fmt(S.total_loc)} LOC` },
    { v: fmt(S.hotspots), k: "Hotspots", n: "score ≥ 0.25", hot: 1 },
    { v: S.repo_bus_factor == null ? "-" : S.repo_bus_factor, k: "Bus factor", n: S.repo_main_author ? `${esc(S.repo_main_author)} wrote ${pct(S.repo_main_author_share)}` : "" },
    { v: pct(goneN / ch), k: "Owner left", n: `${goneN} of ${S.code_files_changed} changed files`, hot: goneN / ch > 0.2 },
  ].map(x => `<div class="kpi${x.hot ? " hot" : ""}" title="${esc(x.n)}"><div class="v">${x.v}</div><div class="k">${x.k}</div></div>`).join("");
}
function linkify(t, files) {
  let s = esc(t);
  const list = Array.from(new Set(files)).sort((a, b) => b.length - a.length);
  for (const f of list) { const e = esc(f); s = s.split(e).join(`<code>${e}</code>`); }
  return s;
}
function findingsHtml() {
  const cat = { hotspot: "Hotspot", trend: "Trend", coupling: "Coupling", knowledge: "Knowledge", info: "Note" };
  return D.findings.map(f => {
    const can = f.f.some(p => byPath.has(p));
    return `<div class="finding${can ? " clickable" : ""}" ${can ? `data-focus="${esc(f.f.find(p => byPath.has(p)))}" title="Show on the map"` : ""}>
      <div class="no">${f.i}</div><div><span class="pill ${f.s}">${f.s === "medium" ? "med" : f.s}</span></div>
      <div class="body"><div class="t">${linkify(f.t, f.f)}</div>${f.d ? `<div class="d">${esc(f.d)}</div>` : ""}<div class="cat">${cat[f.k] || f.k}</div></div></div>`;
  }).join("");
}

/* hotspot table */
const TCOLS = [
  { k: "r", t: "#", f: f => f.r || "-" },
  { k: "p", t: "File", cls: "l", f: f => { const i = f.p.lastIndexOf("/"); return `<span class="fdir">${esc(f.p.slice(0, i + 1))}</span><span class="fname">${esc(f.p.slice(i + 1))}</span>${isTest(f.p) ? '<span class="tag">TEST</span>' : ""}${f.px ? '<span class="tag" title="Indentation-based proxy; language not supported by lizard">PROXY</span>' : ""}`; }, cmp: (a, b) => a.p.localeCompare(b.p) },
  { k: "n", t: "Commits", f: f => f.n },
  { k: "a", t: "Authors", f: f => f.a },
  { k: "ch", t: "Churn", f: f => `<span style="color:var(--good)">+${fmt(f.ad)}</span> <span style="color:var(--sev-high)">−${fmt(f.de)}</span>`, v: f => f.ad + f.de },
  { k: "l", t: "LOC", f: f => fmt(f.l) },
  { k: "c", t: "CCN", f: f => fmt(f.c) + (f.px ? "*" : "") },
  { k: "m", t: "Max fn", f: f => (f.px ? "-" : `<span class="${f.m > 30 ? "num-hot" : f.m > M.ccn_threshold ? "num-warm" : ""}">${f.m}</span>`) },
  { k: "s", t: "Score", f: f => `<div class="scorecell"><div class="scorebar"><i style="width:${(f.s * 100).toFixed(0)}%;background:${heatCss(Math.pow(f.s, .85))}"></i></div><b>${f.s.toFixed(2)}</b></div>` },
  { k: "tr", t: "Trend", f: f => trendSpark(f.p), v: f => { const t = D.trends.find(x => x.p === f.p); return t ? (t.ch || 0) : -9; } },
];
function trendSpark(p) {
  const t = D.trends.find(x => x.p === p); if (!t) return '<span class="muted">–</span>';
  const v = t.pts.map(q => q[1]); const nums = v.filter(x => x != null); if (nums.length < 2) return "";
  const lo = Math.min(...nums), hi = Math.max(...nums), top = Math.max(hi, lo + 0.25 * hi), W = 70, H = 20;
  const pts = v.map((x, i) => x == null ? null : [i / (v.length - 1) * W, H - 2 - (x - lo) / (top - lo || 1) * (H - 4)]).filter(Boolean);
  const up = (t.ch || 0) > 0.05;
  return `<svg class="spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><polyline fill="none" stroke="${up ? css("--sev-high") : css("--ink-3")}" stroke-width="1.6" stroke-linejoin="round" points="${pts.map(p => p.map(n => n.toFixed(1)).join(",")).join(" ")}"/><circle cx="${pts[pts.length - 1][0].toFixed(1)}" cy="${pts[pts.length - 1][1].toFixed(1)}" r="2.2" fill="${up ? css("--sev-high") : css("--ink-3")}"/></svg>`;
}
function tableRows() {
  let rows = hot.slice();
  const q = st.filter.trim().toLowerCase();
  if (q) rows = rows.filter(f => f.p.toLowerCase().includes(q));
  const col = TCOLS.find(c => c.k === st.sort.k) || TCOLS[0];
  const val = col.v || (f => f[col.k]);
  rows.sort((a, b) => { const c = col.cmp ? col.cmp(a, b) : (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0); return c * st.sort.dir || a.r - b.r; });
  return rows;
}
function drawTable() {
  const rows = tableRows(); const shown = st.tabAll ? rows : rows.slice(0, 20);
  const head = TCOLS.map(c => `<th class="${c.cls || ""}" data-k="${c.k}">${c.t}<span class="arrow">${st.sort.k === c.k ? (st.sort.dir > 0 ? "▴" : "▾") : ""}</span></th>`).join("");
  const body = shown.map(f => `<tr class="expandable" data-p="${esc(f.p)}">${TCOLS.map(c => `<td class="${c.cls || ""}${c.k === "p" ? " file" : ""}">${c.f(f)}</td>`).join("")}</tr>`).join("");
  $("#hotspot-table").innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body || `<tr><td colspan="${TCOLS.length}" class="empty">No matching files.</td></tr>`}</tbody>`;
  $("#tfoot-count").textContent = `Showing ${shown.length} of ${rows.length} scored files`;
  const b = $("#toggle-all"); b.style.display = rows.length > 20 ? "" : "none"; b.textContent = st.tabAll ? "Show top 20" : `Show all ${rows.length}`;
}
function wireTable() {
$("#hotspot-table").addEventListener("click", e => {
  const th = e.target.closest("th");
  if (th) { const k = th.dataset.k; st.sort = st.sort.k === k ? { k, dir: -st.sort.dir } : { k, dir: k === "p" || k === "r" ? 1 : -1 }; drawTable(); return; }
  const tr = e.target.closest("tr.expandable"); if (!tr) return;
  const nxt = tr.nextElementSibling;
  if (nxt && nxt.classList.contains("sub")) { nxt.remove(); return; }
  const f = FILES[byPath.get(tr.dataset.p)];
  const fmax = Math.max(1, ...f.tf.map(x => x[1]));
  const sub = document.createElement("tr"); sub.className = "sub";
  sub.innerHTML = `<td colspan="${TCOLS.length}"><div class="fl"><div><h4 style="margin:0 0 6px;font:700 .68rem/1 var(--sans);letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3)">Most complex functions</h4>${f.tf.length ? f.tf.map(x => `<div class="fnrow"><code title="${esc(x[0])}">${esc(x[0])} <span class="muted">:${x[2]}</span></code><b class="${x[1] > 30 ? "num-hot" : x[1] > M.ccn_threshold ? "num-warm" : ""}">${x[1]}</b><div class="b"><i style="width:${(x[1] / fmax * 100).toFixed(0)}%"></i></div></div>`).join("") : '<span class="muted">no per-function data</span>'}</div>
    <div><h4 style="margin:0 0 6px;font:700 .68rem/1 var(--sans);letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3)">Ownership</h4>${ownBar(f.ow, 9)}<div class="owner-line" style="margin-top:8px"><span class="dot" style="background:${authColor(f.ma)}"></span><b>${esc(authName(f.ma))}</b><span class="muted">${pct(f.ms)} · bus factor ${f.bf}</span></div><button class="link-btn" data-show="${esc(f.p)}">Show on map</button></div></div></td>`;
  tr.after(sub);
});
$("#hotspot-table").addEventListener("click", e => { const b = e.target.closest("[data-show]"); if (b) focusFile(b.dataset.show); });
$("#filter").addEventListener("input", e => { st.filter = e.target.value; drawTable(); });
$("#toggle-all").addEventListener("click", () => { st.tabAll = !st.tabAll; drawTable(); });

}
/* trends */
function trendCard(t) {
  const W = 340, H = 118, L = 34, R = 8, T = 8, B = 20;
  const v = t.pts.map(p => p[1]); const nums = v.filter(x => x != null);
  if (!nums.length) return "";
  const mx = Math.max(...nums), mn = Math.min(...nums);
  const lo = (mx - mn) / (mx || 1) > 0.3 ? 0 : Math.max(0, mn - 0.35 * mx), hi = mx + (mx - lo) * 0.08 || 1;
  const X = i => L + (i / (v.length - 1)) * (W - L - R), Y = x => T + (1 - (x - lo) / (hi - lo)) * (H - T - B);
  const segs = []; let cur = [];
  v.forEach((x, i) => { if (x == null) { if (cur.length) segs.push(cur); cur = []; } else cur.push([X(i), Y(x)]); }); if (cur.length) segs.push(cur);
  const col = (t.ch || 0) > 0.05 ? css("--sev-high") : (t.ch || 0) < -0.05 ? css("--good") : css("--accent");
  const line = s => s.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");
  const ticks = [lo, (lo + hi) / 2, hi].map(x => Math.round(x));
  const last = segs[segs.length - 1], lp = last[last.length - 1];
  const gid = "g" + Math.abs(t.p.split("").reduce((a, c) => (a * 31 + c.charCodeAt(0)) | 0, 7));
  const dateL = [t.pts[0][0], t.pts[t.pts.length - 1][0]];
  return `<div class="card tcard"><div class="hd"><span class="nm" title="${esc(t.p)}">${esc(t.p)}</span><span class="ch ${(t.ch || 0) > 0.05 ? "up" : (t.ch || 0) < -0.05 ? "down" : "flat"}">${t.ch == null ? "-" : (t.ch > 0 ? "+" : "") + (t.ch * 100).toFixed(0) + "%"}</span></div>
  <svg viewBox="0 0 ${W} ${H}" data-t="${esc(t.p)}"><defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${col}" stop-opacity=".32"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
  <g class="axis">${ticks.map(x => `<line class="grid-line" x1="${L}" x2="${W - R}" y1="${Y(x).toFixed(1)}" y2="${Y(x).toFixed(1)}"/><text x="${L - 6}" y="${(Y(x) + 3).toFixed(1)}" text-anchor="end">${x}</text>`).join("")}
  <text x="${L}" y="${H - 4}">${dateL[0]}</text><text x="${W - R}" y="${H - 4}" text-anchor="end">${dateL[1]}</text></g>
  ${segs.map(s => `<path d="${line(s)} L${s[s.length - 1][0].toFixed(1)} ${Y(lo)} L${s[0][0].toFixed(1)} ${Y(lo)}Z" fill="url(#${gid})"/><path d="${line(s)}" fill="none" stroke="${col}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`).join("")}
  ${v.map((x, i) => x == null ? "" : `<circle cx="${X(i).toFixed(1)}" cy="${Y(x).toFixed(1)}" r="${i === v.length - 1 ? 3.6 : 2}" fill="${i === v.length - 1 ? col : css("--card")}" stroke="${col}" stroke-width="1.5"><title>${t.pts[i][0]}: CCN ${x}, ${fmt(t.pts[i][2])} LOC</title></circle>`).join("")}
  <text x="${Math.min(lp[0], W - R - 2).toFixed(1)}" y="${(lp[1] - 9).toFixed(1)}" text-anchor="end" style="font:700 11px var(--sans);fill:${col}">${v[v.length - 1]}</text></svg></div>`;
}
function activityHtml() {
  const A = D.activity; if (!A.length) return "";
  const W = 1180, H = 120, L = 30, B = 20, T = 8; const mx = Math.max(1, ...A.map(a => a.commits));
  const bw = (W - L) / A.length;
  const bars = A.map((a, i) => {
    const h = (a.commits / mx) * (H - T - B), x = L + i * bw;
    const lab = A.length <= 14 || i % Math.ceil(A.length / 12) === 0;
    return `<rect x="${(x + bw * .14).toFixed(1)}" y="${(H - B - h).toFixed(1)}" width="${(bw * .72).toFixed(1)}" height="${Math.max(h, a.commits ? 1.5 : 0).toFixed(1)}" rx="2.5" fill="${heatCss(.25 + .6 * a.commits / mx)}"><title>${a.month}: ${a.commits} commits, ${a.authors} authors</title></rect>` +
      (lab ? `<text x="${(x + bw / 2).toFixed(1)}" y="${H - 5}" text-anchor="middle">${a.month.slice(2)}</text>` : "");
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><g class="axis"><line class="grid-line" x1="${L}" x2="${W}" y1="${T}" y2="${T}"/><text x="${L - 6}" y="${T + 4}" text-anchor="end">${mx}</text><text x="${L - 6}" y="${H - B + 3}" text-anchor="end">0</text>${bars}</g></svg>`;
}

/* coupling */
function couplingHtml() {
  const P = D.coupling.pairs.filter(p => st.cpl === "all" || p.surprising).slice(0, 14);
  if (!P.length) return `<div class="empty">No file pairs reach the thresholds (≥${M.min_shared} shared commits, ≥${pct(M.min_degree)} coupling).</div>`;
  const kindL = { "cross-module": "cross-module", "test-source": "test ↔ source", "docs-source": "docs ↔ source", "config-source": "config", "same-module": "same module", "test-test": "tests", "docs-docs": "docs" };
  return P.map(p => `<div class="pair"><div><code>${esc(p.a)}</code><span class="arrow">↔</span><code>${esc(p.b)}</code></div>
    <div class="deg"><b>${pct(p.degree)}</b><div><i style="width:${p.degree * 100}%"></i></div></div>
    <div class="meta">${p.shared} shared commits · changed ${p.revs_a} / ${p.revs_b} times<span class="badge ${p.surprising ? "x" : "k"}">${kindL[p.kind] || p.kind}</span></div></div>`).join("");
}
function matrixHtml() {
  const P = D.coupling.pairs.slice(0, 60);
  if (P.length < 1) return `<div class="empty">Nothing to plot.</div>`;
  const score = new Map(); P.forEach(p => { score.set(p.a, (score.get(p.a) || 0) + p.strength); score.set(p.b, (score.get(p.b) || 0) + p.strength); });
  const names = Array.from(score.keys()).sort((a, b) => score.get(b) - score.get(a)).slice(0, 18).sort();
  const n = names.length, ix = new Map(names.map((p, i) => [p, i]));
  const cell = new Map(); P.forEach(p => { if (ix.has(p.a) && ix.has(p.b)) { cell.set(ix.get(p.a) + "," + ix.get(p.b), p); cell.set(ix.get(p.b) + "," + ix.get(p.a), p); } });
  const W = 560, Lm = 168, Tm = 96, cs = Math.min(26, (W - Lm - 8) / n), H = Tm + n * cs + 6;
  const short = (p, k) => { const b = p.split("/").pop(); const d = p.includes("/") ? p.split("/").slice(-2, -1)[0] + "/" : ""; const s = d + b; return s.length > k ? "…" + s.slice(-(k - 1)) : s; };
  let s = "";
  for (let c = 0; c < n; c++) s += `<text transform="translate(${(Lm + c * cs + cs / 2 + 3).toFixed(1)},${Tm - 6}) rotate(-58)" text-anchor="start"><title>${esc(names[c])}</title>${esc(short(names[c], 16))}</text>`;
  for (let r = 0; r < n; r++) {
    s += `<text x="${Lm - 8}" y="${(Tm + r * cs + cs / 2 + 3.5).toFixed(1)}" text-anchor="end"><title>${esc(names[r])}</title>${esc(short(names[r], 26))}</text>`;
    for (let c = 0; c < n; c++) {
      const p = cell.get(r + "," + c), x = Lm + c * cs, y = Tm + r * cs;
      if (r === c) s += `<rect class="cell" x="${x}" y="${y}" width="${cs}" height="${cs}" rx="3" fill="${css("--line")}" opacity=".6"/>`;
      else if (p) s += `<rect class="cell" x="${x}" y="${y}" width="${cs}" height="${cs}" rx="3" fill="${heatCss(clamp((p.degree - .25) / .75) * .9 + .1)}"><title>${esc(p.a)} ↔ ${esc(p.b)}\n${p.shared} shared commits, ${pct(p.degree)} coupling</title></rect>` + (p.surprising ? `<circle cx="${x + cs / 2}" cy="${y + cs / 2}" r="2.6" fill="${css("--card")}" opacity=".95"/>` : "");
      else s += `<rect class="cell" x="${x}" y="${y}" width="${cs}" height="${cs}" rx="3" fill="${css("--bg-2")}"/>`;
    }
  }
  return `<svg id="matrix" viewBox="0 0 ${W} ${H}">${s}</svg><div class="legend" style="padding:6px 0 0"><span class="sw">weak<span class="ramp" style="width:110px"></span>strong</span><span class="sw"><i style="background:var(--ink-3);border-radius:50%;width:7px;height:7px"></i>crosses modules</span></div>`;
}

/* knowledge */
function knowledgeHtml() {
  const rows = D.dirs.filter(d => d.d >= 1 && d.d <= 2).sort((a, b) => b.n - a.n).slice(0, 12);
  const bf = b => `<span class="bf b${Math.min(3, b)}">${b}</span>`;
  const dirT = `<div class="tablewrap"><table><thead><tr><th class="l" style="text-align:left;width:auto">Directory</th><th>Commits</th><th>Authors</th><th>Bus</th><th class="l" style="text-align:left">Ownership (lines added)</th><th class="l" style="text-align:left">Main author</th></tr></thead><tbody>` +
    rows.map(d => `<tr><td class="l" style="text-align:left;color:var(--ink);width:auto"><code>${esc(d.p)}/</code></td><td>${d.n}</td><td>${d.a}</td><td>${bf(d.bf)}</td><td class="l" style="text-align:left"><div class="own-bar">${ownBar(d.ow, 9)}</div></td><td class="l" style="text-align:left"><span class="dot" style="background:${authColor(d.ma)}"></span> ${esc(authName(d.ma))} <span class="muted">${pct(d.ms)}</span>${d.gone ? ' <span class="status-gone">· left</span>' : ""}</td></tr>`).join("") + `</tbody></table></div>`;
  const A = D.authors.filter(a => !a.bot).slice(0, 12);
  const authT = `<div class="tablewrap"><table><thead><tr><th class="l" style="text-align:left;width:auto">Author</th><th>Commits</th><th>Owns (LOC)</th><th>Last commit</th></tr></thead><tbody>` +
    A.map((a, i) => `<tr><td class="l" style="text-align:left;color:var(--ink);width:auto"><span class="dot" style="background:${authColor(D.authors.indexOf(a))}"></span> ${esc(a.n)}</td><td>${a.c}</td><td>${fmt(a.own)}</td><td class="${a.gone ? "status-gone" : "status-ok"}">${a.last ? a.last.slice(0, 10) : "-"}${a.gone ? " · inactive" : ""}</td></tr>`).join("") + `</tbody></table></div>`;
  const gone = FILES.filter(f => f.n && f.gone).sort((a, b) => b.l - a.l).slice(0, 8);
  const goneT = gone.length ? `<div class="tablewrap"><table><thead><tr><th class="l" style="text-align:left;width:auto">File</th><th>LOC</th><th>Commits</th><th class="l" style="text-align:left">Main author</th><th>Last seen</th><th>Score</th></tr></thead><tbody>` +
    gone.map(f => `<tr><td class="l file" style="text-align:left;color:var(--ink);width:auto"><code>${esc(f.p)}</code></td><td>${fmt(f.l)}</td><td>${f.n}</td><td class="l" style="text-align:left"><span class="dot" style="background:${authColor(f.ma)}"></span> ${esc(authName(f.ma))} <span class="muted">${pct(f.ms)}</span></td><td class="status-gone">${f.ml ? f.ml.slice(0, 10) : "-"}</td><td>${f.s.toFixed(2)}</td></tr>`).join("") + `</tbody></table></div>` : `<div class="empty">Every changed file has a main author who is still active.</div>`;
  return { dirT, authT, goneT };
}

/* ---------- page skeleton ---------- */
function skeleton() {
  const k = knowledgeHtml();
  $("#top").innerHTML = `
  <div class="wrap">
    <section class="hero"><div class="hero-grid"><div>
      <div class="eyebrow">Code health report</div>
      <h1>${esc(M.repo)}<em>.</em></h1>
      <div class="sub"><span>branch <b class="mono">${esc(M.branch)}</b> @ <span class="mono">${esc(M.head)}</span></span><span>${esc(M.since)} \u2192 ${esc(M.until)} (${days} days)</span><span>codeheat ${esc(M.version)}${M.seconds != null ? " \u00b7 analysed in " + M.seconds.toFixed(1) + "s" : ""}</span></div></div>
      <div class="kpis">${kpis()}</div></div>
    </section>

    <section class="sec" id="map"><h2>Hotspot map</h2>
      <p class="lede" style="margin-bottom:12px">Size = lines of code. Hot = complex <b>and</b> changed often. Switch the lens to see who owns what.</p>
      <div class="maprow"><div class="card" style="overflow:hidden">
        <div class="toolbar"><div class="seg" id="modes">${MODES.map(m => `<button data-m="${m.id}" aria-pressed="${m.id === st.mode}">${m.label}</button>`).join("")}</div><label class="chk"><input type="checkbox" id="tests-toggle" checked> test files</label><div class="crumbs" id="crumbs"></div></div>
        <div id="mapwrap"><svg id="treemap" role="img" aria-label="Treemap of source files"></svg></div>
        <div class="legend" id="legend"></div></div>
        <aside class="card detail" id="detail"></aside></div></section>

    <section class="sec" id="findings"><h2>What to look at first</h2>
      <p class="lede">The findings below combine all four analyses, most important first. Click one to find the code on the map.</p>
      <div class="card findings" id="findings-list">${findingsHtml()}</div></section>

    <section class="sec" id="hotspots"><h2>Hotspots</h2>
      <p class="lede">Score = normalised change frequency &times; normalised complexity (rank + log scaled, so a single giant file cannot flatten the rest). Click a column to sort, a row for functions and ownership.</p>
      <div class="card"><div class="toolbar"><input class="filter" id="filter" type="search" placeholder="Filter files…" aria-label="Filter files"><span class="muted" style="font-size:.8rem;margin-left:auto">CCN = sum of function cyclomatic complexity${hot.some(f => f.px) ? " &middot; * = indentation proxy" : ""}</span></div>
      <div class="tablewrap"><table id="hotspot-table"></table></div>
      <div class="tfoot"><span id="tfoot-count"></span><button class="link-btn" id="toggle-all"></button></div></div></section>

    <section class="sec" id="trends"><h2>Is it getting better or worse?</h2>
      <p class="lede">Complexity of the top hotspots, re-measured at ${D.trends[0] ? D.trends[0].pts.length : 12} points across the window by running the analyser on each historical version of the file. Rising lines are debt compounding.</p>
      ${D.trends.length ? `<div class="cards3">${D.trends.map(trendCard).join("")}</div>` : `<div class="card empty">No trend data for this window.</div>`}
      <div class="card activity" style="margin-top:14px"><div class="hd" style="display:flex;justify-content:space-between"><b style="font-family:var(--serif)">Commit activity per month</b><span class="muted" style="font-size:.8rem">${fmt(S.commits)} commits</span></div>${activityHtml()}</div></section>

    <section class="sec" id="coupling"><h2>Change coupling</h2>
      <p class="lede">Files that keep changing in the same commits, whatever the import graph says. <b>Degree</b> = shared commits &divide; revisions of the less-changed file. ${fmt(D.coupling.total)} pairs reach ≥${M.min_shared} shared commits and ≥${pct(M.min_degree)}; ${D.coupling.surprising} cross module boundaries${D.coupling.skipped ? `; ${D.coupling.skipped} bulk commits (&gt;${M.max_commit_files} files) were ignored` : ""}.</p>
      <div class="two"><div class="card"><div class="toolbar"><div class="seg" id="cpl-seg"><button data-c="all" aria-pressed="${st.cpl === "all"}">All pairs</button><button data-c="x" aria-pressed="${st.cpl === "x"}">Cross-module only</button></div></div><div id="pairs">${couplingHtml()}</div></div>
      <div class="card pad"><div style="font:700 1rem var(--serif);margin-bottom:8px">Coupling matrix</div><div id="matrix-wrap">${matrixHtml()}</div></div></div></section>

    <section class="sec" id="knowledge"><h2>Knowledge &amp; bus factor</h2>
      <p class="lede">Ownership is measured by <b>lines added</b> in the window (commit share shown in the file detail). Bus factor = fewest people who account for 50% of the contributions. A main author with no commit for ${M.inactive_months} months counts as <b>left</b>.</p>
      <div class="card"><div style="padding:16px 18px 6px;font:700 1rem var(--serif)">Directories</div>${k.dirT}</div>
      <div class="two" style="margin-top:16px"><div class="card"><div style="padding:16px 18px 6px;font:700 1rem var(--serif)">Authors</div>${k.authT}</div>
      <div class="card"><div style="padding:16px 18px 6px;font:700 1rem var(--serif)">Knowledge-loss risk <span class="muted" style="font:400 .8rem var(--sans)">changed code whose main author has gone quiet</span></div>${k.goneT}</div></div></section>

    <section class="sec" id="method"><h2>How to read this</h2>
      <div class="method">
        <div class="card"><h4>Hotspot score</h4><p><code>score = norm(commits) &times; norm(complexity)</code>, where <code>norm(x) = &frac12;&middot;percentile_rank(x) + &frac12;&middot;log(1+x)/log(1+max)</code>. Zero stays zero. Only source files changed in the window are scored.</p><p>Complexity is the sum of lizard cyclomatic complexity (CCN) over all functions. Languages lizard cannot parse fall back to an indentation proxy, flagged <code>PROXY</code>, and are ranked only against each other.</p></div>
        <div class="card"><h4>Change coupling</h4><p>Pairs of files in the same commit. Needs ≥${M.min_shared} shared commits and degree ≥${pct(M.min_degree)}. Commits touching more than ${M.max_commit_files} files are ignored. Pairs that cross top-level modules, other than test, docs and config files, are flagged as surprising.</p></div>
        <div class="card"><h4>Knowledge</h4><p>Main author = most lines added in the window (ties: commits). Identities are merged through <code>.mailmap</code>, case-insensitive e-mail and identical full names; bots are excluded. History follows renames, so moved files keep their past.</p></div>
        <div class="card"><h4>Limits</h4><p>Behavioural signals say <i>where</i> to look, not <i>what</i> is wrong. Lines added reward typing, not understanding; squash-merge workflows credit the merger. A short window gives a noisy picture.</p></div>
      </div>
    </section>
    <footer><span>codeheat ${esc(M.version)} &middot; open-source behavioural code analysis</span><span>Self-contained report &mdash; no network requests</span></footer>
  </div>`;
}

/* ---------- wiring ---------- */
function setTheme(t) {
  if (t) root.setAttribute("data-theme", t); else root.removeAttribute("data-theme");
}
function curTheme() { return root.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); }
const ICON = { light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>', dark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>' };
function refreshTheme() { $("#theme").innerHTML = curTheme() === "dark" ? ICON.light : ICON.dark; }
function redrawAll() {
  readRamp(); drawMap(); drawLegend(); if (st.sel != null) select(st.sel, true);
  $("#trends .cards3") && ($("#trends .cards3").innerHTML = D.trends.map(trendCard).join(""));
  drawTable(); $("#matrix-wrap").innerHTML = matrixHtml();
  const a = $(".activity svg"); if (a) a.outerHTML = activityHtml();
}
function init() {
  readRamp(); skeleton(); mapEl = $("#treemap"); wireMap(); wireTable(); refreshTheme();
  $("#theme").addEventListener("click", () => { setTheme(curTheme() === "dark" ? "light" : "dark"); refreshTheme(); redrawAll(); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { refreshTheme(); redrawAll(); });
  $("#modes").addEventListener("click", e => { const b = e.target.closest("[data-m]"); if (!b) return; st.mode = b.dataset.m; $$("#modes button").forEach(x => x.setAttribute("aria-pressed", x === b)); drawMap(); drawLegend(); });
  $("#tests-toggle").addEventListener("change", e => { st.tests = e.target.checked; TREE = buildTree(); if (!TREE.idx.has(st.zoom)) st.zoom = ""; drawMap(); });
  $("#cpl-seg").addEventListener("click", e => { const b = e.target.closest("[data-c]"); if (!b) return; st.cpl = b.dataset.c; $$("#cpl-seg button").forEach(x => x.setAttribute("aria-pressed", x === b)); $("#pairs").innerHTML = couplingHtml(); });
  $("#findings-list").addEventListener("click", e => { const f = e.target.closest("[data-focus]"); if (f) focusFile(f.dataset.focus); });
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { drawMap(); }, 120); });
  drawMap(); drawLegend(); drawTable();
  const first = hot[0] ? byPath.get(hot[0].p) : (FILES.length ? 0 : null);
  if (first != null) select(first, true); else $("#detail").innerHTML = '<div class="placeholder">Select a file on the map.</div>';
}
init();
})();
