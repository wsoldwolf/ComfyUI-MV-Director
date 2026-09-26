"""Prepare and optionally infer 31B fixed-motion ownership comparisons.

Only the fixed composition's ownership changes. Event, lyrics, Shot positions,
and the production Performance system stay frozen except where the candidate
must be explicitly declared nonbinding. No generated text is patched into EMD.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_gemma4_31b_pipeline_phases import original_calls
from tools.run_gemma4_31b_motion_p1 import infer, write_json
from tools.generate_workflows import DEFAULT_USER_PROMPT


DEST = ROOT / "docs/assets/research/gemma4-31b-motion-pipeline-p2-2026-09-25"
P0 = ROOT / "docs/assets/research/gemma4-31b-motion-pipeline-p0-2026-09-25/manifest.json"
SCENES = (5, 10)

FIXED_PARAGRAPH = (
    "scheduled_motion_compositionがある場合、そのtextは指定Shotの演技へアプリが別行で合成する確定動作である。"
    "本文に複写せず、その身体移動と両立する表情・腕・歌詞への反応及び前後Shotへの連続を計画する。"
    "合成動作と逆向きの移動や同時の静止を新たに指定しない。"
)
OPTIONAL_PARAGRAPH = (
    "motion_candidate_optionalがある場合、そのtextは作者固定指示でもアプリが後置する確定動作でもない。"
    "今回の歌詞、出来事及び前Sceneの状態に適合すれば、その身体運動を自由に採用又は発展させて本文へ統合してよい。"
    "適合しなければ使わず、自分で身体フレーズを作る。採用時も本文を重複して書かない。"
)


def prepare(*, include_optional: bool = False, compare_candidate_removal: bool = False) -> list[Path]:
    manifest = json.loads(P0.read_text(encoding="utf-8"))
    calls = original_calls()
    paths: list[Path] = []
    for scene in SCENES:
        original = calls[(scene, "performance")]
        frozen = manifest["scenes"][scene - 1]["adopted_calls"]["performance"]
        if hashlib.sha256(original["file"].read_bytes()).hexdigest() != frozen["file_sha256"]:
            raise ValueError(f"Scene {scene} adopted call changed since P0")
        base_payload = original["payload"]
        composition = base_payload.get("scheduled_motion_composition")
        if not composition:
            raise ValueError(f"Scene {scene} has no composition to compare")
        base_system = original["item"]["request"]["messages"][0]["content"]
        if base_system.count(FIXED_PARAGRAPH) != 1:
            raise ValueError("production Performance system changed")
        variants = ("none", "optional") if include_optional else ("none",)
        for variant in variants:
            payload = copy.deepcopy(base_payload)
            payload.pop("scheduled_motion_composition")
            system = base_system
            if variant == "optional":
                payload["motion_candidate_optional"] = composition
                system = base_system.replace(FIXED_PARAGRAPH, OPTIONAL_PARAGRAPH)
            item = {
                "scene": scene,
                "variant": f"composition_{variant}",
                "source_adopted_call": frozen["path"],
                "source_baseline_response_sha256": hashlib.sha256(
                    original["item"]["response"].encode("utf-8")
                ).hexdigest(),
                "composition": composition,
                "postappend_composition": False,
                "system": system,
                "user": payload,
                "sampling": {
                    "n_ctx": 24576,
                    "max_tokens": 2048,
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "repetition_penalty": 1.05,
                    "seed": 2,
                },
            }
            path = DEST / f"scene{scene}-{variant}-request.json"
            write_json(path, item)
            paths.append(path)

        if compare_candidate_removal:
            prompt_candidates = [
                line[2:] for line in DEFAULT_USER_PROMPT.splitlines()
                if line.startswith("* ")
            ]
            four_motifs = prompt_candidates[:4]
            old_candidates = base_payload["staging_candidates_optional"]
            if len(old_candidates) != 7 or len(four_motifs) != 4 or old_candidates[:2] != four_motifs[:2]:
                raise ValueError("motif/body candidate boundary changed")
            for label, candidates in (
                ("none-motifs2", old_candidates[:2]),
                ("none-motifs4", four_motifs),
            ):
                payload = copy.deepcopy(base_payload)
                payload.pop("scheduled_motion_composition")
                payload["staging_candidates_optional"] = candidates
                item = {
                    "scene": scene,
                    "variant": label,
                    "source_adopted_call": frozen["path"],
                    "composition_removed": True,
                    "candidate_count": len(candidates),
                    "system": base_system,
                    "user": payload,
                    "sampling": {
                        "n_ctx": 24576,
                        "max_tokens": 2048,
                        "temperature": 0.2,
                        "top_p": 0.9,
                        "repetition_penalty": 1.05,
                        "seed": 2,
                    },
                }
                path = DEST / f"scene{scene}-{label}-request.json"
                write_json(path, item)
                paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--infer", action="store_true")
    parser.add_argument("--include-optional", action="store_true")
    parser.add_argument("--compare-candidate-removal", action="store_true")
    args = parser.parse_args()
    paths = prepare(
        include_optional=args.include_optional,
        compare_candidate_removal=args.compare_candidate_removal,
    )
    print("P2 requests prepared: " + ", ".join(str(path) for path in paths), flush=True)
    if args.infer:
        infer(paths)


if __name__ == "__main__":
    main()
