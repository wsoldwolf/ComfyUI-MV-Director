"""ComfyUI folder_paths adapter for Vision model/projector pairs."""

from __future__ import annotations

from typing import Any

try:
    from ...core.vision import (
        VisionModelPair,
        VisionModelSelectionError,
        discover_vision_model_pairs,
        resolve_vision_model_pair,
    )
except ImportError:  # Standalone repository tests.
    from core.vision import (
        VisionModelPair,
        VisionModelSelectionError,
        discover_vision_model_pairs,
        resolve_vision_model_pair,
    )

from .gguf_discovery import _AUTO, collect_comfy_gguf_roots


NO_VISION_MODELS = "(no Vision GGUF pairs found)"


def discover_comfy_vision_models(
    folder_paths_module: Any = _AUTO,
) -> tuple[VisionModelPair, ...]:
    roots = collect_comfy_gguf_roots(folder_paths_module)
    return discover_vision_model_pairs(roots)


def vision_model_choices(folder_paths_module: Any = _AUTO) -> list[str]:
    choices = [
        pair.selection_id
        for pair in discover_comfy_vision_models(folder_paths_module)
    ]
    return choices or [NO_VISION_MODELS]


def resolve_comfy_vision_model(
    selection_id: str,
    folder_paths_module: Any = _AUTO,
) -> VisionModelPair:
    if selection_id == NO_VISION_MODELS:
        raise VisionModelSelectionError(
            "no Vision GGUF pair was found; place a model and mmproj in the same directory"
        )
    roots = collect_comfy_gguf_roots(folder_paths_module)
    return resolve_vision_model_pair(selection_id, roots)
