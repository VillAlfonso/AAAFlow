/* ============================================================
   Qwen3-TTS Studio — frontend logic (vanilla JS, no build step)
   ============================================================ */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (t, c, h) => { const n = document.createElement(t); if (c) n.className = c; if (h != null) n.innerHTML = h; return n; };
const icon = (id, cls = "") => `<svg class="${cls}"><use href="#${id}"/></svg>`;

const state = {
  mode: "custom",
  settings: {}, status: {}, history: [],
  voices: { builtin: [], custom: [], languages: [], design_presets: [] },
  resultItem: null,
  chunks: [],
};

const QUICK_EMOTIONS = [
  "Warm and friendly", "Calm documentary narrator", "Energetic and upbeat",
  "Serious and authoritative", "Soft and soothing", "Storytelling, expressive",
];

/* ---------- api ---------- */
async function _err(r){ try{ const j = await r.json(); return new Error(j.detail || r.statusText); }catch{ return new Error(r.statusText); } }
const api = {
  async get(u){ const r = await fetch(u); if(!r.ok) throw await _err(r); return r.json(); },
  async post(u,b){ const r = await fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)}); if(!r.ok) throw await _err(r); return r.json(); },
  async put(u,b){ const r = await fetch(u,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)}); if(!r.ok) throw await _err(r); return r.json(); },
  async del(u){ const r = await fetch(u,{method:"DELETE"}); if(!r.ok) throw await _err(r); return r.json(); },
  async form(u,fd){ const r = await fetch(u,{method:"POST",body:fd}); if(!r.ok) throw await _err(r); return r.json(); },
};
function pollJob(id, onProgress){
  return new Promise((resolve, reject) => {
    const t = setInterval(async () => {
      try {
        const j = await api.get("/api/jobs/" + id);
        onProgress && onProgress(j);
        if (j.status === "done"){ clearInterval(t); resolve(j.result || {}); }
        else if (j.status === "error"){ clearInterval(t); reject(new Error(j.error || "Job failed")); }
      } catch(e){ clearInterval(t); reject(e); }
    }, 600);
  });
}

/* ---------- helpers ---------- */
const pad = n => String(n).padStart(2, "0");
function fmtDur(s){ s = Math.max(0, Math.round(s||0)); return `${Math.floor(s/60)}:${pad(s%60)}`; }
const dispName = id => (id || "").replace(/_/g, " ");
function toast(msg, kind="ok"){
  const t = el("div", `toast ${kind}`, `${icon(kind==="err"?"i-x":"i-check")}<span>${msg}</span>`);
  $("#toasts").appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = ".4s"; setTimeout(()=>t.remove(), 400); }, kind==="err"?4200:2600);
}

/* light client-side chunk preview (server does the authoritative split) */
function previewChunks(text, max){
  const out = [];
  text.replace(/\r\n?/g,"\n").split(/\n\s*\n+/).forEach(para => {
    const p = para.replace(/\s+/g," ").trim();
    if(!p) return;
    const sents = p.match(/[^.!?。！？…]+[.!?。！？…]*\s*/g) || [p];
    let buf = "";
    sents.forEach(s => {
      s = s.trim(); if(!s) return;
      if(buf && (buf.length + s.length + 1) > max){ out.push(buf); buf = s; }
      else buf = buf ? buf + " " + s : s;
    });
    if(buf) out.push(buf);
  });
  return out;
}

/* ---------- router ---------- */
function showView(name){
  $$(".nav-item").forEach(b => b.classList.toggle("is-active", b.dataset.view === name));
  $$(".view").forEach(v => v.classList.toggle("is-active", v.dataset.view === name));
  if(name === "voices") renderVoices();
  if(name === "history") renderHistory();
  if(name === "settings") renderSettings();
  if(name === "humanize") renderHumanize();
}
$("#nav").addEventListener("click", e => { const b = e.target.closest(".nav-item"); if(b) showView(b.dataset.view); });

/* ---------- chips ---------- */
function renderChips(){
  const s = state.status;
  $("#chipDevice").textContent = (s.device === "cuda" ? "GPU · CUDA" : "CPU");
  $("#chipModel").textContent = "Qwen3-TTS " + (s.model_size || "1.7B");
  $("#chipFfmpeg").hidden = s.ffmpeg !== false;
}

/* ============================================================
   STUDIO
   ============================================================ */
const scriptInput = $("#scriptInput");
const voiceSelect = $("#voiceSelect");
const languageSelect = $("#languageSelect");
const wave = $("#wave");
const stageText = $("#stageText");

const TONE_CHIPS = ["sarcastic","excited","calm","sad","angry","whispering","cheerful","serious","suspenseful","sincere"];

function populateLanguages(){
  languageSelect.innerHTML = state.voices.languages
    .map(l => `<option value="${l}">${l === "Auto" ? "Auto-detect" : l}</option>`).join("");
  languageSelect.value = state.settings.default_language || "Auto";
}

function populateVoices(){
  if(state.mode === "custom"){
    voiceSelect.innerHTML = state.voices.builtin
      .map(v => `<option value="${v.id}">${dispName(v.id)} — ${v.native}${v.youtube?" ★":""}</option>`).join("");
    voiceSelect.value = state.settings.default_speaker || "Ryan";
  } else {
    const cs = state.voices.custom;
    if(!cs.length){
      voiceSelect.innerHTML = `<option value="">No custom voices yet — create one in Voices</option>`;
    } else {
      voiceSelect.innerHTML = cs.map(v => `<option value="${v.id}">${v.name} (${v.type})</option>`).join("");
    }
  }
  updateVoiceHint();
}
function updateVoiceHint(){
  const hint = $("#voiceHint");
  if(state.mode === "custom"){
    const v = state.voices.builtin.find(x => x.id === voiceSelect.value);
    hint.textContent = v ? v.desc : "";
  } else {
    const v = state.voices.custom.find(x => x.id === voiceSelect.value);
    hint.textContent = v ? "Your voice — per-line tone works but is subtler than built-in voices" : "";
  }
}
function renderQuickEmotions(){ /* tones are per-line now */ }

function updateScriptMeta(){
  const text = scriptInput.value;
  const words = (text.trim().match(/\S+/g) || []).length;
  const chars = text.replace(/\s/g, "").length;
  const est = words / 150 * 60; // ~150 wpm narration
  $("#scriptMeta").innerHTML = `<span>${words} words</span><span>${chars} chars</span><span>~${fmtDur(est)}</span>`;
}

