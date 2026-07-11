"""FastAPI application: REST API + static SPA, bound to localhost."""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (animate, assemble, audiolib, brandkit, captions, channels,
               characters, config, effects, gpu, grade, grammar, humanize,
               images, janitor, jobs, music, packaging, pilot, produce,
               projects, recipe, roulette, scenes, score, service, sfx,
               shorts, storage, style_refs, training, transcribe, voiceover,
               webresearch, writer, youtube)
from .audio import ffmpeg_ok
from .engine import engine
from .image_engine import image_engine
from .voices import DESIGN_PRESETS, LANGUAGES, SPEAKERS

app = FastAPI(title="AAAFlow Studio", version="2.0.0")


@app.middleware("http")
async def _no_cache(request, call_next):
    """Local dev app: never let the browser serve stale HTML/CSS/JS."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


# --- request models --------------------------------------------------------
class TTSReq(BaseModel):
    mode: str = "custom"            # "custom" | "clone"
    text: str
    language: Optional[str] = None
    speaker: Optional[str] = None
    instruct: Optional[str] = None
    voice_id: Optional[str] = None
    preview: bool = False
    format: Optional[str] = None     # "mp3" | "wav" | "both"
    loudnorm: Optional[bool] = None
    speed: Optional[float] = None    # pacing time-stretch: <1 slower, >1 faster (0.5–2.0)
    humanize: Optional[dict] = None  # voice filter; e.g. {"preset": "natural"} or null


class DesignReq(BaseModel):
    name: Optional[str] = "Designed voice"
    instruct: str
    preview_text: Optional[str] = None
    language: Optional[str] = "English"


class PreloadReq(BaseModel):
    task: str


class ChunkReq(BaseModel):
    mode: str = "custom"            # "custom" | "clone"
    text: str
    language: Optional[str] = None
    speaker: Optional[str] = None
    voice_id: Optional[str] = None
    instruct: Optional[str] = None


class ExportChunk(BaseModel):
    file: str
    paragraph: int = 0
    text: Optional[str] = ""


class ExportReq(BaseModel):
    chunks: List[ExportChunk]
    title: Optional[str] = None
    voice: Optional[str] = None
    language: Optional[str] = None
    format: Optional[str] = None
    loudnorm: Optional[bool] = None


class HumanizeReq(BaseModel):
    source: str                       # a filename in data/outputs
    params: Optional[dict] = None
    voice: Optional[str] = None
    language: Optional[str] = None


# --- helpers ---------------------------------------------------------------
def _voices_payload():
    return {
        "builtin": SPEAKERS,
        "languages": LANGUAGES,
        "custom": storage.get_custom_voices(),
        "design_presets": DESIGN_PRESETS,
    }


def _safe_output(name: str) -> Path:
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="bad filename")
    path = config.OUTPUTS_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    return path


# --- lifecycle -------------------------------------------------------------
@app.on_event("startup")
def _startup():
    jobs.start_worker()
    gpu.start_reaper()      # auto-free models after idle (settings.gpu)

    def _warm():
        try:
            engine.ensure_imports()   # imports only, no weights on the GPU
        except Exception:
            pass

    threading.Thread(target=_warm, name="warm-imports", daemon=True).start()


# --- API: state ------------------------------------------------------------
@app.get("/api/bootstrap")
def bootstrap():
    return {
        "status": _status_payload(),
        "settings": storage.get_settings(),
        "voices": _voices_payload(),
        "history": storage.get_history(),
        "projects": projects.list_projects(),
        "channels": channels.load(),
        "image_models": _image_models_payload(),
    }


def _image_models_payload():
    """Built-in SD/FLUX bases + any imported checkpoints/LoRAs."""
    builtin = [
        {"id": k, "label": v["label"], "kind": "checkpoint", "builtin": True,
         "type": v.get("type", "sd"), "gated": v.get("gated", False),
         "size": v.get("size", ""), "steps": v.get("steps"), "guidance": v.get("guidance"),
         "width": v.get("width"), "height": v.get("height"),
         "ip_adapter": bool(v.get("ip_adapter"))}
        for k, v in config.IMAGE_BASES.items()
    ]
    return {
        "builtin": builtin,
        "default": config.DEFAULT_IMAGE_MODEL,
        "imported": storage.get_image_models(),
        # Optional global-style presets the Images page can insert verbatim.
        "style_presets": [
            {"id": "flat-cartoon", "label": "Flat cartoon (krea2 look)",
             "text": config.KREA2_STYLE},
        ],
    }


def _status_payload():
    st = engine.status()
    st["ffmpeg"] = ffmpeg_ok()
    st["image"] = image_engine.status()
    try:
        from .comfy_engine import comfy_engine
        st["comfy"] = comfy_engine.status()
    except Exception:  # noqa: BLE001
        st["comfy"] = {"alive": False, "available": False}
    try:
        from .wan_engine import wan_engine
        st["wan"] = {**wan_engine.status(), "enhance": config.enhance_ready()}
    except Exception:  # noqa: BLE001
        st["wan"] = {"ready": False}
    try:
        st["transcribe"] = transcribe.status()
    except Exception:  # noqa: BLE001
        st["transcribe"] = {"available": False}
    try:
        from .music_engine import music_engine
        st["music"] = music_engine.status()
    except Exception:  # noqa: BLE001
        st["music"] = {"available": False}
    return st


@app.get("/api/status")
def status():
    return _status_payload()


@app.get("/api/gpu")
def gpu_status():
    """What is holding the GPU right now + the idle-unload policy."""
    return gpu.status()


@app.post("/api/gpu/release")
def gpu_release():
    """Free every model this app (or its sidecars) holds on the GPU, now."""
    return gpu.release_all("manual")


@app.get("/api/settings")
def get_settings():
    return storage.get_settings()


@app.put("/api/settings")
def put_settings(patch: dict):
    return storage.save_settings(patch or {})


@app.get("/api/voices")
def voices():
    return _voices_payload()


# --- API: synthesis --------------------------------------------------------
@app.post("/api/tts")
def tts(req: TTSReq):
    try:
        job_id = service.submit_tts(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


@app.post("/api/design")
def design(req: DesignReq):
    try:
        job_id = service.submit_design(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


@app.post("/api/chunk")
def chunk(req: ChunkReq):
    try:
        return {"job_id": service.submit_chunk(req.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/export")
def export_render(req: ExportReq):
    try:
        return {"job_id": service.submit_export(req.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/humanize/presets")
def humanize_presets():
    return {
        "defaults": humanize.DEFAULTS,
        "presets": humanize.PRESETS,
        "ambiance_types": humanize.AMBIANCE_TYPES,
    }


@app.post("/api/humanize")
def humanize_audio(req: HumanizeReq):
    try:
        return {"job_id": service.submit_humanize(req.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/humanize/ambiance")
async def upload_ambiance(file: UploadFile = File(...)):
    suffix = Path(file.filename or "amb.wav").suffix or ".wav"
    tmp = config.DATA_DIR / "ambiance" / f"upload_{storage.new_id()}{suffix}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(await file.read())
    try:
        name = service.store_ambiance(str(tmp), file.filename or "ambiance")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not process ambiance: {exc}")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return {"file": name, "name": (file.filename or "Custom")}


@app.post("/api/preload")
def preload(req: PreloadReq):
    return {"job_id": service.submit_preload(req.task)}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Stop a queued/running job. Queued jobs drop instantly; a running render
    stops at its next progress checkpoint (~1 scene)."""
    ok = jobs.cancel(job_id)
    return {"cancelled": ok, "job": jobs.get_job(job_id)}


