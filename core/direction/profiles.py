"""Direction profiles loaded from external EMD files."""

from __future__ import annotations

from .profile_loader import PROFILE_ROOT, load_direction_profiles


_CATALOG = load_direction_profiles(PROFILE_ROOT)

STYLE_PROFILES = _CATALOG.style
MOTION_PROFILES = _CATALOG.motion
MOTION_COMPOSITION_TIMINGS = _CATALOG.motion_composition_timing
MOTION_COMPOSITION_RESELECTIONS = _CATALOG.motion_composition_reselection
MOTION_TEMPLATES = _CATALOG.motion_templates
CAMERA_PROFILES = _CATALOG.camera
LOCKED_STYLE_PROFILES = _CATALOG.locked_style
STYLE_RETENTION_POLICIES = _CATALOG.style_retention
STYLE_SCENE_REINFORCEMENTS = _CATALOG.style_scene_reinforcement
CAMERA_ARC_ROLL_POLICIES = _CATALOG.camera_arc_roll_policy
RENDER_PROMPTS = _CATALOG.render_prompts


def render_profile_direction(kind: str, profile_id: str, values: tuple[str, ...]) -> tuple[str, ...]:
    """Project only exact profile-owned prose; never rewrite authored/LLM text."""
    source = {"motion": MOTION_PROFILES, "camera": CAMERA_PROFILES}[kind].get(profile_id)
    target = RENDER_PROMPTS.get(kind, {}).get(profile_id)
    if not source or not target:
        return values
    return tuple(target if value == source else value for value in values)


def planner_profile_metadata(profile_id: str, motion_profile_id: str = "") -> dict[str, object]:
    """Cache identity includes metadata that is not part of Direction prose."""
    metadata = {
        "strategy": "scene_author",
        "render_prompts": {
            "camera": RENDER_PROMPTS.get("camera", {}).get(profile_id, ""),
            "motion": RENDER_PROMPTS.get("motion", {}).get(motion_profile_id, ""),
        },
        "motion_templates": list(MOTION_TEMPLATES.get(motion_profile_id, ())),
        "composition_timing": MOTION_COMPOSITION_TIMINGS.get(motion_profile_id, "pre_author"),
        "arc_roll_policy": CAMERA_ARC_ROLL_POLICIES.get(profile_id, "off"),
    }
    reselection = MOTION_COMPOSITION_RESELECTIONS.get(motion_profile_id, "off")
    if reselection != "off":
        metadata["composition_reselection"] = reselection
    return metadata


# Presets only group three independently selectable external profiles. They are
# not a second source of prompt text.
DIRECTION_PRESETS = {
    "anime_emotional": (
        "anime_emotional_mv",
        "anime_emotional_mv",
        "anime_emotional_mv",
    ),
    "cinematic_anime_story_mv": (
        "anime_story_mv",
        "anime_story_mv",
        "anime_story_mv",
    ),
    "cinema_mv": (
        "anime_story_mv",
        "cinema_mv",
        "cinema_mv",
    ),
    "cinematic_performance": (
        "reference_cinematic",
        "natural_performance",
        "readable_depth",
    ),
    "painterly_mv": (
        "reference_painterly",
        "natural_performance",
        "cinematic_depth",
    ),
}
