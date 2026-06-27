/* ============================================================
   AAAFlow Studio — frontend (vanilla JS, no build step)
   storyboard JSON -> voiceover -> images -> synced video
   ============================================================ */
"use strict";

/* ---------- tiny helpers ---------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (t, c, h) => { const n = document.createElement(t); if (c) n.className = c; if (h != null) n.innerHTML = h; return n; };
const icon = (id, cls = "") => `<svg class="${cls}"><use href="#${id}"/></svg>`;
const esc = s => (s == null ? "" : String(s)).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pad = n => String(n).padStart(2, "0");
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const dispName = id => (id || "").replace(/_/g, " ");
function fmtClock(s) { s = Math.max(0, Math.round(s || 0)); return `${Math.floor(s / 60)}:${pad(s % 60)}`; }
function fmtSec(s) { return (s == null) ? "—" : `${(+s).toFixed(1)}s`; }
function fmtAgo(ts) { if (!ts) return ""; const d = (Date.now() / 1000) - ts; if (d < 60) return "just now"; if (d < 3600) return `${Math.floor(d / 60)}m ago`; if (d < 86400) return `${Math.floor(d / 3600)}h ago`; return `${Math.floor(d / 86400)}d ago`; }

/* ---------- api ---------- */
async function _err(r) { try { const j = await r.json(); return new Error(j.detail || r.statusText); } catch { return new Error(r.statusText); } }
const api = {
  async get(u) { const r = await fetch(u); if (!r.ok) throw await _err(r); return r.json(); },
  async post(u, b) { const r = await fetch(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) }); if (!r.ok) throw await _err(r); return r.json(); },
  async put(u, b) { const r = await fetch(u, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) }); if (!r.ok) throw await _err(r); return r.json(); },
  async patch(u, b) { const r = await fetch(u, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) }); if (!r.ok) throw await _err(r); return r.json(); },
  async del(u) { const r = await fetch(u, { method: "DELETE" }); if (!r.ok) throw await _err(r); return r.json(); },
  async form(u, fd) { const r = await fetch(u, { method: "POST", body: fd }); if (!r.ok) throw await _err(r); return r.json(); },
};
function pollJob(id, onProgress) {
  return new Promise((resolve, reject) => {
    const t = setInterval(async () => {
      try {
        const j = await api.get("/api/jobs/" + id);
        onProgress && onProgress(j);
        if (j.status === "done") { clearInterval(t); resolve(j.result || {}); }
        else if (j.status === "error") { clearInterval(t); reject(new Error(j.error || "Job failed")); }
      } catch (e) { clearInterval(t); reject(e); }
    }, 700);
  });
}

/* ---------- toast / modal ---------- */
function toast(msg, kind = "ok") {
  const t = el("div", `toast ${kind}`, `${icon(kind === "err" ? "i-x" : "i-check")}<span>${esc(msg)}</span>`);
  $("#toasts").appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = ".4s"; setTimeout(() => t.remove(), 400); }, kind === "err" ? 4600 : 2600);
}
function openModal(html) { const m = $("#modal"); $("#modalCard").innerHTML = html; m.hidden = false; return $("#modalCard"); }
function closeModal() { $("#modal").hidden = true; $("#modalCard").innerHTML = ""; }
$("#modal").addEventListener("click", e => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });
function confirmModal(title, body, okLabel = "Confirm", danger = true) {
  return new Promise(resolve => {
    const card = openModal(`
      <div class="modal-head"><h2 class="mb0">${esc(title)}</h2>
        <button class="btn-icon" id="mClose">${icon("i-x")}</button></div>
      <p class="muted" style="line-height:1.5">${body}</p>
      <div class="row row-end" style="margin-top:20px">
        <button class="btn btn-ghost" id="mCancel">Cancel</button>
        <button class="btn ${danger ? "btn-danger" : "btn-primary"}" id="mOk">${esc(okLabel)}</button></div>`);
    const done = v => { closeModal(); resolve(v); };
    $("#mClose", card).onclick = () => done(false);
    $("#mCancel", card).onclick = () => done(false);
    $("#mOk", card).onclick = () => done(true);
  });
}

/* ---------- state ---------- */
const state = {
  status: {}, settings: {}, voices: { builtin: [], custom: [], languages: [] },
  imageModels: { builtin: [], imported: [], default: "flux-dev" },
  projects: [], history: [],
  currentPid: null, project: null, page: "projects",
};

/* ---------- nav ---------- */
const NAV = [
  { id: "projects", label: "Projects", icon: "i-projects" },
  { sep: true },
  { id: "storyboard", label: "Storyboard", icon: "i-storyboard", proj: true },
  { id: "voiceover", label: "Voiceover", icon: "i-voice", proj: true },
  { id: "images", label: "Images", icon: "i-image", proj: true },
  { id: "assemble", label: "Assemble", icon: "i-assemble", proj: true },
  { id: "preview", label: "Preview", icon: "i-preview", proj: true },
  { sep: true },
  { id: "history", label: "History", icon: "i-history" },
  { id: "voices", label: "Voice Lab", icon: "i-voices" },
  { id: "settings", label: "Settings", icon: "i-settings" },
];
// Project-scoped nav uses the open project, else the most-recently-updated one,
// so the Storyboard/Voiceover/Images/... links work straight from the Projects list.
function effectivePid() {
  if (state.currentPid) return state.currentPid;
  const ps = state.projects || [];
  if (!ps.length) return null;
  return ps.slice().sort((a, b) => (b.updated || 0) - (a.updated || 0))[0].id;
}
function routeFor(item) {
  if (item.proj) { const pid = effectivePid(); return pid ? `#/p/${pid}/${item.id}` : null; }
  return `#/${item.id}`;
}
function renderNav() {
  const nav = $("#nav"); nav.innerHTML = "";
  NAV.forEach(item => {
    if (item.sep) { nav.appendChild(el("div", "nav-sep")); return; }
    const disabled = item.proj && !effectivePid();
    const active = state.page === item.id;
    const b = el("button", "nav-item" + (active ? " is-active" : ""),
      `${icon(item.icon)}<span>${item.label}</span>`);
    if (disabled) b.disabled = true;
    else b.onclick = () => { location.hash = routeFor(item); };
    nav.appendChild(b);
  });
  // project chip
  const chip = $("#projChip");
  if (state.project) {
    chip.hidden = false;
    chip.innerHTML = `<b>${esc(state.project.name)}</b><span>${state.project.scenes.length} scenes</span>`;
  } else chip.hidden = true;
}

/* ---------- chips ---------- */
function renderChips() {
  const s = state.status;
  $("#chipDevice").textContent = s.device === "cuda" ? "GPU · CUDA" : (s.device ? "CPU" : "…");
  $("#chipDevice").className = "chip" + (s.device === "cuda" ? " chip-on" : "");
  // image-engine chip reflects the selected model, not a hardcoded family
  const im = (state.settings && state.settings.image) || {};
  const modelId = (s.image && s.image.model) || im.model || "";
  const reg = state.imageModels || {};
  const found = [...(reg.builtin || []), ...(reg.imported || [])].find(m => m.id === modelId);
  const type = found ? (found.type || found.base_type || "sd") : (/flux/i.test(modelId) ? "flux" : "sd");
  $("#chipFlux").textContent = type === "comfyui" ? "Krea-2 · cartoon" : (type === "flux" ? "FLUX" : "SD 1.5");
  $("#chipFfmpeg").hidden = s.ffmpeg !== false;
}

/* ---------- asset urls ---------- */
const assetUrl = (rel, bust) => rel ? `/projects/${state.currentPid}/${rel}${bust ? "?t=" + bust : ""}` : "";

/* ============================================================
   ROUTER
   ============================================================ */
