"""Explicit opt-in motion composition directives, not semantic repair."""
from __future__ import annotations


def split_motion_templates(text: str) -> tuple[str, tuple[str, ...] | None]:
    """None inherits the profile; an explicit '* 無効' disables composition."""
    kept: list[str] = []
    values: list[str] = []
    active = seen = False
    for number, line in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        stripped = line.strip()
        if stripped == "# モーション補完":
            if seen:
                raise ValueError("duplicate # モーション補完")
            active = seen = True
            continue
        if stripped.startswith("# "):
            active = False
        if not active:
            kept.append(line)
            continue
        if not stripped:
            continue
        if not stripped.startswith("* ") or not stripped[2:].strip():
            raise ValueError(f"line {number}: モーション補完 requires a nonempty list item")
        value = stripped[2:].strip()
        if len(value) > 500 or any(ord(c) < 32 for c in value):
            raise ValueError(f"line {number}: invalid モーション補完 (max 500 characters)")
        values.append(value)
        if len(values) > 12:
            raise ValueError("モーション補完 supports at most 12 items")
    if seen and not values:
        raise ValueError("# モーション補完 requires an item or '* 無効'")
    if "無効" in values:
        if values != ["無効"]:
            raise ValueError("モーション補完 無効 must be the sole item")
        values = []
    return "\n".join(kept).strip(), tuple(values) if seen else None