@app.get("/api/projects/{pid}/active_job")
def project_active_job(pid: str):
    """The project's in-flight build (assemble/score/animate/…), so the UI can
    RECONNECT its progress after a page switch or refresh instead of losing the
    handle. null when nothing is running."""
    return {"job": jobs.active_for(pid)}


# --- API: voices (clone / delete) -----------------------------------------
@app.post("/api/voices/clone")
async def clone_voice(
    file: UploadFile = File(...),
    name: str = Form("My voice"),
    ref_text: str = Form(""),
    language: str = Form("Auto"),
):
    suffix = Path(file.filename or "sample.wav").suffix or ".wav"
    tmp = config.REFS_DIR / f"upload_{storage.new_id()}{suffix}"
    data = await file.read()
    tmp.write_bytes(data)
    try:
        voice = service.register_clone(name, str(tmp), ref_text, language)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not process audio: {exc}")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return {"voice": voice}


@app.delete("/api/voices/{voice_id}")
def delete_voice(voice_id: str):
    voice = storage.get_custom_voice(voice_id)
    if voice:
        for key in ("ref_audio_path",):
            p = voice.get(key)
            if p:
                try:
                    Path(p).unlink()
                except OSError:
                    pass
    ok = storage.delete_custom_voice(voice_id)
    return {"deleted": ok}


# --- API: history ----------------------------------------------------------
@app.get("/api/history")
def history():
    return storage.get_history()


@app.delete("/api/history/{item_id}")
def delete_history(item_id: str):
    return {"deleted": storage.delete_history(item_id)}


# --- API: projects ---------------------------------------------------------
class CreateProjectReq(BaseModel):
    text: Optional[str] = None       # raw JSON text to parse
    data: Optional[dict] = None      # ...or an already-parsed storyboard object
    name: Optional[str] = None
    engines: Optional[dict] = None   # {"image_model", "animate_engine", "quality", "preset", "authoring"}
    channel: Optional[str] = None    # channel id — inherits that channel's defaults


@app.get("/api/image_models")
def image_models():
    return _image_models_payload()


@app.get("/api/comfy_loras")
def comfy_loras():
    """LoRA files in ComfyUI's models/loras — usable by comfyui-type models (krea2)."""
    d = config.comfy_models_dir() / "loras"
    out = []
    if d.exists():
        for f in sorted(d.glob("*.safetensors")):
            if "ltx" in f.name.lower():        # LTX video LoRAs aren't for krea2
                continue
            try:
                mb = round(f.stat().st_size / 1e6)
            except OSError:
                mb = None
            out.append({"name": f.name, "size_mb": mb})
    return {"loras": out}


@app.get("/api/projects")
def get_projects(channel: Optional[str] = None):
    return {"projects": projects.list_projects(channel)}


@app.post("/api/projects")
def create_project(req: CreateProjectReq):
    raw = req.data
    if raw is None and req.text:
        import json as _json
        try:
            raw = _json.loads(req.text)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Provide a storyboard JSON object.")
    try:
        project = projects.create_project(raw, req.name, engines=req.engines,
                                          channel=req.channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"project": project}


