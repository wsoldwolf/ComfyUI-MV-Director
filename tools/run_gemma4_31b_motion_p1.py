"""Compare the archived full-song and successful short Performance contracts.

Preparation is CPU-only. Inference runs only with --infer and never modifies a
production workflow, prompt, profile, or the archived baseline response.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from tools.run_gemma4_31b_pipeline_phases import MODEL, SUCCESS, original_calls


DEST = ROOT / "docs/assets/research/gemma4-31b-motion-pipeline-p1-2026-09-25"
P0 = ROOT / "docs/assets/research/gemma4-31b-motion-pipeline-p0-2026-09-25/manifest.json"
SCENES = (5, 10)


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare() -> list[Path]:
    p0 = json.loads(P0.read_text(encoding="utf-8"))
    source = original_calls()
    successful_system = (SUCCESS / "system-performance.txt").read_text(encoding="utf-8")
    paths: list[Path] = []
    for scene in SCENES:
        frozen = p0["scenes"][scene - 1]
        baseline = source[(scene, "performance")]
        if frozen["adopted_calls"]["performance"]["file_sha256"] != hashlib.sha256(
            baseline["file"].read_bytes()
        ).hexdigest():
            raise ValueError(f"Scene {scene} baseline changed since P0")
        original = baseline["payload"]
        candidate = copy.deepcopy(original)
        candidate.pop("previous_scene_state", None)
        candidate["current_lyric_focus"] = [
            {"shot": item["shot"], "lines": [lyric["text"] for lyric in item["lyrics"]]}
            for item in original["original_lyrics"]
        ]
        candidate["shot_progression"] = [
            {"shot": item["shot"], "role": "trigger" if index == 0 else "carry_forward"}
            for index, item in enumerate(original["shot_positions"])
        ]
        candidate["start_condition"] = {
            "continuation": bool(original["continuation"]),
            "source": "previous_video_frame" if original["continuation"] else "new_scene_cut",
        }
        if candidate["accepted_event"] != original["accepted_event"]:
            raise ValueError("Event changed")
        if candidate.get("scheduled_motion_composition") != original.get("scheduled_motion_composition"):
            raise ValueError("motion composition changed")
        if candidate["shot_positions"] != original["shot_positions"]:
            raise ValueError("Shot positions changed")
        item = {
            "scene": scene,
            "variant": "short_contract",
            "source_adopted_call": frozen["adopted_calls"]["performance"]["path"],
            "source_adopted_camera": frozen["adopted_calls"]["camera"]["path"],
            "source_adopted_event": frozen["adopted_calls"]["event"]["path"],
            "baseline_response_sha256": digest(baseline["item"]["response"]),
            "baseline_system_sha256": digest(baseline["item"]["request"]["messages"][0]["content"]),
            "variant_system_sha256": digest(successful_system),
            "unchanged_fields": sorted(set(original) & set(candidate)),
            "removed_fields": sorted(set(original) - set(candidate)),
            "added_fields": sorted(set(candidate) - set(original)),
            "system": successful_system,
            "user": candidate,
            "sampling": {
                "n_ctx": 24576,
                "max_tokens": 2048,
                "temperature": 0.2,
                "top_p": 0.9,
                "repetition_penalty": 1.05,
                "seed": 2,
            },
        }
        path = DEST / f"scene{scene}-request.json"
        write_json(path, item)
        paths.append(path)

        focus = copy.deepcopy(original)
        focus["current_lyric_focus"] = candidate["current_lyric_focus"]
        focus["shot_progression"] = candidate["shot_progression"]
        focus_item = {
            **item,
            "variant": "production_contract_with_lyric_focus",
            "system": baseline["item"]["request"]["messages"][0]["content"],
            "user": focus,
            "variant_system_sha256": item["baseline_system_sha256"],
            "unchanged_fields": sorted(set(original)),
            "removed_fields": [],
            "added_fields": ["current_lyric_focus", "shot_progression"],
        }
        focus_path = DEST / f"scene{scene}-focus-request.json"
        write_json(focus_path, focus_item)
        paths.append(focus_path)
    return paths


def infer(paths: list[Path]) -> None:
    if not MODEL.is_file():
        raise FileNotFoundError(MODEL)
    lifecycle = LlamaCppLifecycle()
    config = LlamaRuntimeConfig(
        n_ctx=24576, max_tokens=2048, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False, seed=2,
    )
    try:
        lifecycle.ensure_loaded(MODEL, config)
        for path in paths:
            item = json.loads(path.read_text(encoding="utf-8"))
            scene = item["scene"]
            output = path.with_name(path.name.replace("request.json", "response.json"))
            request_hash = digest(item["system"] + "\n" + canonical(item["user"]))
            if output.exists():
                existing = json.loads(output.read_text(encoding="utf-8"))
                if existing["request_hash"] != request_hash:
                    raise ValueError(f"saved response request mismatch: {output}")
                print(f"Scene {scene}: existing response retained", flush=True)
                continue
            print(f"Scene {scene} {item['variant']}: 31B Performance comparison started", flush=True)
            started = time.monotonic()
            response = lifecycle.complete_chat(
                [
                    {"role": "system", "content": item["system"]},
                    {"role": "user", "content": canonical(item["user"])},
                ],
                config,
            )
            expected = {int(slot["slot"]) for slot in item["user"]["slots"]}
            lines = response.strip().splitlines()
            fields = [line.split("\t", 2) for line in lines]
            if (
                len(fields) != len(expected)
                or any(len(row) != 3 or row[0] != "PERFORMANCE" or not row[1].isdigit() or not row[2].strip() for row in fields)
                or {int(row[1]) for row in fields} != expected
            ):
                raise ValueError(f"Scene {scene}: response does not match Performance slots")
            write_json(output, {
                "scene": scene,
                "request_hash": request_hash,
                "response": response,
                "elapsed_seconds": round(time.monotonic() - started, 3),
            })
            print(f"Scene {scene} {item['variant']}: completed in {time.monotonic() - started:.1f}s", flush=True)
    finally:
        lifecycle.clear()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--infer", action="store_true", help="Run local 31B on GPU after preparation")
    args = parser.parse_args()
    paths = prepare()
    print("P1 requests prepared: " + ", ".join(str(path) for path in paths), flush=True)
    if args.infer:
        infer(paths)


if __name__ == "__main__":
    main()