/* ----- chunk model ----- */
// One sentence per line, so each can carry its own tone. Paragraph index is
// kept so the export stage can add a longer pause between paragraphs.
function chunkScript(text){
  const out = [];
  text.replace(/\r\n?/g, "\n").split(/\n\s*\n+/).forEach((para, pi) => {
    const p = para.replace(/\s+/g, " ").trim();
    if(!p) return;
    const sents = p.match(/[^.!?。！？…]+[.!?。！？…]*(?:\s+|$)/g) || [p];
    sents.forEach(s => { s = s.trim(); if(s) out.push({ text: s, paragraph: pi }); });
  });
  return out;
}

$("#splitBtn").addEventListener("click", () => {
  const text = scriptInput.value.trim();
  if(!text){ toast("Write or paste a script first.", "err"); scriptInput.focus(); return; }
  const parts = chunkScript(text);
  state.chunks = parts.map((c, i) => ({ id: "c" + Date.now() + "_" + i, text: c.text, instruct: "", paragraph: c.paragraph, status: "empty", file: null, duration: 0 }));
  $("#scriptPanel").hidden = true;
  $("#chunkEditor").hidden = false;
  $("#result").hidden = true;
  renderChunkList();
  setStageText("Idle · press Render all lines to render & save");
  saveSession();
});
$("#backToScript").addEventListener("click", () => {
  $("#chunkEditor").hidden = true;
  $("#scriptPanel").hidden = false;
});

/* ----- session persistence (so a reload never loses rendered lines) ----- */
const SESSION_KEY = "qwentts_session_v1";
let _saveT;
function saveSession(){
  try {
    if(!state.chunks || !state.chunks.length){ localStorage.removeItem(SESSION_KEY); return; }
    localStorage.setItem(SESSION_KEY, JSON.stringify({
      mode: state.mode, voice: voiceSelect.value, language: languageSelect.value,
      script: scriptInput.value,
      chunks: state.chunks.map(c => ({
        text: c.text, instruct: c.instruct, paragraph: c.paragraph,
        status: c.status === "rendering" ? "stale" : c.status,
        file: c.file, duration: c.duration })),
    }));
  } catch(e){ /* storage may be unavailable */ }
}
function saveSessionSoon(){ clearTimeout(_saveT); _saveT = setTimeout(saveSession, 500); }
function restoreSession(){
  try {
    const d = JSON.parse(localStorage.getItem(SESSION_KEY) || "null");
    if(!d || !d.chunks || !d.chunks.length) return;
    if(d.script != null) scriptInput.value = d.script;
    if(d.mode){ state.mode = d.mode; $$("#modeSeg .seg-btn").forEach(x => x.classList.toggle("is-active", x.dataset.mode === d.mode)); populateVoices(); }
    if(d.voice){ voiceSelect.value = d.voice; updateVoiceHint(); }
    if(d.language) languageSelect.value = d.language;
    state.chunks = d.chunks.map((c, i) => ({
      id: "c" + Date.now() + "_" + i, text: c.text, instruct: c.instruct || "",
      paragraph: c.paragraph || 0, status: c.status || "empty",
      file: c.file || null, duration: c.duration || 0 }));
    $("#scriptPanel").hidden = true;
    $("#chunkEditor").hidden = false;
    renderChunkList();
    updateScriptMeta();
    const ready = state.chunks.filter(c => c.status === "done").length;
    setStageText(ready ? `Restored · ${ready}/${state.chunks.length} lines rendered` : "Restored your lines");
  } catch(e){ /* ignore corrupt session */ }
}

function renderChunkList(){
  const list = $("#chunkList"); list.innerHTML = "";
  $("#chunkCount").textContent = "· " + state.chunks.length;
  state.chunks.forEach((ch, i) => list.appendChild(chunkCard(ch, i)));
}
function chunkCard(ch, idx){
  const card = el("div", "chunk-card");
  card.dataset.idx = idx;
  card.innerHTML = `
    <div class="chunk-gutter">
      <span class="chunk-num">${idx+1}</span>
      <button class="chunk-play" title="Play this line">${icon("i-play")}</button>
      <span class="chunk-dot"></span>
    </div>
    <div class="chunk-main">
      <textarea class="chunk-text" rows="1"></textarea>
      <div class="chunk-tone-row">
        <input class="chunk-tone" placeholder="tone for this line (optional) — e.g. sarcastic, excited, whispering" />
        <button class="chunk-render mini-btn">${icon("i-play")}<span>Render</span></button>
      </div>
      <div class="chunk-chips"></div>
    </div>`;
  const ta = $(".chunk-text", card); ta.value = ch.text;
  const tone = $(".chunk-tone", card); tone.value = ch.instruct || "";
  const autosize = () => { ta.style.height = "auto"; ta.style.height = (ta.scrollHeight + 2) + "px"; };
  requestAnimationFrame(autosize);
  ta.addEventListener("input", () => { ch.text = ta.value; markStale(ch, card); autosize(); saveSessionSoon(); });
  tone.addEventListener("input", () => { ch.instruct = tone.value; markStale(ch, card); saveSessionSoon(); });
  const chips = $(".chunk-chips", card);
  TONE_CHIPS.forEach(t => {
    const c = el("button", "emo-chip", t);
    c.onclick = () => { tone.value = tone.value.trim() ? tone.value.trim() + ", " + t : t; ch.instruct = tone.value; markStale(ch, card); saveSessionSoon(); };
    chips.appendChild(c);
  });
  $(".chunk-play", card).onclick = () => { if(ch.file) playAux("/audio/" + ch.file); };
  $(".chunk-render", card).onclick = () => renderChunk(idx);
  updateCardStatus(card, ch);
  return card;
}
function markStale(ch, card){ if(ch.status === "done"){ ch.status = "stale"; updateCardStatus(card, ch); } }
function updateCardStatus(card, ch){
  $(".chunk-dot", card).className = "chunk-dot " + ch.status;
  $(".chunk-play", card).disabled = !ch.file;
  card.classList.toggle("is-rendering", ch.status === "rendering");
  const lbl = $(".chunk-render span", card);
  if(lbl) lbl.textContent = (ch.status === "done" || ch.status === "stale") ? "Re-render" : "Render";
}

