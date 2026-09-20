"""Small real-model diagnostic, not a full-song or video-quality benchmark.

Run with ComfyUI's Python. Outputs include exact inputs, LLM replies and
field-level translation evidence. No model download or video job is implicit.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.artifacts import DirectionArtifact
from core.compiler import LlamaPromptTranslator, compile_ref2va
from core.direction.profiles import MOTION_PROFILES, CAMERA_PROFILES
from core.inference import LlamaRuntimeConfig, LlamaCppLifecycle, SuccessCache
from core.planner import plan_timeline
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts
from nodes.node_emd_compiler.node import _system_prompt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO)
    lyrics = ("この想いをあなたへ届けたい", "昨日の願いが苔に還る", "宙を舞う狐火")
    template = "\n".join(
        f"> `シーン` {i+1}\n# シーン 00:{i*10:02d}.000 --> 00:{(i+1)*10:02d}.000"
        + (" 継続" if i else "") + "\n* `H3長` 243\n"
        + f"> `セクション` CHORUS\n> `歌詞` {lyric}\n## ショット 00:{i*10:02d}.000\n* 未計画"
        for i, lyric in enumerate(lyrics)
    )
    concept = "# サブジェクト\n* `画像1` 金髪、狐耳、白と赤の衣装の女性。\n"
    direction = DirectionArtifact(
        motion_profile_id="anime_emotional_mv", camera_profile_id="anime_emotional_mv",
        motion_direction=(MOTION_PROFILES["anime_emotional_mv"],),
        camera_direction=(CAMERA_PROFILES["anime_emotional_mv"],),
        time_lighting_direction=("夜間、月明かり。",),
    )
    config = LlamaRuntimeConfig(n_ctx=16384, max_tokens=4096, temperature=0.2,
                               seed=args.seed, gpu_layers=-1, n_batch=512,
                               keep_model_loaded=False)
    lifecycle = LlamaCppLifecycle()
    backend = _LlamaPlannerBackend(lifecycle)
    translator = None
    started = time.perf_counter()
    record = {"fixture": "three-scene synthetic diagnostic, not the full original song",
              "model": str(args.model), "runtime": config.to_dict(),
              "template": template, "concept": concept, "complete": False}
    try:
        lifecycle.ensure_loaded(args.model, config)
        prompts = _system_prompts()
        record["prompt_sha256"] = {key: hashlib.sha256(value.encode()).hexdigest()
                                   for key, value in prompts.items()}
        result = plan_timeline(backend, template_emd=template, concept_emd=concept,
            direction=direction, lip_sync_mode="context_loop", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=1, system_prompts=prompts,
            runtime_config=config)
        record["planner_seconds"] = time.perf_counter() - started
        record["missing"] = result.missing
        if result.content:
            record["content"] = asdict(result.content)
        (args.output / "generated.emd.md").write_text(result.emd.text, encoding="utf-8")
        if result.complete:
            translator = LlamaPromptTranslator(lifecycle, system_prompt=_system_prompt(), runtime_config=config)
            compiled = compile_ref2va(result.emd.text, translator, steps=8)
            (args.output / "plan.json").write_text(compiled.plan_json(), encoding="utf-8")
            # Exercise the same strict serialization boundary as the node.
            # json.dumps(evidence) alone silently accepts tuples and misses it.
            SuccessCache(args.output / "compiler-cache").put_success(
                hashlib.sha256(result.emd.text.encode()).hexdigest(),
                {"plan_json": compiled.plan_json(),
                 "required_references": compiled.required_references.to_dict(),
                 "translation_trace": translator.translation_trace},
            )
            record["complete"] = True
    except Exception:
        record["error"] = traceback.format_exc()
        logging.exception("diagnostic failed")
    finally:
        record["seconds"] = time.perf_counter() - started
        record["trace"] = backend.trace
        if translator:
            record["translation_trace"] = translator.translation_trace
            record["translation_batches"] = translator.batch_count
        lifecycle.clear()
        (args.output / "evidence.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: record.get(key) for key in ("complete", "seconds", "missing", "error")}))
    return 0 if record["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
