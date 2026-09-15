"""Deterministic GGUF discovery without importing ComfyUI."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ModelSelectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GGUFModel:
    selection_id: str
    root_id: str
    relative_path: str
    path: Path
    size: int
    mtime_ns: int
    fingerprint: str


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def discover_gguf_models(roots: Mapping[str, str | Path]) -> tuple[GGUFModel, ...]:
    candidates: list[tuple[str, str, Path, int, int]] = []
    seen_roots: set[Path] = set()
    for root_id in sorted(roots):
        if not root_id or "::" in root_id:
            raise ValueError("root IDs must be non-empty and must not contain '::'")
        root = Path(roots[root_id]).resolve()
        if root in seen_roots or not root.is_dir():
            continue
        seen_roots.add(root)
        for candidate in root.rglob("*"):
            if candidate.suffix.lower() != ".gguf" or "mmproj" in candidate.name.lower():
                continue
            resolved = candidate.resolve()
            if not resolved.is_file() or not _inside(resolved, root):
                continue
            relative = resolved.relative_to(root).as_posix()
            stat = resolved.stat()
            candidates.append(
                (root_id, relative, resolved, stat.st_size, stat.st_mtime_ns)
            )

    counts: dict[str, int] = {}
    for _, relative, _, _, _ in candidates:
        counts[relative] = counts.get(relative, 0) + 1
    models: list[GGUFModel] = []
    for root_id, relative, path, size, mtime_ns in candidates:
        selection_id = f"{root_id}::{relative}" if counts[relative] > 1 else relative
        signature = f"{root_id}\0{relative}\0{size}\0{mtime_ns}"
        models.append(
            GGUFModel(
                selection_id=selection_id,
                root_id=root_id,
                relative_path=relative,
                path=path,
                size=size,
                mtime_ns=mtime_ns,
                fingerprint=hashlib.sha256(signature.encode("utf-8")).hexdigest(),
            )
        )
    return tuple(sorted(models, key=lambda item: (item.selection_id.casefold(), item.selection_id)))


def resolve_model_selection(
    selection_id: str, roots: Mapping[str, str | Path]
) -> GGUFModel:
    if not isinstance(selection_id, str) or not selection_id:
        raise ModelSelectionError("a GGUF model selection is required")
    if Path(selection_id).is_absolute():
        raise ModelSelectionError("absolute model paths are not accepted")
    matches = [
        model
        for model in discover_gguf_models(roots)
        if model.selection_id == selection_id
    ]
    if len(matches) != 1:
        raise ModelSelectionError(
            "model selection is missing, stale, or ambiguous; refresh the model list"
        )
    return matches[0]

