# -*- coding: utf-8 -*-
"""Easy-Podcast model manager.

Wraps the SoulX-Podcast engine (https://github.com/Soul-AILab/SoulX-Podcast).

Responsibilities:
- Lazy model loading (base / dialect models, loaded on demand)
- Serialized generation (one task at a time)
- Automatic VRAM release after an idle timeout (default 120s), per-request
  unload policy (auto / immediate / keep) and manual unload endpoint
- ComfyUI-style task queue: submit -> task_id -> poll status
"""
import gc
import os
import re
import sys
import time
import base64
import random
import threading
import traceback
import uuid

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

STATE_UNLOADED = "unloaded"
STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_GENERATING = "generating"

TASK_QUEUED = "queued"
TASK_RUNNING = "running"
TASK_DONE = "done"
TASK_ERROR = "error"

SAMPLE_RATE = 24000
SPEAKER_RE = re.compile(r"(\[S[1-4]\])")
SEGMENT_RE = re.compile(r"(\[S[1-4]\][^\[\]]*)")
DIALECT_PREFIXES = ("<|Sichuan|>", "<|Yue|>", "<|Henan|>")
SUBLENGTH_TOKENS = ["<|laughter|>", "<|sigh|>", "<|breathing|>", "<|coughing|>", "<|throat_clearing|>"]


class Task:
    def __init__(self, task_id: str, params: dict):
        self.task_id = task_id
        self.params = params
        self.status = TASK_QUEUED
        self.created_at = time.time()
        self.started_at = None
        self.finished_at = None
        self.error = None
        self.output_filename = None
        self.audio_duration_sec = None
        self.model_used = None

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_sec": (
                (self.finished_at or time.time()) - self.started_at
                if self.started_at else None
            ),
            "error": self.error,
            "output_filename": self.output_filename,
            "audio_duration_sec": self.audio_duration_sec,
            "model_used": self.model_used,
        }


