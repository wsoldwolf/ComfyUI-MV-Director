"""Direction profiles loaded from external EMD files."""

from __future__ import annotations

from .profile_loader import PROFILE_ROOT, load_direction_profiles


_CATALOG = load_direction_profiles(PROFILE_ROOT)

STYLE_PROFILES = _CATALOG.style
MOTION_PROFILES = _CATALOG.motion
CAMERA_PROFILES = _CATALOG.camera
LOCKED_STYLE_PROFILES = _CATALOG.locked_style
STYLE_RETENTION_POLICIES = _CATALOG.style_retention
STYLE_SCENE_REINFORCEMENTS = _CATALOG.style_scene_reinforcement


# Presets only group three independently selectable external profiles. They are
# not a second source of prompt text.
DIRECTION_PRESETS = {
    "anime_emotional": (
        "reference_anime",
        "anime_mv",
        "anime_mv",
    ),
    "cinematic_anime_mv": (
        "anime_mv",
        "anime_mv",
        "anime_mv",
    ),
    "cinema_mv": (
        "anime_mv",
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
