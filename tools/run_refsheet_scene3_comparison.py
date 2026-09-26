"""Replay the saved Scene 3 clip with old and reference-sheet Picture 1.

The Plan, seed, model, background, vocal, and 0.4 MP settings are inherited
from the frozen nine-candidate API graph. Both variants run on the same live
ComfyUI/Context Loop installation so the image is the only A/B variable.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/assets/research/gemma4-31b-nine-candidate-h3-2026-09-25/h3-api-prompt.json"
DEST = ROOT / "docs/assets/research/refsheet-scene3-ab-2026-09-25"
INPUT_ROOT = Path(r"C:\Software\ComfyUI\input")
IMAGES = {
    "original": "image001_mikofox.jpg",
    "refsheet": "image001_mikofox_ref.jpg",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def graph_for(variant: str) -> dict:
    if variant not in IMAGES:
        raise ValueError(f"unknown variant: {variant}")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert source["26"]["class_type"] == "LoadImage"
    assert source["26"]["inputs"]["image"] == IMAGES["original"]
    assert source["48"]["class_type"] == "MVDirectorSceneDebugSplitter"
    assert source["48"]["inputs"]["scene_start"] == 3
    assert source["48"]["inputs"]["scene_length"] == 7
    assert source["49"]["inputs"]["seed"] == 42
    assert source["47"]["inputs"]["megapixels"] == 0.4
    image = IMAGES[variant]
    if sha256(INPUT_ROOT / image) != sha256(ROOT / "assets/image" / image):
        raise ValueError(f"ComfyUI input does not match repository asset: {image}")

    result = copy.deepcopy(source)
    run_name = f"gemma31b_scene3_{variant}_04mp_20260925"
    result["26"]["inputs"]["image"] = image
    result["48"]["inputs"]["scene_length"] = 1
    result["24"]["inputs"]["run_name"] = run_name
    result["21"]["inputs"]["filename"] = run_name
    return result


def prepare(variant: str) -> Path:
    result = graph_for(variant)
    path = DEST / f"{variant}-api-prompt.json"
    write_json(path, result)
    write_json(DEST / f"{variant}-manifest.json", {
        "source_graph": str(SOURCE),
        "source_graph_sha256": sha256(SOURCE),
        "request_sha256": sha256(path),
        "reference_image": IMAGES[variant],
        "reference_sha256": sha256(INPUT_ROOT / IMAGES[variant]),
        "scene_start": 3,
        "scene_length": 1,
        "seed": 42,
        "megapixels": 0.4,
        "run_name": result["24"]["inputs"]["run_name"],
        "changes_from_source": [
            "Picture 1 image" if variant == "refsheet" else "none",
            "Scene Debug Splitter scene_length 7->1",
            "run_name and output filename",
        ],
    })
    print(path, flush=True)
    return path


def submit(variant: str) -> None:
    path = DEST / f"{variant}-api-prompt.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    payload = json.dumps({"prompt": graph, "client_id": f"mv-director-refsheet-{variant}"}, ensure_ascii=False).encode("utf-8")
    request = Request("http://127.0.0.1:8188/prompt", data=payload,
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    write_json(DEST / f"{variant}-submission.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "submit"))
    parser.add_argument("variant", choices=tuple(IMAGES))
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare(args.variant)
    else:
        submit(args.variant)


if __name__ == "__main__":
    main()
