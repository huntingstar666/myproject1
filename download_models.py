# -*- coding: utf-8 -*-
"""Download SoulX-Podcast model weights (base + dialect) from hf-mirror.com."""
import os
import sys

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# Xet protocol is not reliably proxied by mirrors; force plain HTTP download.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from huggingface_hub import snapshot_download

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pretrained_models")
REPOS = [
    "Soul-AILab/SoulX-Podcast-1.7B",
    "Soul-AILab/SoulX-Podcast-1.7B-dialect",
]

def main():
    for repo in REPOS:
        target = os.path.join(BASE, repo.split("/")[-1])
        print(f"[download] {repo} -> {target}", flush=True)
        snapshot_download(
            repo_id=repo,
            local_dir=target,
            max_workers=8,
        )
        print(f"[done] {repo}", flush=True)
    print("ALL MODELS DOWNLOADED", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
