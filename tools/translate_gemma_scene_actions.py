"""Translate Gemma's recorded Japanese performance lines for an H3 A/B fixture."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/assets/research/gemma4-31b-scene-author-s2-4-2026-09-25"


def main() -> None:
    items: list[dict[str, object]] = []
    for scene in (3, 4):
        data = json.loads(
            (FIXTURE / f"scene-{scene:02d}-performance-gemma-result.json").read_text(
                encoding="utf-8"
            )
        )
        expected = 2 if scene == 3 else 3
        for shot, line in enumerate(data["response"].splitlines(), 1):
            match = re.fullmatch(r"PERFORMANCE\t(\d+)\t(.+)", line)
            if not match or int(match.group(1)) != shot:
                raise ValueError(f"Invalid Gemma performance record: Scene {scene}: {line!r}")
            items.append({"scene": scene, "shot": shot, "japanese": match.group(2)})
        if shot != expected:
            raise ValueError(f"Scene {scene} needs {expected} shots")

    system = (
        "Translate Japanese MV shot action descriptions into concise, faithful English "
        "for a text-to-video prompt. Preserve every temporal change, body movement, "
        "visible object, emotion, and spatial relationship; do not invent or omit events. "
        "Return only JSON: an object with a 'translations' array of exactly five strings "
        "in the same order as the input. No commentary."
    )
    user = json.dumps(items, ensure_ascii=False)
    body = {
        "model": os.environ["GEMMA_PROBE_MODEL"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "top_p": 0.9,
        "max_tokens": 4096,
        "stream": False,
    }
    request = Request(
        os.environ["GEMMA_PROBE_BASE_URL"].rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + os.environ["GEMMA_PROBE_API_KEY"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=1800) as response:
        result = json.load(response)
    text = result["choices"][0]["message"].get("content") or ""
    match = re.search(r"\{\s*\"translations\"\s*:\s*\[.*?\]\s*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Translation JSON missing: {text[:600]!r}")
    translations = json.loads(match.group())["translations"]
    if len(translations) != len(items) or any(not isinstance(x, str) or not x.strip() for x in translations):
        raise ValueError("Translation count or type invalid")
    for item, translation in zip(items, translations):
        item["english"] = translation
    evidence = {
        "model": body["model"],
        "system": system,
        "source": items,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "usage": result.get("usage"),
        "finish_reason": result["choices"][0].get("finish_reason"),
        "raw_response": text,
    }
    (FIXTURE / "gemma-performance-english.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for item in items:
        print(f"scene={item['scene']} shot={item['shot']} {item['english'][:120]}")


if __name__ == "__main__":
    main()
