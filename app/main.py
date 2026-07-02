"""FastAPI application: REST API + static SPA, bound to localhost."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (animate, assemble, captions, characters, config, humanize,
               images, jobs, music, projects, scenes, service, storage,
               style_refs, training, transcribe, voiceover)
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

    def _warm():
        try:
            engine.ensure_imports()
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
        from .ltx_engine import ltx_engine
        st["ltx"] = ltx_engine.status()
    except Exception:  # noqa: BLE001
        st["ltx"] = {"ready": False}
    try:
        from .wan_engine import wan_engine
        st["wan"] = wan_engine.status()
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
def get_projects():
    return {"projects": projects.list_projects()}


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
        project = projects.create_project(raw, req.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"project": project}


@app.post("/api/projects/upload")
async def upload_project(file: UploadFile = File(...), name: str = Form("")):
    import json as _json
    data = await file.read()
    try:
        raw = _json.loads(data.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {exc}")
    try:
        project = projects.create_project(
            raw, name.strip() or Path(file.filename or "").stem or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"project": project}


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


@app.get("/api/ltx/status")
def ltx_status():
    from .ltx_engine import ltx_engine
    return ltx_engine.status()


@app.post("/api/ltx/download")
def ltx_download():
    """Download any missing LTX-2 weights in-app (headless background job)."""
    return {"job_id": animate.submit_ltx_download()}


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


@app.exception_handler(HTTPException)
async def _http_exc(request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# Generated audio + per-project assets (inline playback), then the SPA.
# Mounted last so /api wins; /projects + /audio win over the SPA catch-all.
app.mount("/audio", StaticFiles(directory=str(config.OUTPUTS_DIR)), name="audio")
app.mount("/projects", StaticFiles(directory=str(config.PROJECTS_DIR)), name="projects")
app.mount("/style_refs", StaticFiles(directory=str(config.STYLE_REFS_DIR)), name="style_refs")
app.mount("/music", StaticFiles(directory=str(config.MUSIC_DIR)), name="music")
app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")
