"""Reproduce a body-only Gemma 4 31B / Qwen3 8B comparison on Scene 5.

The archived 8B Scene Author request is an offline trace from the same song,
not the exact production Planner call that made the frozen H3 Plan. Only the
two performance lines are replaced; the H3 camera, seed, audio and model stay
fixed. Run prepare, infer, translate, build, then submit for each variant.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs/assets/research/gemma4-31b-scene5-2026-09-25"
TRACE = ROOT / "docs/assets/research/scene-composition-full-sequence-2026-09-23/p1b-six-scenes-seed2-v2/summary.json"
SYSTEM = ROOT / "prompts/experiments/scene_author_p1b_performance.txt"
SOURCE_EMD = Path(r"C:\Software\ComfyUI\output\mv_director\audio_reference_emd_00001.md")
SOURCE_PLAN = Path(r"C:\Software\ComfyUI\output\mv_director\audio_reference_plan_00001.txt")
SOURCE_GRAPH = Path(r"C:\Software\ComfyUI\output\h3_chains\audio_ref_body_s2_4_context_20260924\api_prompt.json")
PLAN_SHA256 = "3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9"
CAMERAS = ("Arc Shot with large amplitude at fast speed.", "Push In at fast speed.")
RUNS = {
    "qwen": "gemma4_cmp_scene5_qwen8b_20260925",
    "gemma": "gemma4_cmp_scene5_gemma31b_20260925",
}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    assert trace["complete"] and trace["p1b"] and trace["seed"] == 2
    matches = [
        item for item in trace["trace"]
        if item["task"] == "scene-author-performance"
        and json.loads(item["payload"])["scene_number"] == 5
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one archived Scene 5 performance call: {len(matches)}")
    item = matches[0]
    (DEST / "system-performance.txt").write_text(SYSTEM.read_text(encoding="utf-8"), encoding="utf-8")
    (DEST / "scene5-gemma-user.txt").write_text(item["payload"], encoding="utf-8")
    (DEST / "scene5-qwen8b-user.txt").write_text("/no_think\n" + item["payload"], encoding="utf-8")
    (DEST / "scene5-qwen8b-response.txt").write_text(item["response"], encoding="utf-8")
    write_json(DEST / "source-manifest.json", {
        "archived_request": TRACE.relative_to(ROOT).as_posix(),
        "archived_request_sha256": sha256(TRACE),
        "archived_model": trace["model"],
        "not_exact_production_trace": True,
        "source_emd": str(SOURCE_EMD),
        "source_emd_sha256": sha256(SOURCE_EMD),
        "source_plan": str(SOURCE_PLAN),
        "source_plan_sha256": sha256(SOURCE_PLAN),
        "scene": 5,
        "scene_start_ms": 39167,
        "scene_end_ms": 48375,
    })


def completion(system: str, user: str, *, max_tokens: int, temperature: float) -> dict:
    base = os.environ.get("GEMMA_PROBE_BASE_URL", "http://127.0.0.1:30001").rstrip("/")
    model = os.environ.get("GEMMA_PROBE_MODEL", "gemma4-31b-scene5-probe")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "top_p": 0.9,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("GEMMA_PROBE_API_KEY"):
        headers["Authorization"] = f"Bearer {key}"
    request = Request(
        f"{base}/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=1800) as response:
        result = json.load(response)
    choice = result["choices"][0]
    return {
        "model": model,
        "temperature": temperature,
        "top_p": 0.9,
        "max_tokens": max_tokens,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "finish_reason": choice.get("finish_reason"),
        "usage": result.get("usage"),
        "response": choice["message"].get("content") or "",
        "reasoning_content": choice["message"].get("reasoning_content"),
    }


def parse_performances(text: str) -> list[str]:
    lines = text.strip().splitlines()
    if len(lines) != 2:
        raise ValueError(f"Scene 5 needs exactly two performance lines, got {len(lines)}")
    values = []
    for index, line in enumerate(lines, 1):
        match = re.fullmatch(r"PERFORMANCE\t(\d+)\t(.+)", line)
        if not match or int(match.group(1)) != index:
            raise ValueError(f"Malformed Scene 5 performance: {line!r}")
        values.append(match.group(2))
    return values


def infer(max_tokens: int) -> None:
    result = completion(
        (DEST / "system-performance.txt").read_text(encoding="utf-8"),
        (DEST / "scene5-gemma-user.txt").read_text(encoding="utf-8"),
        max_tokens=max_tokens,
        temperature=0.2,
    )
    write_json(DEST / "scene5-gemma-performance.json", result)
    print(f"finish={result['finish_reason']} usage={result['usage']} elapsed={result['elapsed_seconds']}s")
    print(result["response"][:2000])
    parse_performances(result["response"])


def translate(max_tokens: int) -> None:
    source = json.loads((DEST / "scene5-gemma-performance.json").read_text(encoding="utf-8"))
    values = parse_performances(source["response"])
    items = [{"scene": 5, "shot": i, "japanese": value} for i, value in enumerate(values, 1)]
    system = (
        "Translate Japanese MV shot action descriptions into concise, faithful English "
        "for a text-to-video prompt. Preserve every temporal change, body movement, "
        "visible object, emotion, and spatial relationship; do not invent or omit events. "
        "Return only JSON: an object with a 'translations' array of exactly two strings "
        "in the same order as the input. No commentary."
    )
    result = completion(system, json.dumps(items, ensure_ascii=False), max_tokens=max_tokens, temperature=0.1)
    match = re.search(r"\{\s*\"translations\"\s*:\s*\[.*?\]\s*\}", result["response"], re.DOTALL)
    if not match:
        raise ValueError("Translation JSON missing")
    english = json.loads(match.group())["translations"]
    if len(english) != 2 or any(not isinstance(value, str) or not value.strip() for value in english):
        raise ValueError("Translation count or type invalid")
    for item, value in zip(items, english, strict=True):
        item["english"] = value
    result["system"] = system
    result["source"] = items
    write_json(DEST / "scene5-gemma-english.json", result)
    for item in items:
        print(f"Shot {item['shot']}: {item['english']}")


def build() -> None:
    if sha256(SOURCE_PLAN) != PLAN_SHA256:
        raise ValueError("Frozen Plan hash changed")
    original = json.loads(SOURCE_PLAN.read_text(encoding="utf-8"))
    variant = copy.deepcopy(original)
    items = json.loads((DEST / "scene5-gemma-english.json").read_text(encoding="utf-8"))["source"]
    japanese = parse_performances(json.loads((DEST / "scene5-gemma-performance.json").read_text(encoding="utf-8"))["response"])
    if [(item["scene"], item["shot"], item["japanese"]) for item in items] != [(5, i, value) for i, value in enumerate(japanese, 1)]:
        raise ValueError("Translation source no longer matches inference")
    before = original["shots"][4]["prompt"]
    after = variant["shots"][4]["prompt"]
    if not before[5].startswith("[reference generation]"):
        raise ValueError("Scene summary index changed")
    after[5] = "[reference generation] " + items[0]["english"]
    for shot, item in enumerate(items, 1):
        index = 11 + shot
        old = before[index]
        camera = CAMERAS[shot - 1]
        if not old.startswith(f"[Shot {shot}]") or old.count(camera) != 1:
            raise ValueError(f"Scene 5 camera anchor changed for Shot {shot}")
        prefix = old[:old.index(camera)]
        timestamp = ""
        if shot == 2:
            stamp = re.match(r"\[Shot 2\] (At \d\d:\d\d\.\d\d\d, )", prefix)
            if not stamp:
                raise ValueError("Scene 5 Shot 2 timestamp changed")
            timestamp = stamp.group(1)
        after[index] = f"[Shot {shot}] {timestamp}{item['english']} {old[old.index(camera):]}"
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    if changed != [5, 12, 13]:
        raise ValueError(f"Unexpected Plan line changes: {changed}")
    if any(a != b for i, (a, b) in enumerate(zip(original["shots"], variant["shots"], strict=True), 1) if i != 5):
        raise ValueError("Non-target Scene changed")
    for key in original:
        if key != "shots" and original[key] != variant[key]:
            raise ValueError(f"Top-level Plan property changed: {key}")
    write_json(DEST / "gemma-body-scene5-plan.json", variant)

    source = SOURCE_EMD.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    output = []
    scene = shot = 0
    first_body = False
    changed_shots = []
    for line in lines:
        if match := re.match(r"> `シーン` (\d+)$", line.strip()):
            scene, shot = int(match.group(1)), 0
            first_body = False
        elif line.startswith("## ショット "):
            shot += 1
            first_body = True
        if scene == 5 and first_body and line.startswith("* "):
            output.append(f"* 人物演技:{japanese[shot - 1]}\n")
            changed_shots.append(shot)
            first_body = False
        else:
            output.append(line)
    if changed_shots != [1, 2]:
        raise ValueError(f"Unexpected EMD action coverage: {changed_shots}")
    (DEST / "qwen3-8b-full.emd.md").write_text(source, encoding="utf-8")
    (DEST / "gemma4-31b-body-full.emd.md").write_text("".join(output), encoding="utf-8")
    diff = difflib.unified_diff(lines, output, fromfile="qwen3-8b-full.emd.md", tofile="gemma4-31b-body-full.emd.md")
    (DEST / "emd-body-diff.patch").write_text("".join(diff), encoding="utf-8")
    print(f"Plan changed only Scene 5 lines {changed}; EMD changed Shots {changed_shots}")


def submit(variant: str) -> None:
    graph = json.loads(SOURCE_GRAPH.read_text(encoding="utf-8"))
    if graph["48"]["class_type"] != "MVDirectorSceneDebugSplitter":
        raise ValueError("Unexpected graph")
    if graph["24"]["inputs"]["plan_json_input"] != ["48", 0]:
        raise ValueError("Plan connector changed")
    run = RUNS[variant]
    plan_file = SOURCE_PLAN if variant == "qwen" else DEST / "gemma-body-scene5-plan.json"
    # Scene 5 continues Scene 4. Render Scene 4 identically in both arms so
    # the changed Scene 5 performance receives the same visual lead-in.
    graph["48"]["inputs"].update({"enable": True, "scene_start": 4, "scene_length": 2, "plan_json": plan_file.read_text(encoding="utf-8")})
    graph["24"]["inputs"]["run_name"] = run
    graph["21"]["inputs"]["filename"] = run
    write_json(DEST / f"{variant}-submitted-api-prompt.json", graph)
    request = Request(
        "http://127.0.0.1:8188/prompt",
        data=json.dumps({"prompt": graph, "client_id": run}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    write_json(DEST / f"{variant}-submission-response.json", result)
    print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "infer", "translate", "build", "submit"))
    parser.add_argument("--variant", choices=tuple(RUNS))
    parser.add_argument("--max-tokens", type=int, default=8192)
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare()
    elif args.phase == "infer":
        infer(args.max_tokens)
    elif args.phase == "translate":
        translate(args.max_tokens)
    elif args.phase == "build":
        build()
    elif args.variant:
        submit(args.variant)
    else:
        parser.error("submit requires --variant")


if __name__ == "__main__":
    main()
