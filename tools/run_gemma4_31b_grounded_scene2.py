"""Bounded Scene 1–2 grounded-motion comparison from the frozen 31B run.

Only the experimental profile's scheduled movement is changed. Event, lyrics,
scene layout, references, H3 settings, and random seed remain frozen. The
generated Plan is a research artifact; this does not alter production output.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.direction.profiles import MOTION_TEMPLATES
from run_gemma4_31b_pipeline_phases import (
    DEST, SOURCE, DirectGemma, original_calls, response_fields, write_json,
)


RUNS = {
    "baseline": "gemma31b_p5_ground_baseline_04mp_s1_2_20260925",
    "grounded": "gemma31b_p5_grounded_04mp_s1_2_20260925",
}
CONTEXT_RUNS = {
    "baseline": "gemma31b_p5_context_baseline_04mp_s1_2_20260925",
    "grounded": "gemma31b_p5_context_grounded_04mp_s1_2_20260925",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def translated_text(response: str) -> str:
    body = response.strip()
    if body.startswith("```json\n") and body.endswith("\n```"):
        body = body[8:-4].strip()
    item = json.loads(body)
    value = item["translation"]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("translation must be a nonempty JSON string")
    return value.strip()


def prepare() -> None:
    calls = original_calls()
    plan = read_json(SOURCE / "plan.json")
    templates = MOTION_TEMPLATES["anime_scene_composed_mv"]
    if len(templates) != 3 or [plan["shots"][i]["id"] for i in (0, 1)] != [
        "scene_0001", "scene_0002",
    ]:
        raise ValueError("Frozen Scene/profile contract changed")
    model = DirectGemma()
    result: dict[int, dict] = {}
    previous_performance = previous_camera = ""
    try:
        for scene in (1, 2):
            performance_call = calls[(scene, "performance")]
            performance_payload = copy.deepcopy(performance_call["payload"])
            scheduled = performance_payload["scheduled_motion_composition"]
            if scheduled["template"] != scene or scheduled["shot"] != 2:
                raise ValueError("Frozen composition selection changed")
            scheduled["text"] = templates[scene - 1]
            performance_payload["previous_scene_state"] = previous_performance
            performance_system = performance_call["item"]["request"]["messages"][0]["content"]
            performance_raw = model.run(
                f"p5-scene{scene}-grounded-performance", performance_system,
                performance_payload, 2048,
            )
            performances, performance_states = response_fields(performance_raw, "PERFORMANCE", 2)
            previous_performance = performance_states["2"]

            camera_call = calls[(scene, "camera")]
            camera_payload = copy.deepcopy(camera_call["payload"])
            camera_payload["scheduled_motion_composition"]["text"] = templates[scene - 1]
            camera_payload["accepted_performances"] = {
                key: value + (" " + templates[scene - 1] if key == "2" else "")
                for key, value in performances.items()
            }
            camera_payload["previous_scene_state"] = previous_camera
            camera_system = camera_call["item"]["request"]["messages"][0]["content"]
            camera_raw = model.run(
                f"p5-scene{scene}-grounded-camera", camera_system,
                camera_payload, 1536,
            )
            cameras, camera_states = response_fields(camera_raw, "CAMERA", 2)
            previous_camera = camera_states["2"]

            translated = []
            translation_system = (
                "Translate the Japanese performance and camera as one concise English MV "
                "video direction. Preserve the support-foot and weight-transfer sequence, "
                "gesture, emotion, camera motion name and path. Do not invent flight, jumping, "
                "extra objects, or a feet close-up. Return only JSON "
                '{"translation": "..."}.'
            )
            for shot in (1, 2):
                response = model.run(
                    f"p5-scene{scene}-grounded-translate-shot{shot}",
                    translation_system,
                    {
                        "performance": performances[str(shot)] + (
                            " " + templates[scene - 1] if shot == 2 else ""
                        ),
                        "camera": cameras[str(shot)],
                    },
                    1024,
                )
                translated.append(translated_text(response))
            result[scene] = {
                "template": templates[scene - 1],
                "performance": performances,
                "performance_end_state": performance_states,
                "camera": cameras,
                "camera_end_state": camera_states,
                "translated": translated,
                "original_performance": performance_call["item"]["response"],
                "original_camera": camera_call["item"]["response"],
                "source_event_unchanged": (
                    performance_payload["accepted_event"]
                    == performance_call["payload"]["accepted_event"]
                ),
            }
        write_json(DEST / "p5-grounded-scene1-2-text.json", result)
    finally:
        model.close()

    variant = copy.deepcopy(plan)
    for scene in (1, 2):
        source_lines = plan["shots"][scene - 1]["prompt"]
        lines = variant["shots"][scene - 1]["prompt"]
        if lines[11] != "detailed_description:" or not lines[12].startswith("[Shot 1]") \
                or not lines[13].startswith("[Shot 2] At "):
            raise ValueError(f"Frozen prompt layout changed for Scene {scene}")
        summary = source_lines[5].removeprefix("[reference generation] ")
        lines[12] = "[Shot 1] " + summary + " " + result[scene]["translated"][0]
        match = re.match(r"\[Shot 2\] At [0-9:.]+, ", source_lines[13])
        if match is None:
            raise ValueError(f"Scene {scene} Shot 2 timestamp missing")
        lyric_tags = re.findall(r"<d>.*?</d>", source_lines[13])
        lyric = "Lyrics " + " ".join(lyric_tags) + ". " if lyric_tags else ""
        lines[13] = match.group() + lyric + result[scene]["translated"][1]
        if lines[:12] != source_lines[:12] or lines[14:] != source_lines[14:]:
            raise ValueError(f"Scene {scene}: unexpected Plan mutation")
    if variant["shots"][2:] != plan["shots"][2:]:
        raise ValueError("Later scenes were modified")
    write_json(DEST / "p5-grounded-scene1-2-plan.json", variant)

    graph = read_json(SOURCE / "full-api-prompt.json")
    if graph["48"]["class_type"] != "MVDirectorSceneDebugSplitter" \
            or graph["47"]["class_type"] != "ResolutionSelector":
        raise ValueError("Frozen H3 graph changed")
    for name, source_plan in (("baseline", plan), ("grounded", variant)):
        item = copy.deepcopy(graph)
        item["47"]["inputs"]["megapixels"] = 0.4
        item["48"]["inputs"].update({
            "enable": True, "scene_start": 1, "scene_length": 2,
            "plan_json": json.dumps(source_plan, ensure_ascii=False),
        })
        item["24"]["inputs"]["run_name"] = RUNS[name]
        item["21"]["inputs"]["filename"] = RUNS[name]
        write_json(DEST / f"p5-04mp-{name}-api-prompt.json", item)
    print("P5 Scene 1–2 text and 0.4MP A/B graphs prepared", flush=True)


def prepare_context() -> None:
    """Use the current Context Loop lip-sync WF settings, never Audio Reference."""
    workflow = read_json(Path(__file__).resolve().parents[1] / "workflows/02_video_context_loop.json")
    nodes = {node["id"]: node for node in workflow["nodes"]}
    if nodes[40]["type"] != "MiniMaxH3LipSyncOptions" \
            or nodes[30]["widgets_values_named"]["audio_profile"] != "Lip-sync to source audio" \
            or nodes[37]["widgets_values_named"]["reference_alignment"] != "off":
        raise ValueError("Current Context Loop lip-sync WF contract changed")
    baseline = read_json(SOURCE / "plan.json")
    grounded = read_json(DEST / "p5-grounded-scene1-2-plan.json")
    source = read_json(SOURCE / "full-api-prompt.json")
    for name, plan in (("baseline", baseline), ("grounded", grounded)):
        graph = copy.deepcopy(source)
        graph["11"]["inputs"].pop("ref_audios.ref_audio_0", None)
        graph["12"]["inputs"].update({
            "audio_vae": ["5", 0], "lip_sync_voice": ["40", 1],
        })
        graph["30"]["inputs"].update({
            "audio_profile": "Lip-sync to source audio",
            "lip_sync_options": ["40", 0],
        })
        graph["37"]["inputs"].pop("timeline", None)
        graph["37"]["inputs"]["reference_alignment"] = "off"
        graph["40"] = {
            "class_type": "MiniMaxH3LipSyncOptions",
            "inputs": {**nodes[40]["widgets_values_named"], "voice": ["48", 1]},
        }
        graph["48"]["inputs"].update({
            "enable": True, "scene_start": 1, "scene_length": 2,
            "vocal_audio": ["37", 1],
            "plan_json": json.dumps(plan, ensure_ascii=False),
        })
        graph["47"]["inputs"]["megapixels"] = 0.4
        graph["24"]["inputs"].update({
            "generation_fingerprint": source["24"]["inputs"]["generation_fingerprint"].replace(
                "audio_reference", "context_loop"
            ),
            "run_name": CONTEXT_RUNS[name],
        })
        graph["21"]["inputs"]["filename"] = CONTEXT_RUNS[name]
        write_json(DEST / f"p5-context-04mp-{name}-api-prompt.json", graph)
    print("P5 Context Loop lip-sync A/B graphs prepared from current WF settings", flush=True)


def submit(name: str) -> None:
    graph = read_json(DEST / f"p5-04mp-{name}-api-prompt.json")
    request = Request(
        "http://127.0.0.1:8188/prompt",
        data=json.dumps({"prompt": graph, "client_id": RUNS[name]}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urlopen(request, timeout=120) as response:
        output = json.load(response)
    write_json(DEST / f"p5-04mp-{name}-submission-response.json", output)
    print(json.dumps(output, ensure_ascii=False), flush=True)


def submit_context(name: str) -> None:
    graph = read_json(DEST / f"p5-context-04mp-{name}-api-prompt.json")
    request = Request(
        "http://127.0.0.1:8188/prompt",
        data=json.dumps({"prompt": graph, "client_id": CONTEXT_RUNS[name]}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urlopen(request, timeout=120) as response:
        output = json.load(response)
    write_json(DEST / f"p5-context-04mp-{name}-submission-response.json", output)
    print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "submit", "prepare-context", "submit-context"))
    parser.add_argument("--variant", choices=tuple(RUNS))
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare()
    elif args.phase == "prepare-context":
        prepare_context()
    elif args.phase == "submit-context" and args.variant:
        submit_context(args.variant)
    elif args.phase == "submit" and args.variant:
        submit(args.variant)
    else:
        parser.error("submit requires --variant")
