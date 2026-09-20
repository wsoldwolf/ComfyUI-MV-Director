"""Direction profiles loaded from external EMD files."""

from __future__ import annotations

from .profile_loader import PROFILE_ROOT, load_direction_profiles


_CATALOG = load_direction_profiles(PROFILE_ROOT)

STYLE_PROFILES = _CATALOG.style
MOTION_PROFILES = _CATALOG.motion
MOTION_PERFORMANCE_MODES = _CATALOG.motion_performance_mode
CAMERA_PROFILES = _CATALOG.camera
LOCKED_STYLE_PROFILES = _CATALOG.locked_style
STYLE_RETENTION_POLICIES = _CATALOG.style_retention
STYLE_SCENE_REINFORCEMENTS = _CATALOG.style_scene_reinforcement
CAMERA_PLANNER_POLICIES = _CATALOG.camera_planner_policy
CAMERA_LYRIC_CUE_MODES = _CATALOG.camera_lyric_cue_mode
CAMERA_LYRIC_INTERPRETATIONS = _CATALOG.camera_lyric_interpretation
CAMERA_PRIORITY_LYRIC_CUES = _CATALOG.camera_priority_lyric_cues


def planner_profile_metadata(profile_id: str, motion_profile_id: str = "") -> dict[str, object]:
    """Cache identity includes metadata that is not part of Direction prose."""
    cues = CAMERA_PRIORITY_LYRIC_CUES.get(profile_id, ())
    return {
        "performance_mode": MOTION_PERFORMANCE_MODES.get(motion_profile_id, "event_based"),
        "planner_policy": CAMERA_PLANNER_POLICIES.get(profile_id, ""),
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
