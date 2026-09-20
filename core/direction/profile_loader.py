"""Strict loader for user-extensible Direction profile EMD files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from ..artifacts import normalize_newlines


PROFILE_ROOT = Path(__file__).resolve().parents[2] / "profiles"
_PROFILE_ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
_META_RE = re.compile(r"\* `([a-z_]+)`\s+(.+)\Z")
_KIND_HEADINGS = {
    "style": "スタイル",
    "motion": "モーション",
    "camera": "カメラ",
}
_STYLE_META_KEYS = frozenset({"locked", "retention", "scene_reinforcement"})
_MOTION_META_KEYS = frozenset({"performance_mode"})
_CAMERA_META_KEYS = frozenset(
    {"planner_policy", "lyric_cue_mode", "priority_lyric_cues", "lyric_interpretation"}
)
_META_KEYS = _STYLE_META_KEYS | _CAMERA_META_KEYS | _MOTION_META_KEYS
_PERFORMANCE_MODES = frozenset({"event_based", "dance_phrase"})
_PRIORITY_CUE_KINDS = frozenset(
    {"object", "symbolic_motif", "external_effect"}
)
_LYRIC_CUE_MODES = frozenset({"automatic", "priority_only", "off"})
_LYRIC_INTERPRETATIONS = frozenset({"literal", "bounded"})


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
    lyric_cue_mode: str = ""
    lyric_interpretation: str = "literal"
    priority_lyric_cues: tuple[tuple[str, str], ...] = ()
    performance_mode: str = "event_based"


@dataclass(frozen=True, slots=True)
class DirectionProfileCatalog:
    style: dict[str, str]
    motion: dict[str, str]
    camera: dict[str, str]
    locked_style: frozenset[str]
    style_retention: dict[str, str]
    style_scene_reinforcement: dict[str, str]
    camera_planner_policy: dict[str, str]
    camera_lyric_cue_mode: dict[str, str]
    camera_lyric_interpretation: dict[str, str]
    camera_priority_lyric_cues: dict[str, tuple[tuple[str, str], ...]]
    motion_performance_mode: dict[str, str]


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
    body: list[str] = []
    while position < len(lines):
        line = lines[position]
        if not line.startswith("* ") or not line[2:].strip():
            raise _fail(path, f"line {position + 1}: expected a nonempty list item")
        body.append(line[2:].strip())
        position += 1
    if not body:
        raise _fail(path, f"{expected_heading} requires at least one list item")

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
    if performance_mode not in _PERFORMANCE_MODES:
        raise _fail(path, "performance_mode must be event_based or dance_phrase")
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
        lyric_cue_mode=lyric_cue_mode,
        lyric_interpretation=lyric_interpretation,
        priority_lyric_cues=priority_lyric_cues,
        performance_mode=performance_mode,
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
        style={key: value.text for key, value in styles.items()},
        motion={key: value.text for key, value in grouped["motion"].items()},
        motion_performance_mode={
            key: value.performance_mode for key, value in grouped["motion"].items()
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
