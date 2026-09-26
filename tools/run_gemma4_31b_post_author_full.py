"""Replay the frozen 16-Scene song with the opt-in post-author motion profile.

Only the Planner is run. Research artifacts are written outside this repository.
The exact request/response pairs are cached to allow a failed run to resume.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from core.artifacts import DirectionArtifact
from core.inference import LlamaRuntimeConfig
from core.planner import plan_timeline
from core.planner.scene_author import build_scene_author_grammar, build_composition_choice_grammar
from core.planner.template import parse_template_emd
from nodes.node_timeline_planner.node import _system_prompts
from tools import run_gemma4_31b_full as base


RESEARCH = Path(r"E:\ComfyUI\projects\ComfyUI-MV-Director-research\docs\assets\research")
SOURCE = RESEARCH / "scene-composition-full-sequence-2026-09-23"
TEMPLATE = RESEARCH / "gemma4-31b-full-2026-09-25" / "template.md"
DIRECTION = RESEARCH / "gemma4-31b-nine-candidate-h3-2026-09-25" / "direction.json"
DEFAULT_OUTPUT = RESEARCH / "gemma4-31b-post-author-full-2026-09-25"


class ConstrainedPlannerBackend:
    """Match the production Scene Author line grammar and token ceilings."""

    def __init__(self, chat: base.CachedChat) -> None:
        self.chat = chat

    def complete_planner(self, *, task: str, system_prompt: str, payload: str,
                         config: LlamaRuntimeConfig, interrupt_callback=None) -> str:
        slots = json.loads(payload)["slots"]
        if task == "scene-author-composition-choice":
            request = json.loads(payload)
            return self.chat.complete(
                kind=task, system=system_prompt, user=f"/no_think\n{payload}",
                max_tokens=32, temperature=config.temperature,
                grammar=build_composition_choice_grammar(len(request["candidates"])),
            )
        ceiling = {
            "scene-author-event": min(1536, max(512, 256 * len(slots))),
            "scene-author-performance": 1536,
            "scene-author-camera": 1024,
        }[task]
        return self.chat.complete(
            kind=task, system=system_prompt, user=f"/no_think\n{payload}",
            max_tokens=min(config.max_tokens, ceiling),
            temperature=config.temperature,
            grammar=build_scene_author_grammar(task, slots),
        )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    base.DEST = output

    template = TEMPLATE.read_text(encoding="utf-8")
    if len(parse_template_emd(template).scenes) != 16:
        raise ValueError("Frozen template must contain 16 Scenes")
    direction = DirectionArtifact.from_dict(json.loads(DIRECTION.read_text(encoding="utf-8")))
    if direction.motion_profile_id != "anime_scene_composed_mv":
        raise ValueError("Direction does not select the post-author profile")
    prompts = _system_prompts()
    manifest = {
        "purpose": "Full-song Gemma 4 31B post-author Scene Author with profile-gated composition reselection",
        "template": str(TEMPLATE), "template_sha256": _digest(TEMPLATE),
        "concept": str(SOURCE / "concept.md"),
        "concept_sha256": _digest(SOURCE / "concept.md"),
        "scene": str(SOURCE / "scene.md"),
        "scene_sha256": _digest(SOURCE / "scene.md"),
        "direction": str(DIRECTION), "direction_sha256": _digest(DIRECTION),
        "planner_model": str(base.MODEL_PATH),
        "motion_profile_id": direction.motion_profile_id,
        "lip_sync_mode": "context_loop",
        "scene_count": 16,
        "system_prompt_sha256": {
            stage: hashlib.sha256(prompts[f"scene-author-{stage}"].encode("utf-8")).hexdigest()
            for stage in ("event", "performance", "camera", "composition-choice")
        },
        "sampling": {"seed": 2, "temperature": 0.2, "top_p": 0.9, "n_ctx": 24576},
        "line_grammar": "scene_author_v1 + composition_choice_v1",
    }
    base.write_json(output / "source-manifest.json", manifest)
    config = LlamaRuntimeConfig(
        n_ctx=24576, max_tokens=4096, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, seed=2,
    )
    chat = base.CachedChat()
    try:
        result = plan_timeline(
            ConstrainedPlannerBackend(chat), template_emd=template,
            concept_emd=(SOURCE / "concept.md").read_text(encoding="utf-8"),
            scene_emd=(SOURCE / "scene.md").read_text(encoding="utf-8"),
            direction=direction, lip_sync_mode="context_loop",
            lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            scenes_per_batch=1, system_prompts=prompts, runtime_config=config,
        )
    finally:
        chat.close()
    base.write_json(output / "planner-summary.json", {
        "complete": result.complete,
        "missing": [list(item) for item in result.missing],
        "llm_calls": chat.calls,
        "content": result.content.to_dict() if result.content else None,
    })
    if not result.complete:
        raise RuntimeError(f"Planner incomplete: {result.missing[:20]}")
    (output / "planned.md").write_text(result.emd.text, encoding="utf-8")
    print(f"Complete: 16 Scenes, {chat.calls} calls; {output / 'planned.md'}", flush=True)


if __name__ == "__main__":
    main()