async function renderChunk(idx){
  const ch = state.chunks[idx];
  if(!ch || !ch.text.trim()) return;
  const card = $(`.chunk-card[data-idx="${idx}"]`);
  const body = { mode: state.mode, text: ch.text, language: languageSelect.value, instruct: ch.instruct || null };
  if(state.mode === "custom"){ body.speaker = voiceSelect.value; }
  else {
    if(!voiceSelect.value){ toast("Pick a custom voice first (create one in Voices).", "err"); return; }
    body.voice_id = voiceSelect.value;
  }
  ch.status = "rendering"; if(card) updateCardStatus(card, ch);
  try {
    const { job_id } = await api.post("/api/chunk", body);
    const res = await pollJob(job_id);
    ch.file = res.file; ch.duration = res.duration; ch.status = "done";
    if(card) updateCardStatus(card, ch);
    saveSession();
  } catch(e){ ch.status = "error"; if(card) updateCardStatus(card, ch); toast(e.message, "err"); throw e; }
}

/* ----- batch render + export ----- */
let running = false;
function setStageText(msg, cls){ stageText.textContent = msg; stageText.className = "stage-text" + (cls ? " " + cls : ""); }
function setRunning(on, msg, isErr){
  running = on;
  $("#renderAllBtn").disabled = on; $("#exportBtn").disabled = on;
  wave.classList.toggle("is-active", on);
  $(".bg-label").textContent = on ? "Working…" : "Render all lines";
  setStageText(msg || (on ? "Working…" : "Idle · ready"), isErr ? "err" : (on ? "run" : ""));
}
function setStage(j){ setStageText(`${j.stage || "Working"} · ${Math.round((j.progress||0)*100)}%`, "run"); }

async function renderAll(){
  if(running) return;
  const todo = state.chunks.map((c, i) => i).filter(i => state.chunks[i].status !== "done");
  if(!todo.length){
    // Everything's already rendered — just (re)save the finished narration.
    if(state.chunks.some(c => c.status === "done" && c.file)) return exportAll(true);
    toast("Split a script into lines first.", "err"); return;
  }
  setRunning(true, "Rendering lines…");
  let done = 0;
  try {
    for(const i of todo){
      setStageText(`Rendering line ${done+1} of ${todo.length}…`, "run");
      await renderChunk(i);
      done++;
      saveSession();
    }
    setStageText("Saving narration to History…", "run");
    await exportAll(true);   // auto-stitch + save so finishing = saved
  } catch(e){ setRunning(false, "Stopped: " + e.message, true); }
}
$("#renderAllBtn").addEventListener("click", renderAll);

// auto=true: called automatically after a full render (skip prompts/guards)
async function exportAll(auto){
  if(running && !auto) return;
  const done = state.chunks.filter(c => c.status === "done" && c.file);
  if(!done.length){ if(!auto) toast("Render some lines first.", "err"); return; }
  const missing = state.chunks.length - done.length;
  if(!auto && missing > 0 && !confirm(`${missing} line(s) aren't rendered yet. Save the ${done.length} rendered line(s) anyway?`)) return;
  setRunning(true, "Saving narration…");
  const voice = state.mode === "custom" ? dispName(voiceSelect.value)
    : (state.voices.custom.find(v => v.id === voiceSelect.value)?.name || "Cloned voice");
  const chunks = done.map(c => ({ file: c.file, paragraph: c.paragraph, text: c.text }));
  try {
    const { job_id } = await api.post("/api/export", { chunks, voice, language: languageSelect.value, title: done[0].text.slice(0, 90) });
    const res = await pollJob(job_id, setStage);
    state.history.unshift(res.item);
    showResult(res.item);
    setRunning(false, `Saved to History · ${fmtDur(res.item.duration)}`);
    toast(`Narration saved to History (${voice}).`, "ok");
    saveSession();
  } catch(e){ setRunning(false, "Save failed: " + e.message, true); toast(e.message, "err"); }
}
$("#exportBtn").addEventListener("click", () => exportAll(false));

/* ----- result player ----- */
const audio = $("#audio");
const auxAudio = $("#auxAudio");
// Previews and history play through a separate channel so they never hijack
// the main result player's audio source.
function playAux(url){ try { audio.pause(); } catch(e){} auxAudio.src = url; auxAudio.play().catch(()=>{}); }
function showResult(item){
  state.resultItem = item;
  const file = item.files.mp3 || item.files.wav;
  if(!file){ toast("No audio file produced.", "err"); return; }
  setSource("/audio/" + file, true);
  $("#result").hidden = false;
  $("#resultTitle").textContent = `${item.voice} · ${item.language === "Auto" ? "auto" : item.language} · ${fmtDur(item.duration)}`;
  const dl = $("#dlGroup"); dl.innerHTML = "";
  Object.entries(item.files).forEach(([kind, name]) => {
    const a = el("a", "dl-btn", `${icon("i-download")}<span>${kind.toUpperCase()}</span>`);
    a.href = "/download/" + name; a.download = "";
    dl.appendChild(a);
  });
  const hz = el("button", "dl-btn hz-jump", `${icon("i-spark")}<span>Remove AI fingerprints</span>`);
  hz.onclick = () => openHumanize(item);
  dl.appendChild(hz);
  $("#result").scrollIntoView({ behavior: "smooth", block: "nearest" });
}
let resultIsSource = false;
function setSource(url, asResult){
  resultIsSource = !!asResult;
  audio.src = url;
  audio.play().catch(()=>{});
}
const playBtn = $("#playBtn");
playBtn.addEventListener("click", () => { if(audio.paused){ try { auxAudio.pause(); } catch(e){} audio.play(); } else audio.pause(); });
function syncPlayIcon(){
  const playing = !audio.paused && !audio.ended;
  $(".ic-play", playBtn).hidden = playing;
  $(".ic-pause", playBtn).hidden = !playing;
}
audio.addEventListener("play", syncPlayIcon);
audio.addEventListener("pause", syncPlayIcon);
audio.addEventListener("ended", syncPlayIcon);
audio.addEventListener("loadedmetadata", () => { if(resultIsSource) $("#durTime").textContent = fmtDur(audio.duration); });
audio.addEventListener("timeupdate", () => {
  if(!resultIsSource) return;
  const pct = audio.duration ? (audio.currentTime / audio.duration * 100) : 0;
  $("#scrubFill").style.width = pct + "%";
  $("#curTime").textContent = fmtDur(audio.currentTime);
});
$("#scrub").addEventListener("click", e => {
  if(!audio.duration) return;
  const r = e.currentTarget.getBoundingClientRect();
  audio.currentTime = (e.clientX - r.left) / r.width * audio.duration;
});

