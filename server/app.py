# -*- coding: utf-8 -*-
"""SoulX-Podcast HTTP service (ComfyUI-style API + built-in web UI).

Endpoints:
  GET  /                  web UI (single page)
  GET  /docs              swagger UI (auto)
  GET  /health            service health + model state
  GET  /vram              VRAM / model status
  POST /vram/load         load model into VRAM now        {"model": "base"|"dialect"}
  POST /vram/unload       release VRAM now
  POST /prompt            submit a generation task        -> {"task_id": ...}
  GET  /prompt/{task_id}  poll task status / result
  GET  /history           recent tasks
  GET  /view?filename=    download a generated wav
  GET  /audio?filename=   stream an uploaded/sample wav
  POST /upload            upload a prompt audio (multipart)
  GET  /examples          official podcast script examples
  GET  /dialect_prompts   dialect prompt samples (sichuan/yueyu/henan)
  GET  /sample_audios     built-in prompt audios
  GET  /paralanguage      supported paralanguage tags
"""
import io
import os
import sys
import json
import base64
import tempfile
import traceback
from typing import Optional, Union, List

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server.manager import ModelManager  # noqa: E402

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
EXAMPLE_DIR = os.path.join(ROOT, "example")

DEFAULT_BASE = os.path.join(ROOT, "pretrained_models", "SoulX-Podcast-1.7B")
DEFAULT_DIALECT = os.path.join(ROOT, "pretrained_models", "SoulX-Podcast-1.7B-dialect")


class SpeakerSpec(BaseModel):
    audio_path: Optional[str] = None
    audio_b64: Optional[str] = None
    prompt_text: str = ""
    dialect_prompt: str = ""


class PromptRequest(BaseModel):
    mode: str = "podcast"                     # podcast | tts
    speakers: Union[List[SpeakerSpec], dict, None] = None
    text: str
    seed: Optional[int] = None
    temperature: Optional[float] = None
    top_k: Optional[int] = None
    top_p: Optional[float] = None
    repetition_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    unload: str = "auto"                      # auto | immediate | keep
    model: str = "auto"                       # auto | base | dialect


manager = ModelManager(
    model_path=os.environ.get("SOULX_MODEL_PATH", DEFAULT_BASE),
    model_path_dialect=os.environ.get("SOULX_MODEL_PATH_DIALECT", DEFAULT_DIALECT),
    llm_engine=os.environ.get("SOULX_LLM_ENGINE", "hf"),
    fp16_flow=os.environ.get("SOULX_FP16_FLOW", "0") == "1",
    vram_idle_seconds=float(os.environ.get("SOULX_VRAM_IDLE_SECONDS", "120")),
)

app = FastAPI(title="SoulX-Podcast API", version="1.0.0",
              description="Podcast-grade TTS with VRAM auto-release. "
                          "Submit via POST /prompt, poll via GET /prompt/{task_id}.")


def _safe_file(subdir: str, filename: str) -> str:
    filename = os.path.basename(filename)
    if not filename:
        raise HTTPException(400, "filename required")
    path = os.path.abspath(os.path.join(subdir, filename))
    if not path.startswith(os.path.abspath(subdir)):
        raise HTTPException(400, "invalid path")
    return path


@app.get("/")
def index():
    index_html = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_html):
        raise HTTPException(404, "web UI not found")
    return FileResponse(index_html)


@app.get("/health")
def health():
    st = manager.status()
    return {"status": "ok" if st["state"] != "unloaded" or st["error"] is None else "degraded",
            "state": st["state"], "vram": st["vram"]}


@app.get("/vram")
def vram():
    return manager.status()


@app.post("/vram/load")
def vram_load(body: dict = None):
    body = body or {}
    which = body.get("model", "base")
    if which == "dialect":
        if not manager.model_path_dialect:
            raise HTTPException(400, "dialect model path not configured")
        target = manager.model_path_dialect
    else:
        target = manager.model_path
    try:
        manager.ensure_loaded(target_path=target, wait=True)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return manager.status()


@app.post("/vram/unload")
def vram_unload():
    ok = manager.unload()
    return {"unloaded": ok, **manager.status()}