function parseHash() {
  const h = location.hash.replace(/^#\/?/, "");
  const parts = h.split("/").filter(Boolean);
  if (parts[0] === "p" && parts[1]) return { page: parts[2] || "storyboard", pid: parts[1] };
  return { page: parts[0] || "projects", pid: null };
}
async function loadProject(pid) {
  try { state.project = await api.get(`/api/projects/${pid}`); state.currentPid = pid; }
  catch (e) { toast(e.message, "err"); state.project = null; state.currentPid = null; location.hash = "#/projects"; }
}
async function render() {
  const { page, pid } = parseHash();
  state.page = page;
  if (pid && (!state.project || state.project.id !== pid)) await loadProject(pid);
  if (!pid && page === "projects") { /* keep currentPid sticky for nav */ }
  renderNav(); renderChips();
  const host = $("#views"); host.innerHTML = "";
  const fn = Pages[page] || Pages.projects;
  try { await fn(host); } catch (e) { host.appendChild(el("div", "card", `<p class="muted">${esc(e.message)}</p>`)); }
}
window.addEventListener("hashchange", render);

function topbar(title, sub, actionsHtml = "") {
  $("#topbar").innerHTML = `
    <div><h1>${esc(title)}</h1>${sub ? `<div class="sub">${sub}</div>` : ""}</div>
    <div class="grow"></div><div class="topbar-actions">${actionsHtml}</div>`;
}

/* ============================================================
   PIPELINE STEPPER (shared across project pages)
   ============================================================ */
const STEPS = [
  { id: "storyboard", label: "Storyboard" },
  { id: "voiceover", label: "Voiceover" },
  { id: "images", label: "Images" },
  { id: "assemble", label: "Assemble" },
  { id: "preview", label: "Preview" },
];
function stepper(active) {
  const pid = state.currentPid;
  return `<div class="stepper">${STEPS.map((s, i) => `
    <a class="step ${s.id === active ? "is-active" : ""}" href="#/p/${pid}/${s.id}">
      <span class="n">${i + 1}</span>${s.label}</a>`).join("")}</div>`;
}

/* ============================================================
   PAGE: PROJECTS  (import + list)
   ============================================================ */
async function renderProjects(host) {
  topbar("Projects", "Import a storyboard JSON, then generate voiceovers and images.");
  state.projects = (await api.get("/api/projects")).projects;

  const page = el("div", "page");

  // import card
  const imp = el("div", "card");
  imp.innerHTML = `
    <div class="import-grid">
      <div>
        <div class="section-title">Import storyboard</div>
        <label class="dropzone" id="dz">
          ${icon("i-upload")}
          <b>Drop a storyboard .json here</b>
          <span>or click to choose a file — the { "video", "scenes" } format</span>
          <input type="file" id="fileInput" accept=".json,application/json" hidden />
        </label>
      </div>
      <div>
        <div class="section-title">…or paste JSON</div>
        <div class="field"><input type="text" id="pName" placeholder="Project name (optional)" /></div>
        <div class="field"><textarea id="pText" placeholder='{ "video": {...}, "scenes": [...] }' style="min-height:150px;font-family:var(--font-mono);font-size:12px"></textarea></div>
        <div class="row row-end"><button class="btn btn-primary" id="pCreate">${icon("i-plus")} Create project</button></div>
      </div>
    </div>`;
  page.appendChild(imp);

  // list
  const listWrap = el("div", "card");
  listWrap.style.marginTop = "18px";
  if (!state.projects.length) {
    listWrap.innerHTML = `<div class="empty">${icon("i-projects")}<h3>No projects yet</h3>
      <p>Import the storyboard JSON above to begin. Each scene becomes a timed voiceover + generated image, then synced into a video.</p></div>`;
  } else {
    listWrap.innerHTML = `<div class="section-title">Your projects</div><div class="proj-grid" id="grid"></div>`;
    const grid = $("#grid", listWrap);
    state.projects.forEach(p => grid.appendChild(projectCard(p)));
  }
  page.appendChild(listWrap);
  host.appendChild(page);

  // wire import
  const fileInput = $("#fileInput", page), dz = $("#dz", page);
  fileInput.onchange = () => { if (fileInput.files[0]) uploadProject(fileInput.files[0]); };
  dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("drag"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", e => { e.preventDefault(); dz.classList.remove("drag"); const f = e.dataTransfer.files[0]; if (f) uploadProject(f); });
  $("#pCreate", page).onclick = async () => {
    const text = $("#pText", page).value.trim();
    if (!text) return toast("Paste some JSON or use the file picker.", "err");
    try {
      const { project } = await api.post("/api/projects", { text, name: $("#pName", page).value.trim() || null });
      toast(`Imported “${project.name}” (${project.scenes.length} scenes)`);
      location.hash = `#/p/${project.id}/storyboard`;
    } catch (e) { toast(e.message, "err"); }
  };
}
async function uploadProject(file) {
  const fd = new FormData(); fd.append("file", file);
  try {
    const { project } = await api.form("/api/projects/upload", fd);
    toast(`Imported “${project.name}” (${project.scenes.length} scenes)`);
    location.hash = `#/p/${project.id}/storyboard`;
  } catch (e) { toast(e.message, "err"); }
}
function projectCard(p) {
  const c = el("div", "proj-card");
  const aPct = p.scenes ? Math.round(100 * p.audio_done / p.scenes) : 0;
  const iPct = p.scenes ? Math.round(100 * p.image_done / p.scenes) : 0;
  c.innerHTML = `
    <button class="btn-icon del" title="Delete">${icon("i-trash")}</button>
    <h3>${esc(p.name)}</h3>
    <div class="meta"><span>${p.scenes} scenes</span>${p.target_runtime ? `<span>${esc(p.target_runtime)}</span>` : ""}<span>${fmtAgo(p.updated)}</span></div>
    <div class="pbars">
      <div class="pbar">${icon("i-voice")}<div class="track"><div class="fill audio" style="width:${aPct}%"></div></div><span>${p.audio_done}/${p.scenes}</span></div>
      <div class="pbar">${icon("i-image")}<div class="track"><div class="fill image" style="width:${iPct}%"></div></div><span>${p.image_done}/${p.scenes}</span></div>
    </div>`;
  c.onclick = e => { if (e.target.closest(".del")) return; location.hash = `#/p/${p.id}/storyboard`; };
  $(".del", c).onclick = async (e) => {
    e.stopPropagation();
    if (await confirmModal("Delete project?", `“${esc(p.name)}” and all its generated audio, images and video will be removed.`, "Delete")) {
      try { await api.del(`/api/projects/${p.id}`); if (state.currentPid === p.id) { state.currentPid = null; state.project = null; } toast("Project deleted"); render(); }
      catch (err) { toast(err.message, "err"); }
    }
  };
  return c;
}

/* ============================================================
   PAGE: STORYBOARD
   ============================================================ */
function sceneCounts() {
  const sc = state.project.scenes;
  return {
    total: sc.length,
    audio: sc.filter(s => s.status.audio === "ready").length,
    image: sc.filter(s => s.status.image === "ready").length,
  };
}
async function renderStoryboard(host) {
  const p = state.project;
  if (!p) { location.hash = "#/projects"; return; }
  const c = sceneCounts();
  topbar(p.name, `${c.total} scenes · ${c.audio} voiced · ${c.image} imaged`,
    `<button class="btn btn-ghost" onclick="location.hash='#/projects'">${icon("i-back")} Projects</button>
     <button class="btn btn-primary" onclick="location.hash='#/p/${p.id}/voiceover'">${icon("i-voice")} Voiceover →</button>`);

  const page = el("div", "page page-wide");
  page.innerHTML = stepper("storyboard");

  // meta + toolbar
  const v = p.video || {};
  const meta = el("div", "card");
  meta.innerHTML = `
    <div class="spread">
      <div>
        <h2 class="mb0">${esc(v.title || p.name)}</h2>
        <p class="desc mb0" style="margin-top:6px">${esc(v.niche || "")}${v.format ? " · " + esc(v.format) : ""}</p>
      </div>
      <div class="row">
        ${v.aspect_ratio ? `<span class="badge">${esc(v.aspect_ratio)}</span>` : ""}
        ${v.total_runtime ? `<span class="badge gold">${esc(v.total_runtime)}</span>` : ""}
      </div>
    </div>
    ${v.global_style_suffix ? `<div class="kv" style="margin-top:16px"><div class="k">Global style</div><div class="v mono">${esc(v.global_style_suffix)}</div></div>` : ""}`;
  page.appendChild(meta);

  const tb = el("div", "card");
  tb.style.marginTop = "16px";
  tb.innerHTML = `
    <div class="toolbar">
      <input type="text" id="filter" placeholder="Filter scenes by narration, act or prompt…" style="max-width:380px" />
      <select id="statusFilter" style="max-width:200px">
        <option value="all">All scenes</option>
        <option value="need-audio">Needs voiceover</option>
        <option value="need-image">Needs image</option>
        <option value="ready">Fully ready</option>
      </select>
      <div class="grow"></div>
      <span class="muted mono" id="sceneCount"></span>
    </div>
    <div class="scene-list" id="sceneList"></div>`;
  page.appendChild(tb);
  host.appendChild(page);

  const listEl = $("#sceneList", page), filt = $("#filter", page), stf = $("#statusFilter", page);
  function draw() {
    const q = filt.value.trim().toLowerCase(), sf = stf.value;
    const rows = p.scenes.filter(s => {
      if (q && !(`${s.narration} ${s.act} ${s.image_prompt} ${s.on_screen_text}`.toLowerCase().includes(q))) return false;
      if (sf === "need-audio" && s.status.audio === "ready") return false;
      if (sf === "need-image" && s.status.image === "ready") return false;
      if (sf === "ready" && !(s.status.audio === "ready" && s.status.image === "ready")) return false;
      return true;
    });
    listEl.innerHTML = "";
    rows.forEach(s => listEl.appendChild(sceneRow(s)));
    $("#sceneCount", page).textContent = `${rows.length} / ${p.scenes.length}`;
    if (!rows.length) listEl.innerHTML = `<div class="empty" style="padding:40px">${icon("i-storyboard")}<p>No scenes match.</p></div>`;
  }
  filt.oninput = draw; stf.onchange = draw;
  draw();
}
function statusDot(label, st) {
  const cls = st === "ready" ? "ready" : st === "stale" ? "stale" : st === "run" ? "run" : "";
  return `<span class="sdot ${cls}"><span class="d"></span>${label}</span>`;
}
function sceneRow(s) {
  const r = el("div", "scene-row");
  const img = s.image_file ? `<img src="${assetUrl(s.image_file, s.updated || 1)}" loading="lazy" />` : `#${s.id}`;
  r.innerHTML = `
    <div class="sid">scene<b>${s.id}</b></div>
    <div class="scene-thumb">${img}</div>
    <div class="scene-body">
      <div class="narr">${esc(s.narration) || '<span class="muted">— no narration —</span>'}</div>
      <div class="sub">
        <span>${esc(s.timecode || (fmtSec(s.planned_dur)))}</span>
        ${s.shot ? `<span>${esc(s.shot)}</span>` : ""}
        ${s.audio_dur ? `<span class="badge good" style="padding:1px 6px">${fmtSec(s.audio_dur)} real</span>` : ""}
        ${s.on_screen_text ? `<span class="ost">“${esc(s.on_screen_text)}”</span>` : ""}
      </div>
    </div>
    <div class="scene-meta">
      <div class="statusdots">
        ${statusDot("VO", s.status.audio)}
        ${statusDot("IMG", s.status.image)}
      </div>
      <button class="btn-icon" title="Open">${icon("i-edit")}</button>
    </div>`;
  r.onclick = () => openScene(s.id);
  return r;
}

/* scene detail modal (view + edit; per-scene generate buttons added in later phases) */
function openScene(sid) {
  const p = state.project, s = p.scenes.find(x => String(x.id) === String(sid));
  if (!s) return;
  const v = p.video || {};
  const card = openModal(`
    <div class="modal-head">
      <div><h2 class="mb0">Scene ${s.id}</h2><div class="sub muted">${esc(s.act || "")} · ${esc(s.timecode || fmtSec(s.planned_dur))}</div></div>
      <button class="btn-icon" id="scClose">${icon("i-x")}</button>
    </div>
    ${s.image_file ? `<div class="player" style="margin-bottom:16px"><div class="stage"><img src="${assetUrl(s.image_file, Date.now())}"/></div></div>` : ""}
    ${s.audio_file ? `<audio controls style="width:100%;margin-bottom:16px" src="${assetUrl(s.audio_file, Date.now())}"></audio>` : ""}
    <div class="field"><label>Narration</label><textarea id="scNarr" rows="3">${esc(s.narration)}</textarea></div>
    <div class="field"><label>Image prompt</label><textarea id="scPrompt" rows="3">${esc(s.image_prompt)}</textarea></div>
    <div class="grid2">
      <div class="field"><label>On-screen text</label><input type="text" id="scOst" value="${esc(s.on_screen_text)}" /></div>
      <div class="field"><label>Transition</label><input type="text" id="scTrans" value="${esc(s.transition)}" /></div>
    </div>
    ${s.visual ? `<div class="kv"><div class="k">Visual direction</div><div class="v">${esc(s.visual)}</div></div>` : ""}
    <div class="spread" style="margin-top:18px">
      <div class="row" id="scGen"></div>
      <div class="row">
        <button class="btn btn-ghost" id="scCancel">Close</button>
        <button class="btn btn-primary" id="scSave">Save changes</button>
      </div>
    </div>`);
  const genRow = $("#scGen", card);
  const voBtn = el("button", "btn btn-ghost", `${icon("i-voice")} ${s.status.audio === "ready" ? "Re-voice" : "Voiceover"}`);
  voBtn.onclick = () => quickVoice(s.id);
  genRow.appendChild(voBtn);
  if (typeof addSceneImageButton === "function") addSceneImageButton(genRow, s);
  $("#scClose", card).onclick = closeModal;
  $("#scCancel", card).onclick = closeModal;
  $("#scSave", card).onclick = async () => {
    const patch = {
      narration: $("#scNarr", card).value.trim(),
      image_prompt: $("#scPrompt", card).value.trim(),
      on_screen_text: $("#scOst", card).value,
      transition: $("#scTrans", card).value,
    };
    try {
      const updated = await api.patch(`/api/projects/${p.id}/scenes/${s.id}`, patch);
      Object.assign(s, updated);
      toast("Scene updated"); closeModal(); render();
    } catch (e) { toast(e.message, "err"); }
  };
}

/* per-scene voiceover using the project's saved voice (from Storyboard modal) */
async function quickVoice(sid) {
  const p = state.project;
  const voice = Object.assign({ mode: "custom", speaker: "Ryan", language: "English" }, p.settings.voice || {});
  try {
    toast(`Voicing scene ${sid}…`);
    const { job_id } = await api.post(`/api/projects/${p.id}/voiceover`, { voice, scope: "scene", scene_id: String(sid) });
    await pollJob(job_id);
    await loadProject(p.id);
    toast(`Scene ${sid} voiced`); closeModal(); render();
  } catch (e) { toast(e.message, "err"); }
}

/* ============================================================
   PLACEHOLDER PAGES (filled in later phases)
   ============================================================ */
function placeholder(host, title, sub, body) {
  topbar(title, sub, state.currentPid ? `<button class="btn btn-ghost" onclick="location.hash='#/p/${state.currentPid}/storyboard'">${icon("i-back")} Storyboard</button>` : "");
  const page = el("div", "page");
  if (state.currentPid && STEPS.some(s => s.id === state.page)) page.innerHTML = stepper(state.page);
  page.appendChild(el("div", "card", `<div class="empty">${icon("i-wand")}<h3>${esc(title)}</h3><p>${body}</p></div>`));
  host.appendChild(page);
}
async function renderVoiceover(host) {
  const p = state.project; if (!p) { location.hash = "#/projects"; return; }
  const c = sceneCounts();
  topbar(p.name, `Voiceover · ${c.audio}/${c.total} scenes voiced`,
    `<button class="btn btn-ghost" onclick="location.hash='#/p/${p.id}/storyboard'">${icon("i-back")} Storyboard</button>
     <button class="btn btn-primary" onclick="location.hash='#/p/${p.id}/images'">${icon("i-image")} Images →</button>`);
  const page = el("div", "page page-wide");
  page.innerHTML = stepper("voiceover");

  const sel = Object.assign({ mode: "custom", speaker: "Ryan", voice_id: null, language: "English", instruct: "" }, p.settings.voice || {});

  const vcard = el("div", "card");
  vcard.innerHTML = `
    <h2>Voice</h2>
    <p class="desc">Pick the narrator. Each scene is synthesized to its own clip; the timeline rebuilds from the real audio length (audio-led sync), so images always match the narration.</p>
    <div class="row" id="voModes" style="margin-bottom:14px"></div>
    <div class="opt-list" id="voList"></div>
    <div class="grid2" style="margin-top:16px">
      <div class="field"><label>Language</label><select id="voLang"></select></div>
      <div class="field"><label>Style / emotion <span class="hint">(optional, 1.7B only)</span></label><input type="text" id="voInstruct" placeholder="e.g. calm documentary narrator, measured pacing" value="${esc(sel.instruct || "")}"/></div>
    </div>
    <div class="row"><button class="btn btn-ghost" id="voPreview">${icon("i-play")} Preview voice</button><span class="muted mono" id="voPrevMsg"></span></div>`;
  page.appendChild(vcard);

  const gcard = el("div", "card"); gcard.style.marginTop = "16px";
  gcard.innerHTML = `
    <div class="spread"><h2 class="mb0">Generate</h2><div class="row" id="voTiming"></div></div>
    <p class="desc">Synthesize narration for every scene. Long batches run in the background — watch progress below.</p>
    <div class="row" id="voActions"></div>
    <div id="voRun" style="margin-top:16px"></div>
    <div class="divider"></div>
    <div class="scene-list" id="voScenes"></div>`;
  page.appendChild(gcard);
  host.appendChild(page);

  const langSel = $("#voLang", page);
  langSel.innerHTML = (state.voices.languages || ["Auto", "English"]).map(l => `<option value="${l}">${l === "Auto" ? "Auto-detect" : l}</option>`).join("");
  langSel.value = sel.language || "English";
  langSel.onchange = () => sel.language = langSel.value;
  $("#voInstruct", page).oninput = e => sel.instruct = e.target.value;

  const modesEl = $("#voModes", page);
  function drawModes() {
    modesEl.innerHTML = "";
    [["custom", "Built-in speakers"], ["clone", "Your voices"]].forEach(([k, lab]) => {
      const b = el("button", "btn btn-sm " + (sel.mode === k ? "btn-primary" : "btn-ghost"), lab);
      b.onclick = () => { sel.mode = k; drawModes(); drawVoices(); };
      modesEl.appendChild(b);
    });
  }
  function drawVoices() {
    const list = $("#voList", page); list.innerHTML = "";
    if (sel.mode === "clone") {
      const cs = state.voices.custom || [];
      if (!cs.length) { list.innerHTML = `<div class="muted" style="padding:14px">No custom voices yet — create one in <a href="#/voices">Voice Lab</a>, or use a built-in speaker.</div>`; return; }
      if (!sel.voice_id || !cs.some(v => v.id === sel.voice_id)) sel.voice_id = cs[0].id;
      cs.forEach(v => {
        const o = el("div", "opt" + (sel.voice_id === v.id ? " sel" : ""), `<div><div class="nm">${esc(v.name)}</div><div class="ds">${esc(v.type)} voice${v.language ? " · " + esc(v.language) : ""}</div></div><div class="pick"></div>`);
        o.onclick = () => { sel.voice_id = v.id; drawVoices(); }; list.appendChild(o);
      });
    } else {
      (state.voices.builtin || []).forEach(v => {
        const o = el("div", "opt" + (sel.speaker === v.id ? " sel" : ""), `<div><div class="nm">${dispName(v.id)} ${v.youtube ? '<span class="badge gold" style="padding:1px 6px">YT</span>' : ''}</div><div class="ds">${esc(v.native)} · ${esc(v.desc)}</div></div><div class="pick"></div>`);
        o.onclick = () => { sel.speaker = v.id; drawVoices(); }; list.appendChild(o);
      });
    }
  }
  drawModes(); drawVoices();

  function timing() {
    const tl = state.project.timeline;
    const planned = (state.project.video && state.project.video.total_runtime_sec) || state.project.scenes.reduce((a, s) => a + (s.planned_dur || 0), 0);
    const cnt = sceneCounts();
    $("#voTiming", page).innerHTML =
      `<span class="badge">planned ${fmtClock(planned)}</span>` +
      (tl && tl.total_dur ? `<span class="badge gold">real ${fmtClock(tl.total_dur)}</span>` : "") +
      `<span class="badge ${cnt.audio === cnt.total ? "good" : ""}">${cnt.audio}/${cnt.total} voiced</span>`;
  }
  function actions() {
    const cnt = sceneCounts();
    const missing = state.project.scenes.filter(s => (s.narration || "").trim() && s.status.audio !== "ready").length;
    const a = $("#voActions", page); a.innerHTML = "";
    const gen = el("button", "btn btn-primary", `${icon("i-wand")} Generate missing (${missing})`);
    gen.disabled = missing === 0; gen.onclick = () => runVO("missing");
    const all = el("button", "btn btn-ghost", `${icon("i-refresh")} Re-voice all (${cnt.total})`);
    all.onclick = () => runVO("all");
    a.append(gen, all);
  }
  function drawScenes() {
    const list = $("#voScenes", page); list.innerHTML = "";
    state.project.scenes.forEach(s => {
      if (!(s.narration || "").trim()) return;
      const row = el("div", "scene-row"); row.style.gridTemplateColumns = "54px 1fr auto";
      const real = s.audio_dur ? `<span class="badge good" style="padding:1px 6px">${fmtSec(s.audio_dur)}</span>` : `<span class="badge">~${fmtSec(s.planned_dur)}</span>`;
      row.innerHTML = `<div class="sid">scene<b>${s.id}</b></div>
        <div class="scene-body"><div class="narr">${esc(s.narration)}</div>
        <div class="sub">${real}${s.audio_voice ? ` <span>${esc(s.audio_voice)}</span>` : ""}</div></div>
        <div class="scene-meta">${s.audio_file ? `<audio controls preload="none" style="height:32px;max-width:200px" src="${assetUrl(s.audio_file, Date.now())}"></audio>` : ""}
        <button class="btn-icon" title="Voice this scene">${icon("i-wand")}</button></div>`;
      $(".btn-icon", row).onclick = () => runVO("scene", s.id);
      list.appendChild(row);
    });
  }
  timing(); actions(); drawScenes();

  $("#voPreview", page).onclick = async () => {
    const msg = $("#voPrevMsg", page); msg.textContent = "synthesizing…";
    try {
      const body = { mode: sel.mode, preview: true, language: sel.language, instruct: sel.instruct || null, text: "Hey, here's a quick preview of how this narrator will sound." };
      if (sel.mode === "clone") body.voice_id = sel.voice_id; else body.speaker = sel.speaker;
      const { job_id } = await api.post("/api/tts", body);
      const res = await pollJob(job_id, j => { msg.textContent = j.stage + " " + Math.round((j.progress || 0) * 100) + "%"; });
      const f = res.item && res.item.files && (res.item.files.mp3 || res.item.files.wav);
      if (f) { new Audio("/audio/" + f).play(); msg.textContent = "▶ playing"; } else msg.textContent = "";
    } catch (e) { msg.textContent = ""; toast(e.message, "err"); }
  };

  async function runVO(scope, sceneId) {
    const runEl = $("#voRun", page);
    runEl.innerHTML = `<div class="run-panel"><div class="spinner"></div><div style="flex:1"><div class="lab" id="voStage">Starting…</div><div class="progress" style="margin-top:8px"><div class="bar" id="voBar"></div></div></div></div>`;
    try {
      const { job_id } = await api.post(`/api/projects/${state.project.id}/voiceover`, { voice: sel, scope, scene_id: sceneId != null ? String(sceneId) : null });
      const res = await pollJob(job_id, j => { const st = $("#voStage", page); if (st) st.textContent = j.stage; const b = $("#voBar", page); if (b) b.style.width = Math.round((j.progress || 0) * 100) + "%"; });
      await loadProject(state.project.id);
      runEl.innerHTML = "";
      toast(`Voiced ${res.done} scene(s) · ${fmtClock(res.timeline.total_dur)} total`);
      timing(); actions(); drawScenes(); renderNav();
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
  }
}
async function refreshImageModels() {
  try { state.imageModels = await api.get("/api/image_models"); } catch (e) { }
}
async function renderImages(host) {
  const p = state.project; if (!p) { location.hash = "#/projects"; return; }
  await refreshImageModels();
  const c = sceneCounts();
  topbar(p.name, `Images · ${c.image}/${c.total} rendered`,
    `<button class="btn btn-ghost" onclick="location.hash='#/p/${p.id}/voiceover'">${icon("i-back")} Voiceover</button>
     <button class="btn btn-primary" onclick="location.hash='#/p/${p.id}/assemble'">${icon("i-assemble")} Assemble →</button>`);
  const page = el("div", "page page-wide"); page.innerHTML = stepper("images");

  const cfg = Object.assign({ model: "local-sd15", steps: null, guidance: null, width: null, height: null, seed: -1, use_default_lora: true, default_lora_weight: 0.95, gguf_quant: "Q4_K_S", loras: [] }, state.settings.image || {}, p.settings.image || {});
  cfg.loras = (cfg.loras || []).slice();

  const builtin = state.imageModels.builtin || [];
  const importedCk = (state.imageModels.imported || []).filter(m => m.kind === "checkpoint");
  const importedLora = (state.imageModels.imported || []).filter(m => m.kind === "lora");
  const bmap = {}; builtin.forEach(m => bmap[m.id] = m);
  importedCk.forEach(m => bmap[m.id] = { ...m, type: m.type || m.base_type || "sd" });
  const mdef = () => bmap[cfg.model] || { type: "sd", steps: 26, guidance: 7, width: 896, height: 512 };
  const isFlux = () => mdef().type === "flux";
  const dflt = (k, d) => { const v = cfg[k]; return (v === null || v === undefined || v === "") ? (mdef()[k] != null ? mdef()[k] : d) : v; };

  const mcard = el("div", "card");
  mcard.innerHTML = `
    <div class="spread"><h2 class="mb0">Model</h2><span class="badge teal" id="imLoaded"></span></div>
    <p class="desc">Default is <b>Krea-2 Turbo</b> — your local flat-cartoon model, rendered through ComfyUI (no download). <b>SD&nbsp;1.5</b> / <b>FLUX</b> remain available via the in-app diffusers engine. Import your own checkpoints / LoRAs anytime.</p>
    <div class="grid2">
      <div class="field"><label>Base model</label><select id="imModel">
        ${builtin.map(m => `<option value="${m.id}" ${cfg.model === m.id ? "selected" : ""}>${esc(m.label)}${m.size ? " · " + esc(m.size) : ""}${m.gated ? " · gated" : ""}</option>`).join("")}
        ${importedCk.map(m => `<option value="${m.id}" ${cfg.model === m.id ? "selected" : ""}>${esc(m.label)} (imported)</option>`).join("")}
      </select></div>
      <div class="field" id="imQuantField"><label>GGUF quant <span class="hint">(FLUX download size)</span></label><select id="imQuant">
        ${["Q4_K_S", "Q5_K_S", "Q8_0"].map(q => `<option value="${q}" ${cfg.gguf_quant === q ? "selected" : ""}>${q}</option>`).join("")}
      </select></div>
    </div>
    <div class="row"><button class="btn btn-ghost" id="imWarm">${icon("i-download")} Download / warm model</button><span class="muted mono" id="imWarmMsg"></span></div>
    <div class="divider"></div>
    <div class="section-title">Style LoRAs</div>
    <div id="imBuiltinLora">
      <label class="switch" style="margin-bottom:12px"><input type="checkbox" id="imDefLora" ${cfg.use_default_lora ? "checked" : ""}/><span class="track"></span> Built-in simple-sketch / stick-figure LoRA <span class="hint">(FLUX)</span></label>
      <div class="field" id="imDefWrap"><label>Built-in LoRA strength <span class="hint" id="imDefVal"></span></label><input type="range" min="0" max="1.5" step="0.05" id="imDefW" value="${cfg.default_lora_weight}"/></div>
    </div>
    <div id="imLoraList"></div>
    <div class="row"><button class="btn btn-ghost btn-sm" id="imImport">${icon("i-plus")} Import LoRA / checkpoint</button></div>
    <div class="divider"></div>
    <div class="grid3">
      <div class="field"><label>Steps</label><input type="number" id="imSteps" value="${dflt('steps', 26)}" min="1" max="60"/></div>
      <div class="field"><label>Guidance</label><input type="number" id="imGuid" value="${dflt('guidance', 7)}" step="0.5" min="0" max="12"/></div>
      <div class="field"><label>Seed <span class="hint">(-1 random)</span></label><input type="number" id="imSeed" value="${cfg.seed}"/></div>
      <div class="field"><label>Width</label><input type="number" id="imW" value="${dflt('width', 896)}" step="16"/></div>
      <div class="field"><label>Height</label><input type="number" id="imH" value="${dflt('height', 512)}" step="16"/></div>
    </div>`;
  page.appendChild(mcard);

  const gcard = el("div", "card"); gcard.style.marginTop = "16px";
  gcard.innerHTML = `
    <div class="spread"><h2 class="mb0">Generate</h2><div class="row" id="imCounts"></div></div>
    <p class="desc">Each scene's prompt = its <b>image_prompt</b> + the storyboard's global style. Batches run in the background.</p>
    <div class="row" id="imActions"></div>
    <div id="imRun" style="margin-top:16px"></div>
    <div class="divider"></div>
    <div class="media-grid" id="imGrid"></div>`;
  page.appendChild(gcard);
  host.appendChild(page);

  // --- wire model card ---
  const st = state.status.image || {};
  $("#imLoaded", page).textContent = st.loaded ? `loaded: ${st.model || ""}` : "model not loaded";
  const setVal = () => $("#imDefVal", page).textContent = (+$("#imDefW", page).value).toFixed(2);
  const syncDef = () => { $("#imDefWrap", page).style.display = $("#imDefLora", page).checked ? "" : "none"; };
  const applyVis = () => {
    const flux = isFlux();
    $("#imQuantField", page).style.display = flux ? "" : "none";
    $("#imBuiltinLora", page).style.display = flux ? "" : "none";
    if (flux) syncDef();
  };
  setVal(); applyVis();
  $("#imModel", page).onchange = e => {
    cfg.model = e.target.value;
    cfg.steps = cfg.guidance = cfg.width = cfg.height = null;   // re-derive for new model
    $("#imSteps", page).value = dflt('steps', 26);
    $("#imGuid", page).value = dflt('guidance', 7);
    $("#imW", page).value = dflt('width', 896);
    $("#imH", page).value = dflt('height', 512);
    applyVis();
  };
  $("#imQuant", page).onchange = e => { cfg.gguf_quant = e.target.value; };
  $("#imDefLora", page).onchange = e => { cfg.use_default_lora = e.target.checked; syncDef(); };
  $("#imDefW", page).oninput = e => { cfg.default_lora_weight = +e.target.value; setVal(); };
  $("#imSteps", page).oninput = e => cfg.steps = +e.target.value;
  $("#imGuid", page).oninput = e => cfg.guidance = +e.target.value;
  $("#imSeed", page).oninput = e => cfg.seed = +e.target.value;
  $("#imW", page).oninput = e => cfg.width = +e.target.value;
  $("#imH", page).oninput = e => cfg.height = +e.target.value;

  function drawLoras() {
    const wrap = $("#imLoraList", page); wrap.innerHTML = "";
    if (!importedLora.length) { wrap.innerHTML = `<div class="muted" style="font-size:13px;margin-bottom:8px">No imported LoRAs yet.</div>`; return; }
    importedLora.forEach(m => {
      const on = cfg.loras.find(x => x.id === m.id);
      const row = el("div", "row", `
        <label class="switch"><input type="checkbox" ${on ? "checked" : ""}/><span class="track"></span> ${esc(m.label)}</label>
        <input type="number" step="0.05" min="0" max="1.5" value="${on ? on.weight : (m.weight || 1)}" style="width:90px" ${on ? "" : "disabled"}/>
        <button class="btn-icon btn-danger" title="Delete">${icon("i-trash")}</button>`);
      row.style.marginBottom = "8px";
      const [chk, wt] = $$("input", row);
      chk.onchange = () => {
        if (chk.checked) { cfg.loras.push({ id: m.id, weight: +wt.value }); wt.disabled = false; }
        else { cfg.loras = cfg.loras.filter(x => x.id !== m.id); wt.disabled = true; }
      };
      wt.oninput = () => { const e = cfg.loras.find(x => x.id === m.id); if (e) e.weight = +wt.value; };
      $(".btn-danger", row).onclick = async () => {
        if (await confirmModal("Delete LoRA?", esc(m.label), "Delete")) {
          await api.del(`/api/image_models/${m.id}`); await refreshImageModels(); render();
        }
      };
      wrap.appendChild(row);
    });
  }
  drawLoras();

  $("#imImport", page).onclick = () => importImageModel();
  $("#imWarm", page).onclick = async () => {
    const msg = $("#imWarmMsg", page); msg.textContent = "starting…";
    try {
      await api.put(`/api/projects/${p.id}/settings`, { image: cfg });
      await api.put("/api/settings", { image: cfg });
      const { job_id } = await api.post("/api/image/download_defaults", {});
      await pollJob(job_id, j => msg.textContent = j.stage + " " + Math.round((j.progress || 0) * 100) + "%");
      msg.textContent = "model ready ✓"; state.status = await api.get("/api/status"); $("#imLoaded", page).textContent = "model loaded";
    } catch (e) { msg.textContent = ""; toast(e.message, "err"); }
  };

  // --- generate ---
  function counts() {
    const cc = sceneCounts();
    $("#imCounts", page).innerHTML = `<span class="badge ${cc.image === cc.total ? "good" : ""}">${cc.image}/${cc.total} rendered</span>`;
  }
  function actions() {
    const missing = state.project.scenes.filter(s => s.status.image !== "ready" && (s.image_prompt || s.visual || s.narration)).length;
    const a = $("#imActions", page); a.innerHTML = "";
    const gen = el("button", "btn btn-primary", `${icon("i-wand")} Generate missing (${missing})`);
    gen.disabled = missing === 0; gen.onclick = () => runIMG("missing");
    const all = el("button", "btn btn-ghost", `${icon("i-refresh")} Re-render all (${state.project.scenes.length})`);
    all.onclick = () => runIMG("all");
    a.append(gen, all);
  }
  function drawGrid() {
    const grid = $("#imGrid", page); grid.innerHTML = "";
    state.project.scenes.forEach(s => {
      const card = el("div", "media-card");
      const frame = s.image_file
        ? `<img src="${assetUrl(s.image_file, Date.now())}" loading="lazy"/>`
        : `<div class="ph">scene ${s.id}<br><span class="muted">not rendered</span></div>`;
      card.innerHTML = `<div class="frame">${frame}</div>
        <div class="cap"><div class="t">scene <b>${s.id}</b></div>
        <button class="btn-icon" title="Render this scene">${icon("i-wand")}</button></div>`;
      $(".btn-icon", card).onclick = () => runIMG("scene", s.id);
      card.querySelector(".frame").onclick = () => openScene(s.id);
      grid.appendChild(card);
    });
  }
  counts(); actions(); drawGrid();

  async function runIMG(scope, sceneId) {
    const runEl = $("#imRun", page);
    runEl.innerHTML = `<div class="run-panel"><div class="spinner"></div><div style="flex:1"><div class="lab" id="imStage">Starting…</div><div class="progress teal" style="margin-top:8px"><div class="bar" id="imBar"></div></div></div></div>`;
    try {
      await api.put(`/api/projects/${p.id}/settings`, { image: cfg });
      const { job_id } = await api.post(`/api/projects/${p.id}/images`, { image: cfg, scope, scene_id: sceneId != null ? String(sceneId) : null });
      const res = await pollJob(job_id, j => { const s = $("#imStage", page); if (s) s.textContent = j.stage; const b = $("#imBar", page); if (b) b.style.width = Math.round((j.progress || 0) * 100) + "%"; });
      await loadProject(p.id); runEl.innerHTML = "";
      toast(`Rendered ${res.done} image(s)`);
      counts(); actions(); drawGrid(); renderNav();
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
  }
}

/* import LoRA / checkpoint modal */
function importImageModel() {
  const card = openModal(`
    <div class="modal-head"><h2 class="mb0">Import model</h2><button class="btn-icon" id="iiClose">${icon("i-x")}</button></div>
    <p class="muted" style="font-size:13px">Add a FLUX LoRA or a single-file checkpoint (.safetensors / .gguf). Files are copied into the project's local models folder.</p>
    <div class="field"><label>Type</label><select id="iiKind"><option value="lora">LoRA</option><option value="checkpoint">Checkpoint (transformer)</option></select></div>
    <div class="field"><label>Label</label><input type="text" id="iiLabel" placeholder="e.g. My stick-figure LoRA"/></div>
    <div class="grid2">
      <div class="field"><label>Trigger word (LoRA, optional)</label><input type="text" id="iiTrig" placeholder="e.g. stick figure"/></div>
      <div class="field"><label>Default weight</label><input type="number" id="iiW" value="0.9" step="0.05" min="0" max="1.5"/></div>
    </div>
    <div class="field"><label>File</label><input type="file" id="iiFile" accept=".safetensors,.gguf,.ckpt"/></div>
    <div class="row row-end"><button class="btn btn-ghost" id="iiCancel">Cancel</button><button class="btn btn-primary" id="iiGo">${icon("i-upload")} Import</button></div>
    <div class="muted mono" id="iiMsg" style="margin-top:10px"></div>`);
  $("#iiClose", card).onclick = closeModal; $("#iiCancel", card).onclick = closeModal;
  $("#iiGo", card).onclick = async () => {
    const f = $("#iiFile", card).files[0];
    if (!f) return toast("Choose a file", "err");
    const fd = new FormData();
    fd.append("file", f); fd.append("kind", $("#iiKind", card).value);
    fd.append("label", $("#iiLabel", card).value); fd.append("trigger", $("#iiTrig", card).value);
    fd.append("weight", $("#iiW", card).value);
    $("#iiMsg", card).textContent = "uploading…";
    try { await api.form("/api/image_models/import", fd); await refreshImageModels(); closeModal(); toast("Model imported"); render(); }
    catch (e) { $("#iiMsg", card).textContent = ""; toast(e.message, "err"); }
  };
}

/* per-scene image button (used by the Storyboard scene modal) */
function addSceneImageButton(genRow, s) {
  const b = el("button", "btn btn-ghost", `${icon("i-image")} ${s.status.image === "ready" ? "Re-image" : "Image"}`);
  b.onclick = () => quickImage(s.id);
  genRow.appendChild(b);
}
async function quickImage(sid) {
  const p = state.project;
  const cfg = Object.assign({}, state.settings.image || {}, p.settings.image || {});
  try {
    toast(`Rendering scene ${sid}…`);
    const { job_id } = await api.post(`/api/projects/${p.id}/images`, { image: cfg, scope: "scene", scene_id: String(sid) });
    await pollJob(job_id);
    await loadProject(p.id); toast(`Scene ${sid} rendered`); closeModal(); render();
  } catch (e) { toast(e.message, "err"); }
}
async function renderAssemble(host) {
  const p = state.project; if (!p) { location.hash = "#/projects"; return; }
  const c = sceneCounts();
  topbar(p.name, `Assemble · sync voiceover + images into MP4`,
    `<button class="btn btn-ghost" onclick="location.hash='#/p/${p.id}/images'">${icon("i-back")} Images</button>
     <button class="btn btn-primary" onclick="location.hash='#/p/${p.id}/preview'">${icon("i-preview")} Preview →</button>`);
  const page = el("div", "page"); page.innerHTML = stepper("assemble");

  const opts = Object.assign({ width: 1920, height: 1080, fps: 30, ken_burns: true, transitions: true, burn_text: true }, p.settings.assemble || {});
  const RES = [[1920, 1080, "1080p"], [1280, 720, "720p"], [854, 480, "480p (fast)"]];

  const card = el("div", "card");
  card.innerHTML = `
    <h2>Build the video</h2>
    <p class="desc">Each scene shows for its real narration length (audio-led). Stills get a gentle Ken Burns move; on-screen text is composited in post. Scenes without an image use a placeholder card; without audio, they play silent — so a partial project still renders.</p>
    <div class="row" style="margin-bottom:14px">
      <span class="badge ${c.audio === c.total ? "good" : "warn"}">${c.audio}/${c.total} voiced</span>
      <span class="badge ${c.image === c.total ? "good" : "warn"}">${c.image}/${c.total} imaged</span>
    </div>
    <div class="grid3">
      <div class="field"><label>Resolution</label><select id="asRes">
        ${RES.map(([w, h, l]) => `<option value="${w}x${h}" ${opts.width === w ? "selected" : ""}>${l} (${w}×${h})</option>`).join("")}
      </select></div>
      <div class="field"><label>FPS</label><select id="asFps">${[24, 30, 60].map(f => `<option ${opts.fps === f ? "selected" : ""}>${f}</option>`).join("")}</select></div>
      <div class="field" style="justify-content:flex-end"><label>&nbsp;</label>
        <div class="row" style="gap:18px">
          <label class="switch"><input type="checkbox" id="asKB" ${opts.ken_burns ? "checked" : ""}/><span class="track"></span> Ken Burns</label>
        </div></div>
    </div>
    <div class="row" style="gap:18px;margin-bottom:8px">
      <label class="switch"><input type="checkbox" id="asTrans" ${opts.transitions ? "checked" : ""}/><span class="track"></span> Transitions (crossfade)</label>
      <label class="switch"><input type="checkbox" id="asText" ${opts.burn_text ? "checked" : ""}/><span class="track"></span> Burn in on-screen text</label>
    </div>
    <div class="row"><button class="btn btn-primary" id="asGo">${icon("i-assemble")} Build video</button>
      <span class="muted" id="asEta"></span></div>
    <div id="asRun" style="margin-top:16px"></div>`;
  page.appendChild(card);

  const rcard = el("div", "card"); rcard.style.marginTop = "16px";
  rcard.innerHTML = `<div class="section-title">Renders</div><div id="asRenders"></div>`;
  page.appendChild(rcard);
  host.appendChild(page);

  $("#asRes", page).onchange = e => { const [w, h] = e.target.value.split("x").map(Number); opts.width = w; opts.height = h; };
  $("#asFps", page).onchange = e => opts.fps = +e.target.value;
  $("#asKB", page).onchange = e => opts.ken_burns = e.target.checked;
  $("#asTrans", page).onchange = e => opts.transitions = e.target.checked;
  $("#asText", page).onchange = e => opts.burn_text = e.target.checked;

  function drawRenders() {
    const wrap = $("#asRenders", page);
    const rs = state.project.renders || [];
    if (!rs.length) { wrap.innerHTML = `<div class="muted" style="font-size:13px">No renders yet.</div>`; return; }
    wrap.innerHTML = "";
    rs.forEach(r => {
      const url = `/projects/${state.project.id}/${r.file}?t=${Math.round(r.created)}`;
      const row = el("div", "card"); row.style.background = "var(--panel-2)"; row.style.marginBottom = "12px";
      row.innerHTML = `
        <div class="spread" style="margin-bottom:10px">
          <div><b>${fmtClock(r.duration)}</b> <span class="muted mono">· ${r.width}×${r.height} · ${r.fps}fps · ${r.scenes} scenes · ${fmtAgo(r.created)}</span></div>
          <a class="btn btn-sm btn-ghost" href="${url}" download>${icon("i-download")} Download</a>
        </div>
        <video controls preload="metadata" style="width:100%;border-radius:10px;background:#000" src="${url}"></video>`;
      wrap.appendChild(row);
    });
  }
  drawRenders();

  $("#asGo", page).onclick = async () => {
    const runEl = $("#asRun", page);
    runEl.innerHTML = `<div class="run-panel"><div class="spinner"></div><div style="flex:1"><div class="lab" id="asStage">Starting…</div><div class="progress" style="margin-top:8px"><div class="bar" id="asBar"></div></div></div></div>`;
    try {
      await api.put(`/api/projects/${p.id}/settings`, { assemble: opts });
      const { job_id } = await api.post(`/api/projects/${p.id}/assemble`, { opts });
      const res = await pollJob(job_id, j => { const s = $("#asStage", page); if (s) s.textContent = j.stage; const b = $("#asBar", page); if (b) b.style.width = Math.round((j.progress || 0) * 100) + "%"; });
      await loadProject(p.id); runEl.innerHTML = "";
      toast("Video assembled ✓"); drawRenders();
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
  };
}
async function renderPreview(host) {
  const p = state.project; if (!p) { location.hash = "#/projects"; return; }
  topbar(p.name, "Preview · in-browser timeline (audio-led)",
    `<button class="btn btn-ghost" onclick="location.hash='#/p/${p.id}/assemble'">${icon("i-back")} Assemble</button>`);
  const page = el("div", "page"); page.innerHTML = stepper("preview");

  // timeline rows: prefer the saved (audio-led) timeline, else plan from durations
  let rows = (p.timeline && p.timeline.scenes) ? p.timeline.scenes.slice() : null;
  if (!rows) {
    let t = 0; rows = p.scenes.map(s => { const d = Math.max(1.2, s.planned_dur || 2); const r = { id: s.id, start: t, end: t + d, dur: d }; t += d; return r; });
  }
  const byId = {}; p.scenes.forEach(s => byId[s.id] = s);
  const total = rows.length ? rows[rows.length - 1].end : 0;

  const card = el("div", "card");
  card.innerHTML = `
    <div class="player">
      <div class="stage" id="pvStage">
        <img id="pvImg" style="display:none"/>
        <div id="pvPh" class="ph muted" style="font-family:var(--font-display);font-size:28px">scene</div>
        <div class="ost-overlay" id="pvOst"></div>
      </div>
      <div class="ctrl">
        <button class="btn-icon" id="pvPlay" style="font-size:22px">${icon("i-play")}</button>
        <div class="time" id="pvTime">0:00 / ${fmtClock(total)}</div>
        <div class="scrub" id="pvScrub"><div class="marks" id="pvMarks"></div><div class="seek" id="pvSeek"></div></div>
      </div>
    </div>
    <div class="now-narr" id="pvNarr"></div>`;
  page.appendChild(card);
  host.appendChild(page);

  const audio = new Audio();
  const stageImg = $("#pvImg", page), ph = $("#pvPh", page), ostEl = $("#pvOst", page);
  const seek = $("#pvSeek", page), timeEl = $("#pvTime", page), narrEl = $("#pvNarr", page), playBtn = $("#pvPlay", page);

  // scene boundary markers
  $("#pvMarks", page).innerHTML = rows.map(r => total ? `<div class="mk" style="left:${(r.start / total) * 100}%"></div>` : "").join("");

  let playing = false, t = 0, curIdx = -1, raf = null, last = 0;
  const sceneAt = (tt) => { for (let i = 0; i < rows.length; i++) if (tt >= rows[i].start && tt < rows[i].end) return i; return rows.length - 1; };

  function showScene(i, seekAudio) {
    curIdx = i; const r = rows[i], s = byId[r.id]; if (!s) return;
    if (s.image_file) { stageImg.src = assetUrl(s.image_file, 1); stageImg.style.display = "block"; ph.style.display = "none"; }
    else { stageImg.style.display = "none"; ph.style.display = "block"; ph.textContent = "scene " + s.id; }
    ostEl.textContent = (s.on_screen_text || "").trim();
    narrEl.innerHTML = `<span class="muted">scene ${s.id} · ${fmtClock(r.start)}</span><br><b>${esc(s.narration || "")}</b>`;
    if (seekAudio) {
      if (s.audio_file) { audio.src = assetUrl(s.audio_file, 1); audio.currentTime = 0; if (playing) audio.play().catch(() => { }); }
      else { audio.removeAttribute("src"); audio.load(); }
    }
  }
  function frame(now) {
    if (!playing) return;
    const dt = (now - last) / 1000; last = now; t += dt;
    if (t >= total) { t = total; pause(); update(); return; }
    const i = sceneAt(t);
    if (i !== curIdx) showScene(i, true);
    update(); raf = requestAnimationFrame(frame);
  }
  function update() {
    seek.style.width = total ? (t / total * 100) + "%" : "0%";
    timeEl.textContent = `${fmtClock(t)} / ${fmtClock(total)}`;
  }
  function play() { if (playing || !total) return; playing = true; playBtn.innerHTML = icon("i-pause"); last = performance.now(); const i = sceneAt(t); showScene(i, true); const s = byId[rows[i].id]; if (s && s.audio_file) { audio.currentTime = Math.max(0, t - rows[i].start); audio.play().catch(() => { }); } raf = requestAnimationFrame(frame); }
  function pause() { playing = false; playBtn.innerHTML = icon("i-play"); audio.pause(); if (raf) cancelAnimationFrame(raf); }
  playBtn.onclick = () => playing ? pause() : play();
  $("#pvScrub", page).onclick = e => {
    const rect = e.currentTarget.getBoundingClientRect(); t = total * clamp((e.clientX - rect.left) / rect.width, 0, 1);
    const i = sceneAt(t); showScene(i, true); if (playing && byId[rows[i].id].audio_file) audio.currentTime = Math.max(0, t - rows[i].start); update();
  };
  if (rows.length) showScene(0, false);
  update();
  // stop audio when leaving the page
  window.addEventListener("hashchange", () => { try { audio.pause(); } catch (e) { } }, { once: true });
}
async function renderHistory(host) {
  topbar("History", "Every voiceover, image batch and assembled video");
  const page = el("div", "page");
  const items = await api.get("/api/history");
  state.history = items;
  if (!items.length) {
    page.appendChild(el("div", "card", `<div class="empty">${icon("i-history")}<h3>No history yet</h3><p>Voiceover batches, image batches and assembled videos will show up here as you generate them.</p></div>`));
    host.appendChild(page); return;
  }
  const card = el("div", "card");
  card.innerHTML = `<div class="section-title">Recent renders</div><div class="scene-list" id="hList"></div>`;
  page.appendChild(card); host.appendChild(page);
  const wrap = $("#hList", card);
  const ICONS = { voiceover: "i-voice", images: "i-image", video: "i-assemble", tts: "i-voice", humanized: "i-voice", chunked: "i-voice" };
  items.forEach(it => {
    const kind = it.kind || (it.files ? "tts" : "render");
    const row = el("div", "scene-row"); row.style.gridTemplateColumns = "46px 1fr auto";
    let actions = "";
    if (kind === "video" && it.url) actions = `<a class="btn btn-sm btn-ghost" href="${it.url}" target="_blank">${icon("i-play")} Open</a><a class="btn-icon" href="${it.url}" download title="Download">${icon("i-download")}</a>`;
    else if (it.files) { const f = it.files.mp3 || it.files.wav; if (f) actions = `<a class="btn-icon" href="/audio/${f}" target="_blank" title="Play">${icon("i-play")}</a><a class="btn-icon" href="/download/${f}" download title="Download">${icon("i-download")}</a>`; }
    else if (it.project) actions = `<a class="btn btn-sm btn-ghost" href="#/p/${it.project}/storyboard">Open</a>`;
    row.innerHTML = `<div class="scene-thumb" style="width:46px;height:46px;border-radius:11px">${icon(ICONS[kind] || "i-history")}</div>
      <div class="scene-body"><div class="narr">${esc(it.text_preview || it.voice || kind)}</div>
      <div class="sub"><span class="badge ${kind === "video" ? "gold" : kind === "images" ? "teal" : ""}">${kind}</span>${it.project_name ? `<span>${esc(it.project_name)}</span>` : ""}${it.voice ? `<span>${esc(it.voice)}</span>` : ""}${it.duration ? `<span>${fmtClock(it.duration)}</span>` : ""}<span>${fmtAgo(it.created)}</span></div></div>
      <div class="scene-meta">${actions}<button class="btn-icon btn-danger" title="Remove from history">${icon("i-trash")}</button></div>`;
    $(".btn-danger", row).onclick = async () => { try { await api.del(`/api/history/${it.id}`); toast("Removed"); renderHistory(host); } catch (e) { toast(e.message, "err"); } };
    wrap.appendChild(row);
  });
}
async function refreshVoices() { try { state.voices = await api.get("/api/voices"); } catch (e) { } }
async function renderVoiceLab(host) {
  topbar("Voice Lab", "Design or clone narrator voices (used in Voiceover)");
  await refreshVoices();
  const page = el("div", "page page-wide");

  const mine = el("div", "card");
  mine.innerHTML = `<div class="section-title">Your voices</div><div id="vlList"></div>`;
  page.appendChild(mine);

  const make = el("div", "card"); make.style.marginTop = "16px";
  make.innerHTML = `
    <div class="grid2">
      <div>
        <h2>Design a voice</h2>
        <p class="desc">Describe a voice in words; the model invents it. Saved for use in Voiceover.</p>
        <div class="field"><label>Name</label><input type="text" id="dgName" placeholder="e.g. Calm narrator"/></div>
        <div class="field"><label>Description</label><textarea id="dgInstruct" rows="4" placeholder="A calm, warm middle-aged male documentary narrator, measured pacing…"></textarea></div>
        <div class="grid2">
          <div class="field"><label>Language</label><select id="dgLang"></select></div>
          <div class="field"><label>&nbsp;</label><button class="btn btn-primary" id="dgGo">${icon("i-wand")} Design voice</button></div>
        </div>
        <div class="muted mono" id="dgMsg"></div>
      </div>
      <div>
        <h2>Clone a voice</h2>
        <p class="desc">Upload 10–20s of clean speech to narrate in that voice.</p>
        <div class="field"><label>Name</label><input type="text" id="clName" placeholder="e.g. My voice"/></div>
        <div class="field"><label>Reference text <span class="hint">(optional, what's said in the clip)</span></label><textarea id="clText" rows="2"></textarea></div>
        <div class="grid2">
          <div class="field"><label>Sample audio</label><input type="file" id="clFile" accept="audio/*"/></div>
          <div class="field"><label>&nbsp;</label><button class="btn btn-primary" id="clGo">${icon("i-upload")} Clone voice</button></div>
        </div>
        <div class="muted mono" id="clMsg"></div>
      </div>
    </div>`;
  page.appendChild(make);

  const speakers = el("div", "card"); speakers.style.marginTop = "16px";
  speakers.innerHTML = `<div class="section-title">Built-in speakers (${(state.voices.builtin || []).length})</div>
    <div class="media-grid">${(state.voices.builtin || []).map(v => `<div class="card" style="background:var(--panel-2);padding:14px"><b>${dispName(v.id)}</b> ${v.youtube ? '<span class="badge gold">YT</span>' : ''}<div class="muted" style="font-size:12.5px;margin-top:5px">${esc(v.native)} · ${esc(v.desc)}</div></div>`).join("")}</div>`;
  page.appendChild(speakers);
  host.appendChild(page);

  const dgLang = $("#dgLang", page);
  dgLang.innerHTML = (state.voices.languages || ["English"]).filter(l => l !== "Auto").map(l => `<option>${l}</option>`).join("");

  function drawMine() {
    const wrap = $("#vlList", mine); const cs = state.voices.custom || [];
    if (!cs.length) { wrap.innerHTML = `<div class="muted" style="font-size:13px">No custom voices yet — design or clone one below.</div>`; return; }
    wrap.innerHTML = ""; const list = el("div", "scene-list");
    cs.forEach(v => {
      const row = el("div", "scene-row"); row.style.gridTemplateColumns = "1fr auto";
      row.innerHTML = `<div class="scene-body"><div class="narr">${esc(v.name)} <span class="badge">${esc(v.type)}</span></div>
        <div class="sub">${v.instruct ? esc(v.instruct.slice(0, 120)) : (v.language || "")}</div></div>
        <div class="scene-meta">${v.preview_file ? `<a class="btn-icon" href="/audio/${v.preview_file}" target="_blank" title="Play">${icon("i-play")}</a>` : ""}<button class="btn-icon btn-danger" title="Delete">${icon("i-trash")}</button></div>`;
      $(".btn-danger", row).onclick = async () => { if (await confirmModal("Delete voice?", esc(v.name), "Delete")) { await api.del(`/api/voices/${v.id}`); await refreshVoices(); drawMine(); toast("Voice deleted"); } };
      list.appendChild(row);
    });
    wrap.appendChild(list);
  }
  drawMine();

  $("#dgGo", page).onclick = async () => {
    const instruct = $("#dgInstruct", page).value.trim(); if (!instruct) return toast("Describe the voice first", "err");
    const msg = $("#dgMsg", page); msg.textContent = "designing…";
    try {
      const { job_id } = await api.post("/api/design", { name: $("#dgName", page).value.trim() || "Designed voice", instruct, language: dgLang.value });
      await pollJob(job_id, j => msg.textContent = j.stage + " " + Math.round((j.progress || 0) * 100) + "%");
      msg.textContent = "done ✓"; await refreshVoices(); drawMine();
    } catch (e) { msg.textContent = ""; toast(e.message, "err"); }
  };
  $("#clGo", page).onclick = async () => {
    const f = $("#clFile", page).files[0]; if (!f) return toast("Choose an audio file", "err");
    const msg = $("#clMsg", page); msg.textContent = "uploading…";
    const fd = new FormData(); fd.append("file", f); fd.append("name", $("#clName", page).value.trim() || "My voice");
    fd.append("ref_text", $("#clText", page).value.trim()); fd.append("language", "Auto");
    try { await api.form("/api/voices/clone", fd); msg.textContent = "cloned ✓"; await refreshVoices(); drawMine(); }
    catch (e) { msg.textContent = ""; toast(e.message, "err"); }
  };
}
async function renderSettings(host) {
  topbar("Settings", "Models, devices & defaults");
  const [s, st, im] = await Promise.all([api.get("/api/settings"), api.get("/api/status"), api.get("/api/image_models")]);
  state.settings = s; state.status = st;
  const img = s.image || {}; const sync = s.sync || {};
  const page = el("div", "page");

  const status = el("div", "card");
  status.innerHTML = `<div class="section-title">Compute</div>
    <div class="row">
      <span class="badge ${st.device === "cuda" ? "good" : "warn"}">${st.device === "cuda" ? "GPU · CUDA" : "CPU"}</span>
      <span class="badge ${st.ffmpeg ? "good" : "warn"}">ffmpeg ${st.ffmpeg ? "ready" : "missing"}</span>
      <span class="badge">TTS ${st.model_size || "1.7B"}</span>
      <span class="badge ${(st.image || {}).loaded ? "good" : ""}">image ${(st.image || {}).loaded ? ("loaded: " + (st.image.model || "")) : "not loaded"}</span>
    </div>`;
  page.appendChild(status);

  const tts = el("div", "card"); tts.style.marginTop = "16px";
  tts.innerHTML = `<div class="section-title">Voiceover (Qwen3-TTS)</div>
    <div class="grid3">
      <div class="field"><label>Model size</label><select id="seSize">${["1.7B", "0.6B"].map(v => `<option ${s.model_size === v ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <div class="field"><label>Default language</label><select id="seLang">${(state.voices.languages || ["Auto", "English"]).map(l => `<option ${s.default_language === l ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <div class="field"><label>Max chars / chunk</label><input type="number" id="seMax" value="${s.max_chars || 240}"/></div>
      <div class="field"><label>Sentence gap (ms)</label><input type="number" id="seGap" value="${s.gap_ms || 180}"/></div>
      <div class="field"><label>Paragraph gap (ms)</label><input type="number" id="sePGap" value="${s.paragraph_gap_ms || 480}"/></div>
      <div class="field" style="justify-content:flex-end"><label>&nbsp;</label><label class="switch"><input type="checkbox" id="seLoud" ${s.loudnorm ? "checked" : ""}/><span class="track"></span> Loudness normalize</label></div>
    </div>`;
  page.appendChild(tts);

  const imc = el("div", "card"); imc.style.marginTop = "16px";
  imc.innerHTML = `<div class="section-title">Images</div>
    <div class="grid3">
      <div class="field"><label>Default base model</label><select id="seModel">${(im.builtin || []).map(m => `<option value="${m.id}" ${img.model === m.id ? "selected" : ""}>${esc(m.label)}${m.size ? " · " + esc(m.size) : ""}</option>`).join("")}</select></div>
      <div class="field"><label>FLUX offload</label><select id="seOff">${["model", "sequential", "none"].map(o => `<option ${img.offload === o ? "selected" : ""}>${o}</option>`).join("")}</select></div>
      <div class="field"><label>FLUX GGUF quant</label><select id="seQ">${["Q4_K_S", "Q5_K_S", "Q8_0"].map(q => `<option ${img.gguf_quant === q ? "selected" : ""}>${q}</option>`).join("")}</select></div>
    </div>
    <div class="field"><label>Civitai API token <span class="hint">(optional — only if importing from Civitai later)</span></label><input type="password" id="seCivit" value="${esc(img.civitai_token || "")}"/></div>`;
  page.appendChild(imc);

  const syncC = el("div", "card"); syncC.style.marginTop = "16px";
  syncC.innerHTML = `<div class="section-title">Sync (audio-led)</div>
    <div class="grid3">
      <div class="field"><label>Min scene hold (s)</label><input type="number" step="0.1" id="seHold" value="${sync.min_hold_sec ?? 1.2}"/></div>
      <div class="field"><label>Lead-in (ms)</label><input type="number" id="seLead" value="${sync.lead_in_ms ?? 120}"/></div>
      <div class="field"><label>Tail (ms)</label><input type="number" id="seTail" value="${sync.tail_ms ?? 250}"/></div>
    </div>`;
  page.appendChild(syncC);

  const bar = el("div", "row row-end"); bar.style.marginTop = "18px";
  bar.innerHTML = `<button class="btn btn-primary" id="seSave">Save settings</button>`;
  page.appendChild(bar);
  host.appendChild(page);

  $("#seSave", page).onclick = async () => {
    const patch = {
      model_size: $("#seSize", page).value, default_language: $("#seLang", page).value,
      max_chars: +$("#seMax", page).value, gap_ms: +$("#seGap", page).value,
      paragraph_gap_ms: +$("#sePGap", page).value, loudnorm: $("#seLoud", page).checked,
      image: { model: $("#seModel", page).value, offload: $("#seOff", page).value, gguf_quant: $("#seQ", page).value, civitai_token: $("#seCivit", page).value },
      sync: { min_hold_sec: +$("#seHold", page).value, lead_in_ms: +$("#seLead", page).value, tail_ms: +$("#seTail", page).value },
    };
    try { state.settings = await api.put("/api/settings", patch); toast("Settings saved"); renderChips(); }
    catch (e) { toast(e.message, "err"); }
  };
}

const Pages = {
  projects: renderProjects, storyboard: renderStoryboard, voiceover: renderVoiceover,
  images: renderImages, assemble: renderAssemble, preview: renderPreview,
  history: renderHistory, voices: renderVoiceLab, settings: renderSettings,
};

/* ============================================================
   BOOT
   ============================================================ */
(async function boot() {
  try {
    const b = await api.get("/api/bootstrap");
    state.status = b.status || {}; state.settings = b.settings || {};
    state.voices = b.voices || state.voices; state.history = b.history || [];
    state.projects = b.projects || []; state.imageModels = b.image_models || state.imageModels;
  } catch (e) { toast("Could not reach the server: " + e.message, "err"); }
  if (!location.hash) location.hash = "#/projects";
  render();
})();
