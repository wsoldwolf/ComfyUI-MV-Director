"""Strict loader for user-extensible Direction profile EMD files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from ..artifacts import normalize_newlines
from ..emd.common import CommonPromptError, parse_common_prompt_fragment
from ..emd.motion_templates import split_motion_templates


PROFILE_ROOT = Path(__file__).resolve().parents[2] / "profiles"
_PROFILE_ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
_META_RE = re.compile(r"\* `([a-z_]+)`\s+(.+)\Z")
_KIND_HEADINGS = {
    "style": "スタイル",
    "motion": "モーション",
    "camera": "カメラ",
}
_STYLE_META_KEYS = frozenset({"locked", "retention", "scene_reinforcement"})
_MOTION_META_KEYS = frozenset({"composition_timing", "composition_reselection", "render_prompt"})
_CAMERA_META_KEYS = frozenset({"arc_roll_policy", "render_prompt"})
_META_KEYS = _STYLE_META_KEYS | _CAMERA_META_KEYS | _MOTION_META_KEYS
_RETIRED_META_KEYS = frozenset({
    "performance_mode", "body_accent_policy", "choreography_policy",
    "planner_policy", "arc_tilt_policy", "camera_render_style",
    "lyric_cue_mode", "priority_lyric_cues", "lyric_interpretation",
})
_COMPOSITION_TIMINGS = frozenset({"pre_author", "post_author"})
_COMPOSITION_RESELECTIONS = frozenset({"off", "guarded_no_drop"})
_ARC_ROLL_POLICIES = frozenset({"off", "selective_arc"})


class DirectionProfileError(ValueError):
    """Raised when an external Direction profile is malformed."""


@dataclass(frozen=True, slots=True)
class DirectionProfile:
    profile_id: str
    kind: str
    text: str
    source_path: Path
    locked: bool = False
    retention: str = ""
    scene_reinforcement: str = ""
    arc_roll_policy: str = "off"
    composition_timing: str = "pre_author"
    composition_reselection: str = "off"
    render_prompt: str = ""
    motion_templates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DirectionProfileCatalog:
    style: dict[str, str]
    motion: dict[str, str]
    camera: dict[str, str]
    locked_style: frozenset[str]
    style_retention: dict[str, str]
    style_scene_reinforcement: dict[str, str]
    camera_arc_roll_policy: dict[str, str]
    motion_composition_timing: dict[str, str]
    motion_composition_reselection: dict[str, str]
    render_prompts: dict[str, dict[str, str]]
    motion_templates: dict[str, tuple[str, ...]]


def _fail(path: Path, message: str) -> DirectionProfileError:
    return DirectionProfileError(f"{path}: {message}")


def _parse_metadata(path: Path, lines: list[str], position: int) -> tuple[dict[str, str], int]:
    metadata: dict[str, str] = {}
    while position < len(lines) and lines[position] != "# 共通プロンプト":
        match = _META_RE.fullmatch(lines[position])
        if match is None:
            raise _fail(path, f"line {position + 1}: invalid profile metadata")
        key, value = match.groups()
        if key in _RETIRED_META_KEYS:
            raise _fail(path, f"retired metadata {key!r}; remove it (Planner now uses Scene Author)")
        if key not in _META_KEYS:
            raise _fail(path, f"line {position + 1}: unknown metadata {key!r}")
        if key in metadata:
            raise _fail(path, f"line {position + 1}: duplicate metadata {key!r}")
        metadata[key] = value.strip()
        position += 1
    return metadata, position


def load_direction_profile(path: Path, kind: str) -> DirectionProfile:
    """Load one strict profile EMD document."""

    if kind not in _KIND_HEADINGS:
        raise DirectionProfileError(f"unknown Direction profile kind: {kind!r}")
    profile_id = path.stem
    if not _PROFILE_ID_RE.fullmatch(profile_id) or profile_id == "passthrough":
        raise _fail(
            path,
            "filename must be a lowercase profile id and must not be passthrough",
        )
    try:
        source = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise _fail(path, f"cannot read UTF-8 profile: {exc}") from exc
    source = normalize_newlines(source)
    try:
        source, motion_templates = split_motion_templates(source)
    except ValueError as exc:
        raise _fail(path, str(exc)) from exc
    if motion_templates is not None and kind != "motion":
        raise _fail(path, "モーション補完 is supported only by motion profiles")
    if "\x00" in source:
        raise _fail(path, "NUL is not allowed")
    if "```" in source:
        raise _fail(path, "code fences are not allowed")
    lines = [line.strip() for line in source.split("\n") if line.strip()]
    if not lines:
        raise _fail(path, "profile is empty")

    position = 0
    metadata: dict[str, str] = {}
    if lines[position] == "# プロファイル":
        metadata, position = _parse_metadata(path, lines, position + 1)
    if position >= len(lines) or lines[position] != "# 共通プロンプト":
        raise _fail(path, f"line {position + 1}: expected '# 共通プロンプト'")
    position += 1
    expected_heading = f"## {_KIND_HEADINGS[kind]}"
    if position >= len(lines) or lines[position] != expected_heading:
        raise _fail(path, f"line {position + 1}: expected {expected_heading!r}")
    position += 1
    body_lines: list[str] = []
    while position < len(lines):
        line = lines[position]
        if not line.startswith("* ") or not line[2:].strip():
            raise _fail(path, f"line {position + 1}: expected a nonempty list item")
        body_lines.append(line)
        position += 1
    try:
        common = parse_common_prompt_fragment(
            "\n".join(("# 共通プロンプト", expected_heading, *body_lines)),
            allowed_headings=frozenset({_KIND_HEADINGS[kind]}),
        )
    except CommonPromptError as exc:
        raise _fail(path, str(exc)) from exc
    body = common[0].body
    allowed_metadata = (
        _STYLE_META_KEYS
        if kind == "style"
        else _CAMERA_META_KEYS
        if kind == "camera"
        else _MOTION_META_KEYS
    )
    unsupported_metadata = set(metadata) - allowed_metadata
    if unsupported_metadata:
        labels = ", ".join(sorted(unsupported_metadata))
        raise _fail(path, f"metadata is not supported by {kind} profiles: {labels}")
    locked_value = metadata.get("locked", "false")
    if locked_value not in {"true", "false"}:
        raise _fail(path, "locked must be true or false")
    retention = metadata.get("retention", "")
    if retention and not re.match(
        r"`(?:fully_preserved|partially_preserved)`\s+.+\Z", retention
    ):
        raise _fail(
            path,
            "retention must begin with `fully_preserved` or `partially_preserved`",
        )
    arc_roll_policy = metadata.get("arc_roll_policy", "off")
    if arc_roll_policy not in _ARC_ROLL_POLICIES:
        raise _fail(path, "arc_roll_policy must be off or selective_arc")
    composition_timing = metadata.get("composition_timing", "pre_author")
    if composition_timing not in _COMPOSITION_TIMINGS:
        raise _fail(path, "composition_timing must be pre_author or post_author")
    if composition_timing != "pre_author" and not motion_templates:
        raise _fail(path, "post_author composition_timing requires モーション補完")
    composition_reselection = metadata.get("composition_reselection", "off")
    if composition_reselection not in _COMPOSITION_RESELECTIONS:
        raise _fail(path, "composition_reselection must be off or guarded_no_drop")
    if composition_reselection != "off" and composition_timing != "post_author":
        raise _fail(path, "composition_reselection requires post_author composition_timing")
    return DirectionProfile(
        profile_id=profile_id,
        kind=kind,
        text=" ".join(body),
        source_path=path,
        locked=locked_value == "true",
        retention=retention,
        scene_reinforcement=metadata.get("scene_reinforcement", ""),
        arc_roll_policy=arc_roll_policy,
        composition_timing=composition_timing,
        composition_reselection=composition_reselection,
        render_prompt=metadata.get("render_prompt", ""),
        motion_templates=motion_templates or (),
    )


def load_direction_profiles(root: Path = PROFILE_ROOT) -> DirectionProfileCatalog:
    """Load all style, motion and camera profiles below *root*."""

    grouped: dict[str, dict[str, DirectionProfile]] = {}
    for kind in _KIND_HEADINGS:
        directory = root / kind
        if not directory.is_dir():
            raise DirectionProfileError(f"missing Direction profile directory: {directory}")
        definitions: dict[str, DirectionProfile] = {}
        for path in sorted(directory.glob("*.md"), key=lambda item: item.name.casefold()):
            definition = load_direction_profile(path, kind)
            definitions[definition.profile_id] = definition
        if not definitions:
            raise DirectionProfileError(f"no {kind} profiles found in {directory}")
        grouped[kind] = definitions

    styles = grouped["style"]
    return DirectionProfileCatalog(
        motion_templates={key: value.motion_templates for key, value in grouped["motion"].items()
                          if value.motion_templates},
        render_prompts={kind: {key: value.render_prompt for key, value in definitions.items()
                              if value.render_prompt}
                        for kind, definitions in grouped.items()},
        style={key: value.text for key, value in styles.items()},
        motion={key: value.text for key, value in grouped["motion"].items()},
        motion_composition_timing={
            key: value.composition_timing for key, value in grouped["motion"].items()
        },
        motion_composition_reselection={
            key: value.composition_reselection for key, value in grouped["motion"].items()
        },
        camera={key: value.text for key, value in grouped["camera"].items()},
        locked_style=frozenset(
            key for key, value in styles.items() if value.locked
        ),
        style_retention={
            key: value.retention for key, value in styles.items() if value.retention
        },
        style_scene_reinforcement={
            key: value.scene_reinforcement
            for key, value in styles.items()
            if value.scene_reinforcement
        },
        camera_arc_roll_policy={
            key: value.arc_roll_policy
            for key, value in grouped["camera"].items()
        },
    )
