"""Thin ComfyUI wrapper for the Image to Subject EMD core."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

try:
    from ...core.artifacts import ObservationsArtifact
    from ...core.inference import LlamaRuntimeConfig, SuccessCache, build_cache_key
    from ...core.vision import (
        ANALYSIS_PROFILES,
        HINT_CONFLICT_POLICIES,
        HINT_MODES,
        LlamaCppVisionLifecycle,
        VISION_PROMPT_VERSION,
        VisionObservationRequest,
        build_vision_request,
        compose_image_to_subject,
        observe_image,
        prepare_comfy_image,
        resolve_picture_binding,
    )
except ImportError:  # Standalone repository tests.
    from core.artifacts import ObservationsArtifact
    from core.inference import LlamaRuntimeConfig, SuccessCache, build_cache_key
    from core.vision import (
        ANALYSIS_PROFILES,
        HINT_CONFLICT_POLICIES,
        HINT_MODES,
        LlamaCppVisionLifecycle,
        VISION_PROMPT_VERSION,
        VisionObservationRequest,
        build_vision_request,
        compose_image_to_subject,
        observe_image,
        prepare_comfy_image,
        resolve_picture_binding,
    )
from ..common import resolve_comfy_vision_model, vision_model_choices


CACHE_MODES = ("reuse", "refresh", "disabled")
PICTURE_REFERENCE_MODES = ("auto_h3", "manual", "none")
CONCEPT_TYPES = ("person", "location", "object")
_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "prompts"
    / "vision_observation_system_prompt.txt"
)


def _system_prompt() -> str:
    text = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError("Vision observation system prompt is empty")
    return text.rstrip() + "\n"


def _interrupt() -> None:
    try:
        from comfy.model_management import (  # type: ignore
            throw_exception_if_processing_interrupted,
        )
    except Exception:
        return
    throw_exception_if_processing_interrupted()


def _cache() -> SuccessCache | None:
    try:
        import folder_paths  # type: ignore

        root = Path(folder_paths.get_temp_directory())
    except Exception:
        return None
    return SuccessCache(root / "mv_director" / "vision_cache")


class MVDirectorImageToSubjectEMD:
    RETURN_TYPES = (
        "STRING",
        "MV_DIRECTOR_REFERENCE_BINDINGS",
        "IMAGE",
        "STRING",
    )
    RETURN_NAMES = (
        "emd_fragment",
        "reference_bindings",
        "image",
        "observations_json",
    )
    FUNCTION = "image_to_subject_emd"
    CATEGORY = "MV Director/Core"
    DESCRIPTION = "画像の可視事実から編集可能なSubject EMD断片を作成します。"
    IMAGE_OUTPUT_INDEX = 2

    def __init__(self) -> None:
        self._backend = LlamaCppVisionLifecycle()
        self._lock = threading.RLock()

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        models = vision_model_choices()
        return {
            "required": {
                "image": ("IMAGE",),
                "model_name": (models, {"default": models[0]}),
                "analysis_profile": (list(ANALYSIS_PROFILES), {"default": "general"}),
                "subject_hint": ("STRING", {"default": "", "multiline": True}),
                "additional_instruction": ("STRING", {"default": "", "multiline": True}),
                "hint_mode": (list(HINT_MODES), {"default": "lock_identity"}),
                "hint_conflict": (list(HINT_CONFLICT_POLICIES), {"default": "warn"}),
                "picture_reference_mode": (list(PICTURE_REFERENCE_MODES), {"default": "auto_h3"}),
                "concept_type": (list(CONCEPT_TYPES), {"default": "person"}),
                "concept_index": ("INT", {"default": 1, "min": 1, "max": 16}),
                "subject_index": ("INT", {"default": 1, "min": 1, "max": 4}),
                "picture_index": ("INT", {"default": 1, "min": 1, "max": 9}),
                "analysis_max_edge": ("INT", {"default": 1024, "min": 256, "max": 2048, "step": 64}),
                "max_tokens": ("INT", {"default": 1024, "min": 32, "max": 4096, "step": 32}),
                "temperature": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 2.0, "step": 0.05}),
                "top_p": ("FLOAT", {"default": 0.9, "min": 0.01, "max": 1.0, "step": 0.01}),
                "repetition_penalty": ("FLOAT", {"default": 1.05, "min": 0.1, "max": 2.0, "step": 0.05}),
                "gpu_layers": ("INT", {"default": -1, "min": -1, "max": 1000}),
                "n_batch": ("INT", {"default": 512, "min": 1, "max": 4096, "step": 32}),
                "n_ctx": ("INT", {"default": 16384, "min": 0, "max": 131072, "step": 1024}),
                "flash_attn": ("BOOLEAN", {"default": True}),
                "kv_cache_type": (["q8_0", "q4_0", "f16"], {"default": "q8_0"}),
                "op_offload": ("BOOLEAN", {"default": True}),
                "keep_model_loaded": ("BOOLEAN", {"default": False}),
                "seed": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 2147483647,
                        "control_after_generate": "randomize",
                    },
                ),
                "cache_mode": (list(CACHE_MODES), {"default": "reuse"}),
            },
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"},
        }

    @classmethod
    def IS_CHANGED(cls, image: Any, cache_mode: str = "reuse", **kwargs: Any) -> Any:
        if cache_mode != "reuse":
            return float("nan")
        try:
            prepared = prepare_comfy_image(
                image, int(kwargs.get("analysis_max_edge", 1024))
            )
            binding = resolve_picture_binding(
                kwargs.get("picture_reference_mode", "auto_h3"),
                picture_index=int(kwargs.get("picture_index", 1)),
                prompt=kwargs.get("prompt"),
                unique_id=kwargs.get("unique_id"),
                image_output_index=cls.IMAGE_OUTPUT_INDEX,
            )
            return build_cache_key(
                task="image-to-subject-node-change",
                algorithm_version=VISION_PROMPT_VERSION,
                inputs={
                    "image_sha256": prepared.image_sha256,
                    "binding": binding.fingerprint(),
                    "settings": {
                        key: value
                        for key, value in kwargs.items()
                        if key not in {"prompt", "unique_id", "keep_model_loaded"}
                    },
                },
            )
        except Exception as exc:
            return f"vision-change-error:{type(exc).__name__}:{exc}"

    def image_to_subject_emd(
        self,
        image: Any,
        model_name: str,
        analysis_profile: str,
        subject_hint: str,
        additional_instruction: str,
        hint_mode: str,
        hint_conflict: str,
        picture_reference_mode: str,
        concept_type: str,
        concept_index: int,
        subject_index: int,
        picture_index: int,
        analysis_max_edge: int,
        max_tokens: int,
        temperature: float,
        top_p: float,
        repetition_penalty: float,
        gpu_layers: int,
        n_batch: int,
        n_ctx: int,
        flash_attn: bool,
        kv_cache_type: str,
        op_offload: bool,
        keep_model_loaded: bool,
        seed: int,
        cache_mode: str,
        prompt: Any = None,
        unique_id: Any = None,
    ) -> dict[str, Any]:
        with self._lock:
            if cache_mode not in CACHE_MODES:
                raise ValueError("cache_mode must be reuse, refresh, or disabled")
            prepared = prepare_comfy_image(image, analysis_max_edge)
            pair = resolve_comfy_vision_model(model_name)
            request = VisionObservationRequest(
                analysis_profile=analysis_profile,
                subject_hint=subject_hint,
                additional_instruction=additional_instruction,
                hint_mode=hint_mode,
                hint_conflict=hint_conflict,
            )
            config = LlamaRuntimeConfig(
                max_tokens=max_tokens,
                temperature=float(temperature),
                top_p=float(top_p),
                repetition_penalty=float(repetition_penalty),
                gpu_layers=gpu_layers,
                n_batch=n_batch,
                n_ctx=n_ctx,
                flash_attn=flash_attn,
                kv_cache_type=kv_cache_type,
                op_offload=op_offload,
                keep_model_loaded=keep_model_loaded,
                seed=seed,
            )
            config.validate()
            binding = resolve_picture_binding(
                picture_reference_mode,
                picture_index=picture_index,
                prompt=prompt,
                unique_id=unique_id,
                image_output_index=self.IMAGE_OUTPUT_INDEX,
            )
            system_prompt = _system_prompt()
            cache_key = build_cache_key(
                task="vision-observation",
                algorithm_version=VISION_PROMPT_VERSION,
                inputs={
                    "image_sha256": prepared.image_sha256,
                    "model": pair.signature(),
                    "request": build_vision_request(request),
                    "system_prompt": system_prompt,
                    "runtime": config.to_dict(),
                },
            )
            cache = _cache()
            cached = cache.get(cache_key) if cache_mode == "reuse" and cache else None
            if cached is not None and isinstance(cached.get("observations"), dict):
                observations = ObservationsArtifact.from_dict(cached["observations"])
                warnings = tuple(str(item) for item in cached.get("warnings", []))
                cache_status = "hit"
                if not keep_model_loaded:
                    self._backend.clear()
            else:
                try:
                    self._backend.ensure_loaded(pair, config)
                    observations, warnings = observe_image(
                        self._backend,
                        prepared=prepared,
                        request=request,
                        model_identity=pair.signature(),
                        system_prompt=system_prompt,
                        runtime_config=config,
                        interrupt_callback=_interrupt,
                    )
                    if cache_mode in {"reuse", "refresh"} and cache is not None:
                        cache.put_success(
                            cache_key,
                            {
                                "observations": observations.to_dict(),
                                "warnings": list(warnings),
                            },
                        )
                    cache_status = "miss" if cache_mode == "reuse" else cache_mode
                finally:
                    if not keep_model_loaded:
                        self._backend.clear()
            result = compose_image_to_subject(
                observations,
                prepared=prepared,
                request=request,
                binding=binding,
                concept_type=concept_type,
                concept_index=concept_index,
                subject_index=subject_index,
                warnings=warnings,
            )
            status = (
                f"picture={result.resolved_picture_reference}; cache={cache_status}; "
                f"analysis={prepared.analysis_width}x{prepared.analysis_height}"
            )
            return {
                "ui": {
                    "resolved_picture_reference": [result.resolved_picture_reference],
                    "status": [status],
                },
                "result": (
                    result.emd.emd_fragment,
                    result.reference_bindings,
                    image,
                    result.observations.to_json(),
                ),
            }
