"""Export archived real-8B Scene Author calls for a Gemma 4 31B comparison.

This is a research fixture, not a replacement for the production Planner. The
archived requests were made by an offline P1b 8B run on the same song and
Scenes 2-4 as the audio_ref_compact_s2_4_20260924 H3 comparison. They are not
claimed to be the exact requests of that separate production video run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "docs/assets/research/scene-composition-full-sequence-2026-09-23"
    / "p1b-six-scenes-seed2-v2/summary.json"
)
PROMPTS = ROOT / "prompts/experiments"
DEST = ROOT / "docs/assets/research/gemma4-31b-scene-author-s2-4-2026-09-25"
STAGES = ("event", "performance", "camera")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    source = json.loads(source_bytes)
    assert source["model"] == "qwen3-8b-abliterated-Q4_K_M.gguf"
    assert source["complete"] is True
    assert source["p1b"] is True
    assert source["seed"] == 2

    DEST.mkdir(parents=True, exist_ok=True)
    prompts: dict[str, str] = {}
    for stage in STAGES:
        prompt = (PROMPTS / f"scene_author_p1b_{stage}.txt").read_text(
            encoding="utf-8"
        )
        prompts[stage] = prompt
        (DEST / f"system-{stage}.txt").write_text(prompt, encoding="utf-8")

    calls = []
    seen: set[tuple[int, str]] = set()
    for trace in source["trace"]:
        task = trace["task"]
        if not task.startswith("scene-author-"):
            continue
        stage = task.removeprefix("scene-author-")
        if stage not in STAGES:
            continue
        payload = trace["payload"]
        scene = json.loads(payload)["scene_number"]
        if scene not in (2, 3, 4):
            continue
        key = (scene, stage)
        if key in seen:
            raise ValueError(f"Repeated call: {key}")
        seen.add(key)
        stem = f"scene-{scene:02d}-{stage}"
        # The original Qwen user message had this model-specific control line.
        # Gemma receives the same JSON payload without that control line.
        (DEST / f"{stem}-8b-user.txt").write_text(
            "/no_think\n" + payload, encoding="utf-8"
        )
        (DEST / f"{stem}-gemma-user.txt").write_text(
            payload, encoding="utf-8"
        )
        (DEST / f"{stem}-8b-response.txt").write_text(
            trace["response"], encoding="utf-8"
        )
        calls.append(
            {
                "scene": scene,
                "stage": stage,
                "system": f"system-{stage}.txt",
                "gemma_user": f"{stem}-gemma-user.txt",
                "qwen_8b_user": f"{stem}-8b-user.txt",
                "qwen_8b_response_holdout": f"{stem}-8b-response.txt",
                "payload_sha256": sha256(payload.encode("utf-8")),
            }
        )

    expected = {(scene, stage) for scene in (2, 3, 4) for stage in STAGES}
    if seen != expected:
        raise ValueError(f"Unexpected scene/stage coverage: {seen ^ expected}")
    manifest = {
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": sha256(source_bytes),
        "source_model": source["model"],
        "source_seed": source["seed"],
        "source_kind": "archived_offline_real_8b_p1b_probe",
        "not_exact_video_production_trace": True,
        "calls": sorted(calls, key=lambda call: (call["scene"], STAGES.index(call["stage"]))),
    }
    (DEST / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
