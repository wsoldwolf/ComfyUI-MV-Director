"""Environment-only H3 Picture reference prompt contracts."""

from __future__ import annotations


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


__all__ = [
    "build_environment_definition",
    "build_environment_retention",
]
