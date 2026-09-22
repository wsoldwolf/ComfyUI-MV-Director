"""Direction profiles loaded from external EMD files."""

from __future__ import annotations

from .profile_loader import PROFILE_ROOT, load_direction_profiles


_CATALOG = load_direction_profiles(PROFILE_ROOT)

STYLE_PROFILES = _CATALOG.style
MOTION_PROFILES = _CATALOG.motion
MOTION_PERFORMANCE_MODES = _CATALOG.motion_performance_mode
MOTION_BODY_ACCENT_POLICIES = _CATALOG.motion_body_accent_policy
MOTION_CHOREOGRAPHY_POLICIES = _CATALOG.motion_choreography_policy
MOTION_CHOREOGRAPHY_PHRASES = _CATALOG.motion_choreography_phrases
CAMERA_PROFILES = _CATALOG.camera
LOCKED_STYLE_PROFILES = _CATALOG.locked_style
STYLE_RETENTION_POLICIES = _CATALOG.style_retention
STYLE_SCENE_REINFORCEMENTS = _CATALOG.style_scene_reinforcement
CAMERA_PLANNER_POLICIES = _CATALOG.camera_planner_policy
CAMERA_ARC_ROLL_POLICIES = _CATALOG.camera_arc_roll_policy
CAMERA_LYRIC_CUE_MODES = _CATALOG.camera_lyric_cue_mode
CAMERA_LYRIC_INTERPRETATIONS = _CATALOG.camera_lyric_interpretation
CAMERA_PRIORITY_LYRIC_CUES = _CATALOG.camera_priority_lyric_cues
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
    cues = CAMERA_PRIORITY_LYRIC_CUES.get(profile_id, ())
    return {
        "render_prompts": {
            "camera": RENDER_PROMPTS.get("camera", {}).get(profile_id, ""),
            "motion": RENDER_PROMPTS.get("motion", {}).get(motion_profile_id, ""),
        },
        "performance_mode": MOTION_PERFORMANCE_MODES.get(motion_profile_id, "event_based"),
        "body_accent_policy": MOTION_BODY_ACCENT_POLICIES.get(motion_profile_id, "off"),
        "choreography_policy": MOTION_CHOREOGRAPHY_POLICIES.get(motion_profile_id, "off"),
        "choreography_phrases": [
            {"id": phrase_id, "body_path": body_path}
            for phrase_id, body_path in MOTION_CHOREOGRAPHY_PHRASES.get(motion_profile_id, ())
        ],
        "planner_policy": CAMERA_PLANNER_POLICIES.get(profile_id, ""),
        "arc_roll_policy": CAMERA_ARC_ROLL_POLICIES.get(profile_id, "off"),
        "lyric_cue_mode": CAMERA_LYRIC_CUE_MODES.get(
            profile_id, "priority_only" if cues else "off"
        ),
        "lyric_interpretation": CAMERA_LYRIC_INTERPRETATIONS.get(profile_id, "literal"),
        "priority_lyric_cues": [
            {"token": token, "kind": kind} for token, kind in cues
        ],
    }


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
