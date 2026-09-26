"""Bounded P4 Scene 2-3 H3 comparison; preserve the saved full-song baseline."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from run_gemma4_31b_pipeline_phases import DEST, SOURCE, DirectGemma, original_calls, write_json


RUNS = {
    "baseline": "gemma31b_p4_moss_baseline_04mp_s2_3_20260925",
    "joint": "gemma31b_p4_moss_joint_04mp_s2_3_20260925",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_camera(response: str) -> list[str]:
    found: dict[int, str] = {}
    for row in response.splitlines():
        if not row.strip():
            continue
        match = re.fullmatch(r"CAMERA\t([12])\t(.+)", row)
        if not match or int(match.group(1)) in found:
            raise ValueError(f"Camera protocol violation: {row!r}")
        found[int(match.group(1))] = match.group(2)
    if sorted(found) != [1, 2]:
        raise ValueError(f"Camera result missing Shot: {sorted(found)}")
    return [found[1], found[2]]


def parse_translation(response: str) -> str:
    body = response.strip()
    if body.startswith("```json\n") and body.endswith("\n```"):
        body = body[8:-4].strip()
    result = json.loads(body)
    value = result["translation"]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"translation protocol violation: {response!r}")
    return value.strip()


def prepare() -> None:
    joint = read_json(DEST / "p2b-scene3-summary.json")
    saved = read_json(SOURCE / "plan.json")
    original = saved["shots"][2]
    if original["id"] != "scene_0003" or len(joint["joint_events"]) != 2:
        raise ValueError("Frozen Scene 3 contract changed")
    calls = original_calls()
    event_payload = calls[(3, "event")]["payload"]
    camera_system = (
        "You are the camera director for one continuous two-Shot MV Scene. "
        "Use the accepted visible events and physical performances as given. "
        "Use MiniMax H3 camera instruction names such as Arc Shot, Tracking Shot, "
        "Push In, Pull Out, Zoom In, and Static Shot only where useful. "
        "Keep the moss at the base of the tree spatially legible and make the "
        "camera follow the hand's one contact and release. Maintain camera-motion continuity "
        "across the two Shots; do not invent feet close-ups or extra objects. "
        "Output exactly CAMERA<TAB>1<TAB>English camera direction then "
        "CAMERA<TAB>2<TAB>English camera direction. No other text."
    )
    camera_payload = {
        "scene_number": 3,
        "original_lyrics": event_payload["original_lyrics"],
        "shot_positions": event_payload["shot_positions"],
        "accepted_events": joint["joint_events"],
        "accepted_performances": joint["joint_performances"],
    }
    names = ["p4-scene3-joint-camera", "p4-scene3-joint-translate-shot1",
             "p4-scene3-joint-translate-shot2"]
    # A summary-only correction must not reload 31B while ComfyUI still holds
    # the H3 model. The three frozen raw responses are already on disk.
    model = None if all((DEST / "calls" / f"{name}.json").exists() for name in names) else DirectGemma()

    def run(name: str, system: str, payload: dict, max_tokens: int) -> str:
        if model is None:
            return read_json(DEST / "calls" / f"{name}.json")["response"]
        return model.run(name, system, payload, max_tokens)

    try:
        camera_raw = run("p4-scene3-joint-camera", camera_system, camera_payload, 1024)
        cameras = parse_camera(camera_raw)
        translated = []
        translation_system = (
            "Translate the Japanese Event and Performance as one coherent, concise English "
            "MV video prompt, then append the supplied English Camera direction unchanged. "
            "Preserve subject, spatial relationships, gesture sequence, emotion, and the exact "
            "H3 camera instruction names. Do not add events, body actions, or camera moves. "
            "Return only JSON {\"translation\": \"...\"}."
        )
        for index in range(2):
            payload = {
                "event": joint["joint_events"][index],
                "performance": joint["joint_performances"][index],
                "camera": cameras[index],
            }
            response = run(f"p4-scene3-joint-translate-shot{index+1}",
                           translation_system, payload, 1024)
            translated.append(parse_translation(response))
    finally:
        if model is not None:
            model.close()
    plan = copy.deepcopy(saved)
    scene = plan["shots"][2]
    baseline = original["prompt"]
    if baseline[11] != "detailed_description:" or not baseline[12].startswith("[Shot 1]") \
            or not baseline[13].startswith("[Shot 2] At "):
        raise ValueError("Frozen compiled Scene 3 prompt layout changed")
    lyric_tags = re.findall(r"<d>.*?</d>", baseline[13])
    if len(lyric_tags) != 1:
        raise ValueError("Expected one protected lyric tag in Scene 3 Shot 2")
    timestamp = re.match(r"\[Shot 2\] At ([0-9:.]+), ", baseline[13])
    if timestamp is None:
        raise ValueError("Expected Scene 3 Shot 2 timestamp")
    # The summary is visible from the first frame. Never preview a later Shot's
    # object or gesture here; keep the moss reveal local to Shot 2.
    scene["prompt"][5] = "[reference generation] " + translated[0]
    scene["prompt"][12] = "[Shot 1] " + translated[0]
    scene["prompt"][13] = (f"[Shot 2] At {timestamp.group(1)}, Lyrics {lyric_tags[0]}. "
                            + translated[1])
    for other in range(len(plan["shots"])):
        if other != 2 and plan["shots"][other] != saved["shots"][other]:
            raise ValueError(f"Unexpected Scene {other+1} mutation")
    write_json(DEST / "p4-scene3-joint-plan.json", plan)
    write_json(DEST / "p4-scene3-variant-summary.json", {
        "scene": 3,
        "lead_in_scene": 2,
        "same_shot_lengths": [saved["shots"][i]["length"] == plan["shots"][i]["length"] for i in (1, 2)],
        "camera": cameras,
        "joint_events": joint["joint_events"],
        "joint_performances": joint["joint_performances"],
        "translated": translated,
        "changed_prompt_indices": [5, 12, 13],
        "baseline_shot_lines": [baseline[12], baseline[13]],
        "joint_shot_lines": [scene["prompt"][12], scene["prompt"][13]],
    })
    graph = read_json(SOURCE / "full-api-prompt.json")
    if graph["48"]["class_type"] != "MVDirectorSceneDebugSplitter" \
            or graph["24"]["inputs"]["plan_json_input"] != ["48", 0] \
            or graph["47"]["class_type"] != "ResolutionSelector":
        raise ValueError("Frozen graph connector changed")
    for variant, source_plan in (("baseline", saved), ("joint", plan)):
        item = copy.deepcopy(graph)
        item["47"]["inputs"]["megapixels"] = 0.4
        item["48"]["inputs"].update({
            "enable": True, "scene_start": 2, "scene_length": 2,
            "plan_json": json.dumps(source_plan, ensure_ascii=False),
        })
        item["24"]["inputs"]["run_name"] = RUNS[variant]
        item["21"]["inputs"]["filename"] = RUNS[variant]
        write_json(DEST / f"p4-04mp-{variant}-api-prompt.json", item)
    print("P4 plans and API graphs prepared; only Scene 3 summary and Shot text differ.", flush=True)


def submit(variant: str) -> None:
    graph = read_json(DEST / f"p4-04mp-{variant}-api-prompt.json")
    run = RUNS[variant]
    request = Request(
        "http://127.0.0.1:8188/prompt",
        data=json.dumps({"prompt": graph, "client_id": run}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    write_json(DEST / f"p4-04mp-{variant}-submission-response.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


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
