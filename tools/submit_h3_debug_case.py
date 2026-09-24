"""Submit an isolated H3 Scene range or a full-plan comparison.

The metadata JSON must contain prompt/workflow/h3_plan (extracted from ffprobe
tags). The server must already be running; this tool never starts/stops it.
Use a unique run name for a new comparison. A full-plan run may resume its own
durable checkpoint prefix by repeating the run name with --start-clip N.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--scene", type=int, default=1)
    parser.add_argument("--scene-length", type=int, default=1)
    parser.add_argument("--full", action="store_true", help="render the complete Plan without splitting")
    parser.add_argument("--start-clip", type=int, default=1,
                        help="resume a full-plan run from this one-based Scene")
    parser.add_argument("--between-scene-cleanup", choices=("off", "unload_models", "fresh_scene"),
                        default="off")
    parser.add_argument("--scheduler", choices=("simple", "beta"), default="simple")
    parser.add_argument("--url", default="http://127.0.0.1:8191")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]+", args.case):
        parser.error("case must be a safe unique run name")
    metadata = json.loads(args.metadata.read_text(encoding="utf-8-sig"))
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    if not args.full and (not 1 <= args.scene <= len(plan["shots"]) or not 1 <= args.scene_length <= len(plan["shots"]) - args.scene + 1):
        parser.error("scene range is outside the input plan")
    if not 1 <= args.start_clip <= len(plan["shots"]):
        parser.error("start-clip is outside the input plan")
    if not args.full and args.start_clip != 1:
        parser.error("start-clip requires --full")
    graph = copy.deepcopy(metadata["prompt"])
    required = {"48": "MVDirectorSceneDebugSplitter", "24": "MiniMaxH3ChainPlanModern",
                "37": "MVDirectorAudioPadPair", "15": "BasicScheduler",
                "7": "MiniMaxH3ChainLoopStart", "29": "MiniMaxH3ChainPreflight",
                "23": "MiniMaxH3ChainLoopEnd", "28": "MiniMaxH3ChainReview",
                "21": "MiniMaxH3ChainAssemble"}
    if any(graph.get(key, {}).get("class_type") != kind for key, kind in required.items()):
        parser.error("this saved graph does not have the expected splitter/plan wiring")
    # Seed is explicitly inherited, independent of a different output run name.
    for index, shot in enumerate(plan["shots"]):
        shot["seed"] = metadata["h3_plan"]["shots"][index]["seed"]
    text = json.dumps(plan, ensure_ascii=False)
    graph["48"]["inputs"].update(
        plan_json=text, enable=not args.full,
        scene_start=1 if args.full else args.scene,
        scene_length=len(plan["shots"]) if args.full else args.scene_length,
    )
    graph["37"]["inputs"]["plan_json"] = text
    graph["24"]["inputs"].update(run_name=args.case, plan_json=text)
    graph["7"]["inputs"]["start_clip"] = args.start_clip
    graph["29"]["inputs"]["start_clip"] = args.start_clip
    graph["23"]["inputs"]["between_scene_cleanup"] = args.between_scene_cleanup
    graph["15"]["inputs"]["scheduler"] = args.scheduler
    graph["28"]["inputs"]["enabled"] = False
    graph["21"]["inputs"]["filename"] = args.case
    # Only the final output and its dependencies are submitted; embedded file
    # picker state in disconnected nodes is not a runtime dependency.
    selected = {}
    def visit(key):
        if key in selected:
            return
        node = graph[key]
        selected[key] = {"class_type": node["class_type"], "inputs": node["inputs"]}
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in graph:
                visit(value[0])
    visit("21")
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence = {"case": args.case, "scene": "all" if args.full else args.scene,
                "scene_length": len(plan["shots"]) if args.full else args.scene_length,
                "start_clip": args.start_clip,
                "between_scene_cleanup": args.between_scene_cleanup,
                "scheduler": args.scheduler,
                "plan_source": str(args.plan), "prompt": selected}
    request = urllib.request.Request(args.url + "/prompt",
        data=json.dumps({"prompt": selected}).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        evidence["submission"] = result
        print(json.dumps(result))
    finally:
        args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
