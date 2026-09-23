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
_MOTION_META_KEYS = frozenset({"performance_mode", "body_accent_policy", "choreography_policy", "render_prompt"})
_CAMERA_META_KEYS = frozenset(
    {"planner_policy", "arc_roll_policy", "arc_tilt_policy", "lyric_cue_mode", "priority_lyric_cues", "lyric_interpretation", "render_prompt"}
)
_META_KEYS = _STYLE_META_KEYS | _CAMERA_META_KEYS | _MOTION_META_KEYS
_PERFORMANCE_MODES = frozenset({"event_based", "dance_phrase", "scene_author"})
_BODY_ACCENT_POLICIES = frozenset({
    "off", "sparse_chorus", "sparse_chorus_prechorus",
    "sparse_chorus_prechorus_verse_contact", "scene_phrase",
})
_CHOREOGRAPHY_POLICIES = frozenset({"off", "scene_choice"})
_ARC_ROLL_POLICIES = frozenset({"off", "selective_arc"})
_PRIORITY_CUE_KINDS = frozenset(
    {"object", "symbolic_motif", "external_effect"}
)
_LYRIC_CUE_MODES = frozenset({"automatic", "priority_only", "off"})
_LYRIC_INTERPRETATIONS = frozenset({"literal", "bounded"})
_CHOREOGRAPHY_RE = re.compile(r"\* `([a-z][a-z0-9_]*)`\s+(.+)\Z")


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
    planner_policy: str = ""
    arc_roll_policy: str = "off"
    lyric_cue_mode: str = ""
    lyric_interpretation: str = "literal"
    priority_lyric_cues: tuple[tuple[str, str], ...] = ()
    performance_mode: str = "event_based"
    body_accent_policy: str = "off"
    choreography_policy: str = "off"
    render_prompt: str = ""
    choreography_phrases: tuple[tuple[str, str], ...] = ()
    motion_templates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DirectionProfileCatalog:
    style: dict[str, str]
    motion: dict[str, str]
    camera: dict[str, str]
    locked_style: frozenset[str]
    style_retention: dict[str, str]
    style_scene_reinforcement: dict[str, str]
    camera_planner_policy: dict[str, str]
    camera_arc_roll_policy: dict[str, str]
    camera_lyric_cue_mode: dict[str, str]
    camera_lyric_interpretation: dict[str, str]
    camera_priority_lyric_cues: dict[str, tuple[tuple[str, str], ...]]
    motion_performance_mode: dict[str, str]
    motion_body_accent_policy: dict[str, str]
    motion_choreography_policy: dict[str, str]
    motion_choreography_phrases: dict[str, tuple[tuple[str, str], ...]]
    render_prompts: dict[str, dict[str, str]]
    motion_templates: dict[str, tuple[str, ...]]


def _fail(path: Path, message: str) -> DirectionProfileError:
    return DirectionProfileError(f"{path}: {message}")


def _parse_priority_lyric_cues(
    path: Path, value: str
) -> tuple[tuple[str, str], ...]:
    cues: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_entry in value.split(","):
        entry = raw_entry.strip()
        if not entry or ":" not in entry:
            raise _fail(
                path,
                "priority_lyric_cues entries must use TOKEN:KIND",
            )
        token, kind = (part.strip() for part in entry.split(":", 1))
        if (
            not token
            or len(token) > 32
            or any(character.isspace() or ord(character) < 0x20 for character in token)
            or any(character in "=|,`" for character in token)
        ):
            raise _fail(path, "priority_lyric_cues contains an invalid token")
        if kind not in _PRIORITY_CUE_KINDS:
            raise _fail(
                path,
                "priority_lyric_cues kind must be object, symbolic_motif, "
                "or external_effect",
            )
        if token in seen:
            raise _fail(path, f"duplicate priority lyric cue {token!r}")
        seen.add(token)
        cues.append((token, kind))
    if not cues:
        raise _fail(path, "priority_lyric_cues must not be empty")
    return tuple(cues)


