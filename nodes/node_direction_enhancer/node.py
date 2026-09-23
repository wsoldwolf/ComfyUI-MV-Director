"""Thin ComfyUI wrapper for the Direction Enhancer core."""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

try:
    from ...core.artifacts import DirectionArtifact, sha256_text
    from ...core.direction import (
        CAMERA_PROFILES,
        MOTION_PROFILES,
        PASSTHROUGH_PROFILE,
        RETENTION_POLICIES,
        STYLE_PROFILES,
        DirectionEnhancerInput,
        build_direction_payload,
        enhance_direction,
    )
    from ...core.direction.enhancer import DIRECTION_PROMPT_VERSION
    from ...core.inference import (
        LlamaCppLifecycle,
        LlamaRuntimeConfig,
        SuccessCache,
        build_cache_key,
        fit_context_budget,
    )
except ImportError:  # Standalone repository tests.
    from core.artifacts import DirectionArtifact, sha256_text
    from core.direction import (
        CAMERA_PROFILES,
        MOTION_PROFILES,
        PASSTHROUGH_PROFILE,
        RETENTION_POLICIES,
        STYLE_PROFILES,
        DirectionEnhancerInput,
        build_direction_payload,
        enhance_direction,
    )
    from core.direction.enhancer import DIRECTION_PROMPT_VERSION
    from core.inference import (
        LlamaCppLifecycle,
        LlamaRuntimeConfig,
        SuccessCache,
        build_cache_key,
        fit_context_budget,
    )

from ..common import gguf_model_choices, resolve_comfy_gguf_model


CACHE_MODES = ("reuse", "refresh", "disabled")
LOGGER = logging.getLogger("mv_director.nodes")
_DIRECTION_MAX_OUTPUT_TOKENS = 1024
_DIRECTION_MIN_OUTPUT_TOKENS = 128
_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "prompts"
    / "direction_enhancer_system_prompt.txt"
)


def _system_prompt() -> str:
    text = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError("Direction Enhancer system prompt is empty")
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
    return SuccessCache(root / "mv_director" / "direction_cache")


class _LlamaDirectionBackend:
    def __init__(self, lifecycle: LlamaCppLifecycle) -> None:
        self.lifecycle = lifecycle

    def complete_direction(
        self,
        *,
        system_prompt: str,
        payload: str,
        config: LlamaRuntimeConfig,
        interrupt_callback: Any = None,
    ) -> str:
        model_payload = f"/no_think\n{payload}"
        serialized = f"{system_prompt}\n{model_payload}"
        count = self.lifecycle.count_serialized_prompt(serialized)
        effective = self.lifecycle.effective_n_ctx or config.n_ctx
        budget = fit_context_budget(
            count.count,
            config.max_tokens,
            effective,
            minimum_output_tokens=min(
                config.max_tokens, _DIRECTION_MIN_OUTPUT_TOKENS
            ),
            maximum_output_tokens=_DIRECTION_MAX_OUTPUT_TOKENS,
            estimated=count.estimated,
        )
        call_config = config
        if budget.reserved_output_tokens != config.max_tokens:
            call_config = replace(
                config, max_tokens=budget.reserved_output_tokens
            )
            LOGGER.info(
                "[MV Director - Direction Enhancer] adjusted output budget; "
                "prompt_tokens=%s%d; requested_max_tokens=%d; "
                "effective_max_tokens=%d; safety_margin=%d; n_ctx=%d",
                "~" if count.estimated else "",
                count.count,
                config.max_tokens,
                budget.reserved_output_tokens,
                budget.safety_margin,
                effective,
            )
        return self.lifecycle.complete_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": model_payload},
            ],
            call_config,
            interrupt_callback=interrupt_callback,
        )


