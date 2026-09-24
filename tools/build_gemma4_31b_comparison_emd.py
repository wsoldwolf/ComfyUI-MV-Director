"""Create full-length, inspectable 8B/Gemma EMD comparison documents.

The Gemma document is a research annotation of the five replaced action lines;
the actual rendered video uses the separately frozen English H3 Plan variant.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r"C:\Software\ComfyUI\output\mv_director\audio_reference_emd_00001.md")
DEST = ROOT / "docs/assets/research/gemma4-31b-scene-author-s2-4-2026-09-25"
ANCHOR = {
    3: "対象位置:参道脇の大樹の根元の苔；人物演技:",
    4: "対象位置:参道脇の花と苔；人物演技:",
}


def performances() -> dict[tuple[int, int], str]:
    result = {}
    for scene, count in ((3, 2), (4, 3)):
        evidence = json.loads(
            (DEST / f"scene-{scene:02d}-performance-gemma-result.json").read_text(
                encoding="utf-8"
            )
        )
        lines = evidence["response"].splitlines()
        if len(lines) != count:
            raise ValueError(f"Scene {scene} has {len(lines)} performance lines")
        for shot, line in enumerate(lines, 1):
            match = re.fullmatch(r"PERFORMANCE\t(\d+)\t(.+)", line)
            if not match or int(match.group(1)) != shot:
                raise ValueError(f"Malformed Scene {scene} Shot {shot}: {line!r}")
            result[(scene, shot)] = match.group(2)
    return result


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    original = source.splitlines(keepends=True)
    replacement = performances()
    changed = []
    scene = shot = 0
    first_body = False
    variant = []
    for line in original:
        scene_match = re.match(r"> `シーン` (\d+)$", line.strip())
        if scene_match:
            scene = int(scene_match.group(1))
            shot = 0
        elif line.startswith("## ショット "):
            shot += 1
            first_body = True
        if first_body and line.startswith("* ") and (scene, shot) in replacement:
            variant.append(f"* {ANCHOR[scene]}{replacement[(scene, shot)]}\n")
            changed.append((scene, shot))
            first_body = False
        else:
            variant.append(line)
    if set(changed) != set(replacement) or len(changed) != len(replacement):
        raise ValueError(f"EMD action coverage mismatch: {changed!r}")
    baseline_path = DEST / "qwen3-8b-full.emd.md"
    variant_path = DEST / "gemma4-31b-body-full.emd.md"
    baseline_path.write_text("".join(original), encoding="utf-8")
    variant_path.write_text("".join(variant), encoding="utf-8")
    diff = difflib.unified_diff(
        original, variant,
        fromfile=baseline_path.name, tofile=variant_path.name,
    )
    (DEST / "emd-body-diff.patch").write_text("".join(diff), encoding="utf-8")
    print(f"Replaced {len(changed)} EMD action lines: {changed}")


if __name__ == "__main__":
    main()
