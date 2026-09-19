"""Vision observation rendering without model or ComfyUI dependencies."""

from .subject_emd import (
    SubjectEMDError,
    SubjectEMDResult,
    render_subject_emd,
)
from .scene_emd import SceneEMDResult, render_scene_emd
from .graph_binding import (
    PictureBinding,
    PictureBindingError,
    PictureTarget,
    resolve_picture_binding,
)
from .image_data import (
    PreparedVisionImage,
    VisionImageError,
    pixel_fingerprint,
    prepare_comfy_image,
)
from .model_discovery import (
    VisionModelPair,
    VisionModelSelectionError,
    discover_vision_model_pairs,
    resolve_vision_model_pair,
)
from .image_to_subject import (
    ANALYSIS_PROFILES,
    HINT_CONFLICT_POLICIES,
    HINT_MODES,
    ImageToSubjectResult,
    VISION_PROMPT_VERSION,
    VisionObservationRequest,
    build_vision_request,
    compose_image_to_subject,
    observe_image,
)
from .llama_cpp_vision import LlamaCppVisionLifecycle

__all__ = [
    "PictureBinding",
    "PictureBindingError",
    "PictureTarget",
    "PreparedVisionImage",
    "ANALYSIS_PROFILES",
    "HINT_CONFLICT_POLICIES",
    "HINT_MODES",
    "ImageToSubjectResult",
    "LlamaCppVisionLifecycle",
    "SubjectEMDError",
    "SubjectEMDResult",
    "SceneEMDResult",
    "VisionImageError",
    "VisionModelPair",
    "VisionModelSelectionError",
    "VISION_PROMPT_VERSION",
    "VisionObservationRequest",
    "build_vision_request",
    "compose_image_to_subject",
    "discover_vision_model_pairs",
    "pixel_fingerprint",
    "observe_image",
    "prepare_comfy_image",
    "render_subject_emd",
    "render_scene_emd",
    "resolve_picture_binding",
    "resolve_vision_model_pair",
]
