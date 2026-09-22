"""Re-plan a saved full EMD with the opt-in choreography Motion profile.

Only timing, lyric and Shot boundaries are reused. Saved creative Action and
Camera prose is never sent to the Planner. The original EMD is not modified.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.artifacts import DirectionArtifact
from core.compiler import LlamaPromptTranslator, compile_ref2va
from core.direction.profiles import CAMERA_PROFILES, MOTION_PROFILES, STYLE_PROFILES
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner import normalize_concept_emd, normalize_scene_emd, parse_template_emd, plan_timeline
from nodes.node_emd_compiler.node import _system_prompt as compiler_prompt
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts


_TEMPLATE_RECORDS = {"シーン", "セクション", "歌詞開始", "歌詞終了", "歌詞"}


def source_fragments(source: str) -> tuple[str, str, str, dict[str, tuple[str, ...]]]:
    """Extract provenance-bearing input only, discarding old Action/Camera."""
    lines = source.replace("\r\n", "\n").splitlines()
    subject_at = lines.index("# サブジェクト")
    scene_at = lines.index("# シーン設定")
    common_at = lines.index("# 共通プロンプト")
    first_scene = next(index for index, line in enumerate(lines)
                       if line.startswith("> `シーン` "))
    concept = "\n".join(lines[subject_at:scene_at]).strip() + "\n"
    scene = "\n".join(lines[scene_at:common_at]).strip() + "\n"
    common: dict[str, list[str]] = {}
    section = ""
    for line in lines[common_at + 1:first_scene]:
        if line.startswith("## "):
            section = line[3:]
        elif line.startswith("* ") and section:
            common.setdefault(section, []).append(line[2:])
    template_lines: list[str] = []
    for line in lines[first_scene:]:
        if line.startswith("# シーン ") or line.startswith("* `H3長` "):
            template_lines.append(line)
        elif line.startswith("> `"):
            label = line.split("`", 2)[1]
            if label in _TEMPLATE_RECORDS:
                template_lines.append(line)
        elif line.startswith("## ショット "):
            template_lines.extend((line, "* 未計画"))
    template = "\n".join(template_lines).strip() + "\n"
    normalize_concept_emd(concept)
    normalize_scene_emd(scene)
    parse_template_emd(template)
    return concept, scene, template, {key: tuple(value) for key, value in common.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-emd", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-compiler", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.source_emd.read_text(encoding="utf-8")
    concept, scene, template, common = source_fragments(source)
    direction = DirectionArtifact(
        style_profile_id="anime_emotional_mv",
        motion_profile_id="anime_choreography_mv",
        camera_profile_id="anime_emotional_mv",
        style_direction=(STYLE_PROFILES["anime_emotional_mv"],),
        motion_direction=(MOTION_PROFILES["anime_choreography_mv"],),
        camera_direction=(CAMERA_PROFILES["anime_emotional_mv"],),
        environment_direction=common.get("環境", ()),
        time_lighting_direction=common.get("時間・照明", ()),
        other_direction=common.get("その他", ()),
    )
    config = LlamaRuntimeConfig(
        n_ctx=16384, max_tokens=4096, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, seed=args.seed, gpu_layers=-1,
        n_batch=512, keep_model_loaded=False,
    )
    lifecycle = LlamaCppLifecycle()
    backend = _LlamaPlannerBackend(lifecycle)
    record: dict[str, object] = {
        "source_emd": str(args.source_emd.resolve()),
        "model": str(args.model.resolve()),
        "motion_profile": "anime_choreography_mv",
        "runtime": config.to_dict(),
        "source_scene_count": len(parse_template_emd(template).scenes),
        "complete": False,
    }
    started = time.perf_counter()
    translator = None
    try:
        lifecycle.ensure_loaded(args.model, config)
        result = plan_timeline(
            backend, template_emd=template, concept_emd=concept,
            direction=direction, scene_emd=scene,
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=3,
            system_prompts=_system_prompts(), runtime_config=config,
        )
        record["planner_seconds"] = round(time.perf_counter() - started, 3)
        record["planner_missing"] = result.missing
        record["planner_complete"] = result.complete
        if result.content:
            record["planner_content"] = asdict(result.content)
        if result.emd.text:
            (args.output / "generated.emd.md").write_text(result.emd.text, encoding="utf-8")
        if not result.complete:
            raise RuntimeError("Planner did not produce a complete EMD")
        if not args.skip_compiler:
            translator = LlamaPromptTranslator(
                lifecycle, system_prompt=compiler_prompt(), runtime_config=config,
            )
            compiled = compile_ref2va(result.emd.text, translator, steps=8)
            plan_json = compiled.plan_json()
            (args.output / "plan.json").write_text(plan_json, encoding="utf-8")
            (args.output / "context_loop_plan_choreography.txt").write_text(
                plan_json, encoding="utf-8",
            )
            record["compiler_batches"] = translator.batch_count
        record["complete"] = True
    except Exception:
        record["error"] = traceback.format_exc()
        logging.exception("full choreography experiment failed")
    finally:
        record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        record["trace"] = backend.trace
        if translator:
            record["translation_trace"] = translator.translation_trace
        lifecycle.clear()
        (args.output / "evidence.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    print(json.dumps({key: record.get(key) for key in
                      ("complete", "planner_complete", "source_scene_count",
                       "elapsed_seconds", "planner_missing", "error")}, ensure_ascii=False))
    return 0 if record["complete"] else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