@app.post("/api/projects/upload")
async def upload_project(file: UploadFile = File(...), name: str = Form(""),
                         engines: str = Form(""), channel: str = Form("")):
    import json as _json
    data = await file.read()
    try:
        raw = _json.loads(data.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {exc}")
    eng = None
    if engines.strip():
        try:
            eng = _json.loads(engines)
        except Exception:  # noqa: BLE001
            eng = None
    try:
        project = projects.create_project(
            raw, name.strip() or Path(file.filename or "").stem or None,
            engines=eng, channel=channel.strip() or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"project": project}


class LintReq(BaseModel):
    data: dict
    channel: Optional[str] = None     # lint with this channel's style/mode defaults
    authoring: Optional[str] = None   # "pro" | "assisted" (overrides the channel's)


@app.post("/api/storyboard/lint")
def storyboard_lint(req: LintReq):
    """Auto-direct + lint a storyboard without importing it: returns the fixed
    copy and a report (fixes applied, warnings, hook/runtime stats)."""
    from . import autodirect
    ch = channels.get(req.channel)
    d = (ch or {}).get("defaults") or {}
    mode = req.authoring or d.get("authoring") or "pro"
    fixed, report = autodirect.direct(req.data or {},
                                      default_style=d.get("style_suffix"),
                                      strict=(mode == "assisted"))
    return {"report": report, "fixed": fixed}


# --- API: channels (multi-channel identities + defaults) ---------------------
@app.get("/api/channels")
def get_channels():
    return {"channels": channels.load()}


@app.post("/api/channels")
def upsert_channel(channel: dict):
    """Create or edit a channel (id or name required); defaults deep-merge."""
    try:
        return {"channel": channels.upsert(channel or {})}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/channels/{cid}")
def get_channel(cid: str):
    ch = channels.get(cid)
    if not ch:
        raise HTTPException(status_code=404, detail="channel not found")
    return {"channel": ch}


@app.delete("/api/channels/{cid}")
def delete_channel(cid: str):
    """Moves the whole channel folder (projects included) to data/trash."""
    return {"deleted": channels.remove(cid)}


@app.get("/api/channels/{cid}/brand")
def get_channel_brand(cid: str):
    """The channel's YouTube identity kit: brand stills + Wan video snippets."""
    if not channels.get(cid):
        raise HTTPException(status_code=404, detail="channel not found")
    ident = brandkit.identity(cid)
    return {"assets": ident["stills"], "videos": ident["videos"]}


class BrandPreviewReq(BaseModel):
    seed_offset: int = 0              # bump to regenerate fresh variations


@app.post("/api/channels/{cid}/preview")
def gen_channel_brand(cid: str, req: BrandPreviewReq = BrandPreviewReq()):
    """Render a channel's brand stills via the fixed krea2 node graph (job).
    The graph is saved to data/channels/<cid>/brand/graphs/channel_preview.json."""
    try:
        return {"job_id": brandkit.submit_preview(cid, req.seed_offset)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class SnippetsReq(BaseModel):
    keys: Optional[List[str]] = None  # which stills to animate (default profile+thumbnail)
    seconds: float = 3.0
    quality: str = "balanced"


@app.post("/api/channels/{cid}/snippets")
def gen_channel_snippets(cid: str, req: SnippetsReq = SnippetsReq()):
    """Animate brand stills into short Wan 2.2 motion snippets — the moving half
    of the YouTube identity (logo sting, teaser). ~3-4 min per clip (job)."""
    try:
        return {"job_id": brandkit.submit_snippets(cid, req.keys, req.seconds, req.quality)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/brandkit_slots")
def get_brandkit_slots():
    """The channel-generator architecture, slot by slot (editable dictionary —
    data/brandkit_slots.json). Every channel impression renders from these."""
    return {"slots": brandkit.slots(), "file": "data/brandkit_slots.json"}


@app.put("/api/brandkit_slots")
def put_brandkit_slots(patch: dict):
    try:
        return {"slots": brandkit.save_slots((patch or {}).get("slots") or [])}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/channels/{cid}/brand/comfy")
def export_brand_to_comfy(cid: str):
    """Regenerate this channel's node graph from the current slot dictionary and
    copy all its graphs into ComfyUI's workflow library (sidebar → AAAFlow)."""
    try:
        return brandkit.export_graphs_to_comfy(cid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- API: channel roulette (randomize a whole channel concept) -----------------
class RollReq(BaseModel):
    hint: Optional[str] = None        # optional steer ("something about space")


@app.get("/api/roulette")
def roulette_rolls():
    """Recent rolls (concept + identity stills), newest first."""
    return {"rolls": roulette.list_rolls(), "writer": writer.status()}


@app.post("/api/roulette/roll")
def roulette_roll(req: RollReq = RollReq()):
    """Invent one new channel concept with the local LLM and render its identity
    stills through the fixed krea2 node graph (background job, ~2-3 min GPU)."""
    return {"job_id": roulette.submit_roll(req.hint)}


class AcceptRollReq(BaseModel):
    id: Optional[str] = None          # override the suggested channel id
    name: Optional[str] = None        # override the suggested channel name


@app.post("/api/roulette/{rid}/accept")
def roulette_accept(rid: str, req: AcceptRollReq = AcceptRollReq()):
    """Keep a roll: creates the real channel folder + brand kit from it."""
    try:
        return roulette.accept(rid, req.id, req.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/roulette/{rid}")
def roulette_discard(rid: str):
    """Discard a roll (moved to data/trash/roulette, never destroyed)."""
    return {"discarded": roulette.discard(rid)}


@app.get("/api/channels/{cid}/authoring_prompt")
def channel_authoring_prompt(cid: str, topic: Optional[str] = None):
    """Copy-paste script-writing prompt: the storyboard spec + this channel's
    brief/tone/topic bank. Works for any model — including small ones when the
    channel runs in assisted mode."""
    ch = channels.get(cid)
    if not ch:
        raise HTTPException(status_code=404, detail="channel not found")
    return {"prompt": channels.authoring_prompt(ch, topic)}


# --- API: royalty-free audio libraries + scorer ------------------------------
@app.get("/api/audio/status")
def audio_status():
    """Which providers have keys + how many tracks/SFX are cached."""
    return audiolib.status()


class AudioSearchReq(BaseModel):
    kind: str = "music"               # "music" | "sfx"
    query: str
    seconds: float = 60.0             # music: minimum bed length
    limit: int = 12


@app.post("/api/audio/search")
def audio_search(req: AudioSearchReq):
    """Browse the library (no download) — Jamendo beds or Freesound SFX."""
    if req.kind == "sfx":
        return {"results": audiolib.search_sfx(req.query, limit=req.limit)}
    return {"results": audiolib.search_music(req.query, seconds=req.seconds,
                                             limit=req.limit)}


@app.post("/api/projects/{pid}/score")
def score_project(pid: str):
    """Auto-score: mood-matched bed + real SFX for every beat (background job)."""
    try:
        return {"job_id": score.submit_score(pid)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class GradeReq(BaseModel):
    look: Optional[str] = None   # ember|cinematic|noir|warm|soft|none (blank=mood)


@app.post("/api/projects/{pid}/grade")
def grade_project(pid: str, req: GradeReq = GradeReq()):
    """Cinematic GRADE — the pro 'Lumetri' pass over the finished render: one
    ffmpeg filter_complex (film colour + halation bloom + vignette + film
    grain). Applies to the newest render WITHOUT re-assembling. The look
    defaults to the channel/mood (Menagerie = ember); looks are editable in the
    effects grammar (grades.looks)."""
    try:
        return {"job_id": grade.submit_grade(pid, req.look)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- API: storage janitor ----------------------------------------------------
@app.get("/api/storage")
def storage_report():
    """Disk overview + what the janitor could reclaim."""
    return janitor.report()


class CleanReq(BaseModel):
    actions: List[str] = []


@app.post("/api/storage/clean")
def storage_clean(req: CleanReq):
    return janitor.clean(req.actions)


# --- API: YouTube packaging (SEO) ---------------------------------------------
class PackageReq(BaseModel):
    thumb_text: Optional[str] = None      # thumbnail headline (default: from title)
    thumb_template: Optional[str] = None  # spotlight|case-file|reveal|split|bar


@app.post("/api/projects/{pid}/package")
def build_package(pid: str, req: PackageReq = PackageReq()):
    """SEO kit: curiosity-gap title options, description with chapters, tags +
    mood-graded templated thumbnail (all variants in video/thumbs/).
    Saved on the project (project.seo) so edits persist and uploads use them."""
    try:
        return packaging.build(pid, req.thumb_text, req.thumb_template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- dev hot-reload (no more "wait for the GPU job to finish to restart") ----
class DevReloadReq(BaseModel):
    modules: List[str]


@app.post("/api/dev/reload")
def dev_reload(req: DevReloadReq):
    """Hot-reload app modules IN PLACE — no server restart, running jobs keep
    the code they started with; the NEXT request/job/stage uses the new code.

    Safe for the pure-logic modules (grammar, autodirect, transitions,
    receipts, sfx, thumbs, packaging, recipe, assemble, score, humanize,
    animate, images, voiceover, scenes, projects, channels, brandkit,
    roulette). DO NOT reload engine singletons (engine, comfy_engine,
    wan_engine, image_engine, music_engine) or jobs/produce/main — they hold
    live threads/models."""
    import importlib
    import sys as _sys
    banned = {"main", "jobs", "produce", "engine", "comfy_engine", "wan_engine",
              "image_engine", "music_engine", "config", "storage"}
    out = {}
    for name in req.modules:
        if not name.isidentifier() or name.startswith("_") or name in banned:
            out[name] = "refused"
            continue
        mod = _sys.modules.get(f"app.{name}")
        if mod is None:
            out[name] = "not loaded"
            continue
        try:
            importlib.reload(mod)
            out[name] = "reloaded"
        except Exception as exc:  # noqa: BLE001
            out[name] = f"FAILED: {type(exc).__name__}: {exc}"
    return out


class DevCallReq(BaseModel):
    module: str
    func: str
    kwargs: dict = {}


@app.post("/api/dev/call")
def dev_call(req: DevCallReq):
    """Call app.<module>.<func>(**kwargs) directly — the escape hatch that
    makes a brand-new capability usable BEFORE its real endpoint exists (a
    restart while a GPU job runs would kill the job). Local single-user app;
    private names are refused."""
    import importlib
    if not (req.module.isidentifier() and not req.module.startswith("_")
            and req.func.isidentifier() and not req.func.startswith("_")):
        raise HTTPException(status_code=400, detail="bad module/function name")
    try:
        mod = importlib.import_module(f"app.{req.module}")
        fn = getattr(mod, req.func)
    except (ImportError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        result = fn(**(req.kwargs or {}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        import json as _json
        _json.dumps(result)
        return {"result": result}
    except (TypeError, ValueError):
        return {"result": str(result)}


class EditPreviewReq(BaseModel):
    scene: Optional[str] = None       # center the slice on this scene
    t0: Optional[float] = None        # or give an explicit window
    t1: Optional[float] = None
    seconds: float = 12.0


@app.post("/api/projects/{pid}/edit_preview")
def edit_preview(pid: str, req: EditPreviewReq = EditPreviewReq()):
    """LIVE PREVIEW for the Edit page: render a short slice of the timeline
    through the REAL assembler — transitions, word-synced emphasis, date
    chips, receipt moves, scene FX and the film filter all included — to
    video/edit_preview.mp4 (fast NVENC; never listed in renders)."""
    p = projects.get_project(pid)
    if not p:
        raise HTTPException(status_code=404, detail="project not found")
    tl = projects.recompute_timeline(p)
    t0, t1 = req.t0, req.t1
    if req.scene is not None:
        row = next((r for r in (tl.get("scenes") or [])
                    if str(r.get("id")) == str(req.scene)), None)
        if not row:
            raise HTTPException(status_code=400, detail="scene not on the timeline")
        t0 = max(0.0, float(row["start"]) - 1.5)
        t1 = t0 + max(6.0, float(req.seconds))
    if t0 is None:
        t0 = 0.0
    if t1 is None:
        t1 = t0 + max(6.0, float(req.seconds))
    total = float(tl.get("total_dur") or 0)
    if total:
        t1 = min(t1, total)
        t0 = max(0.0, min(t0, t1 - 2.0))
    try:
        jid = assemble.submit_assemble(pid, {"window": [t0, t1],
                                             "out_name": "edit_preview",
                                             "preview": True})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": jid, "window": [round(t0, 2), round(t1, 2)],
            "file": "video/edit_preview.mp4"}


@app.post("/api/projects/{pid}/autoedit")
def autoedit(pid: str):
    """ONE-CLICK AUTO-EDIT: the AI re-reads the script and re-decides every
    editing call — transitions, SFX cues, shots, word-level emphasis, scene
    FX, date chips, hero flags — from the grammar dictionary. Script, voice
    and images are untouched; assemble afterwards to render the new edit."""
    from . import autodirect
    p = projects.get_project(pid)
    if not p:
        raise HTTPException(status_code=404, detail="project not found")
    ch = channels.get(p.get("channel")) or {}
    d = ch.get("defaults") or {}
    board = {"video": dict(p.get("video") or {}),
             "character_bible": [{"name": c.get("name"),
                                  "description": c.get("description"),
                                  "palette": c.get("palette")}
                                 for c in (p.get("characters") or [])],
             "scenes": [dict(s) for s in (p.get("scenes") or [])]}
    for s in board["scenes"]:            # blank the calls so they're re-decided
        for k in ("transition", "audio_cue", "shot", "emphasis", "fx", "date_chip"):
            s.pop(k, None)
    fixed, report = autodirect.direct(board, default_style=d.get("style_suffix"),
                                      strict=False)
    by_id = {str(s.get("id")): s for s in fixed["scenes"]}
    n = 0
    for s in p["scenes"]:
        f = by_id.get(str(s.get("id")))
        if not f:
            continue
        for k in ("transition", "audio_cue", "shot", "emphasis", "fx", "date_chip"):
            if f.get(k):
                s[k] = f[k]
        n += 1
    p["video"]["direction_card"] = (fixed["video"].get("direction_card")
                                    or p["video"].get("direction_card"))
    projects.save_project(p)
    return {"scenes": n, "card": (p["video"].get("direction_card") or {}).get("id"),
            "fixes": len(report.get("fixes") or []),
            "warnings": (report.get("warnings") or [])[:8]}


@app.get("/api/projects/{pid}/recipe")
def get_recipe(pid: str):
    """The video's RECIPE CARD — exact ingredients + measurements (script,
    direction card, voice, look, edit counts, score, package, research)."""
    try:
        return {"recipe": recipe.build(pid), "file": recipe.write_md(pid)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.put("/api/projects/{pid}/research")
def put_research(pid: str, patch: dict):
    """Attach research to a project: {summary, facts[], sources[{title,url}],
    keywords[]}. The SEO packager builds from it — keywords lead the tags and
    sources become a public Sources block (the anti-AI-slop description)."""
    p = projects.get_project(pid)
    if not p:
        raise HTTPException(status_code=404, detail="project not found")
    r = p.get("research") or {}
    for k in ("summary", "facts", "sources", "keywords"):
        if k in (patch or {}):
            r[k] = patch[k]
    p["research"] = r
    projects.save_project(p)
    return {"research": r}


class RefsReq(BaseModel):
    entities: List[dict]     # [{label, kind: person|place|item, query?, aliases?}]


@app.get("/api/projects/{pid}/refs")
def get_research_refs(pid: str):
    """The reference-image manifest + which scene first mentions each ref."""
    from . import refcards
    try:
        return refcards.plan_for(pid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/projects/{pid}/research/refs")
def fetch_research_refs(pid: str, req: RefsReq):
    """Download reference images (Wikipedia lead images, license recorded)
    into research/refs/. The assembler edits each in at its first spoken
    mention as a floating ref card."""
    try:
        return {"job_id": webresearch.submit_fetch_refs(pid, req.entities)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class ThumbPickReq(BaseModel):
    template: str


@app.post("/api/projects/{pid}/thumbnail")
def pick_thumbnail(pid: str, req: ThumbPickReq):
    """Promote one rendered variant (video/thumbs/<t>.png) to thumbnail.png."""
    from . import thumbs as _thumbs
    try:
        return _thumbs.choose_variant(pid, req.template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class ThumbSetReq(BaseModel):
    video_id: str = ""                # default: the newest upload


@app.post("/api/projects/{pid}/youtube/thumbnail")
def send_thumbnail_to_youtube(pid: str, req: ThumbSetReq = ThumbSetReq()):
    """Set/retry the custom thumbnail on an uploaded video (YouTube 403s
    until the channel is phone-verified at youtube.com/verify)."""
    try:
        return youtube.set_thumbnail(pid, req.video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface YouTube API errors to the UI
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/projects/{pid}/youtube/status")
def youtube_video_status(pid: str, fresh: int = 0):
    """Live YouTube-side state of every upload row (title/privacy/processing/
    deleted), one batched videos.list, cached ~20 s. fresh=1 bypasses the cache."""
    try:
        return youtube.video_status(pid, max_age=0 if fresh else 20)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface YouTube API errors to the UI
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/projects/{pid}/youtube/sync")
def sync_seo_to_youtube(pid: str, req: ThumbSetReq = ThumbSetReq()):
    """Push the saved SEO title/description/tags onto an uploaded video, so
    the live video catches up when the SEO changed after the upload."""
    try:
        return youtube.sync_seo(pid, req.video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface YouTube API errors to the UI
        raise HTTPException(status_code=502, detail=str(exc))


@app.put("/api/projects/{pid}/seo")
def put_seo(pid: str, patch: dict):
    """Persist user edits to the SEO package (title/description/tags…)."""
    p = projects.get_project(pid)
    if not p:
        raise HTTPException(status_code=404, detail="project not found")
    p["seo"] = {**(p.get("seo") or {}), **(patch or {})}
    projects.save_project(p)
    return p["seo"]


# --- API: local script writer (topic in → imported project out) ---------------
@app.get("/api/writer/status")
def writer_status():
    return writer.status()


class WriteReq(BaseModel):
    topic: Optional[str] = None


@app.post("/api/channels/{cid}/write")
def write_script(cid: str, req: WriteReq = WriteReq()):
    """Write this channel's next script with a LOCAL model and import it."""
    try:
        return {"job_id": writer.submit_write(cid, req.topic)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- API: Autopilot (idea in -> finished video out, local agent) ---------------
class AutopilotReq(BaseModel):
    idea: str
    minutes: Optional[float] = None   # target length (default ~2)


@app.post("/api/channels/{cid}/autopilot")
def autopilot_start(cid: str, req: AutopilotReq):
    """Type a video idea (broad or detailed); the local agent researches,
    scripts, fetches reference images, produces and packages the video."""
    try:
        aid = pilot.submit(cid, req.idea, {"minutes": req.minutes})
        return {"autopilot_id": aid}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/autopilot/{aid}")
def autopilot_status(aid: str):
    st = pilot.status(aid)
    if not st:
        raise HTTPException(status_code=404, detail="autopilot run not found")
    return st


@app.post("/api/autopilot/{aid}/cancel")
def autopilot_cancel(aid: str):
    return {"cancelled": pilot.cancel(aid)}


@app.get("/api/queue")
def queue_page():
    """Everything in flight (jobs + produce pipelines + autopilot runs)."""
    return service.queue_snapshot()


@app.get("/api/channels/{cid}/autopilot")
def autopilot_latest(cid: str):
    """The newest autopilot run for this channel (UI reconnect after refresh)."""
    return pilot.latest_for(cid) or {}


# --- API: Shorts cutter --------------------------------------------------------
class ShortsReq(BaseModel):
    count: int = 2                    # hook + payoff (3 adds a mid-peak)
    max_sec: float = 35.0


@app.post("/api/projects/{pid}/shorts")
def cut_shorts(pid: str, req: ShortsReq = ShortsReq()):
    """Cut vertical 9:16 Shorts (hook/payoff) from the assembled timeline."""
    try:
        return {"job_id": shorts.submit_shorts(pid, req.dict())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- API: YouTube upload (per-channel OAuth) -----------------------------------
@app.get("/api/channels/{cid}/youtube/auth_url")
def youtube_auth_url(cid: str, reconnect: bool = False):
    try:
        return {"url": youtube.auth_url(cid, reconnect=reconnect)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/youtube/oauth/callback")
def youtube_oauth_callback(state: str = "", code: str = "", error: str = ""):
    if error or not code:
        return HTMLResponse(f"<h3>YouTube connection failed: {error or 'no code'}</h3>"
                            "<p>Close this tab and try again.</p>", status_code=400)
    try:
        youtube.finish_oauth(state, code)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(f"<h3>Token exchange failed</h3><pre>{exc}</pre>",
                            status_code=400)
    return HTMLResponse("<h3>✓ Channel connected to YouTube.</h3>"
                        "<p>You can close this tab and go back to AAAFlow.</p>")


class UploadReq(BaseModel):
    file: Optional[str] = None        # project-relative mp4 (default: newest final)
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    privacy: Optional[str] = None     # private (default) | unlisted | public
    thumbnail: bool = True
    master: Optional[bool] = None     # upload the 1440p master (default True)
    publish_at: Optional[str] = None  # local datetime -> YouTube publishAt


@app.post("/api/projects/{pid}/upload")
def upload_to_youtube(pid: str, req: UploadReq = UploadReq()):
    """Upload a render to the project's channel YouTube account (job)."""
    try:
        return {"job_id": youtube.submit_upload(pid, req.dict(exclude_none=True))}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- API: in-app YouTube control center (manage the connected account) --------
@app.get("/api/channels/{cid}/youtube/channels")
def youtube_my_channels(cid: str):
    """The channel(s) on the connected account — avatar, banner, description, stats."""
    try:
        return youtube.list_my_channels(cid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface YouTube API errors to the UI
        raise HTTPException(status_code=502, detail=str(exc))


class BrandingReq(BaseModel):
    description: Optional[str] = None
    keywords: Optional[str] = None     # space/comma-separated channel keywords
    country: Optional[str] = None      # ISO 3166-1 alpha-2 (e.g. US)
    title: Optional[str] = None        # best-effort (Google often ignores API renames)
    default_language: Optional[str] = None


@app.put("/api/channels/{cid}/youtube/branding")
def youtube_update_branding(cid: str, req: BrandingReq):
    """Edit the channel description / keywords / country from the app."""
    try:
        return youtube.update_branding(cid, req.dict(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/channels/{cid}/youtube/banner")
async def youtube_set_banner(cid: str, file: UploadFile = File(...)):
    """Upload + set the channel banner (2048×1152 recommended)."""
    data = await file.read()
    try:
        return youtube.set_banner(cid, data, file.content_type or "image/png")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))


class VideoEditReq(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    privacy: Optional[str] = None      # private | unlisted | public


@app.put("/api/channels/{cid}/youtube/video/{video_id}")
def youtube_update_video(cid: str, video_id: str, req: VideoEditReq):
    """Edit an already-uploaded video's title/description/tags/privacy."""
    try:
        return youtube.update_video(cid, video_id, req.dict(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/storyboard/template")
def storyboard_template(scene_count: int = 1, character_count: int = 1):
    """Blank, full-schema storyboard JSON (every importable key) for the paste box / download."""
    return scenes.blank_storyboard(scene_count, character_count)


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    project = projects.get_project(pid)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    return {"deleted": projects.delete_project(pid)}


@app.put("/api/projects/{pid}/settings")
def put_project_settings(pid: str, patch: dict):
    settings = projects.update_settings(pid, patch or {})
    if settings is None:
        raise HTTPException(status_code=404, detail="project not found")
    return settings


@app.patch("/api/projects/{pid}/video")
def patch_video_meta(pid: str, patch: dict):
    """Edit the storyboard-wide prompts (global style / negative) from the UI."""
    meta = projects.update_video_meta(pid, patch or {})
    if meta is None:
        raise HTTPException(status_code=404, detail="project not found")
    return meta


@app.patch("/api/projects/{pid}/scenes/{sid}")
def patch_scene(pid: str, sid: str, patch: dict):
    scene = projects.update_scene(pid, sid, patch or {})
    if scene is None:
        raise HTTPException(status_code=404, detail="project or scene not found")
    return scene


# --- API: voiceover --------------------------------------------------------
class VoiceoverReq(BaseModel):
    voice: dict
    scope: str = "missing"            # "all" | "missing" | "scene"
    scene_id: Optional[str] = None


@app.post("/api/projects/{pid}/voiceover")
def gen_voiceover(pid: str, req: VoiceoverReq):
    try:
        job_id = voiceover.submit_voiceover(pid, req.voice, req.scope, req.scene_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


@app.post("/api/projects/{pid}/voiceover/onetake")
def gen_voiceover_onetake(pid: str, req: VoiceoverReq):
    """Canonical voice flow: whole script in one take + Whisper scene alignment."""
    try:
        job_id = voiceover.submit_onetake(pid, req.voice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


class ProduceReq(BaseModel):
    plan: dict = {}                   # overrides for produce.default_plan


@app.post("/api/projects/{pid}/produce")
def start_produce(pid: str, req: ProduceReq = ProduceReq()):
    """Run the whole pipeline (voice → images → animate → assemble) in one call."""
    try:
        return produce.submit_produce(pid, req.plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/projects/{pid}/produce")
def produce_status(pid: str):
    st = produce.status(pid)
    if st is None:
        raise HTTPException(status_code=404, detail="no production for this project")
    return st


# --- API: effects grammar (the WHEN→WHICH-effect dictionary) ------------------
@app.get("/api/effects_dictionary")
def get_effects_dictionary():
    """The editable cinematic grammar: which SFX/transition/shot/mood for which
    narration beat. autodirect + the audio scorer read this on every video."""
    return grammar.dictionary()


@app.put("/api/effects_dictionary")
def put_effects_dictionary(patch: dict):
    try:
        return grammar.save(patch or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/effects_dictionary/reset")
def reset_effects_dictionary():
    return grammar.reset()


@app.get("/api/effects_presets")
def get_effects_presets():
    return {"presets": effects.load()}


@app.put("/api/effects_presets")
def put_effects_preset(preset: dict):
    """Add/replace one editing-style preset (save a look for future videos)."""
    try:
        return {"presets": effects.upsert(preset or {})}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/sfx")
def get_sfx_library():
    """Browsable stinger library — consult this when writing audio_cue fields."""
    return {"sfx": sfx.library(), "dir": str(config.SFX_LIB_DIR)}


class AttachVoiceReq(BaseModel):
    file: str                         # recording, relative to the outputs dir (e.g. tts_xxx.wav)
    voice: Optional[str] = None       # label stored on the voiced scenes


@app.post("/api/projects/{pid}/voiceover/attach")
def attach_voiceover(pid: str, req: AttachVoiceReq):
    """Voice a project from an existing recording by slicing it at each scene's timing."""
    try:
        job_id = voiceover.submit_attach_recording(
            pid, req.file, (req.voice or "").strip() or "Imported recording")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


# --- API: transcription (timed sentence blocks per scene) ------------------
class TranscribeReq(BaseModel):
    scope: str = "missing"            # "all" | "missing" | "scene"
    scene_id: Optional[str] = None
    split: str = "sentence"           # "sentence" (standard) | "comma" (clause-level)


@app.post("/api/projects/{pid}/transcribe")
def gen_transcribe(pid: str, req: TranscribeReq):
    try:
        job_id = transcribe.submit_transcribe(pid, req.scope, req.scene_id, req.split)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


@app.get("/api/projects/{pid}/transcript")
def get_transcript(pid: str):
    if not projects.get_project(pid):
        raise HTTPException(status_code=404, detail="project not found")
    doc = transcribe.get_transcript(pid)
    if doc is None:
        raise HTTPException(status_code=404, detail="no transcript yet")
    return doc


class FileTranscribeReq(BaseModel):
    file: str                          # a filename in data/outputs (the generated clip)
    text: Optional[str] = None         # the script to anchor sentence text to
    language: Optional[str] = None
    item_id: Optional[str] = None      # the saved history entry to attach the transcript to
    split: str = "sentence"            # "sentence" (standard) | "comma" (clause-level)


@app.post("/api/transcribe")
def transcribe_file(req: FileTranscribeReq):
    """Standalone: transcribe one generated clip into timed sentence JSON."""
    try:
        return {"job_id": transcribe.submit_file_transcribe(
            req.file, req.text, req.language, req.item_id, req.split)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- API: music / SFX (ACE-Step background audio) --------------------------
class MusicReq(BaseModel):
    prompt: str
    kind: str = "music"               # "music" | "sfx"
    seconds: Optional[float] = None
    seed: int = -1
    steps: int = 8
    instrumental: bool = True


def _music_status():
    try:
        from .music_engine import music_engine
        return music_engine.status()
    except Exception:  # noqa: BLE001
        return {"available": False}


@app.get("/api/music")
def music_library():
    return {"library": storage.get_music(), "presets": music.MUSIC_PRESETS,
            "status": _music_status()}


@app.post("/api/music")
def gen_music(req: MusicReq):
    try:
        return {"job_id": music.submit_music(req.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/music/download")
def music_download():
    """Start the music sidecar + download/load the model (~9 GB on first run)."""
    return {"job_id": music.submit_music_download()}


@app.delete("/api/music/{item_id}")
def delete_music(item_id: str):
    m = storage.get_music_item(item_id)
    if m:
        for name in (m.get("files") or {}).values():
            try:
                (config.MUSIC_DIR / name).unlink()
            except OSError:
                pass
    return {"deleted": storage.delete_music(item_id)}


class ProjectMusicReq(BaseModel):
    file: Optional[str] = None        # a filename in data/music (None clears it)
    id: Optional[str] = None
    prompt: Optional[str] = None
    volume: float = 0.18              # background level under the narration (0..1)
    duck: bool = True                 # lower music further while narration plays
    fade: float = 1.5                 # fade in/out seconds


@app.put("/api/projects/{pid}/music")
def set_project_music(pid: str, req: ProjectMusicReq):
    patch = {"music": (None if not req.file else req.model_dump())}
    settings = projects.update_settings(pid, patch)
    if settings is None:
        raise HTTPException(status_code=404, detail="project not found")
    return settings


# --- API: images -----------------------------------------------------------
class ImagesReq(BaseModel):
    image: dict = {}
    scope: str = "missing"            # "all" | "missing" | "scene"
    scene_id: Optional[str] = None


@app.post("/api/projects/{pid}/images")
def gen_images(pid: str, req: ImagesReq):
    try:
        job_id = images.submit_images(pid, req.image, req.scope, req.scene_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


@app.post("/api/image/download_defaults")
def image_download_defaults():
    return {"job_id": images.submit_download_defaults()}


# --- API: character bible (consistent recurring characters) ----------------
class CharacterReq(BaseModel):
    name: str
    description: Optional[str] = ""
    palette: Optional[str] = ""
    aliases: Optional[List[str]] = None


class SheetReq(BaseModel):
    seed: int = -1
    identity: float = 0.72


@app.get("/api/projects/{pid}/characters")
def get_characters(pid: str):
    project = projects.get_project(pid)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return {"characters": characters.list_characters(project),
            "image": _status_payload().get("image", {})}


@app.post("/api/projects/{pid}/characters")
def upsert_character(pid: str, req: CharacterReq):
    try:
        ch = characters.add_or_update(pid, req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if ch is None:
        raise HTTPException(status_code=404, detail="project not found")
    return {"character": ch}


@app.delete("/api/projects/{pid}/characters/{cid}")
def del_character(pid: str, cid: str):
    return {"deleted": characters.delete_character(pid, cid)}


@app.post("/api/projects/{pid}/characters/{cid}/sheet")
def gen_character_sheet(pid: str, cid: str, req: SheetReq = SheetReq()):
    try:
        return {"job_id": characters.submit_character_sheet(pid, cid, req.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/projects/{pid}/characters/seed")
def seed_characters(pid: str):
    try:
        return {"added": characters.seed_from_storyboard(pid)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- API: style references (cartoon RAG pack) ------------------------------
@app.get("/api/style_refs")
def get_style_refs():
    return {"refs": style_refs.list_refs(), "count": style_refs.count(),
            "ip": _status_payload().get("image", {}).get("ip_loaded", False)}


@app.post("/api/style_refs/upload")
async def upload_style_ref(file: UploadFile = File(...), tags: str = Form("")):
    suffix = Path(file.filename or "ref.png").suffix or ".png"
    tmp = config.STYLE_REFS_DIR / f"_upload_{storage.new_id()}{suffix}"
    tmp.write_bytes(await file.read())
    try:
        entry = style_refs.add_ref(str(tmp), tags=tags, source="upload")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return {"ref": entry}


class SeedRefsReq(BaseModel):
    pid: str
    limit: int = 12


@app.post("/api/style_refs/seed")
def seed_style_refs(req: SeedRefsReq):
    try:
        n = style_refs.seed_from_project(req.pid, req.limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"added": n, "count": style_refs.count()}


@app.delete("/api/style_refs/{rid}")
def delete_style_ref(rid: str):
    return {"deleted": style_refs.delete_ref(rid)}


@app.post("/api/image_models/import")
async def import_image_model(
    file: UploadFile = File(...),
    kind: str = Form("lora"),          # "lora" | "checkpoint"
    label: str = Form(""),
    trigger: str = Form(""),
    weight: float = Form(1.0),
):
    suffix = Path(file.filename or "model.safetensors").suffix or ".safetensors"
    if suffix.lower() not in (".safetensors", ".gguf", ".ckpt"):
        raise HTTPException(status_code=400, detail="Use a .safetensors or .gguf file.")
    dest_dir = config.LORAS_DIR if kind == "lora" else config.DIFFUSION_DIR
    mid = storage.new_id()
    dest = dest_dir / f"{mid}{suffix}"
    dest.write_bytes(await file.read())
    entry = {
        "id": mid, "kind": kind,
        "label": (label.strip() or Path(file.filename or str(dest)).stem),
        "filename": file.filename or dest.name, "path": str(dest),
        "trigger": trigger.strip(), "weight": float(weight),
        "source": "import", "created": time.time(),
    }
    storage.add_image_model(entry)
    return {"model": entry}


@app.delete("/api/image_models/{model_id}")
def delete_image_model(model_id: str):
    m = storage.get_image_model(model_id)
    if m and m.get("path"):
        try:
            Path(m["path"]).unlink()
        except OSError:
            pass
    return {"deleted": storage.delete_image_model(model_id)}


# --- API: assemble ---------------------------------------------------------
class AssembleReq(BaseModel):
    opts: dict = {}


@app.post("/api/projects/{pid}/assemble")
def assemble_video(pid: str, req: AssembleReq):
    try:
        job_id = assemble.submit_assemble(pid, req.opts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


# --- API: animate (LTX-2 image->video) ------------------------------------
class AnimateReq(BaseModel):
    opts: dict = {}
    scope: str = "motion"             # "motion" | "all" | "missing" | "scene"
    scene_id: Optional[str] = None


@app.get("/api/wan/status")
def wan_status():
    from .wan_engine import wan_engine
    return {**wan_engine.status(), "enhance": config.enhance_ready()}


@app.post("/api/wan/download")
def wan_download():
    """Download any missing Wan 2.2 weights in-app (headless background job)."""
    return {"job_id": animate.submit_wan_download()}


class AutoPromptReq(BaseModel):
    overwrite: bool = False


@app.post("/api/projects/{pid}/animate/autoprompt")
def animate_autoprompt(pid: str, req: AutoPromptReq):
    try:
        return animate.fill_motion_prompts(pid, req.overwrite)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/projects/{pid}/animate")
def gen_animate(pid: str, req: AnimateReq):
    try:
        job_id = animate.submit_animate(pid, req.opts, req.scope, req.scene_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


# --- API: training (LoRA) --------------------------------------------------
class TrainStartReq(BaseModel):
    base: str = "krea2"
    name: str
    trigger: str = ""
    type: str = "style"
    epochs: int = 12
    dim: int = 32
    blocks_to_swap: int = 24
    autocaption: bool = True


@app.get("/api/training/datasets")
def training_datasets():
    return {"datasets": training.list_datasets(), "status": training.status()}


@app.get("/api/training/status")
def training_status():
    return training.status()


@app.get("/api/training/log")
def training_log():
    return training.get_log()


@app.post("/api/training/start")
def training_start(req: TrainStartReq):
    try:
        rid = training.start(req.base, req.name, req.trigger, req.epochs,
                             req.dim, req.blocks_to_swap, req.autocaption)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": rid}


@app.post("/api/training/stop")
def training_stop():
    return {"stopped": training.stop()}


# --- API: scene-graph -> LoRA dataset (caption generator, JSON source of truth) ---
class DatasetBuildReq(BaseModel):
    pid: str
    base: str = "krea2"
    name: str
    trigger: str = ""
    opts: Optional[dict] = None


class RecaptionReq(BaseModel):
    base: str = "krea2"
    name: str
    trigger: str = ""
    opts: Optional[dict] = None


class CaptionPreviewReq(BaseModel):
    trigger: str = ""
    opts: Optional[dict] = None


@app.get("/api/captions/fields")
def captions_fields():
    return {"defaults": captions.DEFAULT_CAPTION_OPTS}


@app.post("/api/projects/{pid}/captions/preview")
def captions_preview(pid: str, req: CaptionPreviewReq):
    try:
        return {"samples": captions.preview_captions(pid, req.trigger, req.opts)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/training/dataset/from_scenes")
def dataset_from_scenes(req: DatasetBuildReq):
    try:
        return captions.build_dataset_from_project(
            req.pid, req.base, req.name, req.trigger, req.opts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/training/dataset/recaption")
def dataset_recaption(req: RecaptionReq):
    try:
        return captions.recaption(req.base, req.name, req.trigger, req.opts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- file serving ----------------------------------------------------------
@app.get("/download/{name}")
def download(name: str):
    path = _safe_output(name)
    return FileResponse(str(path), filename=name)


def _contained(base: Path, rel: str) -> Path:
    """base/rel, refusing path traversal; 404 when the file doesn't exist."""
    f = (base / rel).resolve()
    try:
        f.relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    if not f.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return f


# Project assets by pid, wherever the project physically lives (its channel's
# folder or legacy data/projects) — the /projects/<pid>/<rel> URLs the SPA and
# stored scene paths use keep working across moves between channels.
@app.get("/projects/{pid}/{rel:path}")
def project_asset(pid: str, rel: str):
    base = projects.project_dir(pid)
    if not (base / "project.json").exists():
        raise HTTPException(status_code=404, detail="project not found")
    return FileResponse(str(_contained(base, rel)))


# Per-channel custom UI: data/channels/<cid>/ui/. index.html = full takeover
# (each channel can look completely different); no index yet -> the studio SPA
# scoped to that channel. theme.css/assets are fetched from the same folder.
@app.get("/ch/{cid}")
@app.get("/ch/{cid}/")
def channel_ui_index(cid: str):
    if not channels.get(cid):
        raise HTTPException(status_code=404, detail="channel not found")
    idx = channels.ui_dir(cid) / "index.html"
    if idx.is_file():
        return FileResponse(str(idx))
    return RedirectResponse(url=f"/#/ch/{cid}")


@app.get("/ch/{cid}/{rel:path}")
def channel_ui_asset(cid: str, rel: str):
    try:
        base = channels.ui_dir(cid)
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(str(_contained(base, rel)))


@app.get("/channels/{cid}/brand/{rel:path}")
def channel_brand_asset(cid: str, rel: str):
    """Serve a channel's generated brand-preview images."""
    try:
        base = brandkit.brand_dir(cid)
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(str(_contained(base, rel)))


@app.get("/roulette/{rid}/{rel:path}")
def roulette_asset(rid: str, rel: str):
    """Serve a channel-roulette roll's identity stills."""
    if not re.fullmatch(r"[0-9a-f]{8}", rid or ""):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(str(_contained(roulette.ROULETTE_DIR / rid, rel)))


@app.exception_handler(HTTPException)
async def _http_exc(request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# Generated audio + shared asset dirs (inline playback), then the SPA.
# Mounted last so /api and the /projects/{pid} + /ch/{cid} routes win.
app.mount("/audio", StaticFiles(directory=str(config.OUTPUTS_DIR)), name="audio")
app.mount("/style_refs", StaticFiles(directory=str(config.STYLE_REFS_DIR)), name="style_refs")
app.mount("/music", StaticFiles(directory=str(config.MUSIC_DIR)), name="music")
app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")