class ModelManager:
    def __init__(
        self,
        model_path: str,
        model_path_dialect: str = "",
        llm_engine: str = "hf",
        fp16_flow: bool = False,
        vram_idle_seconds: float = 120.0,
        default_seed: int = 1988,
        outputs_dir: str = None,
        uploads_dir: str = None,
    ):
        self.model_path = os.path.abspath(model_path)
        self.model_path_dialect = os.path.abspath(model_path_dialect) if model_path_dialect else ""
        self.llm_engine = llm_engine
        self.fp16_flow = fp16_flow
        self.vram_idle_seconds = float(vram_idle_seconds)
        self.default_seed = default_seed

        self.outputs_dir = outputs_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
        self.uploads_dir = uploads_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
        os.makedirs(self.outputs_dir, exist_ok=True)
        os.makedirs(self.uploads_dir, exist_ok=True)

        self.state = STATE_UNLOADED
        self.loaded_model_path = None
        self.last_used = time.time()
        self.error = None

        self.model = None
        self.dataset = None
        self._pending_load_path = None

        self._cond = threading.Condition()
        self._gen_lock = threading.Lock()
        self._tasks = {}
        self._load_started_at = None

        watcher = threading.Thread(target=self._idle_watch, daemon=True, name="vram-idle-watch")
        watcher.start()

    # ------------------------------------------------------------------ VRAM

    def vram_info(self):
        info = {"cuda_available": False}
        try:
            import torch
            if torch.cuda.is_available():
                free_b, total_b = torch.cuda.mem_get_info()
                info.update({
                    "cuda_available": True,
                    "device": torch.cuda.get_device_name(0),
                    "allocated_gb": round(torch.cuda.memory_allocated() / 1024 ** 3, 2),
                    "reserved_gb": round(torch.cuda.memory_reserved() / 1024 ** 3, 2),
                    "free_gb": round(free_b / 1024 ** 3, 2),
                    "total_gb": round(total_b / 1024 ** 3, 2),
                })
        except Exception:
            pass
        return info

    def status(self):
        with self._cond:
            st = {
                "state": self.state,
                "loaded_model": (
                    os.path.basename(self.loaded_model_path) if self.loaded_model_path else None
                ),
                "is_dialect_model": bool(
                    self.loaded_model_path and "dialect" in os.path.basename(self.loaded_model_path)
                ),
                "idle_seconds": self.vram_idle_seconds,
                "idle_remaining": None,
                "error": self.error,
                "model_path": self.model_path,
                "model_path_dialect": self.model_path_dialect,
                "llm_engine": self.llm_engine,
            }
            if self.state in (STATE_READY, STATE_GENERATING) and self.vram_idle_seconds >= 0:
                st["idle_remaining"] = round(
                    max(0.0, self.vram_idle_seconds - (time.time() - self.last_used)), 1
                )
        st["vram"] = self.vram_info()
        return st

    # ------------------------------------------------------ load / unload

    def _load_model(self, target_path: str):
        """Blocking load. Caller must hold no lock. Sets state transitions."""
        import torch
        from soulxpodcast.utils.infer_utils import initiate_model

        with self._cond:
            if self.state == STATE_READY and self.loaded_model_path == target_path:
                self.last_used = time.time()
                return
            if self.state == STATE_GENERATING:
                raise RuntimeError("Cannot load while a generation is running.")
            if self.state == STATE_READY:
                self._unload_locked()
            self.state = STATE_LOADING
            self._pending_load_path = target_path
            self._load_started_at = time.time()
            self.error = None
            self._cond.notify_all()
        try:
            model, dataset = initiate_model(
                seed=self.default_seed,
                model_path=target_path,
                llm_engine=self.llm_engine,
                fp16_flow=self.fp16_flow,
            )
            with self._cond:
                self.model, self.dataset = model, dataset
                self.loaded_model_path = target_path
                self._pending_load_path = None
                self.state = STATE_READY
                self.last_used = time.time()
                self._cond.notify_all()
        except Exception as exc:
            with self._cond:
                self.state = STATE_UNLOADED
                self._pending_load_path = None
                self.error = f"load failed: {exc}"
                self._cond.notify_all()
            raise

    def ensure_loaded(self, target_path: str = None, wait: bool = True):
        """Make sure some model is loaded. Returns the loaded model path."""
        if target_path is None:
            target_path = self.model_path
        with self._cond:
            if self.state == STATE_READY and self.loaded_model_path == target_path:
                self.last_used = time.time()
                return self.loaded_model_path
            if self.state == STATE_LOADING and self._loading_path() == target_path:
                if wait:
                    while self.state == STATE_LOADING:
                        self._cond.wait(timeout=5)
                    if self.state == STATE_READY and self.loaded_model_path == target_path:
                        return self.loaded_model_path
                return None
        self._load_model(target_path)
        return self.loaded_model_path

    def _loading_path(self):
        return getattr(self, "_pending_load_path", None)

    def load_async_or_sync(self, target_path=None):
        """Public: explicit load (synchronous)."""
        return self.ensure_loaded(target_path=target_path, wait=True)

    def _unload_locked(self):
        """Unload model. Caller holds _cond. Does not notify."""
        import torch
        self.model = None
        self.dataset = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        self.loaded_model_path = None
        self.state = STATE_UNLOADED
        self.error = None

    def unload(self, force: bool = False):
        with self._cond:
            if self.state == STATE_GENERATING and not force:
                return False
            if self.state == STATE_LOADING:
                # wait for loading to finish, then unload
                while self.state == STATE_LOADING:
                    self._cond.wait(timeout=5)
            self._unload_locked()
            self._cond.notify_all()
            return True

    def _idle_watch(self):
        while True:
            time.sleep(2)
            try:
                if self.vram_idle_seconds < 0:
                    continue
                with self._cond:
                    if (
                        self.state == STATE_READY
                        and time.time() - self.last_used > self.vram_idle_seconds
                    ):
                        self._unload_locked()
                        print("[manager] VRAM released (idle timeout)", flush=True)
                        self._cond.notify_all()
            except Exception:
                traceback.print_exc()

    # ---------------------------------------------------------------- tasks

    def submit(self, params: dict) -> str:
        task_id = uuid.uuid4().hex[:12]
        task = Task(task_id, params)
        with self._cond:
            self._tasks[task_id] = task
        worker = threading.Thread(target=self._run_task, args=(task,), daemon=True,
                                  name=f"task-{task_id}")
        worker.start()
        return task_id

    def get_task(self, task_id: str):
        with self._cond:
            return self._tasks.get(task_id)

    def history(self, limit: int = 50):
        with self._cond:
            tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
            return [t.to_dict() for t in tasks[:limit]]

    # ------------------------------------------------------- generation

    def _run_task(self, task: Task):
        try:
            with self._gen_lock:
                task.status = TASK_RUNNING
                task.started_at = time.time()
                self._execute(task)
                task.status = TASK_DONE
                task.finished_at = time.time()
        except Exception as exc:
            traceback.print_exc()
            task.status = TASK_ERROR
            task.error = f"{type(exc).__name__}: {exc}"
            task.finished_at = time.time()
        finally:
            with self._cond:
                if self.state in (STATE_GENERATING, STATE_READY):
                    self.state = STATE_READY
                    self.last_used = time.time()
                self._cond.notify_all()
            if task.params.get("unload", "auto") == "immediate":
                self.unload()

    def _resolve_speakers(self, params: dict, task_id: str):
        """Normalize speakers spec to list of dicts with local audio paths."""
        raw = params.get("speakers")
        if raw is None:
            raise ValueError("`speakers` is required (list or dict).")
        if isinstance(raw, dict):
            items = []
            for name in sorted(raw.keys()):
                item = dict(raw[name])
                item.setdefault("_name", name)
                items.append(item)
        else:
            items = [dict(s) for s in raw]
        if not 1 <= len(items) <= 4:
            raise ValueError("1 to 4 speakers are supported.")

        speakers = []
        for i, s in enumerate(items):
            audio_path = s.get("audio_path")
            audio_b64 = s.get("audio_b64")
            if audio_b64:
                ext = os.path.splitext(audio_path or "")[1].lstrip(".") or "wav"
                ext = re.sub(r"[^0-9a-zA-Z]", "", ext)[:5] or "wav"
                fn = f"{task_id}_spk{i + 1}.{ext}"
                fp = os.path.join(self.uploads_dir, fn)
                with open(fp, "wb") as f:
                    f.write(base64.b64decode(audio_b64))
                audio_path = fp
            if not audio_path:
                raise ValueError(f"Speaker {i + 1}: provide `audio_path` or `audio_b64`.")
            if not os.path.isabs(audio_path):
                server_dir = os.path.dirname(os.path.abspath(__file__))
                for base in (ROOT, server_dir):
                    cand = os.path.join(base, audio_path)
                    if os.path.exists(cand):
                        audio_path = cand
                        break
                else:
                    audio_path = os.path.abspath(audio_path)
            if not os.path.exists(audio_path):
                raise ValueError(f"Speaker {i + 1}: audio file not found: {audio_path}")
            prompt_text = (s.get("prompt_text") or "").strip()
            if not prompt_text:
                raise ValueError(f"Speaker {i + 1}: `prompt_text` is required.")
            dialect_prompt = (s.get("dialect_prompt") or "").strip()
            if dialect_prompt and not dialect_prompt.startswith(DIALECT_PREFIXES):
                raise ValueError(
                    f"Speaker {i + 1}: dialect_prompt must start with one of {DIALECT_PREFIXES}"
                )
            speakers.append({
                "audio_path": audio_path,
                "prompt_text": prompt_text,
                "dialect_prompt": dialect_prompt,
            })
        return speakers

    def _parse_text(self, text: str, n_speakers: int, mode: str):
        text = (text or "").strip()
        if not text:
            raise ValueError("`text` is required.")
        if mode == "tts":
            text = re.sub(r"^\[S1\]\s*", "", text)
            return [f"[S1]{text}"]
        segs = [s.strip() for s in SEGMENT_RE.findall(text)]
        if not segs:
            if n_speakers == 1:
                return [f"[S1]{text}"]
            raise ValueError(
                "Text must contain speaker tags like [S1]/[S2] at each turn, "
                "or use mode='tts' with a single speaker."
            )
        for seg in segs:
            tag = seg[:4]
            idx = int(tag[2]) - 1
            if idx >= n_speakers:
                raise ValueError(
                    f"Segment `{tag}` exceeds provided speakers count ({n_speakers})."
                )
        return segs

    def _select_model_for_request(self, use_dialect: bool):
        if use_dialect:
            if not self.model_path_dialect:
                raise ValueError(
                    "Dialect prompt requires the dialect model. Set SOULX_MODEL_PATH_DIALECT."
                )
            if not os.path.isdir(self.model_path_dialect):
                raise ValueError(f"Dialect model not found: {self.model_path_dialect}")
            return self.model_path_dialect
        # Non-dialect request: reuse whatever is loaded (base or dialect both work),
        # otherwise load the base model.
        with self._cond:
            if self.state == STATE_READY and self.loaded_model_path:
                return self.loaded_model_path
        return self.model_path

    def _execute(self, task: Task):
        import torch
        from soulxpodcast.config import SamplingParams
        from soulxpodcast.utils.infer_utils import process_single_input
        from soulxpodcast.utils.commons import set_all_random_seed
        import soundfile as sf

        params = task.params
        speakers = self._resolve_speakers(params, task.task_id)
        segments = self._parse_text(params.get("text"), len(speakers), params.get("mode", "podcast"))

        use_dialect = any(s["dialect_prompt"] for s in speakers)
        unload_mode = params.get("unload", "auto")

        model_choice = params.get("model", "auto")
        if model_choice == "base":
            if use_dialect:
                raise ValueError("model='base' cannot be combined with dialect prompts.")
            model_path = self.model_path
        elif model_choice == "dialect":
            if not self.model_path_dialect or not os.path.isdir(self.model_path_dialect):
                raise ValueError("Dialect model not configured or not found.")
            model_path = self.model_path_dialect
        else:
            model_path = self._select_model_for_request(use_dialect)
        self.ensure_loaded(target_path=model_path)

        seed = params.get("seed")
        seed = self.default_seed if seed is None else int(seed)
        set_all_random_seed(seed)

        prompt_wav_list = [s["audio_path"] for s in speakers]
        prompt_text_list = [s["prompt_text"] for s in speakers]
        dialect_list = [s["dialect_prompt"] for s in speakers]

        processed = process_single_input(
            self.dataset, segments, prompt_wav_list, prompt_text_list,
            use_dialect, dialect_list,
        )
        sp = SamplingParams(use_ras=True, win_size=25, tau_r=0.2)
        for key in ("temperature", "top_k", "top_p", "repetition_penalty", "max_tokens"):
            if params.get(key) is not None:
                setattr(sp, key, params[key])
        processed["sampling_params"] = sp

        with self._cond:
            self.state = STATE_GENERATING
            self.last_used = time.time()
            self._cond.notify_all()

        results = self.model.forward_longform(**processed)
        wavs = results["generated_wavs"]
        if not wavs:
            raise RuntimeError("Model returned no audio.")
        audio = wavs[0]
        for w in wavs[1:]:
            audio = torch.concat([audio, w], axis=1)
        audio_np = audio.cpu().squeeze(0).numpy()

        filename = f"{task.task_id}.wav"
        out_path = os.path.join(self.outputs_dir, filename)
        sf.write(out_path, audio_np, SAMPLE_RATE)

        task.output_filename = filename
        task.audio_duration_sec = round(len(audio_np) / SAMPLE_RATE, 2)
        task.model_used = os.path.basename(self.loaded_model_path or "")
        if unload_mode == "immediate":
            with self._cond:
                self._unload_locked()
                self._cond.notify_all()
