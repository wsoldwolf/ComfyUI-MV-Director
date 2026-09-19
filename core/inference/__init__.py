"""Model discovery, execution contracts, token budgets, and success cache."""

from .budget import (
    ContextBudget,
    ContextBudgetError,
    build_context_budget,
    fit_context_budget,
)
from .cache import SuccessCache, build_cache_key
from .discovery import (
    GGUFModel,
    ModelSelectionError,
    discover_gguf_models,
    resolve_model_selection,
)
from .runtime import LlamaRuntimeConfig, TextInferenceBackend
from .llama_cpp_backend import (
    InferenceBackendError,
    LlamaCppLifecycle,
    TokenCount,
)

__all__ = [
    "ContextBudget",
    "ContextBudgetError",
    "GGUFModel",
    "LlamaRuntimeConfig",
    "LlamaCppLifecycle",
    "ModelSelectionError",
    "SuccessCache",
    "InferenceBackendError",
    "TextInferenceBackend",
    "TokenCount",
    "build_cache_key",
    "build_context_budget",
    "fit_context_budget",
    "discover_gguf_models",
    "resolve_model_selection",
]