/* mode + voice changes invalidate already-rendered lines (different voice) */
function markAllStale(){
  (state.chunks || []).forEach(ch => { if(ch.status === "done") ch.status = "stale"; });
  if(!$("#chunkEditor").hidden) renderChunkList();
}
$("#modeSeg").addEventListener("click", e => {
  const b = e.target.closest(".seg-btn"); if(!b) return;
  state.mode = b.dataset.mode;
  $$("#modeSeg .seg-btn").forEach(x => x.classList.toggle("is-active", x === b));
  populateVoices(); markAllStale();
});
voiceSelect.addEventListener("change", () => { updateVoiceHint(); markAllStale(); });
languageSelect.addEventListener("change", markAllStale);
scriptInput.addEventListener("input", updateScriptMeta);

/* ============================================================
   VOICES
   ============================================================ */
function voiceCard(v){
  const tags = [];
  if(v.youtube) tags.push(`<span class="tag gold">YouTube pick</span>`);
  tags.push(`<span class="tag">${v.gender}</span>`);
  tags.push(`<span class="tag teal">${v.native}</span>`);
  const card = el("div", "vcard");
  card.innerHTML = `
    <div class="vcard-head">
      <button class="vc-play" title="Preview">${icon("i-play")}</button>
      <div><div class="vcard-name">${dispName(v.id)}</div><div class="vcard-sub">Built-in</div></div>
    </div>
    <div class="vcard-desc">${v.desc}</div>
    <div class="vcard-tags">${tags.join("")}</div>`;
  $(".vc-play", card).onclick = () => previewVoice(v.id, null, $(".vc-play", card));
  return card;
}
function customCard(v){
  const card = el("div", "vcard");
  card.innerHTML = `
    <div class="vcard-head">
      <button class="vc-play" title="Preview">${icon("i-play")}</button>
      <div><div class="vcard-name">${v.name}</div><div class="vcard-sub">${v.type === "design" ? "Designed voice" : "Cloned voice"}</div></div>
    </div>
    <div class="vcard-desc">${v.type === "design" ? (v.instruct || "") : "Cloned from your sample. Use it for narration in the Studio."}</div>
    <div class="vcard-tags"><span class="tag teal">${v.language}</span></div>
    <div class="vcard-actions">
      <button class="mini-btn use">${icon("i-studio")}Use</button>
      <button class="mini-btn danger del">${icon("i-trash")}Delete</button>
    </div>`;
  $(".vc-play", card).onclick = () => previewVoice(null, v.id, $(".vc-play", card));
  $(".use", card).onclick = () => { state.mode = "clone"; $$("#modeSeg .seg-btn").forEach(x => x.classList.toggle("is-active", x.dataset.mode === "clone")); populateVoices(); voiceSelect.value = v.id; updateVoiceHint(); showView("studio"); toast(`Using “${v.name}” in Studio.`); };
  $(".del", card).onclick = async () => {
    if(!confirm(`Delete voice “${v.name}”?`)) return;
    try { await api.del("/api/voices/" + v.id); state.voices.custom = state.voices.custom.filter(x => x.id !== v.id); renderVoices(); populateVoices(); toast("Voice deleted."); }
    catch(e){ toast(e.message, "err"); }
  };
  return card;
}
function renderVoices(){
  const bg = $("#builtinVoiceGrid"); bg.innerHTML = "";
  state.voices.builtin.forEach(v => bg.appendChild(voiceCard(v)));
  const cg = $("#customVoiceGrid"); cg.innerHTML = "";
  $("#myVoicesTitle").hidden = state.voices.custom.length === 0;
  state.voices.custom.forEach(v => cg.appendChild(customCard(v)));
}

async function previewVoice(speaker, voiceId, btn){
  if(btn) btn.classList.add("loading");
  const body = { preview: true, language: languageSelect.value || "English" };
  if(speaker){ body.mode = "custom"; body.speaker = speaker; body.text = ""; }
  else { body.mode = "clone"; body.voice_id = voiceId; body.text = ""; }
  body.text = previewSampleText(body.language);
  try {
    const { job_id } = await api.post("/api/tts", body);
    const res = await pollJob(job_id);
    const file = res.item.files.mp3 || res.item.files.wav;
    playAux("/audio/" + file);
  } catch(e){ toast(e.message, "err"); }
  finally { if(btn) btn.classList.remove("loading"); }
}
function previewSampleText(lang){
  // Prefer a snippet of the user's own script so previews reflect their content.
  const s = (scriptInput.value || "").trim();
  if(s){
    const m = s.match(/^[\s\S]{1,180}?[.!?。！？…](\s|$)/);
    return (m ? m[0] : s.slice(0, 160)).trim();
  }
  return previewLine(lang);
}
function previewLine(lang){
  const m = {
    English:"This is a short sample of how this voice sounds.",
    Chinese:"这是这个声音的简短示例。",
    Japanese:"これはこの声の短いサンプルです。",
    Korean:"이 목소리가 어떻게 들리는지 들려주는 짧은 샘플입니다.",
    German:"Dies ist eine kurze Hörprobe dieser Stimme.",
    French:"Voici un court échantillon de cette voix.",
    Spanish:"Esta es una breve muestra de cómo suena esta voz.",
  };
  return m[lang] || m.English;
}

/* ----- clone modal ----- */
function openModal(html){ $("#modalCard").innerHTML = html; $("#modal").hidden = false; }
function closeModal(){ $("#modal").hidden = true; $("#modalCard").innerHTML = ""; }
$("#modal").addEventListener("click", e => { if(e.target.id === "modal") closeModal(); });

function langOptions(sel){ return state.voices.languages.map(l => `<option ${l===sel?"selected":""} value="${l}">${l==="Auto"?"Auto-detect":l}</option>`).join(""); }

