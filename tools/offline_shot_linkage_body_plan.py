"""Build an isolated EMD/Plan probe from the P0 adopted video artifacts.

Only six Action/Camera pairs in Scenes 3, 4 and 9 are changed. This is an
author-written treatment for a controlled H3 comparison, not Planner output.
The source Plan, source EMD, scene timing, audio, references and other Scenes
are preserved. The production Compiler is not used for this English test text.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.emd.parser import parse_emd

PLAN_SHA256 = "7a1b6307b89fc0cbfedfc2c923ea13d7109d8a4928bde9880a05df771eb26ec5"
EMD_SHA256 = "46894f43a2acd92033076daf081d9fead43cf02e36bb1f4bb39fb1c5117a0b77"
SCENES = (3, 4, 9)
SHOT_2_PREFIX = re.compile(r"^\[Shot 2\] At \d{2}:\d{2}\.\d{3},?")
SCENE_HEADER = re.compile(r"^> `シーン` (\d+)$", re.MULTILINE)
SHOT_HEADER = re.compile(r"^## ショット .+$", re.MULTILINE)
BULLET = re.compile(r"^\* .+$", re.MULTILINE)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_treatment(treatment: dict) -> dict[int, tuple[dict, dict]]:
    if set(treatment["scenes"]) != {str(number) for number in SCENES}:
        raise ValueError("Treatment must contain exactly Scenes 3, 4 and 9")
    selected = {}
    for number in SCENES:
        shots = treatment["scenes"][str(number)]["shots"]
        if len(shots) != 2 or any(
            set(shot) != {"action", "camera"}
            or not all(isinstance(value, str) and value.strip() for value in shot.values())
            for shot in shots
        ):
            raise ValueError(f"Scene {number} requires two Action/Camera pairs")
        selected[number] = tuple(shots)
    return selected


def replace_emd(source: str, treatment: dict[int, tuple[dict, dict]]) -> str:
    headers = list(SCENE_HEADER.finditer(source))
    if not headers:
        raise ValueError("No EMD Scenes found")
    parts = [source[:headers[0].start()]]
    changed = set()
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(source)
        block = source[match.start():end]
        number = int(match.group(1))
        if number not in treatment:
            parts.append(block)
            continue
        matches = list(SHOT_HEADER.finditer(block))
        if len(matches) != 2:
            raise ValueError(f"Expected two Shots in Scene {number}")
        prefix = block[:matches[0].start()]
        chunks = []
        for shot_index, shot_match in enumerate(matches):
            next_start = matches[shot_index + 1].start() if shot_index + 1 < len(matches) else len(block)
            chunk = block[shot_match.start():next_start]
            audio = re.search(r"^## 音響$", chunk, re.MULTILINE)
            shot_body = chunk[:audio.start()] if audio else chunk
            suffix = chunk[audio.start():] if audio else ""
            bullets = list(BULLET.finditer(shot_body))
            if len(bullets) != 2:
                raise ValueError(f"Expected Action and Camera in Scene {number} Shot {shot_index + 1}")
            action, camera = treatment[number][shot_index].values()
            for found, replacement in zip(reversed(bullets), (camera, action)):
                shot_body = shot_body[:found.start()] + "* " + replacement + shot_body[found.end():]
            chunks.append(shot_body + suffix)
        parts.append(prefix + "".join(chunks))
        changed.add(number)
    if changed != set(treatment):
        raise ValueError("Not all treatment Scenes occurred in the EMD")
    result = "".join(parts)
    parse_emd(result)
    return result


def replace_plan(source: dict, treatment: dict[int, tuple[dict, dict]]) -> dict:
    result = copy.deepcopy(source)
    if len(result["shots"]) < max(treatment):
        raise ValueError("Plan is missing a treatment Scene")
    for number, shots in treatment.items():
        scene = result["shots"][number - 1]
        if scene["id"] != f"scene_{number:04d}":
            raise ValueError(f"Plan Scene index {number} has unexpected ID")
        prompt = scene["prompt"]
        summary_index = prompt.index("summary:") + 1
        if not prompt[summary_index].startswith("[reference generation]"):
            raise ValueError("Reference generation summary is not where expected")
        prompt[summary_index] = "[reference generation] " + shots[0]["action"]
        detail = [i for i, row in enumerate(prompt) if row.startswith("[Shot ")]
        if len(detail) != 2 or not prompt[detail[0]].startswith("[Shot 1]"):
            raise ValueError(f"Scene {number} has unexpected Shot descriptions")
        second = SHOT_2_PREFIX.match(prompt[detail[1]])
        if second is None:
            raise ValueError(f"Scene {number} has unexpected second Shot timestamp")
        prompt[detail[0]] = "[Shot 1] " + shots[0]["action"] + " " + shots[0]["camera"]
        prompt[detail[1]] = second.group() + " " + shots[1]["action"] + " " + shots[1]["camera"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-emd", type=Path, required=True)
    parser.add_argument("--source-plan", type=Path, required=True)
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_emd = args.source_emd.read_bytes()
    source_plan = args.source_plan.read_bytes()
    if sha256(source_emd) != EMD_SHA256 or sha256(source_plan) != PLAN_SHA256:
        raise ValueError("Source artifacts do not match the P0 adopted video")
    selected = checked_treatment(json.loads(args.treatment.read_text(encoding="utf-8")))
    candidate_emd = replace_emd(source_emd.decode("utf-8-sig").replace("\r\n", "\n"), selected)
    original_plan = json.loads(source_plan)
    candidate_plan = replace_plan(original_plan, selected)
    for index, (before, after) in enumerate(zip(original_plan["shots"], candidate_plan["shots"]), 1):
        if index not in selected and before != after:
            raise AssertionError(f"Untargeted Scene {index} changed")
        if index in selected and (
            {key: value for key, value in before.items() if key != "prompt"}
            != {key: value for key, value in after.items() if key != "prompt"}
        ):
            raise AssertionError(f"Scene {index} non-prompt fields changed")
    args.output.mkdir(parents=True, exist_ok=True)
    emd_path = args.output / "candidate_emd.md"
    plan_path = args.output / "candidate_plan.json"
    if emd_path.exists() or plan_path.exists():
        raise ValueError("Candidate artifacts already exist")
    emd_path.write_text(candidate_emd, encoding="utf-8")
    plan_path.write_text(json.dumps(candidate_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "kind": "manual_offline_probe_not_planner_output",
        "source_emd": str(args.source_emd), "source_emd_sha256": sha256(source_emd),
        "source_plan": str(args.source_plan), "source_plan_sha256": sha256(source_plan),
        "treatment": str(args.treatment),
        "treatment_sha256": sha256(args.treatment.read_bytes()),
        "candidate_emd_sha256": sha256(emd_path.read_bytes()),
        "candidate_plan_sha256": sha256(plan_path.read_bytes()),
        "changed_scenes": list(SCENES),
        "compiler_used": False,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
