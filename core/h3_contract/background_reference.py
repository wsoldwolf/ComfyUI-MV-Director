"""Deterministic video-time binding of an H3 background Picture reference."""

from __future__ import annotations

import json
from typing import Any


_SUBJECT_HEADING = "subject_definitions:"
_RETENTION_HEADING = "retention_analysis:"


def build_environment_definition(picture: str, description: str = "") -> str:
    description_text = description.strip()
    observed = f" Observed scene content: {description_text}." if description_text else ""
    return (
        f"{picture} is the environment reference:{observed} Use only its stable "
        "architecture, vegetation, terrain, materials, and spatial identity as "
        "background evidence. It is not a Subject, performer, storyboard, panel "
        "layout, framing template, or lighting authority. Render one unified "
        "full-frame environment and never reproduce people, characters, poses, "
        "text, borders, split views, or inset compositions from this Picture. "
        "The written Scene environment and time-lighting directions are authoritative "
        "and replace every conflicting season, weather, time of day, illumination, "
        "camera angle, and composition visible in this Picture. Preserve functional "
        "spatial topology: keep paths, shrine approaches, stairs, doorways, and other "
        "circulation routes open and unobstructed. Fixed fixtures such as stone "
        "lanterns, lamps, posts, signs, and statues remain beside or outside the "
        "circulation route where established; never relocate one onto the centerline "
        "or directly into the Subject's travel path. When a Shot calls for interaction "
        "with a fixed fixture, move the Subject toward the fixture at the path edge "
        "instead of moving the fixture toward the Subject."
    )


def build_environment_retention(picture: str) -> str:
    return (
        f"{picture}: environment_partially_preserved - preserve stable architecture, "
        "vegetation, terrain, materials, spatial identity, open circulation routes, "
        "and the established placement of fixed fixtures only; restage framing and "
        "lighting for the current Shot and obey the written Scene environment and "
        "time-lighting directions."
    )


def _section_end(prompt: list[str], heading_index: int) -> int:
    index = heading_index + 1
    while index < len(prompt):
        value = prompt[index]
        if value == "":
            break
        if value.endswith(":"):
            break
        index += 1
    return index


def _replace_contract_line(
    prompt: list[str], *, heading: str, prefix: str, line: str
) -> None:
    try:
        heading_index = prompt.index(heading)
    except ValueError as exc:
        raise ValueError(f"H3 shot prompt is missing {heading}") from exc
    end = _section_end(prompt, heading_index)
    prompt[heading_index + 1 : end] = [
        value
        for value in prompt[heading_index + 1 : end]
        if not value.startswith(prefix)
    ]
    end = _section_end(prompt, heading_index)
    prompt.insert(end, line)


def bind_h3_background_reference(
    plan_json: str, *, picture_index: int = 2
) -> tuple[str, int]:
    """Insert an explicit environment-only Picture contract into every Shot.

    This operation is intentionally performed after planning and compilation.
    It changes no Scene, Shot, action, camera, timing, or audio field.
    """

    if not isinstance(plan_json, str) or not plan_json.strip():
        raise ValueError("plan_json must be a nonempty JSON string")
    if (
        not isinstance(picture_index, int)
        or isinstance(picture_index, bool)
        or not 1 <= picture_index <= 9
    ):
        raise ValueError("picture_index must be in 1..9")
    try:
        plan: Any = json.loads(plan_json)
    except (TypeError, ValueError) as exc:
        raise ValueError("plan_json must contain valid JSON") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("shots"), list):
        raise ValueError("plan_json must contain a shots array")

    picture = f"<Picture {picture_index}>"
    definition_prefix = f"{picture} is the environment reference:"
    retention_prefix = f"{picture}: environment_partially_preserved -"
    definition = build_environment_definition(picture)
    retention = build_environment_retention(picture)

    bound = 0
    for shot_index, shot in enumerate(plan["shots"]):
        if not isinstance(shot, dict) or not isinstance(shot.get("prompt"), list):
            raise ValueError(f"shots[{shot_index}].prompt must be an array")
        if not all(isinstance(value, str) for value in shot["prompt"]):
            raise ValueError(f"shots[{shot_index}].prompt must contain strings")
        prompt = list(shot["prompt"])
        _replace_contract_line(
            prompt,
            heading=_SUBJECT_HEADING,
            prefix=definition_prefix,
            line=definition,
        )
        _replace_contract_line(
            prompt,
            heading=_RETENTION_HEADING,
            prefix=retention_prefix,
            line=retention,
        )
        shot["prompt"] = prompt
        bound += 1

    return (
        json.dumps(
            plan,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        bound,
    )


__all__ = [
    "bind_h3_background_reference",
    "build_environment_definition",
    "build_environment_retention",
]