$("#openClone").addEventListener("click", () => {
  openModal(`
    <div class="modal-head"><h2>Clone a voice</h2><button class="icon-btn" id="mClose">${icon("i-x")}</button></div>
    <div class="modal-body">
      <p class="ghint" style="color:var(--muted);margin:0">Upload <b>10–20 seconds</b> of clean, single-speaker speech (WAV/MP3/M4A). For best results, add the exact transcript.</p>
      <div class="drop" id="drop">${icon("i-upload")}<div>Click or drop an audio file</div><div class="fname" id="fname"></div></div>
      <input type="file" id="fileInput" accept="audio/*" hidden />
      <label class="field"><span class="field-label">Voice name</span><input class="input" id="cName" placeholder="My narrator voice" /></label>
      <label class="field"><span class="field-label">Transcript <em class="opt">recommended</em></span><textarea class="input" id="cText" placeholder="Type exactly what is said in the sample…"></textarea></label>
      <label class="field"><span class="field-label">Primary language</span><select class="select" id="cLang">${langOptions("English")}</select></label>
      <div class="modal-foot"><button class="btn" id="mCancel">Cancel</button><button class="btn primary" id="cSubmit">Create voice</button></div>
    </div>`);
  let file = null;
  const drop = $("#drop"), fi = $("#fileInput");
  drop.onclick = () => fi.click();
  fi.onchange = () => { file = fi.files[0]; if(file) $("#fname").textContent = file.name; };
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); file = e.dataTransfer.files[0]; if(file) $("#fname").textContent = file.name; };
  $("#mClose").onclick = closeModal; $("#mCancel").onclick = closeModal;
  $("#cSubmit").onclick = async () => {
    if(!file){ toast("Choose an audio file.", "err"); return; }
    const fd = new FormData();
    fd.append("file", file); fd.append("name", $("#cName").value || "My voice");
    fd.append("ref_text", $("#cText").value || ""); fd.append("language", $("#cLang").value);
    const btn = $("#cSubmit"); btn.disabled = true; btn.textContent = "Processing…";
    try {
      const { voice } = await api.form("/api/voices/clone", fd);
      state.voices.custom.unshift(voice);
      closeModal(); renderVoices(); populateVoices();
      toast("Voice cloned — try it in the Studio.", "ok");
    } catch(e){ toast(e.message, "err"); btn.disabled = false; btn.textContent = "Create voice"; }
  };
});

$("#openDesign").addEventListener("click", () => {
  const presets = state.voices.design_presets.map(p => `<button class="preset-chip" data-i="${p.instruct.replace(/"/g,"&quot;")}">${p.name}</button>`).join("");
  openModal(`
    <div class="modal-head"><h2>Design a voice</h2><button class="icon-btn" id="mClose">${icon("i-x")}</button></div>
    <div class="modal-body">
      <p class="ghint" style="color:var(--muted);margin:0">Describe the voice you want in plain language. It’s rendered, then saved as a reusable voice. <b>Requires the 1.7B model.</b></p>
      <label class="field"><span class="field-label">Voice name</span><input class="input" id="dName" placeholder="Documentary narrator" /></label>
      <label class="field"><span class="field-label">Describe the voice</span><textarea class="input" id="dInstruct" placeholder="A calm, warm middle-aged male narrator with a deep resonant voice and measured pacing…"></textarea></label>
      <div class="preset-row">${presets}</div>
      <label class="field"><span class="field-label">Sample line <em class="opt">optional</em></span><input class="input" id="dText" placeholder="Leave blank to use a default line" /></label>
      <label class="field"><span class="field-label">Language</span><select class="select" id="dLang">${langOptions("English")}</select></label>
      <div class="stage-text" id="dStage" style="min-height:16px"></div>
      <div class="modal-foot"><button class="btn" id="mCancel">Cancel</button><button class="btn primary" id="dSubmit">${icon("i-spark")} Create voice</button></div>
    </div>`);
  $("#mClose").onclick = closeModal; $("#mCancel").onclick = closeModal;
  $$(".preset-chip").forEach(c => c.onclick = () => { $("#dInstruct").value = c.dataset.i; });
  $("#dSubmit").onclick = async () => {
    const instruct = $("#dInstruct").value.trim();
    if(!instruct){ toast("Describe the voice first.", "err"); return; }
    const btn = $("#dSubmit"); btn.disabled = true;
    const stage = $("#dStage"); stage.className = "stage-text run";
    try {
      const { job_id } = await api.post("/api/design", {
        name: $("#dName").value || "Designed voice", instruct,
        preview_text: $("#dText").value || null, language: $("#dLang").value });
      const res = await pollJob(job_id, j => stage.textContent = `${j.stage} · ${Math.round(j.progress*100)}%`);
      state.voices.custom.unshift(res.voice);
      closeModal(); renderVoices(); populateVoices();
      toast("Voice designed and saved.", "ok");
    } catch(e){ stage.className = "stage-text err"; stage.textContent = e.message; btn.disabled = false; }
  };
});

/* ============================================================
   HISTORY
   ============================================================ */
function renderHistory(){
  const list = $("#historyList"); list.innerHTML = "";
  const items = state.history.filter(h => !h.preview);
  $("#historyEmpty").hidden = items.length > 0;
  items.forEach(item => {
    const file = item.files?.mp3 || item.files?.wav;
    const row = el("div", "hrow");
    const when = new Date((item.created||0)*1000).toLocaleString();
    row.innerHTML = `
      <button class="h-play">${icon("i-play")}</button>
      <div class="h-body">
        <div class="h-title">${item.text_preview || "(no text)"}</div>
        <div class="h-meta"><span>${item.voice}</span><span>${fmtDur(item.duration)}</span><span>${item.chars} chars</span><span>${when}</span></div>
      </div>
      <div class="h-actions"></div>`;
    $(".h-play", row).onclick = () => { if(file) playAux("/audio/" + file); };
    const acts = $(".h-actions", row);
    Object.entries(item.files || {}).forEach(([kind, name]) => {
      const a = el("a", "icon-btn", icon("i-download")); a.href = "/download/" + name; a.title = "Download " + kind.toUpperCase();
      acts.appendChild(a);
    });
    const del = el("button", "icon-btn danger", icon("i-trash")); del.title = "Delete";
    del.onclick = async () => { try { await api.del("/api/history/" + item.id); state.history = state.history.filter(h => h.id !== item.id); renderHistory(); } catch(e){ toast(e.message, "err"); } };
    acts.appendChild(del);
    list.appendChild(row);
  });
}

/* ============================================================
   SETTINGS
   ============================================================ */