@app.post("/prompt")
def submit_prompt(req: PromptRequest):
    if not os.path.isdir(manager.model_path):
        raise HTTPException(500,
            f"Base model not found: {manager.model_path}. Run download_models.py first.")
    if req.mode not in ("podcast", "tts"):
        raise HTTPException(400, "mode must be 'podcast' or 'tts'")
    if req.unload not in ("auto", "immediate", "keep"):
        raise HTTPException(400, "unload must be 'auto', 'immediate' or 'keep'")
    speakers = None
    if req.speakers is not None:
        if isinstance(req.speakers, list):
            speakers = [s.model_dump() for s in req.speakers]
        else:
            speakers = {k: (v.model_dump() if isinstance(v, SpeakerSpec) else v)
                        for k, v in req.speakers.items()}
    if req.model == "dialect":
        if not speakers:
            raise HTTPException(400, "model='dialect' requires speakers to be set")
    params = {
        "mode": req.mode,
        "speakers": speakers,
        "text": req.text,
        "seed": req.seed,
        "temperature": req.temperature,
        "top_k": req.top_k,
        "top_p": req.top_p,
        "repetition_penalty": req.repetition_penalty,
        "max_tokens": req.max_tokens,
        "unload": req.unload,
        "model": req.model,
    }
    for k in ("seed", "temperature", "top_k", "top_p", "repetition_penalty", "max_tokens"):
        if params[k] is None:
            del params[k]
    task_id = manager.submit(params)
    return {"task_id": task_id, "status_url": f"/prompt/{task_id}",
            "audio_url": f"/view?filename={task_id}.wav"}


@app.get("/prompt/{task_id}")
def prompt_status(task_id: str):
    task = manager.get_task(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    d = task.to_dict()
    if task.status == "done" and task.output_filename:
        d["audio_url"] = f"/view?filename={task.output_filename}"
    return d


@app.get("/history")
def history(limit: int = 50):
    return {"tasks": manager.history(limit)}


@app.get("/view")
def view_file(filename: str):
    path = _safe_file(manager.outputs_dir, filename)
    if not os.path.exists(path):
        raise HTTPException(404, "file not found")
    return FileResponse(path, media_type="audio/wav", filename=filename)


@app.get("/audio")
def audio_file(filename: str):
    path = _safe_file(manager.uploads_dir, filename)
    if not os.path.exists(path):
        cand = os.path.join(ROOT, filename)
        cand = os.path.abspath(cand)
        if cand.startswith(os.path.abspath(ROOT)) and os.path.exists(cand):
            return FileResponse(cand, filename=os.path.basename(cand))
        raise HTTPException(404, "file not found")
    return FileResponse(path, filename=filename)


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lstrip(".")
    ext = "".join(ch for ch in ext if ch.isalnum())[:5] or "wav"
    import uuid
    fn = f"{uuid.uuid4().hex[:12]}.{ext}"
    path = os.path.join(manager.uploads_dir, fn)
    with open(path, "wb") as f:
        f.write(await file.read())
    size_mb = round(os.path.getsize(path) / 1024 / 1024, 2)
    return {"filename": fn, "audio_path": fn, "size_mb": size_mb,
            "url": f"/audio?filename={fn}"}

def _read_json_files(folder: str):
    out = []
    if os.path.isdir(folder):
        for fn in sorted(os.listdir(folder)):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(folder, fn), "r", encoding="utf-8") as f:
                        out.append({"name": fn, "data": json.load(f)})
                except Exception:
                    pass
    return out


@app.get("/examples")
def examples():
    return {"examples": _read_json_files(os.path.join(EXAMPLE_DIR, "podcast_script"))}


@app.get("/dialect_prompts")
def dialect_prompts():
    data = {}
    folder = os.path.join(EXAMPLE_DIR, "dialect_prompt")
    mapping = {"sichuan": "<|Sichuan|>", "yueyu": "<|Yue|>", "henan": "<|Henan|>"}
    if os.path.isdir(folder):
        for fn in sorted(os.listdir(folder)):
            key = os.path.splitext(fn)[0]
            if key not in mapping:
                continue
            lines = []
            try:
                with open(os.path.join(folder, fn), "r", encoding="utf-8") as f:
                    lines = [f"{mapping[key]}{ln.strip()}" for ln in f if ln.strip()]
            except Exception:
                pass
            data[key] = lines
    return {"dialects": data}


@app.get("/sample_audios")
def sample_audios():
    folder = os.path.join(EXAMPLE_DIR, "audios")
    out = []
    if os.path.isdir(folder):
        for fn in sorted(os.listdir(folder)):
            if fn.lower().endswith((".wav", ".mp3", ".flac", ".m4a")):
                out.append({"filename": fn, "audio_path": f"example/audios/{fn}",
                            "url": f"/audio?filename=example/audios/{fn}"})
    return {"samples": out}


@app.get("/paralanguage")
def paralanguage():
    return {"tags": ["<|laughter|>", "<|sigh|>", "<|breathing|>", "<|coughing|>",
                     "<|throat_clearing|>"]}


@app.exception_handler(Exception)
def internal_error(request, exc):
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# Static assets (css/js if split later)
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main():
    import uvicorn
    host = os.environ.get("SOULX_API_HOST", "0.0.0.0")
    port = int(os.environ.get("SOULX_API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
