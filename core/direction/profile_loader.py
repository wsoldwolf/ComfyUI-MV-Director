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
_META_KEYS = frozenset({"locked", "retention", "scene_reinforcement"})


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


@dataclass(frozen=True, slots=True)
class DirectionProfileCatalog:
    style: dict[str, str]
    motion: dict[str, str]
    camera: dict[str, str]
    locked_style: frozenset[str]
    style_retention: dict[str, str]
    style_scene_reinforcement: dict[str, str]


def _fail(path: Path, message: str) -> DirectionProfileError:
    return DirectionProfileError(f"{path}: {message}")


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

    if kind != "style" and metadata:
        raise _fail(path, "metadata is supported only by style profiles")
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
    return DirectionProfile(
        profile_id=profile_id,
        kind=kind,
        text=" ".join(body),
        source_path=path,
        locked=locked_value == "true",
        retention=retention,
        scene_reinforcement=metadata.get("scene_reinforcement", ""),
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
    )
