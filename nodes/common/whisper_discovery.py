"""Discover local OpenAI Whisper checkpoints below ComfyUI roots."""

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


NO_WHISPER_MODELS = "(no Whisper models found)"
_AUTO = object()


@dataclass(frozen=True, slots=True)
class WhisperModel:
    selection_id: str
    path: Path
    size: int
    mtime_ns: int


def _folder_paths(value: Any) -> Any | None:
    if value is not _AUTO:
        return value
    try:
        return importlib.import_module("folder_paths")
    except Exception:
        return None


def collect_comfy_whisper_roots(folder_paths_module: Any = _AUTO) -> dict[str, Path]:
    module = _folder_paths(folder_paths_module)
    if module is None:
        return {}
    candidates: list[tuple[str, Path]] = []
    models_dir = getattr(module, "models_dir", None)
    if models_dir:
        candidates.append(("models", Path(models_dir) / "whisper"))
    registered = getattr(module, "folder_names_and_paths", {})
    if isinstance(registered, dict) and "whisper" in registered:
        try:
            values = module.get_folder_paths("whisper")
        except Exception as exc:
            logging.getLogger("mv_director").warning(
                "Could not read registered Whisper paths: %s", exc
            )
            values = ()
        if isinstance(values, (list, tuple)):
            candidates.extend(
                (f"whisper{index}", Path(value))
                for index, value in enumerate(values, 1)
            )
    roots: dict[str, Path] = {}
    seen: set[str] = set()
    for identifier, path in candidates:
        resolved = path.resolve(strict=False)
        key = os.path.normcase(str(resolved))
        if key not in seen:
            roots[identifier] = resolved
            seen.add(key)
    return roots


def discover_comfy_whisper_models(
    folder_paths_module: Any = _AUTO,
) -> tuple[WhisperModel, ...]:
    found: list[tuple[str, Path, str]] = []
    seen: set[str] = set()
    for root_id, root in collect_comfy_whisper_roots(folder_paths_module).items():
        if not root.is_dir():
            continue
        try:
            paths = root.rglob("*.pt")
            for path in paths:
                try:
                    resolved = path.resolve(strict=True)
                    if not resolved.is_file():
                        continue
                    key = os.path.normcase(str(resolved))
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append((root_id, resolved, path.relative_to(root).as_posix()))
                except (OSError, RuntimeError, ValueError):
                    continue
        except OSError:
            continue
    counts: dict[str, int] = {}
    for _, _, relative in found:
        counts[relative.casefold()] = counts.get(relative.casefold(), 0) + 1
    result: list[WhisperModel] = []
    for root_id, path, relative in sorted(found, key=lambda row: (row[2].casefold(), row[0])):
        stat = path.stat()
        selection_id = relative if counts[relative.casefold()] == 1 else f"[{root_id}] {relative}"
        result.append(WhisperModel(selection_id, path, stat.st_size, stat.st_mtime_ns))
    return tuple(result)


def whisper_model_choices(folder_paths_module: Any = _AUTO) -> list[str]:
    values = [item.selection_id for item in discover_comfy_whisper_models(folder_paths_module)]
    return values or [NO_WHISPER_MODELS]


def resolve_comfy_whisper_model(
    selection_id: str, folder_paths_module: Any = _AUTO
) -> WhisperModel:
    roots = collect_comfy_whisper_roots(folder_paths_module)
    if selection_id == NO_WHISPER_MODELS:
        locations = ", ".join(str(path) for path in roots.values())
        raise ValueError(f"no local Whisper .pt model was found: {locations}")
    for model in discover_comfy_whisper_models(folder_paths_module):
        if model.selection_id == selection_id:
            return model
    raise ValueError(f"Whisper model selection is stale: {selection_id!r}")
