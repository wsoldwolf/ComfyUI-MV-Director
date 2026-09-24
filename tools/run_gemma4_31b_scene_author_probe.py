"""Replay archived 8B Scene Author messages against a local Gemma 4 server.

Environment: GEMMA_PROBE_BASE_URL, GEMMA_PROBE_API_KEY, GEMMA_PROBE_MODEL.
The Gemma user message is the original JSON payload without Qwen's /no_think
control line. 8B responses are held out and never sent to Gemma.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/assets/research/gemma4-31b-scene-author-s2-4-2026-09-25"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=int, choices=(2, 3, 4), required=True)
    parser.add_argument("--stage", choices=("event", "performance", "camera"), required=True)
    parser.add_argument("--max-tokens", type=int, default=1024)
    args = parser.parse_args()
    base = os.environ["GEMMA_PROBE_BASE_URL"].rstrip("/")
    key = os.environ["GEMMA_PROBE_API_KEY"]
    model = os.environ["GEMMA_PROBE_MODEL"]
    system = (FIXTURE / f"system-{args.stage}.txt").read_text(encoding="utf-8")
    user = (FIXTURE / f"scene-{args.scene:02d}-{args.stage}-gemma-user.txt").read_text(
        encoding="utf-8"
    )
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": args.max_tokens,
        "stream": False,
    }
    request = Request(
        f"{base}/v1/chat/completions",
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=1800) as response:
        result = json.load(response)
    elapsed = round(time.perf_counter() - started, 3)
    message = result["choices"][0]["message"]
    content = message.get("content") or ""
    evidence = {
        "source_fixture": str(FIXTURE.relative_to(ROOT)).replace("\\", "/"),
        "scene": args.scene,
        "stage": args.stage,
        "model": model,
        "temperature": request_body["temperature"],
        "top_p": request_body["top_p"],
        "max_tokens": args.max_tokens,
        "elapsed_seconds": elapsed,
        "finish_reason": result["choices"][0].get("finish_reason"),
        "usage": result.get("usage"),
        "response": content,
        "reasoning_content": message.get("reasoning_content"),
    }
    output = FIXTURE / f"scene-{args.scene:02d}-{args.stage}-gemma-result.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"scene={args.scene} stage={args.stage} elapsed={elapsed}s ")
    print(f"finish_reason={evidence['finish_reason']} usage={evidence['usage']}")
    print(content[:1500])


if __name__ == "__main__":
    main()