class MVDirectorDirectionEnhancer:
    RETURN_TYPES = ("MV_DIRECTOR_DIRECTION", "STRING", "STRING")
    RETURN_NAMES = ("direction", "direction_emd_preview", "status")
    FUNCTION = "enhance"
    CATEGORY = "MV Director/Core"
    DESCRIPTION = (
        "Style、Environment、Time/Lighting、Motion、Camera、Otherの全体方針を統合します。"
    )

    def __init__(self) -> None:
        self._lifecycle = LlamaCppLifecycle()
        self._backend = _LlamaDirectionBackend(self._lifecycle)
        self._lock = threading.RLock()

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        models = gguf_model_choices()
        return {
            "required": {
                "retention_policy": (list(RETENTION_POLICIES), {"default": "profile"}),
                "user_request": ("STRING", {"default": "", "multiline": True}),
                "style_profile": ([*STYLE_PROFILES, PASSTHROUGH_PROFILE], {"default": "anime_emotional_mv"}),
                "motion_profile": ([*MOTION_PROFILES, PASSTHROUGH_PROFILE], {"default": "anime_emotional_mv"}),
                "camera_profile": ([*CAMERA_PROFILES, PASSTHROUGH_PROFILE], {"default": "anime_emotional_mv"}),
                "model_name": (models, {"default": models[0]}),
                "chat_format": ("STRING", {"default": ""}),
                "max_tokens": ("INT", {"default": 768, "min": 64, "max": 4096, "step": 32}),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 2.0, "step": 0.05}),
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
            "optional": {
                "concept_emd": ("STRING", {"default": "", "multiline": True}),
                "scene_emd": ("STRING", {"default": "", "multiline": True}),
                "direction_emd_passthrough": ("STRING", {"forceInput": True}),
            },
        }

    def enhance(
        self,
        user_request: str,
        style_profile: str,
        motion_profile: str,
        camera_profile: str,
        model_name: str,
        chat_format: str,
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
        retention_policy: str,
        concept_emd: str = "",
        scene_emd: str = "",
        direction_emd_passthrough: str = "",
    ) -> tuple[DirectionArtifact, str, str]:
        with self._lock:
            if cache_mode not in CACHE_MODES:
                raise ValueError("cache_mode must be reuse, refresh, or disabled")
            value = DirectionEnhancerInput(
                concept_emd=concept_emd,
                scene_emd=scene_emd,
                user_request=user_request,
                style_profile=style_profile,
                motion_profile=motion_profile,
                camera_profile=camera_profile,
                retention_policy=retention_policy,
                direction_emd_passthrough=direction_emd_passthrough,
            )
            value.validate()
            config = LlamaRuntimeConfig(
                chat_format=chat_format,
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
            if not value.requires_inference:
                try:
                    result = enhance_direction(
                        self._backend,
                        value=value,
                        system_prompt="",
                        runtime_config=config,
                        interrupt_callback=_interrupt,
                    )
                finally:
                    self._lifecycle.clear()
                return (
                    result.direction,
                    result.direction_emd_preview,
                    "cache=bypass; model=not_loaded; passthrough=yes; "
                    f"issues={len(result.issues)}; missing_retry=no; "
                    f"staging_candidates={len(result.direction.staging_candidates)}",
                )
            model = resolve_comfy_gguf_model(model_name)
            system_prompt = _system_prompt()
            key = build_cache_key(
                task="direction-enhancer",
                algorithm_version=DIRECTION_PROMPT_VERSION,
                inputs={
                    "model": {
                        "selection_id": model.selection_id,
                        "fingerprint": model.fingerprint,
                        "size": model.size,
                        "mtime_ns": model.mtime_ns,
                    },
                    "system_prompt_sha256": sha256_text(system_prompt),
                    "direction_payload_sha256": sha256_text(
                        build_direction_payload(value)
                    ),
                    "input": {
                        "concept_emd": value.normalized_concept_emd,
                        "scene_emd": value.normalized_scene_emd,
                        "user_request": value.normalized_user_request,
                        "style_profile": style_profile,
                        "motion_profile": motion_profile,
                        "camera_profile": camera_profile,
                        "retention_policy": retention_policy,
                        "direction_emd_passthrough": value.normalized_direction_emd_passthrough,
                    },
                    "runtime": config.to_dict(),
                },
            )
            cache = _cache()
            cached = cache.get(key) if cache_mode == "reuse" and cache else None
            if cached is not None and isinstance(cached.get("direction"), dict):
                direction = DirectionArtifact.from_dict(cached["direction"])
                preview = str(cached.get("preview", ""))
                issues = int(cached.get("issues", 0))
                retried = bool(cached.get("retried", False))
                cache_status = "hit"
                if not keep_model_loaded:
                    self._lifecycle.clear()
            else:
                try:
                    self._lifecycle.ensure_loaded(model.path, config)
                    result = enhance_direction(
                        self._backend,
                        value=value,
                        system_prompt=system_prompt,
                        runtime_config=config,
                        interrupt_callback=_interrupt,
                    )
                    direction = result.direction
                    preview = result.direction_emd_preview
                    issues = len(result.issues)
                    retried = bool(result.retried_missing)
                    if cache_mode in {"reuse", "refresh"} and cache is not None:
                        cache.put_success(
                            key,
                            {
                                "direction": direction.to_dict(),
                                "preview": preview,
                                "issues": issues,
                                "retried": retried,
                            },
                        )
                    cache_status = "miss" if cache_mode == "reuse" else cache_mode
                finally:
                    if not keep_model_loaded:
                        self._lifecycle.clear()
            status = (
                f"cache={cache_status}; issues={issues}; "
                f"missing_retry={'yes' if retried else 'no'}; "
                f"staging_candidates={len(direction.staging_candidates)}"
            )
            return direction, preview, status
