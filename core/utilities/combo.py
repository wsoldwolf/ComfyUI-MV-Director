"""Finite string-choice parsing."""

from __future__ import annotations

import json


def _validate_candidates(values: list[str]) -> tuple[str, ...]:
    if not values:
        raise ValueError("candidate list must not be empty")
    if any(not value for value in values):
        raise ValueError("candidate values must not be empty")
    if len(values) != len(set(values)):
        raise ValueError("candidate values must be unique")
    return tuple(values)


def parse_string_combo(value: str) -> tuple[str, ...]:
    """Parse ``|`` delimiters while treating ``||`` as a literal pipe."""

    if not isinstance(value, str):
        raise ValueError("string_list must be a string")
    candidates: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "|":
            current.append(value[index])
            index += 1
            continue
        if index + 1 < len(value) and value[index + 1] == "|":
            current.append("|")
            index += 2
            continue
        candidates.append("".join(current).strip())
        current = []
        index += 1
    candidates.append("".join(current).strip())
    return _validate_candidates(candidates)


def parse_connected_candidates(value: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise ValueError("enum_values_json must be a string")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("enum_values_json must be valid JSON") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise ValueError("enum_values_json must be an array of strings")
    return _validate_candidates(parsed)
