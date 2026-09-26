"""Run the full frozen audio-reference song through Gemma 4 31B.

The source EMD supplies lyric timing only; none of its prior shot prose is
passed to the Planner. Requests and responses are cached for resumability.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifacts import DirectionArtifact
from core.compiler import compile_ref2va
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner import plan_timeline
from core.planner.template import parse_template_emd
from nodes.node_timeline_planner.node import _system_prompts


FIXTURE = ROOT / "docs/assets/research/scene-composition-full-sequence-2026-09-23"
DEST = ROOT / "docs/assets/research/gemma4-31b-full-2026-09-25"
SOURCE_EMD = Path(r"C:\Software\ComfyUI\output\mv_director\audio_reference_emd_00001.md")
SOURCE_GRAPH = Path(r"C:\Software\ComfyUI\output\h3_chains\audio_ref_body_s2_4_context_20260924\api_prompt.json")
MODEL = os.environ.get("GEMMA_FULL_MODEL", "gemma4-31b-full-20260925")
BASE = os.environ.get("GEMMA_FULL_BASE_URL", "http://127.0.0.1:30001").rstrip("/")
MODEL_PATH = Path(r"C:\Users\owner\.lmstudio\models\unsloth\gemma-4-31B-it-GGUF\gemma-4-31B-it-Q4_K_S.gguf")
BACKEND = os.environ.get("GEMMA_FULL_BACKEND", "direct")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def template_from_existing_emd(source: str) -> str:
    """Keep only Scene/Shot boundaries and original lyric evidence."""
    lines = source.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith("> `シーン` "))
    kept: list[str] = []
    for line in lines[first:]:
        if line.startswith(("> `シーン` ", "# シーン ", "* `H3長` ",
                            "> `セクション` ", "> `歌詞開始` ",
                            "> `歌詞終了` ", "> `歌詞` ")):
            kept.append(line)
        elif line.startswith("## ショット "):
            kept.extend((line, "* 未計画"))
        elif not line.strip() and kept and kept[-1] != "":
            kept.append("")
    result = "\n".join(kept).strip() + "\n"
    parse_template_emd(result)
    return result


class CachedChat:
    def __init__(self) -> None:
        self.calls = 0
        self.lifecycle = None
        if BACKEND == "direct":
            self.lifecycle = LlamaCppLifecycle()
            self.lifecycle.ensure_loaded(MODEL_PATH, LlamaRuntimeConfig(
                n_ctx=24576, max_tokens=8192, temperature=0.2,
                top_p=0.9, repetition_penalty=1.05, gpu_layers=-1,
                n_batch=512, keep_model_loaded=False, seed=2,
            ))
        elif BACKEND != "api":
            raise ValueError(f"Unsupported backend: {BACKEND}")

    def close(self) -> None:
        if self.lifecycle is not None:
            self.lifecycle.clear()

    def complete(self, *, kind: str, system: str, user: str,
                 max_tokens: int, temperature: float,
                 grammar: str | None = None) -> str:
        request = {
            "backend": BACKEND,
            "model": MODEL,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            "top_p": 0.9,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if grammar is not None:
            request["grammar"] = grammar
        key = hashlib.sha256(json.dumps(request, ensure_ascii=False,
                                         sort_keys=True).encode("utf-8")).hexdigest()
        path = DEST / "llm_calls" / f"{kind}-{key[:20]}.json"
        self.calls += 1
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            print(f"[{self.calls}] {kind} cache hit chars={len(saved['response'])}", flush=True)
            return saved["response"]
        headers = {"Content-Type": "application/json"}
        if token := os.environ.get("GEMMA_FULL_API_KEY"):
            headers["Authorization"] = f"Bearer {token}"
        started = time.monotonic()
        print(f"[{self.calls}] {kind} input_chars={len(system) + len(user)}", flush=True)
        if self.lifecycle is not None:
            content = self.lifecycle.complete_chat(
                request["messages"],
                LlamaRuntimeConfig(n_ctx=24576, max_tokens=max_tokens,
                                   temperature=temperature, top_p=0.9,
                                   repetition_penalty=1.05, gpu_layers=-1,
                                   n_batch=512, keep_model_loaded=False, seed=2),
                grammar=grammar,
            )
            finish_reason = "direct"
            usage = None
        else:
            if grammar is not None:
                raise ValueError("The research API backend cannot enforce the Planner grammar")
            http_request = Request(
                f"{BASE}/v1/chat/completions",
                data=json.dumps({key: value for key, value in request.items() if key != "backend"},
                                ensure_ascii=False).encode("utf-8"),
                headers=headers, method="POST",
            )
            try:
                with urlopen(http_request, timeout=1800) as response:
                    raw = json.load(response)
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                print(f"[{self.calls}] {kind} HTTP {exc.code}: {detail[:1000]}", flush=True)
                raise
            choice = raw["choices"][0]
            content = choice["message"].get("content") or ""
            finish_reason = choice.get("finish_reason")
            usage = raw.get("usage")
        saved = {
            "request": request,
            "response": content,
            "finish_reason": finish_reason,
            "usage": usage,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        write_json(path, saved)
        print(f"[{self.calls}] {kind} done chars={len(content)} "
              f"seconds={saved['elapsed_seconds']} finish={saved['finish_reason']}", flush=True)
        if not content.strip():
            raise RuntimeError(f"{kind} returned no visible output; finish={saved['finish_reason']}")
        return content


class PlannerBackend:
    def __init__(self, chat: CachedChat) -> None:
        self.chat = chat

    def complete_planner(self, *, task: str, system_prompt: str, payload: str,
                         config: LlamaRuntimeConfig, interrupt_callback=None) -> str:
        # Gemma 4 spends tokens in private reasoning before visible output.
        limit = 8192 if BACKEND == "api" else {
            "scene-author-event": 1024,
            "scene-author-performance": 2048,
            "scene-author-camera": 1536,
        }.get(task, config.max_tokens)
        return self.chat.complete(kind=task, system=system_prompt, user=payload,
                                  max_tokens=limit, temperature=config.temperature)


class GemmaTranslator:
    SYSTEM = (
        "Translate the Japanese text into faithful, natural, concise English for a "
        "text-to-video prompt. Preserve the specific action, subject, camera movement, "
        "temporal order, spatial relations, emotion, and all opaque placeholders. "
        "Do not add or remove events. Return only JSON with one key, translations, "
        "whose value is an array of exactly the requested number of English strings "
        "in the same order. Do not add explanations or markdown."
    )

    def __init__(self, chat: CachedChat) -> None:
        self.chat = chat

    def translate(self, units: tuple[str, ...]) -> tuple[str, ...]:
        # Compiler isolates each EMD field; keep the same semantic boundary.
        # Protected names can divide one field into several fragments. Asking
        # for one fragment at a time prevents omissions and reorderings.
        if len(units) > 1:
            return tuple(self.translate((unit,))[0] for unit in units)
        answer = self.chat.complete(
            kind="translation", system=self.SYSTEM,
            user=json.dumps({"texts": list(units)}, ensure_ascii=False),
            max_tokens=max(1024, min(4096, 512 + len("".join(units)) * 2)),
            temperature=0.1,
        )
        match = re.search(r"\{\s*\"translations\"\s*:\s*\[.*?\]\s*\}",
                          answer, re.DOTALL)
        if match is None:
            raise ValueError(f"Gemma translation JSON missing: {answer[:200]!r}")
        value = json.loads(match.group())["translations"]
        if len(value) != len(units) or any(not isinstance(v, str) or not v.strip()
                                           for v in value):
            raise ValueError("Gemma translation cardinality/content mismatch")
        if any(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", v) for v in value):
            raise ValueError(f"Gemma translation retained Japanese: {value!r}")
        return tuple(value)


def plan() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    template = template_from_existing_emd(SOURCE_EMD.read_text(encoding="utf-8"))
    (DEST / "template.md").write_text(template, encoding="utf-8")
    concept = (FIXTURE / "concept.md").read_text(encoding="utf-8")
    scene = (FIXTURE / "scene.md").read_text(encoding="utf-8")
    direction_path = FIXTURE / "direction.json"
    direction = DirectionArtifact.from_dict(json.loads(direction_path.read_text(encoding="utf-8")))
    write_json(DEST / "input-manifest.json", {
        "source_emd": str(SOURCE_EMD), "source_emd_sha256": sha256(SOURCE_EMD),
        "concept": str(FIXTURE / "concept.md"),
        "concept_sha256": sha256(FIXTURE / "concept.md"),
        "scene": str(FIXTURE / "scene.md"),
        "scene_sha256": sha256(FIXTURE / "scene.md"),
        "direction": str(direction_path), "direction_sha256": sha256(direction_path),
        "template_sha256": sha256(DEST / "template.md"),
        "planner_model": str(MODEL_PATH) if BACKEND == "direct" else MODEL,
        "backend": BACKEND, "lip_sync_mode": "audio_reference",
    })
    config = LlamaRuntimeConfig(n_ctx=24576, max_tokens=4096,
                                temperature=0.2, top_p=0.9,
                                repetition_penalty=1.05, seed=2)
    chat = CachedChat()
    result = plan_timeline(
        PlannerBackend(chat), template_emd=template, concept_emd=concept,
        scene_emd=scene, direction=direction,
        lip_sync_mode="audio_reference", lip_sync_target="サブジェクト1",
        lip_sync_audio_slot=1, scenes_per_batch=1,
        system_prompts=_system_prompts(), runtime_config=config,
    )
    write_json(DEST / "planner-summary.json", {
        "complete": result.complete,
        "missing": [list(item) for item in result.missing],
        "llm_calls": chat.calls,
        "content": result.content.to_dict() if result.content else None,
    })
    if not result.complete:
        raise RuntimeError(f"Planner incomplete: {result.missing[:20]}")
    (DEST / "planned.md").write_text(result.emd.text, encoding="utf-8")
    print(f"Planned {len(parse_template_emd(template).scenes)} scenes; "
          f"EMD={DEST / 'planned.md'}", flush=True)


def compile_plan() -> None:
    source = (DEST / "planned.md").read_text(encoding="utf-8")
    chat = CachedChat()
    result = compile_ref2va(source, GemmaTranslator(chat), steps=8)
    (DEST / "plan.json").write_text(result.plan_json(), encoding="utf-8")
    write_json(DEST / "compile-summary.json", {
        "translator_model": MODEL, "llm_calls": chat.calls,
        "shot_count": len(result.plan["shots"]),
        "required_references": result.required_references.to_dict(),
    })
    print(f"Compiled {len(result.plan['shots'])} shots; "
          f"Plan={DEST / 'plan.json'}", flush=True)


def prepare_video(variant: str) -> None:
    plan_text = (DEST / "plan.json").read_text(encoding="utf-8")
    parsed = json.loads(plan_text)
    if len(parsed["shots"]) != 16:
        raise ValueError("Expected exactly 16 Scene Plan entries")
    graph = copy.deepcopy(json.loads(SOURCE_GRAPH.read_text(encoding="utf-8")))
    if graph["48"]["class_type"] != "MVDirectorSceneDebugSplitter":
        raise ValueError("Source graph is not the audio-reference workflow")
    if graph["24"]["inputs"]["plan_json_input"] != ["48", 0]:
        raise ValueError("Unexpected Plan connection")
    for node in ("24", "37", "48"):
        graph[node]["inputs"]["plan_json"] = plan_text
    graph["48"]["inputs"].update({
        "enable": True, "scene_start": 1,
        "scene_length": 1 if variant == "pilot" else 16,
    })
    graph["47"]["inputs"].update({
        "aspect_ratio": "16:9 (Widescreen)",
        "megapixels": 0.9, "multiple": 32,
    })
    run_name = f"gemma4_31b_full_09mp_20260925_{variant}"
    graph["24"]["inputs"]["run_name"] = run_name
    graph["21"]["inputs"]["filename"] = run_name
    write_json(DEST / f"{variant}-api-prompt.json", graph)
    write_json(DEST / f"{variant}-render-manifest.json", {
        "run_name": run_name, "source_graph": str(SOURCE_GRAPH),
        "source_graph_sha256": sha256(SOURCE_GRAPH),
        "plan_sha256": sha256(DEST / "plan.json"),
        "scene_start": 1, "scene_length": 1 if variant == "pilot" else 16,
        "megapixels_requested": 0.9,
        "model": graph["59"]["inputs"],
    })
    print(f"Prepared {variant}: {run_name}", flush=True)


def submit_video(variant: str) -> None:
    path = DEST / f"{variant}-api-prompt.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    run_name = graph["24"]["inputs"]["run_name"]
    request = Request(
        "http://127.0.0.1:8188/prompt",
        data=json.dumps({"prompt": graph, "client_id": run_name},
                        ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    write_json(DEST / f"{variant}-submission-response.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("plan", "compile", "prepare_video", "submit_video"))
    parser.add_argument("--variant", choices=("pilot", "full"))
    args = parser.parse_args()
    if args.phase == "plan":
        plan()
    elif args.phase == "compile":
        compile_plan()
    elif args.variant is None:
        parser.error("video phase requires --variant")
    elif args.phase == "prepare_video":
        prepare_video(args.variant)
    else:
        submit_video(args.variant)
