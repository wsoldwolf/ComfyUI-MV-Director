"""Reading context from ordered Template annotations; never generated prose.

EMD currently preserves section labels, not original heading occurrence IDs.
Only contiguous label runs can therefore be identified reliably. Adjacent
same-named headings cannot be recovered from this representation.
"""

from __future__ import annotations

from typing import Any

from .template import PlannerTemplate


def section_context_by_scene(template: PlannerTemplate) -> dict[int, list[dict[str, Any]]]:
    groups: list[dict[str, Any]] = []
    active_key: object = object()
    occurrences: dict[str, int] = {}
    for scene in template.scenes:
        for shot in scene.shots:
            for lyric in shot.lyric_annotations:
                label = lyric.section or ""
                # Unlabelled source must not become an invented whole-song section.
                key = label if label else ("unlabelled", scene.scene_number)
                if key != active_key:
                    occurrences[label] = occurrences.get(label, 0) + 1
                    groups.append({
                        "section": label,
                        "occurrence": occurrences[label],
                        "boundary_source": "template_label_run",
                        "coverage": "available_run",
                        "lines": [],
                    })
                    active_key = key
                groups[-1]["lines"].append({
                    "source_line": lyric.line_number,
                    "scene": scene.scene_number,
                    "start_ms": lyric.start_ms,
                    "end_ms": lyric.end_ms,
                    "text": lyric.text,
                })
    contexts = {
        scene.scene_number: [
            group for group in groups
            if any(line["scene"] == scene.scene_number for line in group["lines"])
        ]
        for scene in template.scenes
    }
    # Silence has no current lyric annotations. Only the opt-in activity path
    # supplies a small neighboring reading scope, never an invented sung line.
    if template.audio_activity is not None:
        for scene in template.scenes:
            if contexts[scene.scene_number]:
                continue
            before = [g for g in groups if g["lines"][-1]["scene"] < scene.scene_number]
            after = [g for g in groups if g["lines"][0]["scene"] > scene.scene_number]
            for role, candidates in (("previous_lyrics", before[-1:]), ("following_lyrics", after[:1])):
                for group in candidates:
                    lines = group["lines"][-4:] if role == "previous_lyrics" else group["lines"][:4]
                    contexts[scene.scene_number].append({**group, "lines": lines,
                        "coverage": "neighbor_excerpt", "role": role, "reading_only": True})
    return contexts


def reduce_section_context(request: dict[str, Any]) -> dict[str, Any] | None:
    """Remove distant optional lines on token overflow, keeping source intact."""
    groups = request.get("section_lyric_context")
    scene = request.get("scene_number")
    if not isinstance(groups, list) or not isinstance(scene, int):
        return None
    optional: list[tuple[int, int, int]] = []
    for group_index, group in enumerate(groups):
        lines = group.get("lines", [])
        focus = [index for index, line in enumerate(lines) if line["scene"] == scene]
        if not focus:
            continue
        for index, line in enumerate(lines):
            if line["scene"] != scene:
                optional.append((min(abs(index - center) for center in focus), group_index, index))
    if not optional:
        return None
    removed = {(group, index) for _, group, index in sorted(optional, reverse=True)[:(len(optional) + 1) // 2]}
    reduced = []
    for group_index, group in enumerate(groups):
        lines = group["lines"]
        kept = [line for index, line in enumerate(lines) if (group_index, index) not in removed]
        reduced.append({
            **group,
            "lines": kept,
            "coverage": "partial",
            "omitted_lines": group.get("omitted_lines", 0) + len(lines) - len(kept),
        })
    return {**request, "section_lyric_context": reduced}
