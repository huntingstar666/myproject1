# -*- coding: utf-8 -*-
"""Start the SoulX-Podcast service (web UI + API).

Usage:
  python run_server.py [--host 0.0.0.0] [--port 8000]
                       [--model_path PATH] [--model_path_dialect PATH]
                       [--llm_engine hf] [--fp16_flow] [--vram_idle_seconds 120]

All options can also be set via env vars:
  SOULX_MODEL_PATH, SOULX_MODEL_PATH_DIALECT, SOULX_LLM_ENGINE,
  SOULX_FP16_FLOW, SOULX_VRAM_IDLE_SECONDS, SOULX_API_HOST, SOULX_API_PORT
"""
import os
import sys
import argparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

DEFAULT_BASE = os.path.join(ROOT, "pretrained_models", "SoulX-Podcast-1.7B")
DEFAULT_DIALECT = os.path.join(ROOT, "pretrained_models", "SoulX-Podcast-1.7B-dialect")


def get_args():
    p = argparse.ArgumentParser(description="SoulX-Podcast server")
    p.add_argument("--host", default=os.environ.get("SOULX_API_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("SOULX_API_PORT", "8000")))
    p.add_argument("--model_path", default=os.environ.get("SOULX_MODEL_PATH", DEFAULT_BASE))
    p.add_argument("--model_path_dialect",
                   default=os.environ.get("SOULX_MODEL_PATH_DIALECT", DEFAULT_DIALECT))
    p.add_argument("--llm_engine", default=os.environ.get("SOULX_LLM_ENGINE", "hf"),
                   choices=["hf", "vllm"])
    p.add_argument("--fp16_flow", action="store_true",
                   default=os.environ.get("SOULX_FP16_FLOW", "0") == "1")
    p.add_argument("--vram_idle_seconds", type=float,
                   default=float(os.environ.get("SOULX_VRAM_IDLE_SECONDS", "120")),
                   help="Auto-release VRAM after N idle seconds. 0=right after each "
                        "generation, -1=keep loaded forever.")
    return p.parse_args()


def main():
    args = get_args()
    os.environ["SOULX_MODEL_PATH"] = args.model_path
    os.environ["SOULX_MODEL_PATH_DIALECT"] = args.model_path_dialect
    os.environ["SOULX_LLM_ENGINE"] = args.llm_engine
    os.environ["SOULX_FP16_FLOW"] = "1" if args.fp16_flow else "0"
    os.environ["SOULX_VRAM_IDLE_SECONDS"] = str(args.vram_idle_seconds)
    os.environ["SOULX_API_HOST"] = args.host
    os.environ["SOULX_API_PORT"] = str(args.port)

    import uvicorn
    from server.app import app

    print("=" * 60)
    print("SoulX-Podcast server")
    print(f"  Web UI : http://localhost:{args.port}/")
    print(f"  API    : http://localhost:{args.port}/docs")
    print(f"  Model  : {args.model_path}")
    print(f"  Dialect: {args.model_path_dialect}")
    print(f"  VRAM auto-release after: {args.vram_idle_seconds}s idle "
          f"({'never' if args.vram_idle_seconds < 0 else '0=immediate'})")
    print("=" * 60)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
