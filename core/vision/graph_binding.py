"""Resolve the Image to Subject EMD pass-through output to an H3 Picture slot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

from core.artifacts.base import canonical_json, sha256_text
from core.h3_contract import CONTEXT_LOOP_0_6_6, ContextLoopContract


class PictureBindingError(ValueError):
    def __init__(self, message: str, *, status: str = "ambiguous") -> None:
        self.status = status
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PictureTarget:
    node_id: str
    node_type: str
    input_name: str
    picture_index: int

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "input_name": self.input_name,
            "picture_index": self.picture_index,
        }


@dataclass(frozen=True, slots=True)
class PictureBinding:
    mode: str
    picture_index: int | None
    targets: tuple[PictureTarget, ...] = ()

    @property
    def resolved_picture_reference(self) -> str:
        if self.mode == "none":
            return "none"
        if self.picture_index is None:
            return "unbound"
        return f"<Picture {self.picture_index}>"

    def fingerprint(self) -> str:
        return sha256_text(
            canonical_json(
                {
                    "mode": self.mode,
                    "picture_index": self.picture_index,
                    "targets": [target.to_dict() for target in self.targets],
                }
            )
        )


def _walk(value: Any, prefix: str) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                name = f"{prefix}.{key}" if prefix else key
                yield from _walk(child, name)
        return
    yield prefix, value


def _is_source(value: Any, source_id: str, output_index: int) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and str(value[0]) == source_id
        and value[1] == output_index
    )


def _targets(
    prompt: Any,
    unique_id: Any,
    image_output_index: int,
    contract: ContextLoopContract,
) -> tuple[PictureTarget, ...]:
    if not isinstance(prompt, dict):
        return ()
    source_id = str(unique_id)
    result: list[PictureTarget] = []
    for raw_node_id, raw_node in prompt.items():
        if not isinstance(raw_node, dict):
            continue
        node_type = raw_node.get("class_type", raw_node.get("type"))
        if node_type not in contract.ref2va_node_types:
            continue
        inputs = raw_node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for top_name, raw_value in inputs.items():
            if not isinstance(top_name, str):
                continue
            for input_name, value in _walk(raw_value, top_name):
                match = contract.image_input_pattern.fullmatch(input_name)
                if match is None or not _is_source(value, source_id, image_output_index):
                    continue
                result.append(
                    PictureTarget(
                        node_id=str(raw_node_id),
                        node_type=str(node_type),
                        input_name=input_name,
                        picture_index=int(match.group(1)) + 1,
                    )
                )
    return tuple(
        sorted(
            result,
            key=lambda item: (item.picture_index, item.node_id, item.input_name),
        )
    )


def resolve_picture_binding(
    mode: str,
    *,
    picture_index: int,
    prompt: Any,
    unique_id: Any,
    image_output_index: int = 2,
    contract: ContextLoopContract = CONTEXT_LOOP_0_6_6,
) -> PictureBinding:
    if mode not in {"auto_h3", "manual", "none"}:
        raise PictureBindingError("unknown picture_reference_mode", status="invalid")
    if not isinstance(picture_index, int) or isinstance(picture_index, bool) or not 1 <= picture_index <= 9:
        raise PictureBindingError("picture_index must be in 1..9", status="invalid")
    if mode == "none":
        return PictureBinding("none", None)
    if mode == "manual":
        return PictureBinding("manual", picture_index)

    targets = _targets(prompt, unique_id, image_output_index, contract)
    indices = sorted({target.picture_index for target in targets})
    if len(indices) > 1:
        details = "; ".join(
            f"node {target.node_id} {target.input_name} -> <Picture {target.picture_index}>"
            for target in targets
        )
        raise PictureBindingError(
            f"image output is connected to different H3 Picture numbers: {details}"
        )
    return PictureBinding("auto_h3", indices[0] if indices else None, targets)

