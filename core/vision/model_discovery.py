"""Pure discovery and deterministic pairing of Vision GGUF files."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class VisionModelSelectionError(ValueError):
    pass


_QUANT_SUFFIX_RE = re.compile(r"(?:[-.](?:IQ|Q|F|BF)\d[^.]*)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class VisionModelPair:
    selection_id: str
    root_id: str
    relative_path: str
    model_path: Path
    projector_path: Path
    model_size: int
    model_mtime_ns: int
    projector_size: int
    projector_mtime_ns: int

    def signature(self) -> dict[str, object]:
        return {
            "selection_id": self.selection_id,
            "model_path": str(self.model_path),
            "model_size": self.model_size,
            "model_mtime_ns": self.model_mtime_ns,
            "projector_path": str(self.projector_path),
            "projector_size": self.projector_size,
            "projector_mtime_ns": self.projector_mtime_ns,
        }


def _gguf_magic(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(4) == b"GGUF"
    except OSError:
        return False


def _series_name(path: Path) -> str:
    return _QUANT_SUFFIX_RE.sub("", path.stem).casefold().strip("-._ ")


def _projector_score(model: Path, projector: Path) -> tuple[int, int]:
    name = projector.stem.casefold()
    series = _series_name(model)
    directory = model.parent.name.casefold()
    related = int(
        bool(series and series in name) or bool(directory and directory in name)
    )
    if "f16" in name and "bf16" not in name:
        precision = 4
    elif "bf16" in name:
        precision = 3
    elif "q8_0" in name or "q8-0" in name:
        precision = 2
    else:
        precision = 1
    return related, precision


def _choose_projector(model: Path, projectors: list[Path]) -> Path | None:
    if len(projectors) == 1:
        return projectors[0]
    scored = [(item, _projector_score(model, item)) for item in projectors]
    best_score = max(score for _, score in scored)
    best = [item for item, score in scored if score == best_score]
    return best[0] if len(best) == 1 else None


def discover_vision_model_pairs(
    roots: Mapping[str, str | Path],
) -> tuple[VisionModelPair, ...]:
    candidates: list[tuple[str, str, Path, Path, int, int, int, int]] = []
    seen_roots: set[str] = set()
    seen_models: set[str] = set()
    for root_id, raw_root in roots.items():
        if not root_id or "::" in root_id:
            raise ValueError("root IDs must be non-empty and must not contain '::'")
        root = Path(raw_root).resolve()
        root_key = os.path.normcase(str(root))
        if root_key in seen_roots:
            continue
        seen_roots.add(root_key)
        if not root.is_dir():
            continue
        try:
            files = [
                path.resolve()
                for path in root.rglob("*")
                if path.suffix.casefold() == ".gguf"
            ]
        except OSError:
            continue
        by_directory: dict[Path, list[Path]] = {}
        for path in files:
            if path.is_file() and _gguf_magic(path):
                by_directory.setdefault(path.parent, []).append(path)
        for items in by_directory.values():
            projectors = sorted(
                (item for item in items if "mmproj" in item.name.casefold()),
                key=lambda item: item.name.casefold(),
            )
            if not projectors:
                continue
            models = sorted(
                (item for item in items if "mmproj" not in item.name.casefold()),
                key=lambda item: item.name.casefold(),
            )
            for model in models:
                model_key = os.path.normcase(str(model))
                if model_key in seen_models:
                    continue
                projector = _choose_projector(model, projectors)
                if projector is None:
                    continue
                try:
                    relative = model.relative_to(root).as_posix()
                    model_stat = model.stat()
                    projector_stat = projector.stat()
                except (OSError, ValueError):
                    continue
                seen_models.add(model_key)
                candidates.append(
                    (
                        root_id,
                        relative,
                        model,
                        projector,
                        model_stat.st_size,
                        model_stat.st_mtime_ns,
                        projector_stat.st_size,
                        projector_stat.st_mtime_ns,
                    )
                )
    counts: dict[str, int] = {}
    for _, relative, *_ in candidates:
        key = relative.casefold()
        counts[key] = counts.get(key, 0) + 1
    pairs = []
    for candidate in candidates:
        root_id, relative, model, projector, model_size, model_time, proj_size, proj_time = candidate
        selection_id = (
            f"{root_id}::{relative}"
            if counts[relative.casefold()] > 1
            else relative
        )
        pairs.append(
            VisionModelPair(
                selection_id,
                root_id,
                relative,
                model,
                projector,
                model_size,
                model_time,
                proj_size,
                proj_time,
            )
        )
    return tuple(sorted(pairs, key=lambda item: item.selection_id.casefold()))


def resolve_vision_model_pair(
    selection_id: str, roots: Mapping[str, str | Path]
) -> VisionModelPair:
    if not isinstance(selection_id, str) or not selection_id:
        raise VisionModelSelectionError("Vision model selection is required")
    if Path(selection_id).is_absolute():
        raise VisionModelSelectionError("absolute Vision model paths are not accepted")
    matches = [
        pair
        for pair in discover_vision_model_pairs(roots)
        if pair.selection_id == selection_id
    ]
    if len(matches) != 1:
        raise VisionModelSelectionError(
            "Vision model selection is missing, stale, or ambiguous; refresh the list"
        )
    return matches[0]

