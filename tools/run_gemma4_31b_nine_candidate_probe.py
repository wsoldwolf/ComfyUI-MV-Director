"""Probe the current nine staging candidates on contiguous Scenes 3-9.

This is an isolated research runner. It does not alter production workflows.
The template, references, model, sampling, and H3 graph are frozen inputs.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from tools import run_gemma4_31b_full as base
from tools.generate_workflows import DEFAULT_USER_PROMPT
from core.artifacts import DirectionArtifact
from core.compiler import compile_ref2va
from core.inference import LlamaRuntimeConfig
from core.planner import plan_timeline
from core.planner.template import parse_template_emd
from nodes.node_timeline_planner.node import _system_prompts


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs/assets/research/gemma4-31b-nine-candidate-h3-2026-09-25"
GRAPH = ROOT / "docs/assets/research/gemma4-31b-pipeline-phases-2026-09-25/p5-context-04mp-baseline-api-prompt.json"
SOURCE = ROOT / "docs/assets/research/scene-composition-full-sequence-2026-09-23"
TEMPLATE = ROOT / "docs/assets/research/gemma4-31b-full-2026-09-25/template.md"
RUN_NAME = "gemma31b_nine_candidates_s3_9_04mp_20260925"
base.DEST = DEST


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_direction() -> DirectionArtifact:
    source = DirectionArtifact.from_dict(json.loads((SOURCE / "direction.json").read_text(encoding="utf-8")))
    candidates = tuple(line[2:] for line in DEFAULT_USER_PROMPT.splitlines() if line.startswith("* "))
    if len(candidates) != 9 or candidates[:2] != source.staging_candidates[:2] or candidates[4:] != source.staging_candidates[2:]:
        raise ValueError("Current workflow candidates differ from the frozen comparison")
    direction = replace(
        source,
        staging_candidates=candidates,
        provenance=tuple(record for record in source.provenance
                         if not (record.target or "").startswith("staging_candidates[")),
    )
    direction.validate()
    return direction


def prepare() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    template = TEMPLATE.read_text(encoding="utf-8")
    parsed = parse_template_emd(template)
    if len(parsed.scenes) != 16:
        raise ValueError("Frozen template no longer has 16 Scenes")
    direction = candidate_direction()
    (DEST / "direction.json").write_text(direction.to_json(), encoding="utf-8")
    base.write_json(DEST / "source-manifest.json", {
        "purpose": "Nine-candidate Gemma 4 31B / H3 Context Loop Scene 3-9 probe",
        "template": str(TEMPLATE), "template_sha256": digest(TEMPLATE),
        "concept": str(SOURCE / "concept.md"), "concept_sha256": digest(SOURCE / "concept.md"),
        "scene": str(SOURCE / "scene.md"), "scene_sha256": digest(SOURCE / "scene.md"),
        "direction_sha256": digest(DEST / "direction.json"),
        "candidate_count": len(direction.staging_candidates),
        "graph": str(GRAPH), "graph_sha256": digest(GRAPH),
        "planner_model": str(base.MODEL_PATH), "lip_sync_mode": "context_loop",
        "scene_range": [3, 9], "h3_megapixels": 0.4, "seed": 42,
    })
    print("Prepared 9 candidates, Scenes 3-9, Context Loop", flush=True)


def plan() -> None:
    prepare()
    config = LlamaRuntimeConfig(
        n_ctx=24576, max_tokens=4096, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, seed=2,
    )
    chat = base.CachedChat()
    try:
        result = plan_timeline(
            base.PlannerBackend(chat), template_emd=TEMPLATE.read_text(encoding="utf-8"),
            concept_emd=(SOURCE / "concept.md").read_text(encoding="utf-8"),
            scene_emd=(SOURCE / "scene.md").read_text(encoding="utf-8"),
            direction=candidate_direction(), lip_sync_mode="context_loop",
            lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            scenes_per_batch=1, system_prompts=_system_prompts(), runtime_config=config,
        )
    finally:
        chat.close()
    base.write_json(DEST / "planner-summary.json", {
        "complete": result.complete,
        "missing": [list(item) for item in result.missing],
        "llm_calls": chat.calls,
        "content": result.content.to_dict() if result.content else None,
    })
    if not result.complete:
        raise RuntimeError(f"31B Planner incomplete: {result.missing[:20]}")
    (DEST / "planned.md").write_text(result.emd.text, encoding="utf-8")
    print(f"Planned 16 Scenes; LLM calls={chat.calls}", flush=True)


def compile_plan() -> None:
    chat = base.CachedChat()
    try:
        result = compile_ref2va(
            (DEST / "planned.md").read_text(encoding="utf-8"),
            base.GemmaTranslator(chat), steps=8,
        )
    finally:
        chat.close()
    (DEST / "plan.json").write_text(result.plan_json(), encoding="utf-8")
    base.write_json(DEST / "compile-summary.json", {
        "shot_count": len(result.plan["shots"]), "llm_calls": chat.calls,
        "required_references": result.required_references.to_dict(),
    })
    print(f"Compiled {len(result.plan['shots'])} Scene entries", flush=True)


def prepare_video() -> None:
    plan_path = DEST / "plan.json"
    plan_text = plan_path.read_text(encoding="utf-8")
    plan = json.loads(plan_text)
    if len(plan["shots"]) != 16:
        raise ValueError("Expected 16 Scene entries")
    graph = copy.deepcopy(json.loads(GRAPH.read_text(encoding="utf-8")))
    if graph["48"]["class_type"] != "MVDirectorSceneDebugSplitter":
        raise ValueError("Context Loop source graph changed")
    for node in ("24", "37", "48"):
        graph[node]["inputs"]["plan_json"] = plan_text
    graph["48"]["inputs"].update({"enable": True, "scene_start": 3, "scene_length": 7})
    graph["47"]["inputs"].update({"megapixels": 0.4, "aspect_ratio": "16:9 (Widescreen)", "multiple": 32})
    graph["49"]["inputs"].update({"mode": "fixed", "seed": 42})
    graph["24"]["inputs"]["run_name"] = RUN_NAME
    graph["21"]["inputs"]["filename"] = RUN_NAME
    path = DEST / "h3-api-prompt.json"
    base.write_json(path, graph)
    base.write_json(DEST / "h3-manifest.json", {
        "plan_sha256": digest(plan_path), "graph_sha256": digest(GRAPH),
        "request_sha256": digest(path), "run_name": RUN_NAME,
        "scenes": [3, 4, 5, 6, 7, 8, 9], "megapixels": 0.4, "seed": 42,
        "model": graph["59"]["inputs"],
    })
    print(f"Prepared Context Loop H3 graph for Scenes 3-9: {path}", flush=True)


def prepare_resume_video(start_clip: int = 2) -> None:
    if not 2 <= start_clip <= 7:
        raise ValueError("Resume clip must be within 2..7")
    graph = json.loads((DEST / "h3-api-prompt.json").read_text(encoding="utf-8"))
    for node in ("7", "29"):
        graph[node]["inputs"]["start_clip"] = start_clip
        graph[node]["inputs"]["verify_resume_history"] = True
    graph["23"]["inputs"]["between_scene_cleanup"] = "fresh_scene"
    base.write_json(DEST / f"h3-resume-clip{start_clip}-api-prompt.json", graph)
    print(f"Prepared checkpoint-verified resume from clip {start_clip}/7", flush=True)


def submit(*, resume_clip: int | None = None) -> None:
    name = f"h3-resume-clip{resume_clip}-api-prompt.json" if resume_clip else "h3-api-prompt.json"
    graph = json.loads((DEST / name).read_text(encoding="utf-8"))
    payload = json.dumps({"prompt": graph, "client_id": RUN_NAME}, ensure_ascii=False).encode("utf-8")
    request = Request("http://127.0.0.1:8188/prompt", data=payload,
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    base.write_json(DEST / (f"h3-resume-clip{resume_clip}-submission.json" if resume_clip else "h3-submission.json"), result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "plan", "compile", "prepare_video", "submit",
                                          "prepare_resume_video", "submit_resume"))
    parser.add_argument("--start-clip", type=int, default=2)
    args = parser.parse_args()
    phase = args.phase
    {"prepare": prepare, "plan": plan, "compile": compile_plan,
     "prepare_video": prepare_video, "submit": submit,
     "prepare_resume_video": lambda: prepare_resume_video(args.start_clip),
     "submit_resume": lambda: submit(resume_clip=args.start_clip)}[phase]()
