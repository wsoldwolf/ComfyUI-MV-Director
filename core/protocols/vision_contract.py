"""Constants for the fixed-order Vision protocol implemented in Phase 3."""

from __future__ import annotations


VISION_PROTOCOL_ID = "MVD_VISION_OBSERVATION_LINES_V2"
VISION_END_MARKER = "END_MVD_VISION_OBSERVATION"
VISION_REPEATABLE_TYPES = frozenset(
    {"SUBJECT_FEATURE", "SCENE_ELEMENT", "VISIBLE_TEXT", "UNCERTAINTY"}
)
VISION_SINGLETON_ORDER = (
    "OVERVIEW",
    "PRIMARY_SUBJECT",
    "HINT_STATUS",
    "HINT_REASON",
    "SUBJECT_POSE",
    "SCENE_SETTING",
    "LIGHTING",
    "TIME_WEATHER",
    "SHOT_SIZE",
    "VIEWPOINT",
    "SUBJECT_PLACEMENT",
    "DEPTH",
    "STYLE_MEDIUM",
    "STYLE_RENDERING",
    "STYLE_PALETTE",
)
VISION_COMPOSITION_KEYS = (
    "shot_size",
    "viewpoint",
    "subject_placement",
    "depth",
)
VISION_STYLE_KEYS = ("medium", "rendering", "palette")
