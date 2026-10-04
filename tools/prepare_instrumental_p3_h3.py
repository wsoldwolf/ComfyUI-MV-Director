"""Reuse the verified P2 graph/PCM clock for a single P3 candidate render."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.prepare_instrumental_h3 import render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8191")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--run-name", default="instrumental-p3-momiji2-prompt-20261003")
    args = parser.parse_args()
    if args.render:
        render(args.comparison, "activity", args.url)
        return
    if (args.comparison / "h3-activity.json").exists():
        raise ValueError("Candidate graph already exists")
    original_path = args.previous / "h3-activity-a3.json"
    graph = json.loads(original_path.read_text(encoding="utf-8"))
    saved_plan = json.loads((args.previous / "activity-plan.json").read_text(encoding="utf-8"))
    plan = json.loads((args.comparison / "activity-plan.json").read_text(encoding="utf-8"))
    conditions = json.loads((args.comparison / "conditions.json").read_text(encoding="utf-8"))
    start = conditions["scene_start"] - 1
    if plan["shots"][start] != saved_plan["shots"][start]:
        raise ValueError("Common predecessor changed")
    plan["shots"] = plan["shots"][start:start+2]
    prior_slice = json.loads(graph["24"]["inputs"]["plan_json"])
    if plan["shots"][0] != prior_slice["shots"][0]:
        raise ValueError("Rendered predecessor differs from saved P2 graph")
    for current, previous in zip(plan["shots"], prior_slice["shots"]):
        for key in ("length", "context_length", "seed"):
            if current.get(key) != previous.get(key):
                raise ValueError(f"Render clock or seed changed: {key}")
    name = args.run_name
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in name):
        raise ValueError("Use a simple lowercase run name, not a path")
    for node_id in ("24", "37", "48"):
        graph[node_id]["inputs"]["plan_json"] = json.dumps(plan, ensure_ascii=False)
    graph["24"]["inputs"]["run_name"] = name
    graph["21"]["inputs"]["filename"] = name
    (args.comparison / "h3-activity.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = json.loads((args.previous / "h3-manifest-a3.json").read_text(encoding="utf-8"))
    evidence = []
    for key in ("32", "33"):
        path = Path(r"C:\Software\ComfyUI\input") / graph[key]["inputs"]["audio"]
        evidence.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (args.comparison / "h3-manifest.json").write_text(json.dumps({
        "source_graph": str(original_path), "isolated_audio_clock": manifest["isolated_audio_clock"],
        "audio_files": evidence, "run_name": name, "baseline_is_saved_p2_activity": True,
        "rendered_prefix_is_separately_generated": True, "conditions": conditions,
        "megapixels": 0.4, "default_steps": 20, "standard_context_loop_lip_sync": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Candidate graph ready; same PCM clock, prefix Plan, render seed and WF settings")


if __name__ == "__main__":
    main()
