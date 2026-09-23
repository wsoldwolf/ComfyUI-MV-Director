"""Scene-local, LLM-authored event progression shared by Action and Camera.

The parser validates transport and ordering only. It never composes or rewrites
creative prose; invalid progressions are not partially adopted.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping


_FIELDS = ("PHASE", "FROM", "ADVANCE", "TO", "SHOW")
_EFFECT_FIELD = "EFFECT_TO"
_PHASES = frozenset({"setup", "event", "response"})
_SHOW = frozenset({
    "lyric_target_hands", "lyric_target", "face_eyes_mouth",
    "upper_body_hands", "whole_body", "lyric_target_body",
})
_COVERAGE = {
    "lyric_target_hands": "lyric_target_and_hands",
    "lyric_target": "lyric_target",
    "face_eyes_mouth": "face_eyes_mouth",
    "upper_body_hands": "upper_body_hands",
    "whole_body": "whole_body_emotion",
    "lyric_target_body": "lyric_target_and_body",
}


def build_scene_spine_grammar(
    slots: list[int] | list[Mapping[str, object]], *, allow_target_hands: bool = True,
    track_external_effect: bool = False,
    body_phrase_only: bool = False,
) -> str:
    """Constrain one event, contact coverage, and transport, not authored prose."""

    numbers = [
        slot if type(slot) is int else slot.get("slot")
        for slot in slots
    ]
    if not numbers or any(type(slot) is not int or slot < 1 for slot in numbers):
        raise ValueError("Scene spine grammar requires positive slots")
    if len(set(numbers)) != len(numbers):
        raise ValueError("Scene spine grammar slots must be unique")
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    paths: list[str] = []
    show_rules: list[str] = []
    for event_index in range(len(numbers)):
        rows: list[str] = []
        for index, (item, slot) in enumerate(zip(slots, numbers)):
            phase = (
                "setup" if index < event_index else
                "event" if index == event_index else "response"
            )
            allowed = set(_SHOW)
            if not track_external_effect:
                allowed.discard("lyric_target_body")
            if body_phrase_only:
                allowed.difference_update({
                    "lyric_target", "lyric_target_hands", "lyric_target_body",
                })
                if index == event_index:
                    allowed &= {"whole_body"}
            if allow_target_hands:
                allowed = (
                    {"lyric_target_hands"} if index == event_index
                    else allowed - {"lyric_target_hands"}
                )
            else:
                allowed.discard("lyric_target_hands")
            if isinstance(item, Mapping) and item.get("editorial_role") == "face_performance_cut":
                allowed &= {"face_eyes_mouth"}
            if not allowed:
                break
            show_rule = f"show-{event_index}-{slot}"
            show_rules.append(
                f"{show_rule} ::= " + " | ".join(map(quote, sorted(allowed)))
            )
            rows.append(
                quote(f"SPINE\t{slot}\tPHASE={phase}")
                + quote("｜FROM=") + " cell "
                + quote("｜ADVANCE=") + " cell "
                + quote("｜TO=") + " cell "
                + quote("｜SHOW=") + f" {show_rule}"
                + (quote("｜EFFECT_TO=") + " cell" if track_external_effect else "")
            )
        else:
            path_rule = f"path-{event_index}"
            paths.append(path_rule)
            show_rules.append(
                f"{path_rule} ::= " + ' "\\n" '.join(rows) + ' "\\n"?'
            )
    if not paths:
        raise ValueError("Scene spine has no valid event position")
    return (
        "root ::= " + " | ".join(paths) + "\n"
        + "\n".join(show_rules) + "\n"
        + r"cell ::= [^\x00-\x1f｜]+" + "\n"
    )


@dataclass(frozen=True, slots=True)
class SceneSpineStep:
    phase: str
    from_state: str
    advance: str
    to_state: str
    show: str
    effect_to: str = ""

    @property
    def required_coverage(self) -> str:
        return _COVERAGE[self.show]

    def to_dict(self) -> dict[str, str]:
        result = {
            "phase": self.phase,
            "from": self.from_state,
            "advance": self.advance,
            "to": self.to_state,
            "show": self.show,
        }
        if self.effect_to:
            result["effect_to"] = self.effect_to
        return result


def parse_scene_spine_step(text: str) -> SceneSpineStep:
    """Parse transport fields without changing the LLM-authored prose."""

    parts = text.strip().split("｜")
    if len(parts) not in {len(_FIELDS), len(_FIELDS) + 1}:
        raise ValueError("Scene spine requires five or six fields")
    values: list[str] = []
    names = (*_FIELDS, _EFFECT_FIELD) if len(parts) == len(_FIELDS) + 1 else _FIELDS
    for name, part in zip(names, parts):
        label, separator, value = part.partition("=")
        if not separator or label.strip() != name or not value.strip():
            raise ValueError(f"Scene spine field {name} is missing or out of order")
        values.append(value.strip())
    if values[0] not in _PHASES:
        raise ValueError("Scene spine PHASE is invalid")
    if values[4] not in _SHOW:
        raise ValueError("Scene spine SHOW is invalid")
    return SceneSpineStep(*values)


def validate_scene_spine(steps: tuple[SceneSpineStep, ...]) -> None:
    """One Scene event must advance once, then only react to its result."""

    if not steps:
        raise ValueError("Scene spine requires at least one Shot")
    phases = [step.phase for step in steps]
    if phases.count("event") != 1:
        raise ValueError("Scene spine requires exactly one event Shot")
    event_index = phases.index("event")
    if any(phase != "setup" for phase in phases[:event_index]):
        raise ValueError("Scene spine pre-event order is invalid")
    if any(phase != "response" for phase in phases[event_index + 1:]):
        raise ValueError("Scene spine post-event order is invalid")
    advances = ["".join(step.advance.split()).casefold() for step in steps]
    if len(set(advances)) != len(advances):
        raise ValueError("Scene spine repeats an identical Shot advance")


def validate_contact_coverage(
    steps: tuple[SceneSpineStep, ...], *, contact_allowed: bool
) -> None:
    """Keep target-and-hand coverage on the one contact event Shot only."""

    for step in steps:
        target_hands = step.show == "lyric_target_hands"
        if contact_allowed and target_hands != (step.phase == "event"):
            raise ValueError(
                "contact Scene must show target and hands only in its event Shot"
            )
        if not contact_allowed and target_hands:
            raise ValueError("non-contact Scene cannot require target and hands")


def required_coverage(show: str) -> str:
    return _COVERAGE[show]
