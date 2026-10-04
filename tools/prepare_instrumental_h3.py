"""Build P2 H3 API graphs from the current video WF and live node schema."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import subprocess
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.analyze_audio_activity import decode_audio


def render(comparison, label, url):
    submission_path = comparison / f"submission-{label}.json"
    if submission_path.exists():
        raise ValueError("Already submitted; inspect the recorded job instead of duplicating it")
    with urlopen(url + "/queue", timeout=30) as response:
        queue = json.load(response)
    if queue["queue_running"] or queue["queue_pending"]:
        raise ValueError("ComfyUI is busy; existing jobs left intact")
    graph = json.loads((comparison / f"h3-{label}.json").read_text(encoding="utf-8"))
    request = Request(url + "/prompt", data=json.dumps({"prompt": graph}).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            submission = json.load(response)
    except HTTPError as error:
        print(error.read().decode(), flush=True)
        raise
    submission_path.write_text(json.dumps(submission, indent=2), encoding="utf-8")
    prompt_id = submission["prompt_id"]
    print(f"Submitted {label}: {prompt_id}", flush=True)
    start = time.monotonic()
    while time.monotonic() - start < 3600:
        with urlopen(url + "/history/" + prompt_id, timeout=30) as response:
            history = json.load(response)
        if prompt_id in history:
            result = {"history": history[prompt_id], "elapsed_s": time.monotonic()-start}
            (comparison / f"render-{label}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            status = result["history"]["status"]["status_str"]
            print(f"Finished {label}: {status} elapsed={result['elapsed_s']:.1f}s", flush=True)
            if result["history"]["status"]["status_str"] != "success":
                raise RuntimeError(f"{label} failed; see the saved render history")
            return
        print(f"{label}: running {time.monotonic()-start:.0f}s", flush=True)
        time.sleep(15)
    raise TimeoutError("Render timeout; job/server left intact")


def verify_crop(comparison, attempt):
    import torch
    manifest = json.loads((comparison / f"h3-manifest-a{attempt}.json").read_text(encoding="utf-8"))
    clock = manifest["isolated_audio_clock"]
    rows = []
    for stem in ("vocal", "fullmix"):
        name = "千里の秋を駆ける_vocal.wav" if stem == "vocal" else "千里の秋を駆ける_normalized.wav"
        source, rate, _ = decode_audio(Path(r"E:\OutputCollection\Momiji2") / name, r"C:\Software\ffmpeg\bin\ffmpeg.exe")
        crop, crop_rate, digest = decode_audio(Path(r"C:\Software\ComfyUI\input") / f"mvd_p2_momiji2_{stem}_aligned.wav", r"C:\Software\ffmpeg\bin\ffmpeg.exe")
        equal = rate == crop_rate == clock["sample_rate"] and torch.equal(
            source[..., clock["source_start_sample"]:clock["source_end_sample"]], crop)
        if not equal:
            raise ValueError(f"{stem} cropped PCM differs")
        rows.append({"stem": stem, "samples": crop.shape[-1], "sha256": digest, "source_pcm_equal": equal})
    result = {"clock": clock, "verification": rows}
    path = comparison / "crop-verification.json"
    if path.exists():
        raise ValueError("Crop verification already exists")
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Both cropped PCM stems match exact source samples", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8191")
    parser.add_argument("--render", choices=("baseline", "activity"))
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--aligned-clock", action="store_true")
    parser.add_argument("--verify-crop", action="store_true")
    args = parser.parse_args()
    if args.render:
        label = args.render if args.attempt == 1 else f"{args.render}-a{args.attempt}"
        render(args.comparison, label, args.url)
        return
    if args.verify_crop:
        verify_crop(args.comparison, args.attempt)
        return
    wf = json.loads(args.workflow.read_text(encoding="utf-8-sig"))
    with urlopen(args.url + "/object_info", timeout=60) as response:
        schema = json.load(response)
    nodes = {str(n["id"]): n for n in wf["nodes"]}
    links = {r[0]: r for r in wf["links"]}
    conditions = json.loads((args.comparison / "conditions.json").read_text(encoding="utf-8"))
    slice_start = conditions["scene_start"] - 1
    crop_manifest = None
    if args.aligned_clock:
        full_plan = json.loads((args.comparison / "baseline-plan.json").read_text(encoding="utf-8"))
        shots = full_plan["shots"]
        skip = sum(s["length"] - s.get("context_length", 0) for s in shots[:slice_start])
        preroll = shots[slice_start].get("context_length", 0)
        frames = sum(s["length"] - s.get("context_length", 0) for s in shots[slice_start:slice_start+2]) + preroll
        start_sample = (skip-preroll)*2000
        end_sample = start_sample + frames*2000
        if start_sample < 0:
            raise ValueError("No actual source pre-roll available")
        crop_manifest = {"source_start_sample": start_sample, "source_end_sample": end_sample,
            "sample_rate": 48000, "render_frames": frames, "actual_source_preroll_frames": preroll,
            "reason": "First isolated Scene loses visual context; actual source pre-roll keeps the next Scene at its original audio clock"}
        for stem in ("vocal", "fullmix"):
            source_name = "千里の秋を駆ける_vocal.wav" if stem == "vocal" else "千里の秋を駆ける_normalized.wav"
            target = Path(r"C:\Software\ComfyUI\input") / f"mvd_p2_momiji2_{stem}_aligned.wav"
            if target.exists():
                raise ValueError(f"Crop already exists: {target}")
            subprocess.run([r"C:\Software\ffmpeg\bin\ffmpeg.exe", "-v", "error", "-i",
                str(Path(r"E:\OutputCollection\Momiji2") / source_name), "-af",
                f"atrim=start_sample={start_sample}:end_sample={end_sample},asetpts=PTS-STARTPTS",
                "-c:a", "pcm_f32le", str(target)], check=True)
    assets = (
        ("33", "audio", Path(r"E:\OutputCollection\Momiji2\千里の秋を駆ける_vocal.wav"), "mvd_p2_momiji2_vocal.wav"),
        ("32", "audio", Path(r"E:\OutputCollection\Momiji2\千里の秋を駆ける_normalized.wav"), "mvd_p2_momiji2_fullmix.wav"),
        ("26", "image", Path(r"E:\OutputCollection\Momiji\image_char.webp"), "mvd_p2_momiji_char.webp"),
        ("45", "image", Path(r"E:\OutputCollection\Momiji\image_scene.webp"), "mvd_p2_momiji_scene.webp"),
    )
    evidence = []
    for _, _, source, name in assets:
        target = Path(r"C:\Software\ComfyUI\input") / name
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Asset collision: {target}")
        else:
            shutil.copy2(source, target)
        evidence.append({"source": str(source), "input_copy": str(target), "sha256": digest})

    def source_link(link_id):
        row = links[link_id]
        node = nodes[str(row[1])]
        if node.get("mode", 0) == 4:
            kind = node["outputs"][row[2]]["type"]
            port = next(p for p in node["inputs"] if p["type"] == kind and p.get("link") is not None)
            return source_link(port["link"])
        return [str(row[1]), row[2]]

    primitive = {"STRING", "INT", "FLOAT", "BOOLEAN", "COMBO"}
    for label in ("baseline", "activity"):
        artifact_label = label if args.attempt == 1 else f"{label}-a{args.attempt}"
        plan = json.loads((args.comparison / f"{label}-plan.json").read_text(encoding="utf-8"))
        if args.aligned_clock:
            plan["shots"] = plan["shots"][slice_start:slice_start+2]
        graph = {}
        def visit(key):
            if key in graph:
                return
            node = nodes[key]
            info = schema[node["type"]]
            inputs = {}
            sockets = {p["name"]: p for p in node.get("inputs", [])}
            widgets = iter(node.get("widgets_values", []) or [])
            for section in ("required", "optional"):
                for name, spec in info["input"].get(section, {}).items():
                    kind = spec[0]
                    opts = spec[1] if len(spec) > 1 else {}
                    if kind == "COMFY_DYNAMICCOMBO_V3":
                        selected = next(widgets)
                        inputs[name] = selected
                        option = next(o for o in opts["options"] if o["key"] == selected)
                        for child, child_spec in option["inputs"].get("required", {}).items():
                            inputs[f"{name}.{child}"] = next(widgets, child_spec[1].get("default"))
                    if isinstance(kind, list) or (isinstance(kind, str) and kind in primitive and not opts.get("forceInput")):
                        value = next(widgets, opts.get("default"))
                        inputs[name] = value
                        if opts.get("control_after_generate"):
                            next(widgets, None)
                    port = sockets.get(name)
                    if port and port.get("link") is not None:
                        inputs[name] = source_link(port["link"])
            # Flattened Autogrow slots are represented directly in the API.
            for name, port in sockets.items():
                if name not in inputs and port.get("link") is not None:
                    inputs[name] = source_link(port["link"])
            if key in ("24", "37", "48"):
                inputs["plan_json"] = json.dumps(plan, ensure_ascii=False)
            if key == "24":
                inputs.update(run_name=f"instrumental-p2-momiji2-{artifact_label}-20261003", default_steps=20)
                inputs["plan_json_input"] = ["48", 0]
            if key == "48":
                inputs.update(enable=not args.aligned_clock, scene_start=conditions["scene_start"], scene_length=2)
            if key == "37":
                inputs.pop("timeline", None)
            if key in ("7", "29"):
                inputs.update(start_clip=1, scene_range="")
            if key == "28":
                inputs["enabled"] = False
            if key == "21":
                inputs["filename"] = f"instrumental-p2-momiji2-{artifact_label}-20261003"
            if key == "47":
                inputs["megapixels"] = 0.4
            for asset_key, field, _, name in assets:
                if key == asset_key:
                    inputs[field] = name
            if args.aligned_clock and key in ("32", "33"):
                stem = "fullmix" if key == "32" else "vocal"
                inputs["audio"] = f"mvd_p2_momiji2_{stem}_aligned.wav"
            graph[key] = {"class_type": node["type"], "inputs": inputs}
            for value in inputs.values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in nodes:
                    visit(value[0])
        visit("21")
        if "44" in graph:
            raise ValueError("Turbo LoRA bypass was not preserved")
        if graph["40"]["inputs"]["voice"] != ["48", 1]:
            raise ValueError("Standard Context Loop vocal input was lost")
        target = args.comparison / f"h3-{artifact_label}.json"
        if (args.comparison / f"submission-{artifact_label}.json").exists():
            raise ValueError("Do not replace a submitted comparison graph")
        target.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {"workflow": str(args.workflow), "assets": evidence, "conditions": conditions,
                "isolated_audio_clock": crop_manifest,
                "megapixels": 0.4, "default_steps": 20, "turbo_lora": False,
                "standard_context_loop_lip_sync": True}
    manifest_name = "h3-manifest.json" if args.attempt == 1 else f"h3-manifest-a{args.attempt}.json"
    (args.comparison / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Current-WF graphs ready; no rendering submitted")


if __name__ == "__main__":
    main()
