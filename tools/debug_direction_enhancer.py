"""Run the real Enhancer with saved Vision fragments and workflow settings.

No Vision or H3 generation is performed. Outputs must live outside the repo.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodes.node_direction_enhancer import node as direction_node
from nodes.common.gguf_discovery import resolve_comfy_gguf_model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, default=ROOT / "workflows/01_plan_compiler_context_loop.json")
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--concept", type=Path, required=True)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    if destination.is_relative_to(ROOT):
        raise ValueError("Research output must be outside the project")
    destination.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(destination / "run.log", encoding="utf-8")
    ])
    workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
    item = next(n for n in workflow["nodes"] if n["type"] == "MVDirectorDirectionEnhancer")
    values = item["widgets_values"]
    names = ["retention_policy", "user_request", "style_profile", "motion_profile", "camera_profile",
             "model_name", "chat_format", "max_tokens", "temperature", "top_p", "repetition_penalty",
             "gpu_layers", "n_batch", "n_ctx", "flash_attn", "kv_cache_type", "op_offload", "keep_model_loaded", "seed"]
    inputs = dict(zip(names, values[:19], strict=True))
    inputs["user_request"] = next(n for n in workflow["nodes"] if n.get("title") == "ユーザープロンプト")["widgets_values"][0]
    inputs["seed"] = next(n for n in workflow["nodes"] if n["type"] == "MVDirectorSeed32")["widgets_values"][1]
    inputs.update(cache_mode="disabled", keep_model_loaded=False,
                  concept_emd=args.concept.read_text(encoding="utf-8"),
                  scene_emd=args.scene.read_text(encoding="utf-8"))
    (destination / "inputs.json").write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding="utf-8")
    folder_paths = SimpleNamespace(models_dir=str(args.models_dir), folder_names_and_paths={})
    def resolve(selection: str):
        return resolve_comfy_gguf_model(selection, folder_paths_module=folder_paths)
    instance = direction_node.MVDirectorDirectionEnhancer()
    real_complete = instance._backend.complete_direction
    calls = []
    def record(**kwargs):
        started = time.monotonic()
        response = real_complete(**kwargs)
        calls.append({"system_prompt": kwargs["system_prompt"], "payload": kwargs["payload"],
                      "response": response, "elapsed_seconds": time.monotonic() - started})
        (destination / "calls.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8")
        return response
    instance._backend.complete_direction = record
    started = time.monotonic()
    try:
        with patch.object(direction_node, "resolve_comfy_gguf_model", resolve):
            result, preview, status = instance.enhance(**inputs)
        (destination / "direction.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        (destination / "preview.md").write_text(preview, encoding="utf-8")
        summary = {"status": status, "elapsed_seconds": time.monotonic() - started,
                   "model": str(resolve(inputs["model_name"]).path), "calls": len(calls),
                   "vision_inputs": "saved fragments; Vision was not re-run",
                   "concept_source": str(args.concept.resolve()), "scene_source": str(args.scene.resolve())}
        (destination / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    finally:
        instance._lifecycle.clear()


if __name__ == "__main__":
    main()