def _parse_metadata(path: Path, lines: list[str], position: int) -> tuple[dict[str, str], int]:
    metadata: dict[str, str] = {}
    while position < len(lines) and lines[position] != "# 共通プロンプト":
        match = _META_RE.fullmatch(lines[position])
        if match is None:
            raise _fail(path, f"line {position + 1}: invalid profile metadata")
        key, value = match.groups()
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
    while position < len(lines) and lines[position] != "# 振付候補":
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
    choreography_phrases: list[tuple[str, str]] = []
    if position < len(lines):
        if kind != "motion":
            raise _fail(path, "choreography phrases are supported only by motion profiles")
        position += 1
        seen_phrase_ids: set[str] = set()
        while position < len(lines):
            match = _CHOREOGRAPHY_RE.fullmatch(lines[position])
            if match is None:
                raise _fail(path, f"line {position + 1}: invalid choreography phrase")
            phrase_id, phrase = match.groups()
            if phrase_id in seen_phrase_ids:
                raise _fail(path, f"duplicate choreography phrase {phrase_id!r}")
            if len(phrase) > 512:
                raise _fail(path, f"choreography phrase {phrase_id!r} exceeds 512 characters")
            seen_phrase_ids.add(phrase_id)
            choreography_phrases.append((phrase_id, phrase))
            position += 1
        if len(choreography_phrases) < 2:
            raise _fail(path, "choreography requires at least two phrases")

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
    planner_policy = metadata.get("planner_policy", "")
    if planner_policy and not _PROFILE_ID_RE.fullmatch(planner_policy):
        raise _fail(path, "planner_policy must be a lowercase policy id")
    if "arc_tilt_policy" in metadata:
        raise _fail(path, "arc_tilt_policy is retired; use arc_roll_policy selective_arc for an Arc with a canted frame")
    arc_roll_policy = metadata.get("arc_roll_policy", "off")
    if arc_roll_policy not in _ARC_ROLL_POLICIES:
        raise _fail(path, "arc_roll_policy must be off or selective_arc")
    if arc_roll_policy != "off" and planner_policy != "anime_emotional_mv":
        raise _fail(path, "arc_roll_policy requires anime_emotional_mv planner_policy")
    lyric_cue_mode = metadata.get("lyric_cue_mode", "")
    if lyric_cue_mode and lyric_cue_mode not in _LYRIC_CUE_MODES:
        raise _fail(
            path,
            "lyric_cue_mode must be automatic, priority_only, or off",
        )
    lyric_interpretation = metadata.get("lyric_interpretation", "literal")
    if lyric_interpretation not in _LYRIC_INTERPRETATIONS:
        raise _fail(path, "lyric_interpretation must be literal or bounded")
    performance_mode = metadata.get("performance_mode", "event_based")
    if motion_templates and performance_mode != "scene_author":
        raise _fail(path, "モーション補完 requires performance_mode=scene_author")
    if performance_mode not in _PERFORMANCE_MODES:
        raise _fail(path, "performance_mode must be event_based, dance_phrase, or scene_author")
    body_accent_policy = metadata.get("body_accent_policy", "off")
    if body_accent_policy not in _BODY_ACCENT_POLICIES:
        raise _fail(path, "body_accent_policy must be off, sparse_chorus, sparse_chorus_prechorus, sparse_chorus_prechorus_verse_contact, or scene_phrase")
    if body_accent_policy != "off" and performance_mode != "dance_phrase":
        raise _fail(path, "body_accent_policy requires dance_phrase")
    choreography_policy = metadata.get("choreography_policy", "off")
    if choreography_policy not in _CHOREOGRAPHY_POLICIES:
        raise _fail(path, "choreography_policy must be off or scene_choice")
    if choreography_policy == "scene_choice" and (
        performance_mode != "dance_phrase" or len(choreography_phrases) < 2
    ):
        raise _fail(path, "choreography policy requires dance_phrase and at least two choreography phrases")
    if choreography_phrases and choreography_policy == "off":
        raise _fail(path, "choreography phrases require an enabled choreography_policy")
    priority_lyric_cues = (
        _parse_priority_lyric_cues(path, metadata["priority_lyric_cues"])
        if "priority_lyric_cues" in metadata
        else ()
    )
    return DirectionProfile(
        profile_id=profile_id,
        kind=kind,
        text=" ".join(body),
        source_path=path,
        locked=locked_value == "true",
        retention=retention,
        scene_reinforcement=metadata.get("scene_reinforcement", ""),
        planner_policy=planner_policy,
        arc_roll_policy=arc_roll_policy,
        lyric_cue_mode=lyric_cue_mode,
        lyric_interpretation=lyric_interpretation,
        priority_lyric_cues=priority_lyric_cues,
        performance_mode=performance_mode,
        body_accent_policy=body_accent_policy,
        choreography_policy=choreography_policy,
        render_prompt=metadata.get("render_prompt", ""),
        choreography_phrases=tuple(choreography_phrases),
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
        motion_performance_mode={
            key: value.performance_mode for key, value in grouped["motion"].items()
        },
        motion_body_accent_policy={
            key: value.body_accent_policy for key, value in grouped["motion"].items()
        },
        motion_choreography_policy={
            key: value.choreography_policy for key, value in grouped["motion"].items()
        },
        motion_choreography_phrases={
            key: value.choreography_phrases
            for key, value in grouped["motion"].items()
            if value.choreography_phrases
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
        camera_planner_policy={
            key: value.planner_policy
            for key, value in grouped["camera"].items()
            if value.planner_policy
        },
        camera_arc_roll_policy={
            key: value.arc_roll_policy
            for key, value in grouped["camera"].items()
        },
        camera_lyric_cue_mode={
            key: value.lyric_cue_mode
            for key, value in grouped["camera"].items()
            if value.lyric_cue_mode
        },
        camera_lyric_interpretation={
            key: value.lyric_interpretation
            for key, value in grouped["camera"].items()
        },
        camera_priority_lyric_cues={
            key: value.priority_lyric_cues
            for key, value in grouped["camera"].items()
            if value.priority_lyric_cues
        },
    )
