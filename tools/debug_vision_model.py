"""Exercise subject/scene Vision through the production node, without H3."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodes.node_image_to_subject_emd import node as vision_node
from core.vision.model_discovery import resolve_vision_model_pair


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, default=ROOT / "workflows/01_plan_compiler_context_loop.json")
    parser.add_argument("--gguf-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    if destination.is_relative_to(ROOT):
        raise ValueError("Research output must be outside the project")
    destination.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(destination / "run.log", encoding="utf-8")
    ])
    import numpy as np
    from PIL import Image
    import torch
    workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
    def resolve(selection: str):
        return resolve_vision_model_pair(selection, {"models": args.gguf_root})
    results = []
    for item in workflow["nodes"]:
        if item["type"] != "MVDirectorImageToSubjectEMD":
            continue
        names = ["model_name", "analysis_profile", "subject_hint", "additional_instruction", "hint_mode",
                 "hint_conflict", "picture_reference_mode", "concept_type", "picture_index", "analysis_max_edge",
                 "max_tokens", "temperature", "top_p", "repetition_penalty", "gpu_layers", "n_batch", "n_ctx",
                 "flash_attn", "kv_cache_type", "op_offload", "keep_model_loaded", "seed"]
        inputs = dict(zip(names, item["widgets_values"][:22], strict=True))
        inputs.update(model_name=args.model, seed=42, keep_model_loaded=False, cache_mode="disabled")
        link = next(link for link in workflow["links"] if link[3] == item["id"] and link[4] == 0)
        image_node = next(n for n in workflow["nodes"] if n["id"] == link[1])
        image_path = args.input_dir / image_node["widgets_values"][0]
        with Image.open(image_path) as image:
            pixels = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
        inputs["image"] = torch.from_numpy(pixels).unsqueeze(0)
        profile = inputs["analysis_profile"]
        saved_inputs = {k: v for k, v in inputs.items() if k != "image"}
        saved_inputs["image_path"] = str(image_path)
        (destination / f"{profile}-inputs.json").write_text(json.dumps(saved_inputs, ensure_ascii=False, indent=2), encoding="utf-8")
        instance = vision_node.MVDirectorImageToSubjectEMD()
        real_complete = instance._backend.complete_observation
        calls = []
        def record(**kwargs):
            response = real_complete(**kwargs)
            calls.append({"system_prompt": kwargs["system_prompt"], "request": kwargs["request"], "response": response})
            (destination / f"{profile}-calls.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8")
            return response
        instance._backend.complete_observation = record
        started = time.monotonic()
        try:
            with patch.object(vision_node, "resolve_comfy_vision_model", resolve):
                output = instance.image_to_subject_emd(**inputs)
            fragment, bindings, _, observations = output["result"]
            (destination / f"{profile}.md").write_text(fragment, encoding="utf-8")
            (destination / f"{profile}-observations.json").write_text(observations, encoding="utf-8")
            results.append({"profile": profile, "elapsed_seconds": time.monotonic()-started,
                            "calls": len(calls), "status": output["ui"]["status"],
                            "pair": resolve(args.model).signature()})
            (destination / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
        finally:
            instance._backend.clear()


if __name__ == "__main__":
    main()
