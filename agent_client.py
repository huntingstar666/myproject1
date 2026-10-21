# -*- coding: utf-8 -*-
"""Easy-Podcast agent client — zero-dependency (Python stdlib only).

For agents/scripts to call the Easy-Podcast service (powered by SoulX-Podcast) easily.

Usage:
  # Generate a podcast (blocking until audio is ready, prints wav path)
  python agent_client.py generate ^
    --speakers-json "[{\"audio_path\":\"example/audios/female_mandarin.wav\",\"prompt_text\":\"...\"},{\"audio_path\":\"example/audios/male_mandarin.wav\",\"prompt_text\":\"...\"}]" ^
    --text "[S1]你好呀[S2]大家好" --wait

  # Single-speaker TTS
  python agent_client.py tts --audio example/audios/female_mandarin.wav --prompt-text "..." --text "要合成的文本"

  # From a JSON payload file (full request body)
  python agent_client.py generate --payload-file request.json --wait

  # Other commands
  python agent_client.py status --task-id <id>
  python agent_client.py history
  python agent_client.py vram
  python agent_client.py load [--model base|dialect]
  python agent_client.py unload
  python agent_client.py health
  python agent_client.py examples

Environment:
  SOULX_API_BASE   default: http://127.0.0.1:8000
"""
import os
import sys
import json
import time
import base64
import argparse
import urllib.request
import urllib.error

API_BASE = os.environ.get("SOULX_API_BASE", "http://127.0.0.1:8000").rstrip("/")