async function patchSettings(patch){
  try { state.settings = await api.put("/api/settings", patch); }
  catch(e){ toast(e.message, "err"); }
}
function seg(options, value, onPick){
  const wrap = el("div", "seg small");
  options.forEach(([val, label]) => {
    const b = el("button", "seg-btn" + (val === value ? " is-active" : ""), label);
    b.onclick = () => onPick(val);
    wrap.appendChild(b);
  });
  return wrap;
}
function toggle(value, onToggle){
  const t = el("button", "toggle" + (value ? " on" : ""));
  t.onclick = () => onToggle(!value);
  return t;
}
function numCtl(value, onChange, attrs={}){
  const i = el("input"); i.type = "number"; i.className = "input"; i.value = value;
  Object.entries(attrs).forEach(([k,v]) => i.setAttribute(k, v));
  i.onchange = () => onChange(parseFloat(i.value));
  return i;
}
function row(label, sub, ctl){
  const r = el("div", "srow");
  r.innerHTML = `<div><label>${label}</label>${sub?`<small>${sub}</small>`:""}</div>`;
  const c = el("div", "ctl"); c.appendChild(ctl); r.appendChild(c);
  return r;
}

async function renderSettings(){
  await refreshStatus();
  const s = state.settings, grid = $("#settingsGrid");
  grid.innerHTML = "";

  /* engine */
  const g1 = el("div", "sgroup", `<h3>Engine</h3><p class="ghint">Bigger model = more natural & expressive, but uses more VRAM and is slower.</p>`);
  g1.appendChild(row("Model size", "0.6B is faster; 1.7B adds emotion control & voice design",
    seg([["1.7B","1.7B · quality"],["0.6B","0.6B · fast"]], s.model_size, async v => { await patchSettings({model_size:v}); afterSettingsChange(); renderSettings(); })));
  const onGpu = (state.status && state.status.device === "cuda");
  g1.appendChild(row("Compute device", onGpu
      ? "Synthesis runs on your NVIDIA GPU (CUDA). Falls back to CPU automatically if the GPU is unavailable."
      : "No CUDA GPU detected — running on CPU. Install the CUDA build of PyTorch (see requirements.txt) to use the GPU.",
    el("span", "", `<span class="dot ${onGpu ? "on" : "off"}"></span>${onGpu ? "NVIDIA GPU · CUDA" : "CPU"}`)));
  g1.appendChild(row("Models in RAM", "How many task models stay loaded (LRU)",
    numCtl(s.max_loaded_models, v => patchSettings({max_loaded_models:Math.max(1,Math.round(v))}), {min:1,max:3,step:1})));
  grid.appendChild(g1);

  /* audio */
  const g2 = el("div", "sgroup", `<h3>Audio output</h3><p class="ghint">Loudness & pacing for YouTube-ready files.</p>`);
  g2.appendChild(row("Format", "", seg([["mp3","MP3"],["wav","WAV"],["both","Both"]], s.output_format, v => patchSettings({output_format:v}))));
  g2.appendChild(row("Loudness normalize", `Target ${s.loudnorm_i} LUFS (YouTube ≈ −14)`, toggle(s.loudnorm, v => { patchSettings({loudnorm:v}); renderSettings(); })));
  g2.appendChild(row("Loudness target (LUFS)", "", numCtl(s.loudnorm_i, v => patchSettings({loudnorm_i:v}), {min:-30,max:-8,step:0.5})));
  g2.appendChild(row("Sentence gap (ms)", "Pause between sentences", numCtl(s.gap_ms, v => patchSettings({gap_ms:Math.round(v)}), {min:0,max:1500,step:10})));
  g2.appendChild(row("Paragraph gap (ms)", "Pause between paragraphs", numCtl(s.paragraph_gap_ms, v => patchSettings({paragraph_gap_ms:Math.round(v)}), {min:0,max:3000,step:10})));
  g2.appendChild(row("Trim dead air", "Trim silence at chunk edges", toggle(s.trim_silence, v => patchSettings({trim_silence:v}))));
  grid.appendChild(g2);

  /* defaults */
  const g3 = el("div", "sgroup", `<h3>Defaults & quality</h3><p class="ghint">Starting voice and synthesis parameters.</p>`);
  const spkSel = el("select", "select", state.voices.builtin.map(v => `<option value="${v.id}" ${v.id===s.default_speaker?"selected":""}>${dispName(v.id)}</option>`).join(""));
  spkSel.onchange = () => patchSettings({default_speaker:spkSel.value});
  g3.appendChild(row("Default voice", "", spkSel));
  const langSel = el("select", "select", langOptions(s.default_language));
  langSel.onchange = () => patchSettings({default_language:langSel.value});
  g3.appendChild(row("Default language", "", langSel));
  g3.appendChild(row("Max chars / chunk", "Lower = shorter, safer clips", numCtl(s.max_chars, v => { patchSettings({max_chars:Math.round(v)}); updateScriptMeta(); }, {min:80,max:500,step:10})));
  const samp = s.sampling || {};
  g3.appendChild(row("Temperature", "Higher = more varied delivery", numCtl(samp.temperature, v => patchSettings({sampling:{temperature:v}}), {min:0.1,max:1.5,step:0.05})));
  g3.appendChild(row("Repetition penalty", "", numCtl(samp.repetition_penalty, v => patchSettings({sampling:{repetition_penalty:v}}), {min:1,max:1.5,step:0.01})));
  grid.appendChild(g3);

  /* models on disk */
  const g4 = el("div", "sgroup", `<h3>Local models</h3><p class="ghint">Weights live in <code style="font-family:var(--font-mono);font-size:11px">./models</code>. First use downloads them.</p>`);
  const st = state.status;
  g4.appendChild(row("ffmpeg", st.ffmpeg ? "Detected" : "Not found — install for MP3/loudness", el("span", "", st.ffmpeg ? `<span class="dot on"></span>OK` : `<span class="dot off"></span>missing`)));
  Object.entries(st.tasks || {}).forEach(([task, info]) => {
    const r = el("div", "model-state");
    r.innerHTML = `<div><span class="dot ${info.cached?"on":"off"}"></span>${task}<div class="ms-name">${info.repo}</div></div>`;
    if(info.cached){ r.appendChild(el("span", "", `${info.loaded?"loaded":"on disk"}`)); }
    else { const b = el("button", "ghost-btn", "Download"); b.onclick = () => downloadModel(task, b); r.appendChild(b); }
    g4.appendChild(r);
  });
  grid.appendChild(g4);
}
function afterSettingsChange(){ renderChips(); populateVoices(); updateScriptMeta(); }
async function downloadModel(task, btn){
  btn.disabled = true; btn.textContent = "Downloading…";
  try {
    const { job_id } = await api.post("/api/preload", { task });
    await pollJob(job_id, j => btn.textContent = `${Math.round(j.progress*100)}%`);
    toast(`${task} model ready.`, "ok"); await refreshStatus(); renderSettings();
  } catch(e){ toast(e.message, "err"); btn.disabled = false; btn.textContent = "Download"; }
}
async function refreshStatus(){ try { state.status = await api.get("/api/status"); renderChips(); } catch{} }

