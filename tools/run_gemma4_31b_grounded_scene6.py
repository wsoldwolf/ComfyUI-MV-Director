"""P6: bounded grounded-motion test for Scene 5–6, using Context Loop lip sync."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.direction.profiles import MOTION_TEMPLATES
from run_gemma4_31b_grounded_scene2 import read_json, translated_text
from run_gemma4_31b_pipeline_phases import (
    DEST, SOURCE, DirectGemma, original_calls, response_fields, write_json,
)


RUNS = {
    "baseline": "gemma31b_p6_context_baseline_04mp_s5_6_20260925",
    "grounded": "gemma31b_p6_context_grounded_04mp_s5_6_20260925",
}


def prepare() -> None:
    calls = original_calls()
    baseline = read_json(SOURCE / "plan.json")
    templates = MOTION_TEMPLATES["anime_scene_composed_mv"]
    if len(templates) != 3 or [baseline["shots"][i]["id"] for i in (4, 5)] != [
        "scene_0005", "scene_0006",
    ]:
        raise ValueError("Frozen Scene/profile contract changed")
    previous_performance = calls[(5, "performance")]["payload"]["previous_scene_state"]
    previous_camera = calls[(5, "camera")]["payload"]["previous_scene_state"]
    model = DirectGemma()
    result: dict[int, dict] = {}
    try:
        for scene in (5, 6):
            performance_call = calls[(scene, "performance")]
            payload = copy.deepcopy(performance_call["payload"])
            template_number = (scene - 1) % len(templates) + 1
            scheduled = payload["scheduled_motion_composition"]
            if scheduled["template"] != template_number:
                raise ValueError(f"Scene {scene}: motion template selection changed")
            scheduled["text"] = templates[template_number - 1]
            payload["previous_scene_state"] = previous_performance
            count = len(payload["slots"])
            system = performance_call["item"]["request"]["messages"][0]["content"]
            response = model.run(f"p6-scene{scene}-grounded-performance", system, payload, 2048)
            performances, performance_states = response_fields(response, "PERFORMANCE", count)
            previous_performance = performance_states[str(count)]

            camera_call = calls[(scene, "camera")]
            camera_payload = copy.deepcopy(camera_call["payload"])
            camera_payload["scheduled_motion_composition"]["text"] = scheduled["text"]
            camera_payload["accepted_performances"] = {
                str(shot): performances[str(shot)] + (
                    " " + scheduled["text"] if shot == scheduled["shot"] else ""
                ) for shot in range(1, count + 1)
            }
            camera_payload["previous_scene_state"] = previous_camera
            camera_system = camera_call["item"]["request"]["messages"][0]["content"]
            camera_response = model.run(
                f"p6-scene{scene}-grounded-camera", camera_system, camera_payload, 1536,
            )
            cameras, camera_states = response_fields(camera_response, "CAMERA", count)
            previous_camera = camera_states[str(count)]

            translation_system = (
                "Translate Japanese performance and camera into one concise English MV video "
                "direction. Preserve support and weight transfer, gesture, expression, "
                "the exact camera motion name and direction. Do not invent another event "
                'or object. Return only JSON {"translation": "..."}.'
            )
            translated = []
            for shot in range(1, count + 1):
                item = {
                    "performance": camera_payload["accepted_performances"][str(shot)],
                    "camera": cameras[str(shot)],
                }
                response = model.run(
                    f"p6-scene{scene}-grounded-translate-shot{shot}",
                    translation_system, item, 1024,
                )
                translated.append(translated_text(response))
            result[scene] = {
                "event_unchanged": payload["accepted_event"] == performance_call["payload"]["accepted_event"],
                "template": scheduled,
                "performance": performances,
                "performance_states": performance_states,
                "camera": cameras,
                "camera_states": camera_states,
                "translated": translated,
                "baseline_performance": performance_call["item"]["response"],
                "baseline_camera": camera_call["item"]["response"],
            }
        write_json(DEST / "p6-grounded-scene5-6-text.json", result)

        # Scene 6 baseline summary reproduces the old abrupt reverse movement.
        # Ask the model to keep its lyric motif but align the summary with the
        # accepted replacement body phrase; do not repair prose in Python.
        original_summary = baseline["shots"][5]["prompt"][5]
        summary_response = model.run(
            "p6-scene6-grounded-summary",
            "Rewrite one English MV scene summary. Keep the original lyric motif and setting, "
            "but describe only the new accepted body movement. Do not add an object, "
            "event, gesture, or camera move. Return only JSON {\"translation\": \"...\"}.",
            {
                "original_summary": original_summary,
                "accepted_performance": result[6]["translated"][0],
            },
            1024,
        )
        scene6_summary = translated_text(summary_response)
    finally:
        model.close()

    variant = copy.deepcopy(baseline)
    for scene in (5, 6):
        original = baseline["shots"][scene - 1]["prompt"]
        lines = variant["shots"][scene - 1]["prompt"]
        if lines[11] != "detailed_description:":
            raise ValueError(f"Scene {scene}: prompt layout changed")
        if scene == 6:
            lines[5] = "[reference generation] " + scene6_summary
        for shot in range(1, len(result[scene]["translated"]) + 1):
            index = 11 + shot
            header = re.match(r"\[Shot 1\] " if shot == 1 else r"\[Shot 2\] At [0-9:.]+, ", original[index])
            if header is None:
                raise ValueError(f"Scene {scene} Shot {shot}: timestamp missing")
            tags = re.findall(r"<d>.*?</d>", original[index])
            lyric = ("Lyrics " + " ".join(tags) + ". ") if tags else ""
            event = original[5].removeprefix("[reference generation] ") if scene == 5 and shot == 1 else ""
            lines[index] = header.group() + lyric + (event + " " if event else "") + result[scene]["translated"][shot - 1]
            if re.findall(r"<d>.*?</d>", lines[index]) != tags:
                raise ValueError(f"Scene {scene} Shot {shot}: lyric tags changed")
        if lines[:5] != original[:5] or lines[6:12] != original[6:12] \
                or lines[12 + len(result[scene]["translated"]):] != original[12 + len(result[scene]["translated"]):]:
            raise ValueError(f"Scene {scene}: unexpected prompt mutation")
    if variant["shots"][:4] != baseline["shots"][:4] or variant["shots"][6:] != baseline["shots"][6:]:
        raise ValueError("Other scenes were modified")
    write_json(DEST / "p6-grounded-scene5-6-plan.json", variant)
    write_json(DEST / "p6-grounded-scene5-6-summary.json", {
        "scene6_old_summary": original_summary,
        "scene6_new_summary": scene6_summary,
        "same_lengths": [variant["shots"][i]["length"] == baseline["shots"][i]["length"] for i in (4, 5)],
        "changed_scenes": [i + 1 for i, (a, b) in enumerate(zip(baseline["shots"], variant["shots"])) if a != b],
    })

    source_graph = read_json(DEST / "p5-context-04mp-baseline-api-prompt.json")
    if source_graph["40"]["class_type"] != "MiniMaxH3LipSyncOptions" \
            or "ref_audios.ref_audio_0" in source_graph["11"]["inputs"]:
        raise ValueError("Expected Context Loop lip-sync graph")
    for name, plan in (("baseline", baseline), ("grounded", variant)):
        graph = copy.deepcopy(source_graph)
        graph["48"]["inputs"].update({
            "scene_start": 5, "scene_length": 2,
            "plan_json": json.dumps(plan, ensure_ascii=False),
        })
        graph["24"]["inputs"]["run_name"] = RUNS[name]
        graph["21"]["inputs"]["filename"] = RUNS[name]
        write_json(DEST / f"p6-context-04mp-{name}-api-prompt.json", graph)
    print("P6 Scene 5–6 text and Context Loop A/B graphs prepared", flush=True)


def submit(name: str) -> None:
    graph = read_json(DEST / f"p6-context-04mp-{name}-api-prompt.json")
    request = Request(
        "http://127.0.0.1:8188/prompt",
        data=json.dumps({"prompt": graph, "client_id": RUNS[name]}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urlopen(request, timeout=120) as response:
        output = json.load(response)
    write_json(DEST / f"p6-context-04mp-{name}-submission-response.json", output)
    print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "submit"))
    parser.add_argument("--variant", choices=tuple(RUNS))
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare()
    elif args.variant:
        submit(args.variant)
    else:
        parser.error("submit requires --variant")