def http(method: str, path: str, body: dict = None, timeout: int = 600):
    url = f"{API_BASE}{path}"
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            try:
                return json.loads(payload.decode("utf-8"))
            except Exception:
                return {"raw": payload[:200]}
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
        except Exception:
            detail = str(exc)
        raise SystemExit(f"[HTTP {exc.code}] {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"[connection error] {exc.reason} — is the server running at {API_BASE}?")


def wait_task(task_id: str, poll_interval: float = 2.0, timeout: float = 3600):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        r = http("GET", f"/prompt/{task_id}", timeout=30)
        status = r.get("status")
        if status != last:
            print(f"  status: {status}", flush=True)
            last = status
        if status == "done":
            return r
        if status == "error":
            raise SystemExit(f"task failed: {r.get('error')}")
        time.sleep(poll_interval)
    raise SystemExit("timed out waiting for task")


def encode_speaker(s: dict, base_dir: str = None) -> dict:
    """Resolve local audio file to base64 (service may run on another machine)."""
    s = dict(s)
    ap = s.get("audio_path")
    if ap and not os.path.exists(ap):
        # leave as-is; server may resolve it relative to its own ROOT
        pass
    elif ap:
        with open(ap, "rb") as f:
            s["audio_b64"] = base64.b64encode(f.read()).decode("ascii")
        s["audio_path"] = os.path.basename(ap)
    return s


def cmd_generate(args):
    if args.payload_file:
        with open(args.payload_file, "r", encoding="utf-8") as f:
            body = json.load(f)
    else:
        body = {"mode": args.mode, "text": args.text}
        speakers = None
        if args.speakers_json:
            raw = json.loads(args.speakers_json)
            speakers = [encode_speaker(s) for s in raw]
        elif args.audio:
            speakers = [{
                "audio_path": args.audio,
                "prompt_text": args.prompt_text or "",
                "dialect_prompt": args.dialect_prompt or "",
            }]
        if speakers is None:
            raise SystemExit("provide --speakers-json, --audio, or --payload-file")
        body["speakers"] = speakers
        if args.seed is not None:
            body["seed"] = args.seed
        if args.unload:
            body["unload"] = args.unload
        if args.model:
            body["model"] = args.model
        if args.temperature is not None:
            body["temperature"] = args.temperature

    r = http("POST", "/prompt", body)
    print(f"task_id: {r['task_id']}")
    if not args.wait:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    result = wait_task(r["task_id"])
    filename = result.get("output_filename")
    print(json.dumps({k: result[k] for k in
                      ("task_id", "status", "audio_duration_sec", "model_used", "elapsed_sec")},
                     ensure_ascii=False, indent=2))
    print(f"audio: {API_BASE}/view?filename={filename}")
    if args.output:
        dest = args.output
        urllib.request.urlretrieve(f"{API_BASE}/view?filename={filename}", dest)
        print(f"saved: {os.path.abspath(dest)}")


def cmd_tts(args):
    speakers = [{"audio_path": args.audio, "prompt_text": args.prompt_text,
                 "dialect_prompt": args.dialect_prompt or ""}]
    argv = ["generate", "--mode", "tts", "--speakers-json", json.dumps(speakers),
            "--text", args.text]
    if args.wait:
        argv.append("--wait")
    if args.output:
        argv += ["--output", args.output]
    if args.unload:
        argv += ["--unload", args.unload]
    parser = build_parser()
    ns = argparse.Namespace(**vars(parser.parse_args(argv)))
    ns.__dict__.setdefault("payload_file", None)
    ns.__dict__.setdefault("seed", None)
    ns.__dict__.setdefault("model", None)
    ns.__dict__.setdefault("temperature", None)
    cmd_generate(ns)


def cmd_status(args):
    print(json.dumps(http("GET", f"/prompt/{args.task_id}", timeout=30),
                     ensure_ascii=False, indent=2))


def cmd_simple(args):
    if args.command in ("health", "vram", "history", "examples"):
        path = {"health": "/health", "vram": "/vram", "history": "/history",
                "examples": "/examples"}[args.command]
        print(json.dumps(http("GET", path, timeout=30), ensure_ascii=False, indent=2))
    elif args.command == "unload":
        print(json.dumps(http("POST", "/vram/unload", {}), ensure_ascii=False, indent=2))
    elif args.command == "load":
        body = {"model": args.model or "base"}
        print(json.dumps(http("POST", "/vram/load", body), ensure_ascii=False, indent=2))


def build_parser():
    p = argparse.ArgumentParser(description="Easy-Podcast API client (powered by SoulX-Podcast)")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="submit a podcast/tts generation task")
    g.add_argument("--mode", default="podcast", choices=["podcast", "tts"])
    g.add_argument("--speakers-json", help="JSON list of speaker dicts")
    g.add_argument("--payload-file", help="full JSON request body file")
    g.add_argument("--text", default="", help="[S1]...\\n[S2]... dialogue text")
    g.add_argument("--wait", action="store_true", help="wait until done")
    g.add_argument("--output", help="download wav to this path when done")
    g.add_argument("--seed", type=int)
    g.add_argument("--temperature", type=float)
    g.add_argument("--unload", choices=["auto", "immediate", "keep"])
    g.add_argument("--model", choices=["auto", "base", "dialect"])

    t = sub.add_parser("tts", help="single-speaker shortcut")
    t.add_argument("--audio", required=True)
    t.add_argument("--prompt-text", required=True)
    t.add_argument("--dialect-prompt", default="")
    t.add_argument("--text", required=True)
    t.add_argument("--wait", action="store_true")
    t.add_argument("--output")
    t.add_argument("--unload", choices=["auto", "immediate", "keep"])

    s = sub.add_parser("status", help="poll a task")
    s.add_argument("--task-id", required=True)

    for name, help_text in [
        ("health", "service health"), ("vram", "VRAM/model status"),
        ("history", "task history"), ("examples", "official examples"),
        ("unload", "release VRAM now"),
    ]:
        sub.add_parser(name, help=help_text)

    l = sub.add_parser("load", help="load model into VRAM now")
    l.add_argument("--model", choices=["base", "dialect"], default="base")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "tts":
        cmd_tts(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        cmd_simple(args)


if __name__ == "__main__":
    main()