/* ============================================================
   POLISH / DE-AI HUMANIZER
   ============================================================ */
const HZ_SCHEMA = [
  {key:"eq", title:"Tone — de-crisp & warmth", desc:"Roll off the digital high-end, add low-mid vocal warmth.", controls:[
    {key:"high_gain", label:"High roll-off", min:-10, max:0, step:0.5, unit:"dB"},
    {key:"high_freq", label:"Roll-off above", min:6000, max:14000, step:500, unit:"Hz"},
    {key:"warmth_gain", label:"Warmth (200–500 Hz)", min:0, max:6, step:0.5, unit:"dB"},
  ]},
  {key:"saturation", title:"Tube saturation", desc:"Gentle harmonic grit, like a real microphone.", controls:[
    {key:"amount", label:"Drive", min:0, max:50, step:1, unit:"%"},
  ]},
  {key:"wow", title:"Tape wow & flutter", desc:"Slow micro pitch drift that digital audio never has.", controls:[
    {key:"amount", label:"Depth", min:0, max:80, step:1, unit:"%"},
  ]},
  {key:"tempo_jitter", title:"Break AI pacing", desc:"Tiny timing changes so the rhythm isn't mathematically perfect.", controls:[
    {key:"amount", label:"Timing variation", min:0, max:4, step:0.1, unit:"%"},
    {key:"segments", label:"Sections", min:2, max:20, step:1, unit:""},
  ]},
  {key:"ambiance", title:"Background ambiance", desc:"Quiet room tone so the gaps are never true digital silence.", ambiance:true, controls:[
    {key:"level_db", label:"Level", min:-50, max:-12, step:1, unit:"dB"},
  ]},
  {key:"output", title:"Export", desc:"Downsampling + MP3 blends the frequency profile.", noToggle:true, controls:[
    {key:"sample_rate", label:"Sample rate", type:"select", options:[[32000,"32 kHz"],[44100,"44.1 kHz"],[48000,"48 kHz"]]},
    {key:"bitrate", label:"MP3 bitrate", type:"select", options:[[128,"128 kbps"],[160,"160 kbps"],[192,"192 kbps"]]},
  ]},
];

function hzDeepMerge(a, b){
  const o = structuredClone(a);
  for(const k in (b||{})){
    o[k] = (b[k] && typeof b[k] === "object" && !Array.isArray(b[k])) ? hzDeepMerge(o[k]||{}, b[k]) : b[k];
  }
  return o;
}
async function ensureHzLoaded(){
  if(state.hzData) return;
  state.hzData = await api.get("/api/humanize/presets");
  state.hzAmbiance = [];
  $$("#hzWave span").forEach((s, i) => s.style.setProperty("--i", i));
  applyHzPreset("minimal", true);
}
function applyHzPreset(name, skipRender){
  state.hz = hzDeepMerge(state.hzData.defaults, state.hzData.presets[name] || {});
  $$("#hzPresetSeg .seg-btn").forEach(b => b.classList.toggle("is-active", b.dataset.preset === name));
  if(!skipRender) renderHzControls();
}
async function renderHumanize(){
  try { await ensureHzLoaded(); }
  catch(e){ toast("Could not load polish settings: " + e.message, "err"); return; }
  populateHzSource();
  renderHzControls();
}
function populateHzSource(){
  const sel = $("#hzSource"), noSrc = $("#hzNoSource"), before = $("#hzBefore");
  const items = state.history.filter(h => !h.preview && h.files && (h.files.mp3 || h.files.wav) && !h.humanized);
  if(!items.length){
    sel.innerHTML = `<option value="">No exported clips yet</option>`;
    noSrc.hidden = false; before.hidden = true; state.hzSource = null; return;
  }
  noSrc.hidden = true; before.hidden = false;
  sel.innerHTML = items.map(h => {
    const f = h.files.mp3 || h.files.wav;
    return `<option value="${f}">${h.voice || "Narration"} · ${fmtDur(h.duration)}${h.text_preview ? " · " + h.text_preview.slice(0,38) : ""}</option>`;
  }).join("");
  const want = state.pendingSource && items.find(h => (h.files.mp3 || h.files.wav) === state.pendingSource);
  state.hzSource = want ? state.pendingSource : (items[0].files.mp3 || items[0].files.wav);
  sel.value = state.hzSource;
  setHzBefore();
  state.pendingSource = null;
}
function setHzBefore(){
  if(!state.hzSource) return;
  $("#hzBefore").src = "/audio/" + state.hzSource;
  $("#hzBeforeDl").href = "/download/" + state.hzSource;
}
function renderHzControls(){
  const grid = $("#hzControls"); grid.innerHTML = "";
  HZ_SCHEMA.forEach(g => grid.appendChild(hzCard(g)));
}
function hzCard(g){
  const group = state.hz[g.key];
  const enabled = g.noToggle ? true : (group.enabled !== false);
  const card = el("div", "hz-card" + (enabled ? "" : " is-off"));
  card.innerHTML = `<div class="hz-card-head"><div><h3>${g.title}</h3><small>${g.desc}</small></div></div><div class="hz-card-body"></div>`;
  if(!g.noToggle){
    const tg = el("button", "toggle" + (enabled ? " on" : ""));
    tg.onclick = () => { group.enabled = !enabled; renderHzControls(); };
    $(".hz-card-head", card).appendChild(tg);
  }
  const body = $(".hz-card-body", card);
  g.controls.forEach(c => body.appendChild(hzControl(g, c, enabled)));
  if(g.ambiance) body.appendChild(hzAmbianceExtra(enabled));
  return card;
}
function hzControl(g, c, enabled){
  const group = state.hz[g.key];
  const wrap = el("div", "hz-ctl");
  if(c.type === "select"){
    wrap.innerHTML = `<div class="hz-ctl-top"><label>${c.label}</label></div>`;
    const sel = el("select", "select");
    sel.innerHTML = c.options.map(([v,t]) => `<option value="${v}" ${String(group[c.key])===String(v)?"selected":""}>${t}</option>`).join("");
    sel.disabled = !enabled;
    sel.onchange = () => { group[c.key] = isNaN(+sel.value) ? sel.value : +sel.value; };
    wrap.appendChild(sel);
  } else {
    const val = group[c.key];
    const fmt = v => `${(+v).toFixed(c.step < 1 ? 1 : 0)}${c.unit ? " " + c.unit : ""}`;
    wrap.innerHTML = `<div class="hz-ctl-top"><label>${c.label}</label><span class="hz-val">${fmt(val)}</span></div>`;
    const inp = el("input"); inp.type = "range"; inp.min = c.min; inp.max = c.max; inp.step = c.step; inp.value = val; inp.disabled = !enabled;
    const out = $(".hz-val", wrap);
    inp.oninput = () => { group[c.key] = +inp.value; out.textContent = fmt(inp.value); };
    wrap.appendChild(inp);
  }
  return wrap;
}
function hzAmbianceExtra(enabled){
  const group = state.hz.ambiance;
  const wrap = el("div", "hz-ctl");
  wrap.innerHTML = `<div class="hz-ctl-top"><label>Type</label></div>`;
  const row = el("div", "hz-amb-row");
  const sel = el("select", "select"); sel.disabled = !enabled;
  const types = state.hzData.ambiance_types.map(t => ["" + t, t[0].toUpperCase() + t.slice(1)]);
  const customs = (state.hzAmbiance || []).map(a => ["file:" + a.file, a.name + " (yours)"]);
  const cur = group.file ? "file:" + group.file : (group.type || "room");
  sel.innerHTML = [...types, ...customs].map(([v,t]) => `<option value="${v}" ${v===cur?"selected":""}>${t}</option>`).join("");
  sel.onchange = () => {
    const v = sel.value;
    if(v.startsWith("file:")){ group.file = v.slice(5); group.type = "custom"; }
    else { group.file = null; group.type = v; }
  };
  const up = el("button", "mini-btn"); up.innerHTML = `${icon("i-upload")}<span>Upload bed</span>`; up.disabled = !enabled;
  up.onclick = hzUploadAmbiance;
  row.appendChild(sel); row.appendChild(up);
  wrap.appendChild(row);
  return wrap;
}
function hzUploadAmbiance(){
  const inp = el("input"); inp.type = "file"; inp.accept = "audio/*";
  inp.onchange = async () => {
    const f = inp.files[0]; if(!f) return;
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await api.form("/api/humanize/ambiance", fd);
      state.hzAmbiance.push({ file: r.file, name: r.name });
      state.hz.ambiance.file = r.file; state.hz.ambiance.type = "custom";
      renderHzControls();
      toast("Ambiance bed added (café / lo-fi etc.).", "ok");
    } catch(e){ toast(e.message, "err"); }
  };
  inp.click();
}
$("#hzPresetSeg").addEventListener("click", e => { const b = e.target.closest(".seg-btn"); if(b) applyHzPreset(b.dataset.preset); });
$("#hzSource").addEventListener("change", e => { state.hzSource = e.target.value; setHzBefore(); });

