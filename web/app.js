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
  { id: "characters", label: "Characters", icon: "i-voices", proj: true },
  { id: "voiceover", label: "Voiceover", icon: "i-voice", proj: true },
  { id: "images", label: "Images", icon: "i-image", proj: true },
  { id: "animate", label: "Animate", icon: "i-preview", proj: true },
  { id: "assemble", label: "Assemble", icon: "i-assemble", proj: true },
  { id: "preview", label: "Preview", icon: "i-preview", proj: true },
  { sep: true },
  { id: "history", label: "History", icon: "i-history" },
  { id: "voices", label: "Voice Lab", icon: "i-voices" },
  { id: "transcribe", label: "Script → JSON", icon: "i-clock" },
  { id: "training", label: "Training", icon: "i-wand" },
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
  $("#chipFlux").textContent = modelId === "cartoon-rag" ? "Cartoon · RAG" : (type === "comfyui" ? "Krea-2 · cartoon" : (type === "flux" ? "FLUX" : (type === "sdxl" ? "SDXL" : "SD 1.5")));
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
  { id: "animate", label: "Animate" },
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
  const [projData, history] = await Promise.all([api.get("/api/projects"), api.get("/api/history").catch(() => [])]);
  state.projects = projData.projects;

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
        <div class="row" style="justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
          <div class="row" style="gap:6px;align-items:center">
            <button class="btn btn-ghost btn-sm" id="pTemplate">${icon("i-plus")} Template</button>
            <input type="number" id="pTplScenes" min="1" max="200" value="1" title="number of scene blocks" style="width:56px" />
            <span class="muted">scenes</span>
            <button class="btn btn-ghost btn-sm" id="pTplDownload">${icon("i-download")} Download</button>
          </div>
          <button class="btn btn-primary" id="pCreate">${icon("i-plus")} Create project</button>
        </div>
        <div class="muted mono" style="font-size:11px;margin-top:7px;line-height:1.5">
          Template = every importable key, blank. <b>type</b>: scene·diagram·title — <b>motion_type</b>: still·ambient·transform
        </div>
      </div>
    </div>
    <div class="field" id="pVoiceoverWrap" style="margin-top:14px;display:none">
      <label>Attach recorded voiceover <span class="hint">(optional — slices a saved recording into the scenes so the project imports already-voiced)</span></label>
      <select id="pVoiceover"><option value="">— none (voice it later) —</option></select>
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

  // saved recordings → "attach voiceover" dropdown (already-voiced import)
  const recs = (history || []).filter(it => it.files && (it.files.wav || it.files.mp3) && it.kind !== "transcript" && !it.project);
  const vsel = $("#pVoiceover", page), vwrap = $("#pVoiceoverWrap", page);
  if (vsel && vwrap && recs.length) {
    vwrap.style.display = "";
    recs.forEach(it => {
      const f = it.files.wav || it.files.mp3;
      const o = document.createElement("option");
      o.value = f; o.dataset.voice = it.voice || "Imported recording";
      o.textContent = `${it.voice || "voice"}${it.duration ? " · " + fmtClock(it.duration) : ""}${it.text_preview ? " · " + it.text_preview.slice(0, 44) : ""}`;
      vsel.appendChild(o);
    });
  }

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
      await finishCreate(project);
    } catch (e) { toast(e.message, "err"); }
  };

  // Blank full-schema template (every importable key) — insert into the box or download.
  const tplCount = () => Math.max(1, Math.min(parseInt($("#pTplScenes", page).value, 10) || 1, 200));
  const fetchTemplate = () => api.get(`/api/storyboard/template?scene_count=${tplCount()}&character_count=1`);
  $("#pTemplate", page).onclick = async () => {
    const box = $("#pText", page);
    if (box.value.trim() &&
        !(await confirmModal("Replace paste box?", "This overwrites the JSON currently in the box with a blank template.", "Replace"))) return;
    try {
      box.value = JSON.stringify(await fetchTemplate(), null, 2);
      box.focus();
      toast("Template inserted — fill in the fields, then Create project.");
    } catch (e) { toast(e.message, "err"); }
  };
  $("#pTplDownload", page).onclick = async () => {
    try {
      const blob = new Blob([JSON.stringify(await fetchTemplate(), null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "storyboard_template.json";
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
    } catch (e) { toast(e.message, "err"); }
  };
}
async function uploadProject(file) {
  const fd = new FormData(); fd.append("file", file);
  try {
    const { project } = await api.form("/api/projects/upload", fd);
    await finishCreate(project);
  } catch (e) { toast(e.message, "err"); }
}

// After creating a project: if a saved recording was picked in the import card,
// slice it into the scenes (already-voiced import) and land on Voiceover;
// otherwise go straight to the Storyboard.
async function finishCreate(project) {
  const selEl = document.getElementById("pVoiceover");
  const file = selEl ? selEl.value : "";
  const opt = selEl && selEl.selectedOptions[0];
  toast(`Imported “${project.name}” (${project.scenes.length} scenes)`);
  if (!file) { location.hash = `#/p/${project.id}/storyboard`; return; }
  try {
    toast("Attaching your recording to the scenes…");
    const { job_id } = await api.post(`/api/projects/${project.id}/voiceover/attach`, { file, voice: (opt && opt.dataset.voice) || "Imported recording" });
    const res = await pollJob(job_id);
    toast(`Voiceover attached · ${res.done}/${res.scenes} scenes voiced`);
  } catch (e) { toast("Project created, but attaching the recording failed: " + e.message, "err"); }
  location.hash = `#/p/${project.id}/voiceover`;
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
    <div class="field"><label>Image prompt <span class="hint">(the global style is appended at render — edit it on the Images page)</span></label><textarea id="scPrompt" rows="3">${esc(s.image_prompt)}</textarea></div>
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

  // Voiceover-first projects are voiced by one continuous recording (see attach):
  // show that master track up front; the per-scene generator below still works too.
  if (p.narration && p.narration.file) {
    const nb = el("div", "card");
    nb.innerHTML = `
      <div class="spread"><h2 class="mb0">Narration track</h2><span class="badge good">${c.audio} / ${c.total} scenes timed</span></div>
      <p class="desc">This project is voiced by one continuous recording${p.narration.voice ? ` — <b>${esc(p.narration.voice)}</b>` : ""} (${fmtClock(p.narration.dur || 0)}). The images are timed to it and the audio is never cut. (Generating per-scene voiceover below would switch back to per-scene clips.)</p>
      <audio controls preload="none" src="${assetUrl(p.narration.file, 1)}" style="width:100%"></audio>
      <div class="row" style="margin-top:10px"><button class="btn btn-ghost btn-sm" id="voReplace">${icon("i-history")} Replace recording</button></div>`;
    page.appendChild(nb);
  }

  const sel = Object.assign({ mode: "custom", speaker: "Ryan", voice_id: null, language: "English", instruct: "" }, p.settings.voice || {});

  const vcard = el("div", "card");
  vcard.innerHTML = `
    <div class="spread"><h2 class="mb0">Voice</h2>
      <button class="btn btn-ghost btn-sm" id="voImport">${icon("i-history")} Use a saved recording</button></div>
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

  const tcard = el("div", "card"); tcard.style.marginTop = "16px";
  tcard.innerHTML = `
    <div class="spread"><h2 class="mb0">Transcribe <span class="hint">→ timed sentences</span></h2><div class="row" id="trMeta"></div></div>
    <p class="desc">Turn the generated voice into a timestamped script: every sentence becomes its own block with an accurate <b>start</b>/<b>end</b>, anchored to your narration so the wording stays exact. Runs locally on your GPU (Whisper). Exports <b>transcript.json</b> + <b>.srt</b> / <b>.vtt</b> subtitles.</p>
    <p class="muted" style="margin:-6px 0 14px;font-size:13px">First run downloads the Whisper model into <code>./models</code> (medium ≈ 1.5&nbsp;GB) — later runs are fast.</p>
    <div class="row" id="trActions"></div>
    <div id="trRun" style="margin-top:16px"></div>
    <div class="divider"></div>
    <div id="trOut"></div>`;
  page.appendChild(tcard);
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

  // ---- Use a saved Script→JSON voiceover: attach the recording (slice it into the
  //      scenes, already-voiced) or just adopt its voice + style to re-generate ----
  function applyImportedVoice(it) {
    const mode = it.mode || (it.voice_id ? "clone" : "custom");
    sel.mode = mode;
    if (mode === "clone") sel.voice_id = it.voice_id;
    else { sel.speaker = it.speaker || sel.speaker; sel.voice_id = null; }
    sel.instruct = it.instruct || "";
    if (it.language) sel.language = it.language;
    drawModes(); drawVoices();
    const ls = $("#voLang", page);
    if (ls && [...ls.options].some(o => o.value === sel.language)) ls.value = sel.language;
    const inst = $("#voInstruct", page); if (inst) inst.value = sel.instruct;
    if (p.settings) p.settings.voice = { ...sel };                                  // reflect locally
    api.put(`/api/projects/${p.id}/settings`, { voice: sel }).catch(() => {});      // persist (per-scene quick-voice reads this)
  }
  async function attachRecording(it) {
    const f = it.files && (it.files.wav || it.files.mp3);
    if (!f) return toast("That entry has no audio file.", "err");
    closeModal();
    const runEl = $("#voRun", page);
    runEl.innerHTML = `<div class="run-panel"><div class="spinner"></div><div style="flex:1"><div class="lab" id="voStage">Attaching recording…</div><div class="progress" style="margin-top:8px"><div class="bar" id="voBar"></div></div></div></div>`;
    try {
      const { job_id } = await api.post(`/api/projects/${state.project.id}/voiceover/attach`, { file: f, voice: it.voice || "Imported recording" });
      const res = await pollJob(job_id, j => { const st = $("#voStage", page); if (st) st.textContent = j.stage; const b = $("#voBar", page); if (b) b.style.width = Math.round((j.progress || 0) * 100) + "%"; });
      await loadProject(state.project.id);
      runEl.innerHTML = "";
      toast(`Recording attached · ${res.done}/${res.scenes} scenes voiced`);
      timing(); actions(); drawScenes(); renderNav();
      if (typeof trActions === "function") trActions();
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
  }
  async function openVoiceImport() {
    const card = openModal(`
      <div class="modal-head"><h2 class="mb0">Use a saved voiceover</h2><button class="btn-icon" id="mClose">${icon("i-x")}</button></div>
      <p class="muted" style="line-height:1.5"><b>Use recording</b> slices that exact clip into your scenes by their timing — already voiced, no re-synthesis (the scene timings came from this recording's transcript). <b>Voice only</b> just adopts its voice + style to re-generate.</p>
      <div id="viList" style="max-height:56vh;overflow:auto;margin-top:4px"><div class="muted" style="padding:14px">Loading…</div></div>`);
    $("#mClose", card).onclick = closeModal;
    let items = [];
    try { items = await api.get("/api/history"); }
    catch (e) { const l = $("#viList", card); if (l) l.innerHTML = `<div class="muted" style="padding:14px">Couldn't load history: ${esc(e.message)}</div>`; return; }
    const saved = items.filter(it => it.files && (it.files.wav || it.files.mp3) && it.kind !== "transcript" && !it.project);
    const list = $("#viList", card); if (!list) return;
    list.innerHTML = "";
    if (!saved.length) { list.innerHTML = `<div class="muted" style="padding:14px">No saved recordings yet — generate one on the <a href="#/transcribe">Script → JSON</a> page.</div>`; return; }
    saved.forEach(it => {
      const f = it.files.wav || it.files.mp3;
      const mode = it.mode || (it.voice_id ? "clone" : (it.speaker ? "custom" : null));
      const canVoice = mode === "custom" ? !!it.speaker : (mode === "clone" ? (state.voices.custom || []).some(v => v.id === it.voice_id) : false);
      const row = el("div", "opt"); row.style.cssText = "align-items:flex-start;gap:12px;cursor:default";
      row.innerHTML = `
        <div style="flex:1;min-width:0">
          <div class="nm">${esc(it.voice || "Voice")}${mode ? ` <span class="badge ${mode === "clone" ? "teal" : ""}" style="padding:1px 6px">${mode === "clone" ? "cloned" : "built-in"}</span>` : ""}${it.duration ? ` <span class="muted" style="font-size:12px">· ${fmtClock(it.duration)}</span>` : ""}${it.language ? ` <span class="muted" style="font-size:12px">· ${esc(it.language)}</span>` : ""}</div>
          ${it.instruct ? `<div class="ds">style: “${esc(it.instruct)}”</div>` : ""}
          ${it.text_preview ? `<div class="ds" style="opacity:.7">${esc(it.text_preview)}</div>` : ""}
          <audio controls preload="none" src="/audio/${f}" style="height:32px;width:100%;max-width:360px;margin-top:8px"></audio>
        </div>
        <div class="row" style="flex-direction:column;gap:6px;align-items:stretch;min-width:118px">
          <button class="btn btn-sm btn-primary useRec">Use recording</button>
          <button class="btn btn-sm btn-ghost useVoice"${canVoice ? "" : " disabled title='voice config unavailable'"}>Voice only</button>
        </div>`;
      $(".useRec", row).onclick = () => attachRecording(it);
      const uv = $(".useVoice", row);
      if (canVoice && uv) uv.onclick = () => { applyImportedVoice(it); closeModal(); toast(`Voice set: ${it.voice || "voice"}`); };
      list.appendChild(row);
    });
  }
  $("#voImport", page).onclick = openVoiceImport;
  const voReplace = $("#voReplace", page); if (voReplace) voReplace.onclick = openVoiceImport;

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
    // Canonical flow: the WHOLE script in one take — tone flows across scenes,
    // Whisper aligns each scene to the recording. Per-scene stays for fixes.
    const one = el("button", "btn btn-primary", `${icon("i-voice")} One-take narration (whole script)`);
    one.onclick = () => runVO("onetake");
    const gen = el("button", "btn btn-ghost", `${icon("i-wand")} Per-scene: missing (${missing})`);
    gen.disabled = missing === 0; gen.onclick = () => runVO("missing");
    const all = el("button", "btn btn-ghost", `${icon("i-refresh")} Per-scene: all (${cnt.total})`);
    all.onclick = () => runVO("all");
    a.append(one, gen, all);
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
      const url = scope === "onetake"
        ? `/api/projects/${state.project.id}/voiceover/onetake`
        : `/api/projects/${state.project.id}/voiceover`;
      const { job_id } = await api.post(url, { voice: sel, scope, scene_id: sceneId != null ? String(sceneId) : null });
      const res = await pollJob(job_id, j => { const st = $("#voStage", page); if (st) st.textContent = j.stage; const b = $("#voBar", page); if (b) b.style.width = Math.round((j.progress || 0) * 100) + "%"; });
      await loadProject(state.project.id);
      runEl.innerHTML = "";
      if (scope === "onetake" && res.qa && !res.qa.ok) {
        toast(`Narrated ${fmtClock(res.duration)} — QA flagged the transcript (overlap ${res.qa.overlap}); listen before rendering`, "err");
      } else {
        toast(`Voiced ${res.done} scene(s) · ${fmtClock((res.timeline || {}).total_dur || res.duration || 0)} total`);
      }
      timing(); actions(); drawScenes(); renderNav();
      if (typeof trActions === "function") trActions();
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
  }

  /* ---- transcribe (timed sentence blocks) ---- */
  const trTS = t => { t = Math.max(0, +t || 0); const m = Math.floor(t / 60); return `${m}:${(t - m * 60).toFixed(2).padStart(5, "0")}`; };
  function trCounts() {
    const voiced = state.project.scenes.filter(s => (s.narration || "").trim() && s.status.audio === "ready");
    return { voiced: voiced.length, missing: voiced.filter(s => (s.status.transcript || "none") !== "ready").length };
  }
  function trMeta() {
    const t = state.status.transcribe || {};
    $("#trMeta", page).innerHTML =
      `<span class="badge">Whisper ${esc(t.model || "medium")}</span>` +
      `<span class="badge ${t.available === false ? "" : "teal"}">${t.available === false ? "not installed" : esc(t.device || "auto")}</span>`;
  }
  function trActions() {
    const a = $("#trActions", page); a.innerHTML = ""; const c = trCounts();
    const go = el("button", "btn btn-primary", `${icon("i-wand")} Transcribe voiced (${c.missing})`);
    go.disabled = c.missing === 0; go.onclick = () => runTR("missing");
    const all = el("button", "btn btn-ghost", `${icon("i-refresh")} Re-transcribe all (${c.voiced})`);
    all.disabled = c.voiced === 0; all.onclick = () => runTR("all");
    a.append(go, all);
    if (c.voiced === 0) a.append(el("span", "muted", `<span style="padding-left:8px">Voice some scenes first.</span>`));
  }
  function renderTranscript(doc) {
    const out = $("#trOut", page); out.innerHTML = "";
    if (!doc || !doc.sentences || !doc.sentences.length) {
      out.innerHTML = `<div class="muted" style="padding:6px 2px">No transcript yet — voice the scenes, then transcribe.</div>`; return;
    }
    const base = `/projects/${state.project.id}/transcript/`;
    const dl = el("div", "row"); dl.style.cssText = "margin-bottom:14px;align-items:center";
    dl.innerHTML = `<span class="muted" style="margin-right:4px">Download</span>
      <a class="btn btn-ghost btn-sm" href="${base}transcript.json" download>${icon("i-download")} JSON</a>
      <a class="btn btn-ghost btn-sm" href="${base}captions.srt" download>${icon("i-download")} SRT</a>
      <a class="btn btn-ghost btn-sm" href="${base}captions.vtt" download>${icon("i-download")} VTT</a>
      <span class="grow"></span><span class="badge gold">${doc.sentence_count} sentences</span>`;
    out.appendChild(dl);
    doc.scenes.forEach(s => {
      const row = el("div", "scene-row"); row.style.gridTemplateColumns = "54px 1fr";
      const lines = s.sentences.map(b =>
        `<div style="display:flex;gap:10px;padding:3px 0;align-items:baseline">
           <span class="badge mono" style="padding:1px 7px;white-space:nowrap">${trTS(b.start)}&nbsp;→&nbsp;${trTS(b.end)}</span>
           <span>${esc(b.text)}</span></div>`).join("");
      row.innerHTML = `<div class="sid">scene<b>${s.id}</b></div><div class="scene-body">${lines}</div>`;
      out.appendChild(row);
    });
  }
  async function runTR(scope, sceneId) {
    const runEl = $("#trRun", page);
    runEl.innerHTML = `<div class="run-panel"><div class="spinner"></div><div style="flex:1"><div class="lab" id="trStage">Starting…</div><div class="progress" style="margin-top:8px"><div class="bar" id="trBar"></div></div></div></div>`;
    try {
      const { job_id } = await api.post(`/api/projects/${state.project.id}/transcribe`, { scope, scene_id: sceneId != null ? String(sceneId) : null });
      const res = await pollJob(job_id, j => { const st = $("#trStage", page); if (st) st.textContent = j.stage; const b = $("#trBar", page); if (b) b.style.width = Math.round((j.progress || 0) * 100) + "%"; });
      await loadProject(state.project.id);
      runEl.innerHTML = "";
      toast(`Transcribed ${res.done} scene(s) · ${res.sentences} sentences`);
      trActions(); renderTranscript(res.transcript);
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
  }
  trMeta(); trActions();
  api.get(`/api/projects/${p.id}/transcript`).then(renderTranscript).catch(() => renderTranscript(null));
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

  const cfg = Object.assign({ model: "cartoon-rag", steps: null, guidance: null, width: null, height: null, seed: -1, use_default_lora: true, default_lora_weight: 0.95, gguf_quant: "Q4_K_S", loras: [], use_refs: true, ip_scale: 0.7, comfy_lora: null }, state.settings.image || {}, p.settings.image || {});
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
    <p class="desc">Default is <b>Krea-2 Turbo</b> — local, rendered through ComfyUI (no download). The look now comes from the <b>Global prompts</b> card below, not a baked-in style. <b>SD&nbsp;1.5</b> / <b>FLUX</b> remain available via the in-app diffusers engine.</p>
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
    <div id="imComfyLora">
      <div class="grid2">
        <div class="field"><label>Krea-2 LoRA <span class="hint">(ComfyUI models/loras — e.g. your trained style)</span></label><select id="imCLora"><option value="">— none —</option></select></div>
        <div class="field"><label>LoRA strength</label><input type="number" id="imCLoraW" step="0.05" min="0" max="1.5" value="${cfg.comfy_lora && cfg.comfy_lora.strength != null ? cfg.comfy_lora.strength : 0.8}"/></div>
      </div>
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

  // --- reference style pack (RAG / IP-Adapter) — cartoon-rag model only ---
  const rcard = el("div", "card"); rcard.id = "imRefsCard"; rcard.style.marginTop = "16px";
  rcard.innerHTML = `
    <div class="spread"><h2 class="mb0">Cartoon style references <span class="hint">(RAG)</span></h2><span class="badge teal" id="imRefCount"></span></div>
    <p class="desc">No ComfyUI: the cartoon look comes from these reference images, fed to <b>IP-Adapter</b> in style-transfer mode. Seed the pack from your existing krea2 renders, or upload your own. <b>Composition</b> still follows each scene's prompt.</p>
    <div class="grid2">
      <div class="field"><label>Style strength <span class="hint" id="imIpVal"></span></label><input type="range" min="0" max="1.2" step="0.05" id="imIp" value="${cfg.ip_scale}"/></div>
      <div class="field" style="justify-content:flex-end"><label>&nbsp;</label>
        <label class="switch"><input type="checkbox" id="imUseRefs" ${cfg.use_refs ? "checked" : ""}/><span class="track"></span> Use references</label></div>
    </div>
    <div class="row" style="margin:6px 0 12px">
      <button class="btn btn-ghost btn-sm" id="imRefSeed">${icon("i-image")} Seed from this project</button>
      <button class="btn btn-ghost btn-sm" id="imRefAdd">${icon("i-plus")} Upload reference</button>
      <input type="file" id="imRefFile" accept=".png,.jpg,.jpeg,.webp" multiple style="display:none"/>
      <span class="muted mono" id="imRefMsg"></span>
    </div>
    <div class="media-grid" id="imRefGrid"></div>`;
  page.appendChild(rcard);

  // --- global prompts (storyboard-wide style + negative, editable) ---
  const v0 = p.video || {};
  const pcard = el("div", "card"); pcard.style.marginTop = "16px";
  pcard.innerHTML = `
    <div class="spread"><h2 class="mb0">Global prompts</h2><span class="badge" id="gpState">saved</span></div>
    <p class="desc">Applied to <b>every</b> scene: final prompt = scene <b>image_prompt</b> + the global style below. Style clauses a scene already contains aren't repeated, so storyboards that bake the style into each scene stay clean.</p>
    <div class="field"><label>Global style <span class="hint">(appended to every scene's prompt)</span></label>
      <textarea id="gpStyle" rows="4">${esc((v0.global_style_suffix || "").replace(/^[\s,]+/, ""))}</textarea></div>
    <div class="field"><label>Global negative <span class="hint" id="gpNegHint"></span></label>
      <textarea id="gpNeg" rows="2">${esc(v0.global_negative_prompt || "")}</textarea></div>
    <div class="row">
      <button class="btn btn-primary btn-sm" id="gpSave">${icon("i-check")} Save global prompts</button>
      <button class="btn btn-ghost btn-sm" id="gpPreset">${icon("i-wand")} Insert flat-cartoon preset</button>
      <span class="muted mono" id="gpMsg"></span>
    </div>
    <div class="divider"></div>
    <div class="field" style="margin-bottom:0"><label>Final prompt preview <span class="hint">— scene <span id="gpPrevId"></span>, exactly what the model will get</span></label>
      <div class="mono" id="gpPreview" style="font-size:12px;line-height:1.6;white-space:pre-wrap;opacity:.75"></div></div>`;
  page.appendChild(pcard);

  const gcard = el("div", "card"); gcard.style.marginTop = "16px";
  gcard.innerHTML = `
    <div class="spread"><h2 class="mb0">Generate</h2><div class="row" id="imCounts"></div></div>
    <p class="desc">Each scene's prompt = its <b>image_prompt</b> + the global style above. Batches run in the background.</p>
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
  const syncNegHint = () => {
    const t = mdef().type, h = $("#gpNegHint", page);
    if (!h) return;
    h.textContent = t === "comfyui" ? "(krea2: only used when guidance > 1 — the turbo default is 1.0)"
      : t === "flux" ? "(FLUX ignores negative prompts)"
        : "(applies on SD / SDXL)";
  };
  const applyVis = () => {
    const flux = isFlux(), comfy = mdef().type === "comfyui";
    $("#imQuantField", page).style.display = flux ? "" : "none";
    $("#imBuiltinLora", page).style.display = flux ? "" : "none";
    $("#imComfyLora", page).style.display = comfy ? "" : "none";
    $("#imLoraList", page).style.display = comfy ? "none" : "";
    $("#imRefsCard", page).style.display = mdef().ip_adapter ? "" : "none";
    if (flux) syncDef();
    syncNegHint();
  };
  const setIp = () => $("#imIpVal", page).textContent = (+$("#imIp", page).value).toFixed(2);
  setVal(); setIp(); applyVis();

  // --- Krea-2 (ComfyUI) LoRA picker ---
  const syncCLora = () => {
    const name = $("#imCLora", page).value;
    cfg.comfy_lora = name ? { name, strength: +$("#imCLoraW", page).value || 0.8 } : null;
  };
  $("#imCLora", page).onchange = syncCLora;
  $("#imCLoraW", page).oninput = syncCLora;
  (async () => {
    let data = { loras: [] };
    try { data = await api.get("/api/comfy_loras"); } catch (e) { }
    const cur = (cfg.comfy_lora && cfg.comfy_lora.name) || "";
    $("#imCLora", page).innerHTML = `<option value="">— none —</option>` + data.loras.map(l =>
      `<option value="${esc(l.name)}" ${l.name === cur ? "selected" : ""}>${esc(l.name)}${l.size_mb ? ` · ${l.size_mb} MB` : ""}</option>`).join("");
    if (cur && !data.loras.some(l => l.name === cur)) { cfg.comfy_lora = null; }
  })();

  // --- global prompts (mirror of scenes.merge_style on the backend) ---
  const normClause = c => c.replace(/\s+/g, " ").trim().replace(/^[\s.;:]+|[\s.;:]+$/g, "").toLowerCase();
  function mergeStyle(base, style) {
    base = (base || "").trim().replace(/^,+|,+$/g, "").trim();
    const have = new Set(base.split(",").map(normClause));
    const add = (style || "").split(",").map(c => c.trim()).filter(c => normClause(c) && !have.has(normClause(c)));
    if (!add.length) return base;
    return base ? `${base}, ${add.join(", ")}` : add.join(", ");
  }
  const prevScene = p.scenes.find(s => (s.image_prompt || "").trim()) || p.scenes[0];
  function drawPreview() {
    if (!prevScene) return;
    $("#gpPrevId", page).textContent = prevScene.id;
    const base = (prevScene.image_prompt || prevScene.visual || prevScene.narration || "").trim();
    $("#gpPreview", page).textContent = mergeStyle(base, $("#gpStyle", page).value) || "—";
  }
  const setGpState = dirty => {
    const b = $("#gpState", page);
    b.textContent = dirty ? "unsaved changes" : "saved";
    b.className = dirty ? "badge gold" : "badge";
  };
  $("#gpStyle", page).oninput = () => { setGpState(true); drawPreview(); };
  $("#gpNeg", page).oninput = () => setGpState(true);
  $("#gpPreset", page).onclick = () => {
    const pr = (state.imageModels.style_presets || [])[0];
    if (!pr) return toast("No preset available", "err");
    $("#gpStyle", page).value = pr.text;
    setGpState(true); drawPreview();
  };
  $("#gpSave", page).onclick = async () => {
    const msg = $("#gpMsg", page);
    try {
      const meta = await api.patch(`/api/projects/${p.id}/video`, {
        global_style_suffix: $("#gpStyle", page).value.trim(),
        global_negative_prompt: $("#gpNeg", page).value.trim(),
      });
      p.video = Object.assign(p.video || {}, meta);
      setGpState(false);
      msg.textContent = "saved ✓ — re-render scenes to apply";
      setTimeout(() => { if (msg.textContent.startsWith("saved")) msg.textContent = ""; }, 5000);
    } catch (e) { toast(e.message, "err"); }
  };
  drawPreview();

  // --- reference pack (RAG) ---
  async function loadRefs() {
    let data = { refs: [], count: 0 };
    try { data = await api.get("/api/style_refs"); } catch (e) { }
    $("#imRefCount", page).textContent = `${data.count} reference${data.count === 1 ? "" : "s"}`;
    const grid = $("#imRefGrid", page); grid.innerHTML = "";
    if (!data.refs.length) { grid.innerHTML = `<div class="muted" style="font-size:13px">No references yet — seed from this project to copy your krea2 cartoon look.</div>`; return; }
    data.refs.forEach(r => {
      const card = el("div", "media-card");
      card.innerHTML = `<div class="frame"><img src="${r.url}" loading="lazy"/></div>
        <div class="cap"><div class="t muted mono" style="font-size:11px">${esc((r.tags || []).join(" ") || r.source || "")}</div>
        <button class="btn-icon btn-danger" title="Remove">${icon("i-trash")}</button></div>`;
      $(".btn-danger", card).onclick = async () => { await api.del(`/api/style_refs/${r.id}`); loadRefs(); };
      grid.appendChild(card);
    });
  }
  $("#imIp", page).oninput = e => { cfg.ip_scale = +e.target.value; setIp(); };
  $("#imUseRefs", page).onchange = e => cfg.use_refs = e.target.checked;
  $("#imRefSeed", page).onclick = async () => {
    const msg = $("#imRefMsg", page); msg.textContent = "seeding…";
    try { const r = await api.post("/api/style_refs/seed", { pid: p.id, limit: 24 }); msg.textContent = `added ${r.added}`; loadRefs(); }
    catch (e) { msg.textContent = ""; toast(e.message, "err"); }
  };
  $("#imRefAdd", page).onclick = () => $("#imRefFile", page).click();
  $("#imRefFile", page).onchange = async e => {
    const files = [...e.target.files]; if (!files.length) return;
    const msg = $("#imRefMsg", page); msg.textContent = `uploading ${files.length}…`;
    try {
      for (const f of files) { const fd = new FormData(); fd.append("file", f); fd.append("tags", "cartoon"); await api.form("/api/style_refs/upload", fd); }
      msg.textContent = "uploaded ✓"; loadRefs();
    } catch (err) { msg.textContent = ""; toast(err.message, "err"); }
  };
  loadRefs();
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
/* ============================================================
   PAGE: ANIMATE  (LTX-2 image -> short clip)
   ============================================================ */
function animatableScenes() {
  return state.project.scenes.filter(s =>
    s.status.image === "ready" && (
      (s.motion_prompt && s.motion_prompt.trim()) ||
      ["ambient", "transform"].includes((s.motion_type || "").toLowerCase())));
}
async function renderAnimate(host) {
  const p = state.project; if (!p) { location.hash = "#/projects"; return; }
  try { state.status = await api.get("/api/status"); } catch (e) { }
  const ltx = (state.status && state.status.ltx) || { ready: false };
  const imgReady = p.scenes.filter(s => s.status.image === "ready").length;
  const vidReady = p.scenes.filter(s => s.status.video === "ready").length;
  const motion = animatableScenes();

  topbar(p.name, `Animate · ${vidReady}/${imgReady} stills animated`,
    `<button class="btn btn-ghost" onclick="location.hash='#/p/${p.id}/images'">${icon("i-back")} Images</button>
     <button class="btn btn-primary" onclick="location.hash='#/p/${p.id}/assemble'">${icon("i-assemble")} Assemble →</button>`);
  const page = el("div", "page page-wide"); page.innerHTML = stepper("animate");

  const cfg = Object.assign({ engine: "ltx", seconds: 1.5, fps: 12, width: 768, height: 512, seed: 42, motion_prompt: "" }, p.settings.animate || {});
  const wan = (state.status && state.status.wan) || { ready: false };
  const ENGINE_DEFAULTS = { ltx: { fps: 12, width: 768, height: 512, seconds: 1.5 }, wan: { fps: 16, width: 640, height: 640, seconds: 3 } };

  // --- model / readiness card ---
  const fileRow = (ok, label) => `<div class="row" style="gap:8px"><span class="badge ${ok ? "good" : ""}">${ok ? "✓" : "—"}</span><span class="${ok ? "" : "muted"}">${esc(label)}</span></div>`;
  const mcard = el("div", "card");
  mcard.innerHTML = `
    <div class="spread"><h2 class="mb0">LTX-2 model</h2><span class="badge ${ltx.ready ? "good" : "teal"}">${ltx.ready ? "ready" : "weights missing"}</span></div>
    <p class="desc">Animation turns each generated <b>still</b> into a short clip with <b>LTX-2</b> (image-to-video), through your local ComfyUI. It's heavy on a 16&nbsp;GB GPU, so only scenes whose storyboard declares motion (a <span class="mono">motion_prompt</span>, or <span class="mono">motion_type</span> = ambient/transform) are animated by default. <span class="mono">transform</span> scenes morph from the still to a krea2-rendered end frame.</p>
    <div class="grid2" style="margin:10px 0">
      ${fileRow(ltx.checkpoint, (ltx.files && ltx.files.checkpoint) || "LTX-2 19B checkpoint (fused)")}
      ${fileRow(ltx.text_encoder, (ltx.files && ltx.files.text_encoder) || "gemma text encoder")}
    </div>
    <div class="row" id="ltxDlRow" ${ltx.ready ? 'style="display:none"' : ""}>
      <button class="btn btn-ghost" id="ltxDl">${icon("i-download")} Download LTX-2 weights</button>
      <span class="muted" id="ltxDlMsg">LTX-2 19B (fp4, fits 16&nbsp;GB) + gemma encoder — downloads in-app.</span>
    </div>`;
  page.appendChild(mcard);

  // --- settings card ---
  const scard = el("div", "card"); scard.style.marginTop = "16px";
  scard.innerHTML = `
    <h2>Motion settings</h2>
    <div class="field"><label>Engine</label><select id="anEngine">
      <option value="ltx" ${cfg.engine === "ltx" ? "selected" : ""}>LTX-2 19B ${ltx.ready ? "" : "(weights missing)"}</option>
      <option value="wan" ${cfg.engine === "wan" ? "selected" : ""}>Wan 2.2 14B ${wan.ready ? "" : "(downloading / missing)"}</option>
    </select><span class="hint">LTX = flat-cartoon (short clips); Wan = best quality, shines on claymation/semi-real</span></div>
    <div class="grid3">
      <div class="field"><label>Clip length (s)</label><input type="number" id="anSec" value="${cfg.seconds}" min="1" max="8" step="0.5"/></div>
      <div class="field"><label>FPS</label><input type="number" id="anFps" value="${cfg.fps}" min="8" max="30"/></div>
      <div class="field"><label>Seed <span class="hint">(-1 random)</span></label><input type="number" id="anSeed" value="${cfg.seed}"/></div>
      <div class="field"><label>Width</label><input type="number" id="anW" value="${cfg.width}" step="32"/></div>
      <div class="field"><label>Height</label><input type="number" id="anH" value="${cfg.height}" step="32"/></div>
    </div>
    <div class="field"><label>Fallback motion <span class="hint">(used for scenes with no motion_prompt)</span></label>
      <input type="text" id="anMP" value="${esc(cfg.motion_prompt)}" placeholder="e.g. subtle ambient motion, slow drifting camera"/></div>`;
  page.appendChild(scard);

  // --- generate card ---
  const gcard = el("div", "card"); gcard.style.marginTop = "16px";
  gcard.innerHTML = `
    <div class="spread"><h2 class="mb0">Animate</h2><div class="row"><span class="badge ${vidReady ? "good" : ""}">${vidReady}/${imgReady} animated</span></div></div>
    <p class="desc">Clips are saved per scene and used automatically by Assemble (stills without a clip keep their Ken Burns pan).</p>
    <div class="row" id="anActions"></div>
    <div id="anRun" style="margin-top:16px"></div>
    <div class="divider"></div>
    <div class="media-grid" id="anGrid"></div>`;
  page.appendChild(gcard);
  host.appendChild(page);

  // wire settings
  const num = (id, k, f) => $(id, page).oninput = e => cfg[k] = f ? f(e.target.value) : +e.target.value;
  num("#anSec", "seconds"); num("#anFps", "fps"); num("#anSeed", "seed");
  num("#anW", "width"); num("#anH", "height");
  $("#anMP", page).oninput = e => cfg.motion_prompt = e.target.value;
  $("#anEngine", page).onchange = e => {
    cfg.engine = e.target.value;
    Object.assign(cfg, ENGINE_DEFAULTS[cfg.engine] || {});
    $("#anSec", page).value = cfg.seconds; $("#anFps", page).value = cfg.fps;
    $("#anW", page).value = cfg.width; $("#anH", page).value = cfg.height;
  };

  // download (headless in-app job)
  $("#ltxDl", page).onclick = async () => {
    const btn = $("#ltxDl", page), msg = $("#ltxDlMsg", page);
    btn.disabled = true;
    try {
      const { job_id } = await api.post("/api/ltx/download", {});
      await pollJob(job_id, j => msg.textContent = `${j.stage} ${Math.round((j.progress || 0) * 100)}%`);
      msg.textContent = "weights ready ✓";
      toast("LTX-2 weights ready");
      render();
    } catch (e) { btn.disabled = false; msg.textContent = ""; toast(e.message, "err"); }
  };

  function actions() {
    const a = $("#anActions", page); a.innerHTML = "";
    const gen = el("button", "btn btn-primary", `${icon("i-wand")} Animate motion scenes (${motion.length})`);
    gen.disabled = !ltx.ready || motion.length === 0;
    gen.onclick = () => runANI("motion");
    const all = el("button", "btn btn-ghost", `${icon("i-refresh")} Animate all stills (${imgReady})`);
    all.disabled = !ltx.ready || imgReady === 0;
    all.onclick = () => runANI("all");
    const fill = el("button", "btn btn-ghost", `${icon("i-wand")} Auto-fill prompts`);
    fill.onclick = async () => {
      try {
        const r = await api.post(`/api/projects/${p.id}/animate/autoprompt`, { overwrite: false });
        toast(`Filled ${r.filled}/${r.total} motion prompts`);
        await loadProject(p.id); render();
      } catch (e) { toast(e.message, "err"); }
    };
    a.append(gen, all, fill);
    a.append(el("span", "muted", "Tip: click a scene to preview, edit its prompt, and re-animate. For all 162 at once, run animate_all.bat (its own terminal)."));
    if (!ltx.ready) a.append(el("span", "muted", "Download the LTX-2 weights above to enable animation."));
  }
  function drawGrid() {
    const grid = $("#anGrid", page); grid.innerHTML = "";
    state.project.scenes.forEach(s => {
      if (s.status.image !== "ready") return;
      const card = el("div", "media-card");
      const can = (s.motion_prompt && s.motion_prompt.trim()) || ["ambient", "transform"].includes((s.motion_type || "").toLowerCase());
      const frame = s.video_file
        ? `<video src="${assetUrl(s.video_file, Date.now())}" muted loop autoplay playsinline></video>`
        : `<img src="${assetUrl(s.image_file, Date.now())}" loading="lazy"/>`;
      const stale = s.status.video === "stale";
      const tag = s.video_file ? `<span class="badge ${stale ? "" : "good"}">${stale ? "edited" : "clip"}</span>` : (can ? `<span class="badge teal">${esc((s.motion_type || "motion"))}</span>` : "");
      card.innerHTML = `<div class="frame">${frame}</div>
        <div class="cap"><div class="t">scene <b>${s.id}</b> ${tag}</div>
        <button class="btn-icon" title="Preview / edit / animate">${icon("i-wand")}</button></div>`;
      const open = () => openAnimScene(s.id);
      card.querySelector(".frame").onclick = open;
      $(".btn-icon", card).onclick = open;
      grid.appendChild(card);
    });
  }
  actions(); drawGrid();

  async function runANI(scope, sceneId) {
    const runEl = $("#anRun", page);
    runEl.innerHTML = `<div class="run-panel"><div class="spinner"></div><div style="flex:1"><div class="lab" id="anStage">Starting…</div><div class="progress teal" style="margin-top:8px"><div class="bar" id="anBar"></div></div></div></div>`;
    try {
      await api.put(`/api/projects/${p.id}/settings`, { animate: cfg });
      const { job_id } = await api.post(`/api/projects/${p.id}/animate`, { opts: cfg, scope, scene_id: sceneId != null ? String(sceneId) : null });
      const res = await pollJob(job_id, j => { const st = $("#anStage", page); if (st) st.textContent = j.stage; const b = $("#anBar", page); if (b) b.style.width = Math.round((j.progress || 0) * 100) + "%"; });
      await loadProject(p.id); runEl.innerHTML = "";
      toast(`Animated ${res.done} scene(s)`);
      render();
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
  }
}

/* scene animation modal: preview the clip, edit the motion prompt, re-animate */
function openAnimScene(sid) {
  const p = state.project; if (!p) return;
  const s = p.scenes.find(x => String(x.id) === String(sid)); if (!s) return;
  const ltxReady = !!(state.status && state.status.ltx && state.status.ltx.ready);
  const a = Object.assign({ seconds: 4, fps: 25, width: 768, height: 512, seed: 42 }, p.settings.animate || {});
  const preview = s.video_file
    ? `<video src="${assetUrl(s.video_file, Date.now())}" controls loop autoplay muted playsinline style="width:100%;border-radius:10px;background:#000"></video>`
    : (s.image_file ? `<img src="${assetUrl(s.image_file, Date.now())}" style="width:100%;border-radius:10px"/>` : `<div class="ph">scene ${s.id}</div>`);
  const mt = (s.motion_type || "ambient").toLowerCase();
  const card = openModal(`
    <div class="modal-head"><h2 class="mb0">Scene ${s.id} · animation</h2><button class="btn-icon" id="asX">${icon("i-x")}</button></div>
    <div style="margin-bottom:12px">${preview}</div>
    <p class="muted" style="font-size:12px;margin:-4px 0 10px">Still subject: ${esc((s.image_prompt || "").slice(0, 140))}</p>
    <div class="field"><label>Motion prompt <span class="hint">(what moves + camera)</span></label>
      <textarea id="asMP" rows="3" style="width:100%">${esc(s.motion_prompt || "")}</textarea></div>
    <div class="grid2">
      <div class="field"><label>Motion type</label><select id="asMT">
        ${["ambient", "transform", "still"].map(o => `<option value="${o}" ${mt === o ? "selected" : ""}>${o}</option>`).join("")}
      </select></div>
      <div class="field"><label>Clip length (s)</label><input type="number" id="asSec" value="${a.seconds}" min="1" max="8" step="0.5"/></div>
    </div>
    <div class="field" id="asEndWrap" style="display:${mt === "transform" ? "" : "none"}"><label>End-frame prompt <span class="hint">(transform: krea2 renders this, LTX morphs to it)</span></label>
      <input type="text" id="asEnd" value="${esc(s.end_image_prompt || "")}" placeholder="e.g. the same scene but the chart has skyrocketed"/></div>
    <div id="asRun" style="margin:10px 0"></div>
    <div class="row row-end">
      <button class="btn btn-ghost" id="asSave">Save prompt</button>
      <button class="btn btn-primary" id="asGo" ${ltxReady ? "" : "disabled"}>${icon("i-wand")} ${s.video_file ? "Re-animate" : "Animate"}</button>
    </div>
    ${ltxReady ? "" : '<p class="muted" style="font-size:12px;margin-top:8px">LTX-2 weights not ready — download them on the Animate page.</p>'}`);
  $("#asX", card).onclick = closeModal;
  $("#asMT", card).onchange = e => $("#asEndWrap", card).style.display = e.target.value === "transform" ? "" : "none";

  const collect = () => ({
    motion_prompt: $("#asMP", card).value.trim(),
    motion_type: $("#asMT", card).value,
    end_image_prompt: $("#asEnd", card).value.trim(),
  });
  async function save() {
    await api.patch(`/api/projects/${p.id}/scenes/${s.id}`, collect());
    await loadProject(p.id);
  }
  $("#asSave", card).onclick = async () => {
    try { await save(); toast(`Scene ${s.id} prompt saved`); render(); } catch (e) { toast(e.message, "err"); }
  };
  $("#asGo", card).onclick = async () => {
    const runEl = $("#asRun", card);
    runEl.innerHTML = `<div class="run-panel"><div class="spinner"></div><div style="flex:1"><div class="lab" id="asStage">Starting ComfyUI…</div><div class="progress teal" style="margin-top:8px"><div class="bar" id="asBar"></div></div><div class="muted" style="font-size:11px;margin-top:6px">~10 min on a 16 GB GPU — watch it in the ComfyUI window/tab that opens.</div></div></div>`;
    try {
      await save();
      const opts = { ...a, seconds: +$("#asSec", card).value };
      await api.put(`/api/projects/${p.id}/settings`, { animate: opts });
      const { job_id } = await api.post(`/api/projects/${p.id}/animate`, { opts, scope: "scene", scene_id: String(s.id) });
      await pollJob(job_id, j => { const st = $("#asStage", card); if (st) st.textContent = j.stage; const b = $("#asBar", card); if (b) b.style.width = Math.round((j.progress || 0) * 100) + "%"; });
      await loadProject(p.id); toast(`Scene ${s.id} animated`);
      closeModal(); render(); openAnimScene(s.id);
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
  };
}

async function renderAssemble(host) {
  const p = state.project; if (!p) { location.hash = "#/projects"; return; }
  const c = sceneCounts();
  topbar(p.name, `Assemble · sync voiceover + images into MP4`,
    `<button class="btn btn-ghost" onclick="location.hash='#/p/${p.id}/images'">${icon("i-back")} Images</button>
     <button class="btn btn-primary" onclick="location.hash='#/p/${p.id}/preview'">${icon("i-preview")} Preview →</button>`);
  const page = el("div", "page"); page.innerHTML = stepper("assemble");

  const opts = Object.assign({ width: 1920, height: 1080, fps: 30, preset: "cinematic", ken_burns: true, transitions: true, sfx: true }, p.settings.assemble || {});
  delete opts.burn_text;   // on-screen text is never burned anymore
  const RES = [[1920, 1080, "1080p"], [1280, 720, "720p"], [854, 480, "480p (fast)"]];
  const SOURCES = [["", "Preset default"], ["clips,parallax", "LTX clips + parallax (both)"], ["parallax", "Parallax only (no LTX)"], ["clips", "LTX clips only"], ["stills", "Stills (Ken Burns)"]];

  const card = el("div", "card");
  card.innerHTML = `
    <h2>Build the video</h2>
    <p class="desc">Each scene shows for its real narration length. The <b>style preset</b> decides how scenes move — LTX clips, 2.5D <b>parallax</b> (depth camera moves on stills), or classic Ken Burns — plus stinger SFX and music ducking. Presets live in <span class="mono">data/effects_presets.json</span> and are reusable across projects.</p>
    <div class="row" style="margin-bottom:14px">
      <span class="badge ${c.audio === c.total ? "good" : "warn"}">${c.audio}/${c.total} voiced</span>
      <span class="badge ${c.image === c.total ? "good" : "warn"}">${c.image}/${c.total} imaged</span>
      <span class="badge" id="asVoiceKind">${p.narration ? "one-take narration ✓" : "per-scene audio"}</span>
    </div>
    <div class="grid3">
      <div class="field"><label>Style preset</label><select id="asPreset"><option>${esc(opts.preset || "cinematic")}</option></select></div>
      <div class="field"><label>Scene motion</label><select id="asSources">
        ${SOURCES.map(([v, l]) => `<option value="${v}" ${(opts.sources || []).join(",") === v ? "selected" : ""}>${l}</option>`).join("")}
      </select></div>
      <div class="field"><label>Resolution</label><select id="asRes">
        ${RES.map(([w, h, l]) => `<option value="${w}x${h}" ${opts.width === w ? "selected" : ""}>${l} (${w}×${h})</option>`).join("")}
      </select></div>
    </div>
    <div class="grid3">
      <div class="field"><label>FPS</label><select id="asFps">${[24, 30, 60].map(f => `<option ${opts.fps === f ? "selected" : ""}>${f}</option>`).join("")}</select></div>
      <div class="field" style="justify-content:flex-end"><label>&nbsp;</label>
        <div class="row" style="gap:18px">
          <label class="switch"><input type="checkbox" id="asTrans" ${opts.transitions ? "checked" : ""}/><span class="track"></span> Transitions</label>
          <label class="switch"><input type="checkbox" id="asSfx" ${opts.sfx !== false ? "checked" : ""}/><span class="track"></span> Stinger SFX</label>
        </div></div>
    </div>
    <div class="row">
      <button class="btn btn-primary" id="asGo">${icon("i-assemble")} Build video</button>
      <button class="btn btn-ghost" id="asProduce" title="voice → images → animate → assemble in one go">${icon("i-wand")} Produce everything</button>
      <label class="switch" style="margin-left:6px"><input type="checkbox" id="asRevoice"/><span class="track"></span> Re-voice (one take)</label>
      <span class="muted" id="asEta"></span>
    </div>
    <div id="asRun" style="margin-top:16px"></div>`;
  page.appendChild(card);

  const rcard = el("div", "card"); rcard.style.marginTop = "16px";
  rcard.innerHTML = `<div class="section-title">Renders</div><div id="asRenders"></div>`;
  page.appendChild(rcard);
  host.appendChild(page);

  $("#asRes", page).onchange = e => { const [w, h] = e.target.value.split("x").map(Number); opts.width = w; opts.height = h; };
  $("#asFps", page).onchange = e => opts.fps = +e.target.value;
  $("#asTrans", page).onchange = e => opts.transitions = e.target.checked;
  $("#asSfx", page).onchange = e => opts.sfx = e.target.checked;
  $("#asSources", page).onchange = e => {
    opts.sources = e.target.value ? e.target.value.split(",") : null;
    if (!opts.sources) delete opts.sources;
  };
  // fill the preset dropdown from the shared library
  (async () => {
    try {
      const { presets } = await api.get("/api/effects_presets");
      $("#asPreset", page).innerHTML = presets.map(pr =>
        `<option value="${esc(pr.id)}" ${pr.id === (opts.preset || "cinematic") ? "selected" : ""}>${esc(pr.label || pr.id)}</option>`).join("");
    } catch (e) { }
  })();
  $("#asPreset", page).onchange = e => opts.preset = e.target.value;

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

  // One click, whole pipeline: voice (one-take) → images → animate → assemble.
  $("#asProduce", page).onclick = async () => {
    const runEl = $("#asRun", page);
    runEl.innerHTML = `<div class="run-panel"><div class="spinner"></div><div style="flex:1"><div class="lab" id="asStage">Starting production…</div><div class="progress" style="margin-top:8px"><div class="bar" id="asBar"></div></div></div></div>`;
    try {
      await api.put(`/api/projects/${p.id}/settings`, { assemble: opts });
      const plan = { assemble: opts };
      if ($("#asRevoice", page).checked) plan.voice = "onetake";
      await api.post(`/api/projects/${p.id}/produce`, { plan });
      const st = await new Promise((resolve, reject) => {
        const t = setInterval(async () => {
          try {
            const s = await api.get(`/api/projects/${p.id}/produce`);
            const lab = $("#asStage", page); if (lab) lab.textContent = s.stage || s.status;
            const b = $("#asBar", page); if (b && s.progress != null) b.style.width = Math.round(s.progress * 100) + "%";
            if (s.status === "done") { clearInterval(t); resolve(s); }
            else if (s.status === "error") { clearInterval(t); reject(new Error(s.error || "production failed")); }
          } catch (e) { clearInterval(t); reject(e); }
        }, 3000);
      });
      await loadProject(p.id); runEl.innerHTML = "";
      toast("Production finished ✓"); drawRenders(); renderNav();
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
  };
}
async function renderPreview(host) {
  const p = state.project; if (!p) { location.hash = "#/projects"; return; }
  topbar(p.name, p.narration ? "Preview · plays your voiceover, images timed to it" : "Preview · in-browser timeline (audio-led)",
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
  const bgAudio = new Audio(); bgAudio.loop = true;
  // Voiceover-first projects play one continuous master track (the audio is the
  // clock; we only switch images). Per-scene projects keep the old per-clip path.
  const master = (p.narration && p.narration.file) ? assetUrl(p.narration.file, 1) : null;
  if (master) audio.src = master;
  const _pm = (p.settings && p.settings.music) || null;
  if (_pm && _pm.file) { bgAudio.src = `/music/${_pm.file}`; bgAudio.volume = clamp(_pm.volume != null ? _pm.volume : 0.18, 0, 1); }
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
    if (seekAudio && !master) {
      if (s.audio_file) { audio.src = assetUrl(s.audio_file, 1); audio.currentTime = 0; if (playing) audio.play().catch(() => { }); }
      else { audio.removeAttribute("src"); audio.load(); }
    }
  }
  function frame(now) {
    if (!playing) return;
    if (master) t = audio.currentTime;                       // the recording is the clock
    else { const dt = (now - last) / 1000; t += dt; }
    last = now;
    if (t >= total) { t = total; pause(); update(); return; }
    const i = sceneAt(t);
    if (i !== curIdx) showScene(i, true);
    update(); raf = requestAnimationFrame(frame);
  }
  function update() {
    seek.style.width = total ? (t / total * 100) + "%" : "0%";
    timeEl.textContent = `${fmtClock(t)} / ${fmtClock(total)}`;
  }
  function play() {
    if (playing || !total) return;
    playing = true; playBtn.innerHTML = icon("i-pause"); last = performance.now();
    const i = sceneAt(t); showScene(i, true);
    if (master) { try { audio.currentTime = t; } catch (e) { } audio.play().catch(() => { }); }
    else { const s = byId[rows[i].id]; if (s && s.audio_file) { audio.currentTime = Math.max(0, t - rows[i].start); audio.play().catch(() => { }); } }
    if (bgAudio.src) { try { bgAudio.currentTime = t % (bgAudio.duration || 1e9); } catch (e) { } bgAudio.play().catch(() => { }); }
    raf = requestAnimationFrame(frame);
  }
  function pause() { playing = false; playBtn.innerHTML = icon("i-play"); audio.pause(); bgAudio.pause(); if (raf) cancelAnimationFrame(raf); }
  playBtn.onclick = () => playing ? pause() : play();
  $("#pvScrub", page).onclick = e => {
    const rect = e.currentTarget.getBoundingClientRect(); t = total * clamp((e.clientX - rect.left) / rect.width, 0, 1);
    const i = sceneAt(t); showScene(i, true);
    if (master) { try { audio.currentTime = t; } catch (e2) { } }
    else if (playing && byId[rows[i].id].audio_file) audio.currentTime = Math.max(0, t - rows[i].start);
    update();
  };
  if (rows.length) showScene(0, false);
  update();
  page.appendChild(await musicCard(p, bgAudio));
  // stop audio when leaving the page
  window.addEventListener("hashchange", () => { try { audio.pause(); bgAudio.pause(); } catch (e) { } }, { once: true });
}

/* ---------- background music / SFX panel (ACE-Step) ---------- */
async function musicCard(p, bgAudio) {
  const card = el("div", "card"); card.style.marginTop = "16px";
  card.innerHTML = `
    <div class="spread"><h2 class="mb0">Background music <span class="hint">(ACE-Step)</span></h2><div class="row" id="muMeta"></div></div>
    <p class="desc">Generate an instrumental bed or a sound effect, then set one as this video's background — it plays under the narration here in the preview and in the final render.</p>
    <div id="muSetup"></div>
    <div id="muGen" hidden>
      <div class="grid2" style="margin-bottom:10px;align-items:end">
        <div class="field"><label>Describe the music / sound</label><textarea id="muPrompt" rows="2" placeholder="e.g. calm cinematic ambient bed, soft warm pads, slow, instrumental"></textarea></div>
        <div>
          <div class="field"><label>Type</label><div class="row" id="muKind"></div></div>
          <div class="field"><label>Length <span class="hint" id="muLenVal"></span></label><input type="range" id="muLen" min="3" max="120" step="1" value="30"/></div>
        </div>
      </div>
      <div class="row" id="muPresets" style="gap:6px;flex-wrap:wrap;margin-bottom:10px"></div>
      <div class="row"><button class="btn btn-primary" id="muGo">${icon("i-voice")} Generate</button><span class="muted mono" id="muMsg"></span></div>
      <div id="muRun" style="margin-top:12px"></div>
    </div>
    <div class="divider"></div>
    <div class="section-title">This video's background</div>
    <div id="muCurrent" style="margin-bottom:6px"></div>
    <div class="divider"></div>
    <div class="section-title">Library</div>
    <div class="scene-list" id="muLib"></div>`;

  const sel = { kind: "music", seconds: 30 };
  let data = { library: [], presets: [], status: {} };
  try { data = await api.get("/api/music"); } catch (e) { }

  function meta() {
    const s = data.status || {};
    let label = "not installed", cls = "";
    if (s.available && s.loaded) { label = "ready · " + (s.model || ""); cls = "good"; }
    else if (s.available && s.loading) { label = "loading…"; cls = "teal"; }
    else if (s.available && s.model_ready) { label = "model ready"; cls = "teal"; }
    else if (s.available) { label = "needs download"; cls = ""; }
    $("#muMeta", card).innerHTML = `<span class="badge ${cls}">${esc(label)}</span>`;
  }
  function setup() {
    const s = data.status || {}; const host = $("#muSetup", card); host.innerHTML = "";
    const gen = $("#muGen", card);
    if (!s.available) {
      host.innerHTML = `<div class="muted" style="padding:8px 2px">ACE-Step isn't installed yet (its isolated venv is still being set up). Check back once setup finishes.</div>`;
      gen.hidden = true; return;
    }
    if (!s.model_ready && !s.loaded) {
      const b = el("button", "btn btn-primary", `${icon("i-download")} Download music model (~9 GB, one-time)`);
      const msg = el("span", "muted mono"); msg.style.marginLeft = "10px";
      b.onclick = async () => {
        b.disabled = true;
        try {
          const { job_id } = await api.post("/api/music/download", {});
          await pollJob(job_id, j => { msg.textContent = j.stage + " " + Math.round((j.progress || 0) * 100) + "%"; });
          data = await api.get("/api/music"); meta(); setup();
          toast("Music model ready");
        } catch (e) { b.disabled = false; msg.textContent = ""; toast(e.message, "err"); }
      };
      host.append(b, msg); gen.hidden = true; return;
    }
    gen.hidden = false;
  }
  function drawKind() {
    const k = $("#muKind", card); k.innerHTML = "";
    [["music", "Music bed"], ["sfx", "Sound effect"]].forEach(([v, lab]) => {
      const b = el("button", "btn btn-sm " + (sel.kind === v ? "btn-primary" : "btn-ghost"), lab);
      b.onclick = () => { sel.kind = v; if (v === "sfx" && sel.seconds > 10) { sel.seconds = 5; $("#muLen", card).value = 5; lenVal(); } drawKind(); };
      k.appendChild(b);
    });
  }
  const lenVal = () => { sel.seconds = +$("#muLen", card).value; $("#muLenVal", card).textContent = sel.seconds + "s"; };
  function drawPresets() {
    const host = $("#muPresets", card); host.innerHTML = "";
    (data.presets || []).forEach(pr => {
      const b = el("button", "btn btn-sm btn-ghost", esc(pr.name));
      b.title = pr.prompt;
      b.onclick = () => { $("#muPrompt", card).value = pr.prompt; sel.kind = pr.kind || "music"; sel.seconds = pr.seconds || (sel.kind === "sfx" ? 5 : 30); $("#muLen", card).value = sel.seconds; lenVal(); drawKind(); };
      host.appendChild(b);
    });
  }
  function current() {
    const host = $("#muCurrent", card); host.innerHTML = "";
    const m = (state.project.settings && state.project.settings.music) || null;
    if (!m || !m.file) { host.innerHTML = `<div class="muted" style="padding:4px 2px">No background music set — generate one below and click “Use as background”.</div>`; return; }
    const row = el("div", "scene-row"); row.style.gridTemplateColumns = "1fr auto";
    row.innerHTML = `
      <div class="scene-body">
        <div class="narr">${esc(m.prompt || m.file)}</div>
        <div class="sub" style="align-items:center;gap:10px"><span>volume</span><input type="range" id="muVol" min="0" max="0.6" step="0.02" value="${m.volume != null ? m.volume : 0.18}" style="max-width:160px"/><span class="mono" id="muVolVal"></span></div>
        <audio controls preload="none" src="/music/${m.file}" style="height:34px;width:100%;max-width:440px;margin-top:6px"></audio>
      </div>
      <div class="scene-meta"><button class="btn btn-sm btn-ghost" id="muClear">${icon("i-x")} Remove</button></div>`;
    host.appendChild(row);
    const vv = () => $("#muVolVal", card).textContent = (+$("#muVol", card).value).toFixed(2);
    vv();
    $("#muVol", card).oninput = () => { bgAudio.volume = clamp(+$("#muVol", card).value, 0, 1); vv(); };
    $("#muVol", card).onchange = () => setBg(m.file, m.id, m.prompt, +$("#muVol", card).value);
    $("#muClear", card).onclick = () => setBg(null);
  }
  async function setBg(file, id, prompt, volume) {
    try {
      const body = file ? { file, id, prompt, volume: volume != null ? volume : 0.18 } : { file: null };
      const settings = await api.put(`/api/projects/${state.project.id}/music`, body);
      state.project.settings = settings;
      if (file) { bgAudio.src = `/music/${file}`; bgAudio.volume = clamp(volume != null ? volume : 0.18, 0, 1); }
      else { bgAudio.removeAttribute("src"); bgAudio.load(); }
      current();
      toast(file ? "Background music set" : "Background removed");
    } catch (e) { toast(e.message, "err"); }
  }
  function library() {
    const host = $("#muLib", card); host.innerHTML = "";
    if (!data.library.length) { host.innerHTML = `<div class="muted" style="padding:8px 2px">No clips yet — generate one above.</div>`; return; }
    data.library.forEach(it => {
      const f = (it.files || {}).mp3 || (it.files || {}).wav; if (!f) return;
      const row = el("div", "scene-row"); row.style.gridTemplateColumns = "1fr auto";
      row.innerHTML = `
        <div class="scene-body">
          <div class="narr">${esc(it.prompt || "clip")}</div>
          <div class="sub"><span class="badge ${it.kind === "sfx" ? "" : "teal"}">${esc(it.kind || "music")}</span>${it.duration ? `<span>${fmtClock(it.duration)}</span>` : ""}<span>${fmtAgo(it.created)}</span></div>
          <audio controls preload="none" src="/music/${f}" style="height:34px;width:100%;max-width:440px;margin-top:6px"></audio>
        </div>
        <div class="scene-meta">
          <button class="btn btn-sm btn-ghost muUse">${icon("i-check")} Use as background</button>
          <a class="btn-icon" href="/music/${f}" download title="Download">${icon("i-download")}</a>
          <button class="btn-icon btn-danger muDel" title="Delete">${icon("i-trash")}</button>
        </div>`;
      $(".muUse", row).onclick = () => setBg(f, it.id, it.prompt, ((state.project.settings || {}).music || {}).volume);
      $(".muDel", row).onclick = async () => { try { await api.del(`/api/music/${it.id}`); data.library = data.library.filter(x => x.id !== it.id); library(); toast("Deleted"); } catch (e) { toast(e.message, "err"); } };
      host.appendChild(row);
    });
  }

  async function runGen() {
    const prompt = $("#muPrompt", card).value.trim();
    if (!prompt) { toast("Describe the music or sound first.", "err"); return; }
    const runEl = $("#muRun", card), btn = $("#muGo", card);
    btn.disabled = true;
    runEl.innerHTML = `<div class="run-panel"><div class="spinner"></div><div style="flex:1"><div class="lab" id="muStage">Starting…</div><div class="progress" style="margin-top:8px"><div class="bar" id="muBar"></div></div></div></div>`;
    try {
      const { job_id } = await api.post("/api/music", { prompt, kind: sel.kind, seconds: sel.seconds, instrumental: true });
      const res = await pollJob(job_id, j => { const st = $("#muStage", card); if (st) st.textContent = j.stage; const b = $("#muBar", card); if (b) b.style.width = Math.round((j.progress || 0) * 100) + "%"; });
      runEl.innerHTML = "";
      data = await api.get("/api/music"); meta(); library();
      toast("Clip generated");
      if (res.item) { const f = (res.item.files || {}).mp3 || (res.item.files || {}).wav; if (f) new Audio(`/music/${f}`).play().catch(() => { }); }
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
    finally { btn.disabled = false; }
  }

  meta(); setup(); drawKind(); lenVal(); drawPresets(); current(); library();
  $("#muLen", card).oninput = lenVal;
  $("#muGo", card).onclick = runGen;
  return card;
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

/* ---------- Training (LoRA) ---------- */
let _trainPoll = null;
async function renderTraining(host) {
  topbar("Training", "Train custom LoRAs from your own image datasets — no terminal needed");
  if (_trainPoll) { clearInterval(_trainPoll); _trainPoll = null; }
  const page = el("div", "page page-wide");
  host.appendChild(page);

  async function load() {
    let data;
    try { data = await api.get("/api/training/datasets"); }
    catch (e) { page.innerHTML = `<div class="card"><p class="muted">${esc(e.message)}</p></div>`; return; }
    draw(data);
  }

  function draw(data) {
    const st = data.status || {}, run = st.run, dss = data.datasets || [];
    page.innerHTML = "";

    const head = el("div", "card");
    head.innerHTML = `
      <div class="spread"><h2 class="mb0">Train a LoRA</h2>
        <span class="badge ${st.krea2_ready ? "good" : "warn"}">krea2 ${st.krea2_ready ? "ready" : "weights missing"}</span></div>
      <p class="desc">Drop 20–200 images into <code>training/&lt;base&gt;/&lt;name&gt;/dataset/</code> (e.g. <code>training/krea2/my-style/dataset/</code>), then hit <b>Train</b>. The result drops into ComfyUI's loras + the Images page. <b>krea2</b> = your flat-cartoon model; SDXL / SD1.5 / FLUX unlock once their trainers are installed.</p>
      <div class="row"><button class="btn btn-ghost btn-sm" id="trRefresh">${icon("i-refresh")} Rescan datasets</button></div>`;
    page.appendChild(head);
    $("#trRefresh", page).onclick = load;

    // --- Build a LoRA dataset from a project's scenes (caption generator) ---
    const projs = state.projects || [];
    const CAP_FIELDS = [["trigger", "trigger"], ["style", "style"], ["camera", "camera/shot"], ["characters", "characters"], ["emotion", "emotion"], ["action", "pose/action"], ["subject", "subject"], ["act", "act"], ["on_screen_text", "on-screen text"]];
    const capDef = { trigger: true, style: false, camera: true, act: false, characters: true, emotion: true, action: true, subject: true, on_screen_text: false };
    const dsb = el("div", "card"); dsb.style.marginTop = "16px";
    dsb.innerHTML = `
      <h2 class="mb0">Build a dataset from your scenes <span class="hint">(JSON → captions)</span></h2>
      <p class="desc">Turn a project's rendered scenes into a trainer-ready dataset. Each image gets a <b>.txt caption generated from its scene metadata</b> (camera, character emotion/action, subject) plus a rich <b>.json scene graph</b> kept as the source of truth — so you can re-caption everything in seconds by changing the template, no relabeling.</p>
      <div class="grid2">
        <div class="field"><label>From project</label><select id="dsbProj">${projs.map(p => `<option value="${p.id}">${esc(p.name)} · ${p.image_done || 0}/${p.scenes} images</option>`).join("") || `<option value="">— no projects —</option>`}</select></div>
        <div class="field"><label>Base model</label><select id="dsbBase"><option value="krea2">krea2</option><option value="sdxl">sdxl</option><option value="flux">flux</option><option value="sd15">sd15</option></select></div>
      </div>
      <div class="grid2">
        <div class="field"><label>Dataset name</label><input id="dsbName" placeholder="e.g. my-style"/></div>
        <div class="field"><label>Trigger word <span class="hint">(absorbs the look)</span></label><input id="dsbTrig" placeholder="e.g. mychannel"/></div>
      </div>
      <div class="field"><label>Caption template <span class="hint">(toggle what the LoRA learns)</span></label><div class="row" id="dsbOpts" style="gap:14px;flex-wrap:wrap"></div></div>
      <div class="field"><label>Preview</label><div id="dsbPreview" class="mono" style="font-size:12px;white-space:pre-wrap;background:#11100d;color:#d8d2c4;padding:10px;border-radius:8px;min-height:40px"></div></div>
      <div class="row"><button class="btn btn-ghost btn-sm" id="dsbPrev">${icon("i-refresh")} Preview</button><button class="btn btn-primary" id="dsbBuild">${icon("i-plus")} Build dataset</button><button class="btn btn-ghost btn-sm" id="dsbRecap">${icon("i-refresh")} Recaption existing</button><span class="muted mono" id="dsbMsg"></span></div>`;
    page.appendChild(dsb);
    const optsEl = $("#dsbOpts", page);
    CAP_FIELDS.forEach(([k, lab]) => {
      const w = el("label", "switch"); w.style.fontSize = "13px";
      w.innerHTML = `<input type="checkbox" id="dsbOpt_${k}" ${capDef[k] ? "checked" : ""}/><span class="track"></span> ${lab}`;
      optsEl.appendChild(w);
    });
    const readOpts = () => { const o = {}; CAP_FIELDS.forEach(([k]) => o[k] = $("#dsbOpt_" + k, page).checked); return o; };
    async function dsbPreview() {
      const pid = $("#dsbProj", page).value; if (!pid) { $("#dsbPreview", page).textContent = "(no project)"; return; }
      try {
        const { samples } = await api.post(`/api/projects/${pid}/captions/preview`, { trigger: $("#dsbTrig", page).value.trim(), opts: readOpts() });
        $("#dsbPreview", page).textContent = (samples || []).map(s => `scene ${s.scene}: ${s.caption}`).join("\n") || "(render some scene images first)";
      } catch (e) { $("#dsbPreview", page).textContent = e.message; }
    }
    $("#dsbPrev", page).onclick = dsbPreview;
    $("#dsbBuild", page).onclick = async () => {
      const pid = $("#dsbProj", page).value, name = $("#dsbName", page).value.trim();
      if (!pid || !name) { toast("Pick a project and a dataset name.", "err"); return; }
      const b = $("#dsbBuild", page); b.disabled = true; $("#dsbMsg", page).textContent = "building…";
      try {
        const r = await api.post("/api/training/dataset/from_scenes", { pid, base: $("#dsbBase", page).value, name, trigger: $("#dsbTrig", page).value.trim(), opts: readOpts() });
        $("#dsbMsg", page).textContent = ""; toast(`Built ${r.images} image/caption pairs → ${r.base}/${r.name}`); load();
      } catch (e) { $("#dsbMsg", page).textContent = ""; toast(e.message, "err"); } finally { b.disabled = false; }
    };
    $("#dsbRecap", page).onclick = async () => {
      const name = $("#dsbName", page).value.trim(); if (!name) { toast("Enter the dataset name to recaption.", "err"); return; }
      try {
        const r = await api.post("/api/training/dataset/recaption", { base: $("#dsbBase", page).value, name, trigger: $("#dsbTrig", page).value.trim(), opts: readOpts() });
        toast(`Recaptioned ${r.recaptioned} images in seconds`);
        if (r.samples && r.samples.length) $("#dsbPreview", page).textContent = r.samples.map((c, i) => `#${i + 1}: ${c}`).join("\n");
      } catch (e) { toast(e.message, "err"); }
    };
    CAP_FIELDS.forEach(([k]) => $("#dsbOpt_" + k, page).onchange = dsbPreview);
    $("#dsbProj", page).onchange = dsbPreview; $("#dsbTrig", page).oninput = dsbPreview;
    dsbPreview();

    const colab = el("div", "card"); colab.style.marginTop = "16px";
    colab.innerHTML = `
      <div class="spread"><h2 class="mb0">Train on Google Colab</h2><span class="badge gold">A100 · ~30 min · fastest</span></div>
      <p class="desc">Train on a cloud A100 instead of your 16&nbsp;GB card — much faster, and it pulls the weights itself (no big local download). Runs entirely in your own Colab.</p>
      <div class="row" style="margin-bottom:12px">
        <a class="btn btn-primary btn-sm" href="/krea2_lora_colab.ipynb" download>${icon("i-download")} Download Colab notebook</a>
        <a class="btn btn-ghost btn-sm" href="https://colab.research.google.com" target="_blank" rel="noopener">Open Google Colab (new tab)</a>
      </div>
      <ol class="desc" style="line-height:1.75;padding-left:20px;margin:0 0 4px">
        <li>Download the notebook above, then in Colab: <b>File &rsaquo; Upload notebook</b> &rsaquo; pick it.</li>
        <li><b>Runtime &rsaquo; Change runtime type &rsaquo; GPU &rsaquo; A100</b> (Colab Pro). L4 / T4 also work — set <code>SMALL_GPU = True</code> in the train cell.</li>
        <li>Zip your images into one <code>.zip</code>; run the cells top-to-bottom and choose it at the <b>Upload</b> step.</li>
        <li>Set your <b>trigger word</b> + <b>name</b> in the config cell, then let it run (~30&nbsp;min on A100).</li>
        <li>The last cell downloads <code>your-lora.safetensors</code> — drop it in <code>ComfyUI\\models\\loras\\</code> and select it on the <b>Images</b> page.</li>
      </ol>
      <p class="muted" style="font-size:12px;margin-top:10px">Auto-downloaded by the notebook:
        <a href="https://huggingface.co/krea/Krea-2-Raw" target="_blank" rel="noopener">Krea-2-Raw</a> ·
        <a href="https://huggingface.co/Comfy-Org/Qwen3-VL" target="_blank" rel="noopener">Qwen3-VL text encoder</a> ·
        <a href="https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI" target="_blank" rel="noopener">Qwen-Image VAE</a> ·
        <a href="https://github.com/kohya-ss/musubi-tuner/blob/main/docs/krea2.md" target="_blank" rel="noopener">musubi-tuner trainer</a></p>`;
    page.appendChild(colab);

    const card = el("div", "card"); card.style.marginTop = "16px";
    card.innerHTML = `<div class="section-title">Datasets <span class="muted" style="font-weight:400">· or train locally</span></div><div id="trList"></div>`;
    page.appendChild(card);
    const list = $("#trList", card);
    if (!dss.length) list.innerHTML = `<div class="empty">${icon("i-image")}<h3>No datasets yet</h3><p>Create <code>training/krea2/&lt;name&gt;/dataset/</code>, add images, then Rescan.</p></div>`;
    dss.forEach(d => {
      const trig = d.name.toLowerCase().replace(/[^a-z0-9]/g, "");
      const row = el("div", "scene-row"); row.style.gridTemplateColumns = "1fr auto";
      row.innerHTML = `
        <div class="scene-body">
          <div class="narr">${esc(d.name)} <span class="badge">${esc(d.base)}</span>${d.trained.length ? `<span class="badge good">trained</span>` : ""}</div>
          <div class="sub"><span>${d.images} images</span><span>${d.captions} captions</span>${d.trained.length ? `<span>${esc(d.trained.join(", "))}</span>` : ""}${d.trainable ? "" : `<span class="badge warn">trainer not ready</span>`}</div>
        </div>
        <div class="scene-meta">
          <input type="text" class="trTrig" value="${esc(trig)}" placeholder="trigger" title="trigger word" style="width:120px"/>
          <input type="number" class="trEp" value="12" min="1" max="40" title="epochs" style="width:60px"/>
          <button class="btn btn-primary btn-sm trGo" ${(!d.trainable || st.active || !d.images) ? "disabled" : ""}>${icon("i-wand")} Train</button>
        </div>`;
      $(".trGo", row).onclick = async () => {
        try {
          await api.post("/api/training/start", { base: d.base, name: d.name,
            trigger: $(".trTrig", row).value.trim(), epochs: +$(".trEp", row).value || 12 });
          toast("Training started"); load();
        } catch (e) { toast(e.message, "err"); }
      };
      list.appendChild(row);
    });

    if (run) {
      const p = run.progress || {}, t = el("div", "card"); t.style.marginTop = "16px";
      t.innerHTML = `
        <div class="spread"><h2 class="mb0">${esc(run.name)} <span class="badge ${st.active ? "" : (run.status === "done" ? "good" : "warn")}">${run.status}</span></h2>
          ${st.active ? `<button class="btn btn-danger btn-sm" id="trStop">${icon("i-x")} Stop</button>` : ""}</div>
        <div class="track" style="margin:12px 0 8px"><div class="fill image" id="trBar" style="width:${p.pct || 0}%"></div></div>
        <div class="row" id="trMeta" style="gap:6px"></div>
        <pre id="trLog" style="background:#11100d;color:#d8d2c4;font-family:var(--font-mono);font-size:11.5px;line-height:1.45;padding:12px;border-radius:10px;max-height:340px;overflow:auto;white-space:pre-wrap;margin-top:10px">loading…</pre>`;
      page.appendChild(t);
      if (st.active) $("#trStop", t).onclick = async () => { try { await api.post("/api/training/stop", {}); toast("Stopping…"); } catch (e) { toast(e.message, "err"); } };
      pollLog();
    }
  }

  async function pollLog() {
    if (_trainPoll) clearInterval(_trainPoll);
    const tick = async () => {
      const log = $("#trLog", page);
      if (!log) { clearInterval(_trainPoll); _trainPoll = null; return; }
      let s, l;
      try { s = await api.get("/api/training/status"); l = await api.get("/api/training/log"); } catch (e) { return; }
      const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
      log.textContent = l.text || "(waiting for output…)";
      if (atBottom) log.scrollTop = log.scrollHeight;
      const run = s.run || {}, p = run.progress || {};
      const bar = $("#trBar", page); if (bar && p.pct != null) bar.style.width = p.pct + "%";
      const meta = $("#trMeta", page);
      if (meta) meta.innerHTML = [
        p.step != null ? `<span class="badge">step ${p.step}/${p.total || "?"}${p.pct != null ? ` · ${p.pct}%` : ""}</span>` : "",
        p.epoch != null ? `<span class="badge">epoch ${p.epoch}/${p.epoch_total || "?"}</span>` : "",
        p.loss != null ? `<span class="badge">loss ${p.loss}</span>` : "",
        p.rate ? `<span class="badge">${esc(p.rate)}</span>` : "",
        `<span class="badge ${s.active ? "" : (run.status === "done" ? "good" : "warn")}">${run.status || "idle"}</span>`,
      ].join("");
      if (!s.active) { clearInterval(_trainPoll); _trainPoll = null; if (run.status === "done") toast("Training complete ✓"); }
    };
    await tick();
    _trainPoll = setInterval(tick, 2500);
  }

  await load();
}

/* ============================================================
   PAGE: SCRIPT → JSON  (paste script · voice it · timestamped JSON)
   ============================================================ */
async function renderTranscribe(host) {
  topbar("Script → JSON", "Paste a script, generate the voice, then copy timestamped sentence JSON.");
  const v = state.voices || {};
  const sel = { value: "custom:Ryan", language: "English", instruct: "" };
  let generatedFile = null;   // wav in data/outputs
  let currentItemId = null;   // saved history entry id (to attach the transcript to)
  let lastTranscript = null;

  const page = el("div", "page");

  const card = el("div", "card");
  card.innerHTML = `
    <h2>Script</h2>
    <p class="desc">Paste your narration. The selected voice reads it locally (Qwen3-TTS); then Whisper aligns each sentence to the audio and emits timestamped JSON — your exact wording, accurate times.</p>
    <div class="grid2" style="margin-bottom:14px">
      <div class="field"><label>Voice</label><select id="tsVoice"></select></div>
      <div class="field"><label>Language</label><select id="tsLang"></select></div>
    </div>
    <div class="field"><label>Style / emotion <span class="hint">(optional, 1.7B only — plain English works)</span></label><input type="text" id="tsInstruct" placeholder="e.g. suspenseful, like he's telling a spooky campfire story"/></div>
    <div class="row" id="tsStyles" style="margin:8px 0 14px;gap:6px;flex-wrap:wrap"></div>
    <div class="field" style="max-width:300px;margin-bottom:14px"><label>Pace <span class="hint">(delivery speed)</span></label><select id="tsPace">
      <option value="0.8">🐢 Very slow</option>
      <option value="0.9">Slow &amp; deliberate</option>
      <option value="1" selected>Natural</option>
      <option value="1.1">Brisk</option>
      <option value="1.2">🐇 Fast</option>
    </select></div>
    <div class="row" style="gap:16px;align-items:center;margin-bottom:14px;flex-wrap:wrap">
      <label class="switch"><input type="checkbox" id="tsFilter"/><span class="track"></span> Voice filter <span class="hint">(humanize — real mic/room character, removes synthetic tells)</span></label>
      <select id="tsFilterPreset" style="max-width:170px" disabled>
        <option value="natural" selected>Natural (recommended)</option>
        <option value="minimal">Minimal</option>
        <option value="balanced">Balanced</option>
        <option value="heavy">Heavy</option>
      </select>
    </div>
    <div class="field"><label>Script</label><textarea id="tsText" rows="8" placeholder="Paste your script here…"></textarea></div>
    <div class="row" style="margin-top:14px">
      <button class="btn btn-primary" id="tsGen">${icon("i-voice")} Generate voice</button>
      <span class="muted mono" id="tsGenMsg"></span>
    </div>
    <div id="tsAudio" style="margin-top:14px"></div>`;
  page.appendChild(card);

  const tcard = el("div", "card"); tcard.style.marginTop = "16px";
  tcard.innerHTML = `
    <div class="spread"><h2 class="mb0">Timestamps</h2><div class="row" id="tsMeta"></div></div>
    <p class="desc">Each block gets an accurate <b>start</b>/<b>end</b>, anchored to your script. Copy the JSON or download it.</p>
    <div class="row" style="align-items:center;gap:10px;margin-bottom:12px">
      <label class="muted" for="tsSplit" style="white-space:nowrap">Split by</label>
      <select id="tsSplit" style="max-width:230px">
        <option value="sentence" selected>Sentences (standard)</option>
        <option value="comma">Commas (clause-level)</option>
        <option value="phrase">Phrases (finer)</option>
        <option value="tight">Tight (~3-4 words)</option>
      </select>
    </div>
    <div class="row" id="tsTrActions"></div>
    <div id="tsRun" style="margin-top:14px"></div>
    <div id="tsJsonWrap" style="margin-top:14px" hidden>
      <div class="row" style="align-items:center;margin-bottom:8px;gap:10px">
        <label class="muted" for="tsFormat" style="white-space:nowrap">Format</label>
        <select id="tsFormat" style="max-width:210px">
          <option value="transcript" selected>Transcript (timed blocks)</option>
          <option value="storyboard">Storyboard (uploadable)</option>
        </select>
        <label class="switch" id="tsWordsWrap"><input type="checkbox" id="tsWords"/><span class="track"></span> Include per-word times</label>
        <span class="grow"></span>
        <button class="btn btn-ghost btn-sm" id="tsCopy">${icon("i-check")} Copy JSON</button>
        <button class="btn btn-ghost btn-sm" id="tsDownload">${icon("i-download")} Download</button>
      </div>
      <textarea id="tsJson" rows="16" readonly spellcheck="false" style="width:100%;white-space:pre;font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;line-height:1.5"></textarea>
    </div>`;
  page.appendChild(tcard);

  const scard = el("div", "card"); scard.style.marginTop = "16px";
  scard.innerHTML = `
    <div class="spread"><h2 class="mb0">Saved voiceovers</h2><button class="btn btn-ghost btn-sm" id="tsReload">${icon("i-refresh")} Refresh</button></div>
    <p class="desc">Every voice you generate here is saved (also under <a href="#/history">History</a>). Play it back, re-download it, or load one to transcribe.</p>
    <div class="scene-list" id="tsSaved"></div>`;
  page.appendChild(scard);
  host.appendChild(page);

  // --- voice + language selects ---
  const vsel = $("#tsVoice", page);
  let opts = "";
  if ((v.builtin || []).length)
    opts += `<optgroup label="Built-in speakers">` + v.builtin.map(s => `<option value="custom:${esc(s.id)}">${esc(dispName(s.id))}${s.youtube ? " · YT" : ""} — ${esc(s.desc)}</option>`).join("") + `</optgroup>`;
  if ((v.custom || []).length)
    opts += `<optgroup label="Your voices">` + v.custom.map(c => `<option value="clone:${esc(c.id)}">${esc(c.name)} (${esc(c.type)})</option>`).join("") + `</optgroup>`;
  vsel.innerHTML = opts || `<option value="custom:Ryan">Ryan</option>`;
  if ([...vsel.options].some(o => o.value === sel.value)) vsel.value = sel.value; else vsel.selectedIndex = 0;
  sel.value = vsel.value;
  vsel.onchange = () => sel.value = vsel.value;

  const lsel = $("#tsLang", page);
  lsel.innerHTML = (v.languages || ["Auto", "English"]).map(l => `<option value="${l}">${l === "Auto" ? "Auto-detect" : l}</option>`).join("");
  lsel.value = sel.language; lsel.onchange = () => sel.language = lsel.value;
  $("#tsInstruct", page).oninput = e => sel.instruct = e.target.value;

  // One-click style/emotion presets (Qwen3-TTS 1.7B follows plain-English delivery cues).
  const STYLE_PRESETS = [
    ["🔥 Campfire spooky", "Suspenseful and hushed, as if telling a scary story around a campfire at night — slow and tense, building quiet dread, almost a whisper at the scariest parts."],
    ["🎙️ Calm documentary", "Calm, warm, authoritative documentary narrator with measured, deliberate pacing."],
    ["⚡ Energetic", "Upbeat, energetic and friendly — fast and lively, with a smile you can hear."],
    ["🎬 Dramatic trailer", "Deep, dramatic movie-trailer voice — intense, slow and powerful, weight on every word."],
    ["😢 Somber", "Soft, somber and melancholic — gentle, slow and emotional, almost mournful."],
  ];
  const stylesEl = $("#tsStyles", page);
  STYLE_PRESETS.forEach(([label, text]) => {
    const b = el("button", "btn btn-sm btn-ghost", label);
    b.title = text;
    b.onclick = () => { const inp = $("#tsInstruct", page); inp.value = text; sel.instruct = text; inp.focus(); };
    stylesEl.appendChild(b);
  });
  $("#tsFilter", page).onchange = e => { $("#tsFilterPreset", page).disabled = !e.target.checked; };

  const meta = state.status.transcribe || {};
  $("#tsMeta", page).innerHTML =
    `<span class="badge">Whisper ${esc(meta.model || "medium")}</span>` +
    `<span class="badge ${meta.available === false ? "" : "teal"}">${meta.available === false ? "not installed" : esc(meta.device || "auto")}</span>`;

  function trActions() {
    const a = $("#tsTrActions", page); a.innerHTML = "";
    const btn = el("button", "btn btn-primary", `${icon("i-clock")} Transcribe to JSON`);
    btn.disabled = !generatedFile; btn.onclick = runTranscribe;
    a.append(btn);
    if (!generatedFile) a.append(el("span", "muted", `<span style="padding-left:8px">Generate the voice first.</span>`));
  }
  trActions();

  // --- generate the voice (reuses the TTS pipeline) ---
  $("#tsGen", page).onclick = async () => {
    const text = $("#tsText", page).value.trim();
    if (!text) { toast("Paste a script first.", "err"); return; }
    const msg = $("#tsGenMsg", page); const btn = $("#tsGen", page);
    const [mode, id] = sel.value.split(":");
    const speed = parseFloat($("#tsPace", page).value) || 1;
    const filterOn = $("#tsFilter", page).checked;
    const body = { mode, text, language: sel.language, instruct: sel.instruct || null, format: "wav", loudnorm: false, speed, humanize: filterOn ? { preset: $("#tsFilterPreset", page).value || "natural" } : null };
    if (mode === "clone") body.voice_id = id; else body.speaker = id;
    btn.disabled = true; msg.textContent = "synthesizing…";
    try {
      const { job_id } = await api.post("/api/tts", body);
      const res = await pollJob(job_id, j => { msg.textContent = j.stage + " " + Math.round((j.progress || 0) * 100) + "%"; });
      const files = (res.item && res.item.files) || {};
      generatedFile = files.wav || files.mp3 || null;
      currentItemId = (res.item && res.item.id) || null;
      if (!generatedFile) throw new Error("No audio was produced.");
      msg.textContent = "✓ voice ready — review below, then transcribe";
      $("#tsAudio", page).innerHTML = `<audio controls src="/audio/${generatedFile}" style="width:100%"></audio>`;
      // a fresh voice invalidates the old JSON
      lastTranscript = null; $("#tsJsonWrap", page).hidden = true; $("#tsRun", page).innerHTML = "";
      trActions();
      loadSaved();
    } catch (e) { msg.textContent = ""; toast(e.message, "err"); }
    finally { btn.disabled = false; }
  };

  // Blank scene shape pulled once from the importer's own template, so the
  // storyboard we emit can never drift from what the Projects tab accepts.
  let blankTpl = null;
  async function storyboardDoc() {
    if (!blankTpl) blankTpl = await api.get("/api/storyboard/template?scene_count=1&character_count=0");
    const shape = blankTpl.scenes[0];
    const scenes = (lastTranscript.sentences || []).map((b, i) => ({
      ...shape,
      characters: [],            // fresh array — don't share the template's reference
      id: i + 1,
      narration: b.text || "",   // transcript text → narration
      start_sec: b.start,        // transcript timing → scene timing
      end_sec: b.end,
      duration_sec: b.dur,
    }));
    return {
      video: { ...blankTpl.video, character_bible: [], total_runtime_sec: lastTranscript.duration || null },
      scenes,
    };
  }
  async function showJson() {
    if (!lastTranscript) return;
    const fmt = ($("#tsFormat", page) || {}).value || "transcript";
    const wordsWrap = $("#tsWordsWrap", page);
    if (wordsWrap) wordsWrap.style.display = fmt === "storyboard" ? "none" : "";  // per-word only applies to transcript
    let doc;
    if (fmt === "storyboard") {
      doc = await storyboardDoc();
    } else {
      const withWords = $("#tsWords", page).checked;
      doc = {
        duration: lastTranscript.duration,
        language: lastTranscript.language,
        model: lastTranscript.model,
        sentences: (lastTranscript.sentences || []).map(b => withWords ? b
          : { index: b.index, text: b.text, start: b.start, end: b.end, dur: b.dur }),
      };
    }
    $("#tsJson", page).value = JSON.stringify(doc, null, 2);
  }

  async function runTranscribe() {
    if (!generatedFile) return;
    const text = $("#tsText", page).value.trim();
    const runEl = $("#tsRun", page);
    runEl.innerHTML = `<div class="run-panel"><div class="spinner"></div><div style="flex:1"><div class="lab" id="tsStage">Starting…</div><div class="progress" style="margin-top:8px"><div class="bar" id="tsBar"></div></div></div></div>`;
    try {
      const split = ($("#tsSplit", page) || {}).value || "sentence";
      const { job_id } = await api.post("/api/transcribe", { file: generatedFile, text, language: sel.language, item_id: currentItemId, split });
      const res = await pollJob(job_id, j => { const st = $("#tsStage", page); if (st) st.textContent = j.stage; const b = $("#tsBar", page); if (b) b.style.width = Math.round((j.progress || 0) * 100) + "%"; });
      lastTranscript = res.transcript;
      runEl.innerHTML = "";
      $("#tsJsonWrap", page).hidden = false;
      await showJson();
      loadSaved();   // reflect the now-saved timestamps in the list
      toast(`${(lastTranscript.sentences || []).length} sentence(s) timestamped & saved`);
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
  }

  $("#tsWords", page).onchange = showJson;
  $("#tsFormat", page).onchange = showJson;
  $("#tsCopy", page).onclick = async () => {
    const ta = $("#tsJson", page);
    try { await navigator.clipboard.writeText(ta.value); toast("JSON copied"); }
    catch (_) { ta.select(); document.execCommand("copy"); toast("JSON copied"); }
  };
  $("#tsDownload", page).onclick = () => {
    const fmt = ($("#tsFormat", page) || {}).value || "transcript";
    const blob = new Blob([$("#tsJson", page).value], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = fmt === "storyboard" ? "storyboard.json" : "transcript.json"; a.click(); URL.revokeObjectURL(a.href);
  };

  // --- saved voiceovers (persisted server-side; also in History) ---
  async function loadSaved() {
    const wrap = $("#tsSaved", page); if (!wrap) return;
    let items;
    try { items = await api.get("/api/history"); state.history = items; }
    catch (_) { items = state.history || []; }
    const saved = items.filter(it => it.files && (it.files.wav || it.files.mp3) && it.kind !== "transcript" && !it.project);
    wrap.innerHTML = "";
    if (!saved.length) { wrap.innerHTML = `<div class="muted" style="padding:8px 2px">No saved voiceovers yet — generate one above.</div>`; return; }
    saved.forEach(it => {
      const f = it.files.wav || it.files.mp3;
      const hasJson = !!it.transcript_file;
      const row = el("div", "scene-row"); row.style.gridTemplateColumns = "1fr auto";
      row.innerHTML = `
        <div class="scene-body">
          <div class="narr">${esc(it.text_preview || it.voice || "voiceover")}</div>
          <div class="sub">${it.voice ? `<span>${esc(it.voice)}</span>` : ""}${it.language ? `<span>${esc(it.language)}</span>` : ""}${it.duration ? `<span>${fmtClock(it.duration)}</span>` : ""}<span>${fmtAgo(it.created)}</span>${hasJson ? `<span class="badge good">JSON · ${it.sentence_count || "?"} sent.</span>` : `<span class="badge">no JSON yet</span>`}</div>
          <audio controls preload="none" src="/audio/${f}" style="height:34px;width:100%;max-width:440px;margin-top:8px"></audio>
        </div>
        <div class="scene-meta">
          <button class="btn btn-sm btn-ghost tsUse" title="${hasJson ? "Load this clip and its saved timestamps" : "Load this clip to transcribe"}">${icon("i-clock")} ${hasJson ? "View JSON" : "Use for JSON"}</button>
          ${hasJson ? `<a class="btn-icon" href="/download/${it.transcript_file}" download title="Download timestamps JSON">${icon("i-download")}</a>` : ""}
          <a class="btn-icon" href="/download/${f}" download title="Download audio">${icon("i-voice")}</a>
          <button class="btn-icon btn-danger tsDel" title="Remove from saved">${icon("i-trash")}</button>
        </div>`;
      $(".tsUse", row).onclick = async () => {
        generatedFile = f; currentItemId = it.id;
        const t = it.text || it.text_preview || "";
        if (t) $("#tsText", page).value = t;
        if (it.language && [...lsel.options].some(o => o.value === it.language)) { lsel.value = it.language; sel.language = it.language; }
        $("#tsAudio", page).innerHTML = `<audio controls src="/audio/${f}" style="width:100%"></audio>`;
        $("#tsRun", page).innerHTML = ""; trActions();
        if (hasJson) {
          try {
            lastTranscript = await api.get(`/audio/${it.transcript_file}`);
            $("#tsJsonWrap", page).hidden = false; showJson();
            $("#tsGenMsg", page).textContent = "✓ loaded saved voice + timestamps";
          } catch (_) {
            lastTranscript = null; $("#tsJsonWrap", page).hidden = true;
            $("#tsGenMsg", page).textContent = "✓ loaded saved voice — ready to transcribe";
          }
        } else {
          lastTranscript = null; $("#tsJsonWrap", page).hidden = true;
          $("#tsGenMsg", page).textContent = "✓ loaded saved voice — ready to transcribe";
        }
        tcard.scrollIntoView({ behavior: "smooth", block: "center" });
      };
      $(".tsDel", row).onclick = async () => { try { await api.del(`/api/history/${it.id}`); toast("Removed"); loadSaved(); } catch (e) { toast(e.message, "err"); } };
      wrap.appendChild(row);
    });
  }
  $("#tsReload", page).onclick = loadSaved;
  loadSaved();
}

/* ============================================================
   PAGE: CHARACTERS  (character bible — consistent recurring characters)
   ============================================================ */
async function renderCharacters(host) {
  const p = state.project; if (!p) { location.hash = "#/projects"; return; }
  topbar(p.name, "Character bible · consistent recurring characters",
    `<button class="btn btn-ghost" onclick="location.hash='#/p/${p.id}/storyboard'">${icon("i-back")} Storyboard</button>
     <button class="btn btn-primary" onclick="location.hash='#/p/${p.id}/images'">${icon("i-image")} Images →</button>`);
  const page = el("div", "page page-wide");

  let data = { characters: [], image: {} };
  try { data = await api.get(`/api/projects/${p.id}/characters`); } catch (e) { }

  const top = el("div", "card");
  top.innerHTML = `
    <h2>Character bible</h2>
    <p class="desc">Define each recurring character once, then generate a <b>reference sheet</b> (angles + expressions). When a scene features a character, the app feeds that sheet to IP-Adapter so they stay <b>on-model</b> across the whole video. Sheets render with the <b>Cartoon (SDXL · RAG)</b> model.</p>
    <div class="row" id="chSeedRow" style="margin-bottom:12px"></div>
    <div class="divider"></div>
    <div class="grid2">
      <div class="field"><label>Name</label><input id="chName" placeholder="e.g. Otto the banker"/></div>
      <div class="field"><label>Palette <span class="hint">(optional)</span></label><input id="chPalette" placeholder="e.g. navy suit, grey hair, red tie"/></div>
    </div>
    <div class="field"><label>Description <span class="hint">(the fixed look)</span></label><textarea id="chDesc" rows="2" placeholder="e.g. a short round middle-aged man, bald with a grey moustache, navy pinstripe suit"></textarea></div>
    <div class="row"><button class="btn btn-primary" id="chAdd">${icon("i-plus")} Add character</button></div>`;
  page.appendChild(top);

  const listCard = el("div", "card"); listCard.style.marginTop = "16px";
  listCard.innerHTML = `<div class="section-title">Characters</div><div id="chList"></div>`;
  page.appendChild(listCard);
  host.appendChild(page);

  function drawSeed() {
    const r = $("#chSeedRow", page); r.innerHTML = "";
    const b = el("button", "btn btn-ghost btn-sm", "Seed from storyboard's character bible");
    b.onclick = async () => {
      try { const { added } = await api.post(`/api/projects/${p.id}/characters/seed`, {}); toast(added ? `Added ${added} character(s)` : "No character bible found in the storyboard"); await reload(); }
      catch (e) { toast(e.message, "err"); }
    };
    r.appendChild(b);
  }

  function drawList() {
    const wrap = $("#chList", page); wrap.innerHTML = "";
    if (!data.characters.length) { wrap.innerHTML = `<div class="muted" style="padding:8px 2px">No characters yet — add one above, or seed from the storyboard.</div>`; return; }
    data.characters.forEach(c => {
      const card = el("div", "card"); card.style.cssText = "margin:10px 0;background:rgba(255,255,255,.02)";
      const sheet = (c.sheet || []).map(s => `<figure style="margin:0;text-align:center"><img src="${s.url}" loading="lazy" style="width:92px;height:112px;object-fit:cover;border-radius:8px;background:#15140f;border:1px solid rgba(255,255,255,.06)"/><figcaption class="muted" style="font-size:11px;margin-top:3px">${esc(s.label)}</figcaption></figure>`).join("");
      const badge = c.status === "ready" ? `<span class="badge good">${(c.sheet || []).length} refs</span>`
        : c.status === "generating" ? `<span class="badge teal">generating…</span>` : `<span class="badge">no sheet</span>`;
      card.innerHTML = `
        <div class="spread"><div><b style="font-size:16px">${esc(c.name)}</b> ${badge}</div>
          <div class="row">
            <button class="btn btn-sm btn-primary chGen">${icon("i-wand")} ${(c.sheet || []).length ? "Regenerate" : "Generate"} sheet</button>
            <button class="btn-icon btn-danger chDel" title="Delete character">${icon("i-trash")}</button>
          </div></div>
        <div class="muted" style="margin:6px 0 4px">${esc(c.description || "(no description yet — edit below)")}${c.palette ? ` · ${esc(c.palette)}` : ""}</div>
        <div class="chRun"></div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px">${sheet || `<span class="muted">No reference sheet yet — click Generate to draw angles + expressions.</span>`}</div>`;
      $(".chGen", card).onclick = () => genSheet(c, card);
      $(".chDel", card).onclick = async () => {
        if (!await confirmModal("Delete character?", `Remove <b>${esc(c.name)}</b> and its reference sheet?`)) return;
        try { await api.del(`/api/projects/${p.id}/characters/${c.id}`); await reload(); toast("Deleted"); } catch (e) { toast(e.message, "err"); }
      };
      wrap.appendChild(card);
    });
  }

  async function genSheet(c, card) {
    const runEl = $(".chRun", card);
    runEl.innerHTML = `<div class="run-panel"><div class="spinner"></div><div style="flex:1"><div class="lab chStage">Starting… (first run loads the cartoon model)</div><div class="progress" style="margin-top:8px"><div class="bar chBar"></div></div></div></div>`;
    try {
      const { job_id } = await api.post(`/api/projects/${p.id}/characters/${c.id}/sheet`, {});
      await pollJob(job_id, j => { const st = $(".chStage", card); if (st) st.textContent = j.stage; const b = $(".chBar", card); if (b) b.style.width = Math.round((j.progress || 0) * 100) + "%"; });
      await reload(); toast(`${c.name}'s reference sheet is ready`);
    } catch (e) { runEl.innerHTML = ""; toast(e.message, "err"); }
  }

  $("#chAdd", page).onclick = async () => {
    const name = $("#chName", page).value.trim();
    if (!name) { toast("Give the character a name.", "err"); return; }
    try {
      await api.post(`/api/projects/${p.id}/characters`, { name, description: $("#chDesc", page).value.trim(), palette: $("#chPalette", page).value.trim() });
      $("#chName", page).value = ""; $("#chDesc", page).value = ""; $("#chPalette", page).value = "";
      await reload(); toast("Character added");
    } catch (e) { toast(e.message, "err"); }
  };

  async function reload() { try { data = await api.get(`/api/projects/${p.id}/characters`); } catch (e) { } drawList(); }
  drawSeed(); drawList();
}

const Pages = {
  projects: renderProjects, storyboard: renderStoryboard, characters: renderCharacters,
  voiceover: renderVoiceover, images: renderImages, animate: renderAnimate,
  assemble: renderAssemble, preview: renderPreview, history: renderHistory,
  voices: renderVoiceLab, transcribe: renderTranscribe, training: renderTraining,
  settings: renderSettings,
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
  // Setting the hash fires `hashchange` → render(); only render() directly when
  // the hash is already set (no hashchange will fire). Calling both double-renders.
  if (!location.hash) location.hash = "#/projects";
  else render();
})();
