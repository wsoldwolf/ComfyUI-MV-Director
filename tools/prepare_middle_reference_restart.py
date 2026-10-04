"""Restart interrupted B20 in new runs with an immutable reference-sheet copy.

Never mix old-image checkpoints into the new-image clip. Saved Planner and
Compiler results are reused; both full connected variants are prepared on CPU.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.prepare_beat_motion_h3 import read, save
from tools.prepare_instrumental_h3 import render
from tools.debug_instrumental_middle import verify_plan, finalize_middle
from tools.debug_shot_duration import verify_pcm

RUNS = {
    "baseline": "instrumental-middle-b20-ref-r1-momiji2-base-20261004",
    "dance": "instrumental-middle-b20-ref-r1-momiji2-torso-20261004",
}


def prepare(args):
    source, output = args.source.resolve(strict=True), args.output.resolve()
    reference = args.reference.resolve(strict=True)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty research destination")
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    target = Path(r"C:\Software\ComfyUI\input") / ("mvd_momiji2_ref_" + digest[:16] + reference.suffix)
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise ValueError("Reference snapshot collision")
    contract, manifest = read(source / "output-contract.json"), read(source / "h3-manifest.json")
    baseline, candidate = read(source / "baseline-plan.json"), read(source / "dance-plan.json")
    verify_plan(baseline, candidate, contract["baseline_performance"], contract["new_performance"], index=1)
    verify_pcm(manifest, manifest["audio"])
    graphs = {label: read(source / f"h3-{label}.json") for label in RUNS}
    for graph in graphs.values():
        if graph["26"]["class_type"] != "LoadImage":
            raise ValueError("Expected character reference at node 26")
        if graph["7"]["inputs"]["start_clip"] != 1 or graph["29"]["inputs"]["start_clip"] != 1:
            raise ValueError("Require fresh runs, never old checkpoints")
    output.mkdir(parents=True)
    if not target.exists():
        shutil.copy2(reference, target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise ValueError("Reference copy changed during preparation")
    for name in ("baseline.md", "baseline-plan.json", "dance.md", "dance-plan.json",
                 "dance-excerpt.md", "inference.json", "compiler-inference.json", "translation.json",
                 "conditions.json", "input-contract.json", "output-contract.json", "user-request.md",
                 "system-prompts.json", "baseline-request.json"):
        shutil.copy2(source / name, output / name)
    for label, graph in graphs.items():
        original = deepcopy(graph)
        graph["26"]["inputs"]["image"] = target.name
        graph["24"]["inputs"]["run_name"] = graph["21"]["inputs"]["filename"] = RUNS[label]
        expected = deepcopy(original)
        expected["26"]["inputs"]["image"] = target.name
        expected["24"]["inputs"]["run_name"] = expected["21"]["inputs"]["filename"] = RUNS[label]
        if graph != expected:
            raise ValueError("Unexpected graph changes")
        save(output / f"h3-{label}.json", graph)
    save(output / "h3-manifest.json", {**manifest, "run_names": RUNS,
        "comparison_titles": ["New ref - previous motion", "New ref - torso phrase"],
        "baseline_render_reused": False, "new_render_count": 2,
        "source": str(source), "reference_source": str(reference), "reference_snapshot": str(target),
        "reference_sha256": digest, "interrupted_run_preserved": True,
        "comparison": "same new reference for both variants; Scene 12 Performance only; saved 31B results"})
    save(output / "reference-contract.json", {
        "source": str(reference), "input_snapshot": str(target), "sha256": digest,
        "new_reference_used_by_both_variants": True, "old_checkpoint_reused": False,
        "planner_and_compiler_rerun": False, "subject_prose_unchanged": True,
        "background_reference_unchanged": True,
        "note": "The new sheet includes a shield; its effect is not isolated from the image update."})
    print(json.dumps({"prepared": True, "reference": str(target), "sha256": digest,
                      "GPU_used": False}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task", choices=("prepare", "render", "finalize"))
    p.add_argument("--source", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--reference", type=Path)
    p.add_argument("--label", choices=tuple(RUNS))
    p.add_argument("--url", default="http://127.0.0.1:8188")
    args = p.parse_args()
    if args.task == "prepare":
        if not args.source or not args.reference:
            p.error("prepare requires source and reference")
        prepare(args)
    elif args.task == "render":
        if not args.label:
            p.error("render requires label")
        render(args.output, args.label, args.url)
    else:
        finalize_middle(args)