let hzRunning = false;
async function hzProcess(){
  if(hzRunning) return;
  if(!state.hzSource){ toast("Pick a source clip first.", "err"); return; }
  hzRunning = true;
  const btn = $("#hzProcessBtn"); btn.disabled = true;
  $("#hzWave").classList.add("is-active");
  $(".bg-label", btn).textContent = "Polishing…";
  const stage = $("#hzStage"); stage.className = "stage-text run"; stage.textContent = "Queued…";
  try {
    const src = state.history.find(h => h.files && (h.files.mp3 || h.files.wav) === state.hzSource);
    const { job_id } = await api.post("/api/humanize", {
      source: state.hzSource, params: state.hz,
      voice: src ? src.voice : "Narration", language: src ? src.language : "" });
    const res = await pollJob(job_id, j => { stage.textContent = `${j.stage} · ${Math.round((j.progress||0)*100)}%`; });
    const item = res.item; state.history.unshift(item);
    const f = item.files.mp3 || item.files.wav;
    $("#hzAfter").src = "/audio/" + f;
    const dl = $("#hzDl"); dl.innerHTML = "";
    Object.entries(item.files).forEach(([kind, name]) => {
      const a = el("a", "dl-btn", `${icon("i-download")}<span>${kind.toUpperCase()}</span>`);
      a.href = "/download/" + name; a.download = ""; dl.appendChild(a);
    });
    $("#hzResult").hidden = false;
    $("#hzResult").scrollIntoView({ behavior: "smooth", block: "nearest" });
    stage.className = "stage-text"; stage.textContent = `Done · ${fmtDur(item.duration)} polished`;
    toast("Polished — saved to History.", "ok");
  } catch(e){
    stage.className = "stage-text err"; stage.textContent = "Error: " + e.message;
    toast(e.message, "err");
  } finally {
    hzRunning = false; btn.disabled = false;
    $("#hzWave").classList.remove("is-active");
    $(".bg-label", btn).textContent = "Remove AI fingerprints";
  }
}
$("#hzProcessBtn").addEventListener("click", hzProcess);

function openHumanize(item){
  state.pendingSource = item.files.mp3 || item.files.wav;
  showView("humanize");
}

/* ============================================================
   BOOT
   ============================================================ */
async function boot(){
  try {
    const b = await api.get("/api/bootstrap");
    state.settings = b.settings; state.status = b.status;
    state.voices = b.voices; state.history = b.history || [];
  } catch(e){ toast("Could not reach the backend: " + e.message, "err"); return; }
  // assign staggered animation indices to wave bars
  $$("#wave span").forEach((s, i) => s.style.setProperty("--i", i));
  renderChips();
  populateLanguages();
  populateVoices();
  renderQuickEmotions();
  updateScriptMeta();
  syncPlayIcon();
  restoreSession();   // bring back any in-progress chunk editor from a previous reload
  // poll status until torch warms up (so model chips/cached states are fresh)
  if(!state.status.torch_ready) setTimeout(refreshStatus, 4000);
}
boot();
