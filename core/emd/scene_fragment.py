"""Strict parser and renderer for the scene-only EMD fragment."""

from __future__ import annotations

import re

from ..artifacts.base import normalize_newlines
from .ast import SceneSetting


_PICTURE_LINE_RE = re.compile(r"\* `画像([1-9])`\Z")
_SUBSECTIONS = ("環境", "時間・照明", "背景参照")


class SceneEMDFragmentError(ValueError):
    pass


def parse_scene_emd_fragment(source: str) -> SceneSetting:
    if not isinstance(source, str):
        raise SceneEMDFragmentError("scene_emd must be a string")
    normalized = normalize_newlines(source)
    if "\x00" in normalized:
        raise SceneEMDFragmentError("scene_emd contains NUL")
    lines = [line for line in normalized.split("\n") if line]
    if not lines or lines[0] != "# シーン設定":
        raise SceneEMDFragmentError("scene_emd must start with # シーン設定")
    index = 1
    sections: dict[str, tuple[str, ...]] = {}
    expected_index = 0
    while index < len(lines):
        heading = lines[index]
        if not heading.startswith("## "):
            raise SceneEMDFragmentError(f"unexpected scene_emd line: {heading!r}")
        name = heading[3:]
        if name not in _SUBSECTIONS:
            raise SceneEMDFragmentError(f"unknown scene_emd subsection {name!r}")
        actual_index = _SUBSECTIONS.index(name)
        if actual_index < expected_index:
            raise SceneEMDFragmentError("scene_emd subsection order is invalid")
        if name in sections:
            raise SceneEMDFragmentError(f"duplicate scene_emd subsection {name!r}")
        expected_index = actual_index + 1
        index += 1
        values: list[str] = []
        while index < len(lines) and not lines[index].startswith("## "):
            line = lines[index]
            if not line.startswith("* "):
                raise SceneEMDFragmentError(
                    f"scene_emd subsection {name!r} requires list items"
                )
            values.append(line[2:])
            index += 1
        if not values:
            raise SceneEMDFragmentError(
                f"scene_emd subsection {name!r} must not be empty"
            )
        sections[name] = tuple(values)

    environment = sections.get("環境", ())
    if not environment:
        raise SceneEMDFragmentError("scene_emd requires ## 環境")
    if any("`" in value for value in environment):
        raise SceneEMDFragmentError("## 環境 must not contain reserved tokens")
    time_lighting = sections.get("時間・照明", ())
    if any("`" in value for value in time_lighting):
        raise SceneEMDFragmentError(
            "## 時間・照明 must not contain reserved tokens"
        )
    picture_values = sections.get("背景参照", ())
    picture_ref: str | None = None
    if picture_values:
        if len(picture_values) != 1:
            raise SceneEMDFragmentError("## 背景参照 requires exactly one Picture")
        match = _PICTURE_LINE_RE.fullmatch(f"* {picture_values[0]}")
        if match is None:
            raise SceneEMDFragmentError("## 背景参照 must be one `画像1`..`画像9`")
        picture_ref = f"<Picture {match.group(1)}>"
    return SceneSetting(environment, time_lighting, picture_ref)


def render_scene_emd_fragment(setting: SceneSetting) -> str:
    if not isinstance(setting, SceneSetting) or not setting.environment:
        raise SceneEMDFragmentError("SceneSetting requires environment text")
    lines = ["# シーン設定", "## 環境"]
    lines.extend(f"* {value}" for value in setting.environment)
    if setting.time_lighting:
        lines.extend(("", "## 時間・照明"))
        lines.extend(f"* {value}" for value in setting.time_lighting)
    if setting.picture_ref is not None:
        match = re.fullmatch(r"<Picture ([1-9])>", setting.picture_ref)
        if match is None:
            raise SceneEMDFragmentError("invalid SceneSetting Picture reference")
        lines.extend(("", "## 背景参照", f"* `画像{match.group(1)}`"))
    return "\n".join(lines) + "\n"


__all__ = [
    "SceneEMDFragmentError",
    "parse_scene_emd_fragment",
    "render_scene_emd_fragment",
]
