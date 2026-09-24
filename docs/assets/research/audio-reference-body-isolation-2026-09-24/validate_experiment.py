"""CPU-only structural check for the audio-reference body-motion A/B EMDs.

Run from the repository root:
    python docs/assets/research/audio-reference-body-isolation-2026-09-24/validate_experiment.py

IdentityTranslator tests structure only. Its Plan is not an English H3 render Plan.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[3]))

from core.compiler import compile_ref2va
from core.compiler.translator import IdentityTranslator
from core.emd import parse_emd


BASELINE = ROOT / "baseline.md"
VARIANT = ROOT / "body-variant.md"
TARGET_SHOTS = {3: 2, 4: 3, 9: 2}
TARGET_PLAN_LINES = {scene: shots + 1 for scene, shots in TARGET_SHOTS.items()}
EVENT_ANCHORS = (
    ("対象位置:苔；人物位置:大樹の根元", "指先で苔を撫でる"),
    ("対象位置:苔；人物位置:大樹の根元", "手を離す"),
    ("対象位置:花と苔の間；人物位置:石畳の上から", "花を軽く揺すぶる"),
    ("花を放す", "花が散るように自然に動かす"),
    ("花が散るのを見守る", "花が苔に落ちる"),
    ("対象位置:狐火；人物位置:参道の石畳の上", "左手を胸の高さで軽く振る"),
    ("対象位置:狐火；人物位置:参道の石畳の上", "狐火が人物の周囲を旋回し、赤い光が舞う"),
)


def _changed_lines(before: str, after: str) -> list[tuple[str, str]]:
    old_lines = before.splitlines()
    new_lines = after.splitlines()
    changes: list[tuple[str, str]] = []
    for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(
        None, old_lines, new_lines, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        assert tag == "replace" and a1 - a0 == b1 - b0 == 1, (
            tag,
            (a0, a1),
            (b0, b1),
        )
        old, new = old_lines[a0], new_lines[b0]
        assert old.startswith("* ") and new.startswith("* "), (old, new)
        assert not old.startswith("* `") and not new.startswith("* `"), (old, new)
        assert not old.startswith("* Arc Shot") and not new.startswith("* Arc Shot")
        changes.append((old, new))
    return changes


def main() -> None:
    before = BASELINE.read_text(encoding="utf-8")
    after = VARIANT.read_text(encoding="utf-8")
    changes = _changed_lines(before, after)
    assert len(changes) == 7, len(changes)
    for (old, new), anchors in zip(changes, EVENT_ANCHORS, strict=True):
        assert all(anchor in old and anchor in new for anchor in anchors), (
            anchors,
            old,
            new,
        )

    old_doc = parse_emd(before)
    new_doc = parse_emd(after)
    assert len(old_doc.scenes) == len(new_doc.scenes) == 16
    assert sum(len(scene.shots) for scene in old_doc.scenes) == 30
    assert sum(len(scene.shots) for scene in new_doc.scenes) == 30

    # This mock translator deliberately leaves Japanese intact: it only proves
    # that the compiler transports the seven edited Shot bodies and no other
    # Plan fields. A real H3 A/B still needs the normal English translator.
    old_plan = compile_ref2va(before, IdentityTranslator()).plan
    new_plan = compile_ref2va(after, IdentityTranslator()).plan
    assert old_plan["defaults"] == new_plan["defaults"]
    assert old_plan.get("prompt_prefix") == new_plan.get("prompt_prefix")
    plan_changes: dict[int, int] = {}
    for scene_number, (old_scene, new_scene) in enumerate(
        zip(old_plan["shots"], new_plan["shots"], strict=True), start=1
    ):
        assert old_scene.keys() == new_scene.keys()
        assert {
            key: value for key, value in old_scene.items() if key != "prompt"
        } == {
            key: value for key, value in new_scene.items() if key != "prompt"
        }, scene_number
        old_prompt = old_scene["prompt"]
        new_prompt = new_scene["prompt"]
        assert len(old_prompt) == len(new_prompt), scene_number
        changed_prompt_lines = [
            (old_line, new_line)
            for old_line, new_line in zip(old_prompt, new_prompt, strict=True)
            if old_line != new_line
        ]
        if changed_prompt_lines:
            plan_changes[scene_number] = len(changed_prompt_lines)
            assert changed_prompt_lines[0][0].startswith("[reference generation] ")
            assert changed_prompt_lines[0][1].startswith("[reference generation] ")
            assert all(
                old_line.startswith("[Shot ") and new_line.startswith("[Shot ")
                for old_line, new_line in changed_prompt_lines[1:]
            ), scene_number
    assert plan_changes == TARGET_PLAN_LINES, plan_changes
    print(
        json.dumps(
            {
                "result": "pass",
                "edited_emd_lines": len(changes),
                "scenes": len(old_doc.scenes),
                "shots": sum(len(scene.shots) for scene in old_doc.scenes),
                "changed_plan_prompt_lines_by_scene": plan_changes,
                "translator": "IdentityTranslator (structural only)",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
