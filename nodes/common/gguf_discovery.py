"""ComfyUI folder_paths adapter for the pure GGUF discovery core."""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Any

try:
    from ...core.inference import (
        GGUFModel,
        ModelSelectionError,
        discover_gguf_models,
        resolve_model_selection,
    )
except ImportError:  # Standalone repository tests.
    from core.inference import (
        GGUFModel,
        ModelSelectionError,
        discover_gguf_models,
        resolve_model_selection,
    )


NO_GGUF_MODELS = "(no GGUF models found)"
_AUTO = object()


def _get_folder_paths_module(value: Any) -> Any | None:
    if value is not _AUTO:
        return value
    try:
        return importlib.import_module("folder_paths")
    except Exception:
        return None


def collect_comfy_gguf_roots(
    folder_paths_module: Any = _AUTO,
) -> dict[str, Path]:
    """Return ordered GGUF roots without scanning or loading a model."""

    folder_paths = _get_folder_paths_module(folder_paths_module)
    if folder_paths is None:
        return {}

    candidates: list[tuple[str, Path]] = []
    models_dir = getattr(folder_paths, "models_dir", None)
    if models_dir:
        candidates.append(("models", Path(models_dir) / "LLM" / "GGUF"))

    registered = getattr(folder_paths, "folder_names_and_paths", {})
    if isinstance(registered, dict) and "LLM" in registered:
        getter = getattr(folder_paths, "get_folder_paths", None)
        if callable(getter):
            try:
                llm_roots = getter("LLM")
            except Exception as exc:
                logging.getLogger("mv_director").warning(
                    "Could not read registered ComfyUI LLM paths: %s", exc
                )
                llm_roots = ()
            if isinstance(llm_roots, (list, tuple)):
                for index, raw_root in enumerate(llm_roots, 1):
                    root = Path(raw_root)
                    candidates.append((f"LLM{index}-GGUF", root / "GGUF"))
                    candidates.append((f"LLM{index}", root))

    roots: dict[str, Path] = {}
    seen: set[str] = set()
    for root_id, path in candidates:
        try:
            resolved = path.resolve(strict=False)
        except (OSError, RuntimeError):
            resolved = path.absolute()
        path_key = os.path.normcase(str(resolved))
        if path_key in seen:
            continue
        seen.add(path_key)
        roots[root_id] = resolved
    return roots


def discover_comfy_gguf_models(
    folder_paths_module: Any = _AUTO,
) -> tuple[GGUFModel, ...]:
    return discover_gguf_models(collect_comfy_gguf_roots(folder_paths_module))


def gguf_model_choices(folder_paths_module: Any = _AUTO) -> list[str]:
    choices = [
        model.selection_id
        for model in discover_comfy_gguf_models(folder_paths_module)
    ]
    return choices or [NO_GGUF_MODELS]


def resolve_comfy_gguf_model(
    selection_id: str,
    folder_paths_module: Any = _AUTO,
) -> GGUFModel:
    roots = collect_comfy_gguf_roots(folder_paths_module)
    if selection_id == NO_GGUF_MODELS:
        locations = ", ".join(str(path) for path in roots.values())
        suffix = f": {locations}" if locations else ""
        raise ModelSelectionError(f"no GGUF models were found{suffix}")
    return resolve_model_selection(selection_id, roots)
