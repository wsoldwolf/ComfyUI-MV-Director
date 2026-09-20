"""ComfyUI wrapper for the deterministic Ref2VA EMD Compiler."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

try:
    from ...core.artifacts import RequiredReferencesArtifact, normalize_newlines, sha256_text
    from ...core.compiler import (
        IdentityTranslator,
        LlamaPromptTranslator,
        TRANSLATION_PROMPT_VERSION,
        compile_ref2va,
    )
    from ...core.emd import parse_emd
    from ...core.h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
    from ...core.inference import (
        LlamaCppLifecycle,
        LlamaRuntimeConfig,
        SuccessCache,
        build_cache_key,
    )
except ImportError:  # Standalone repository tests.
    from core.artifacts import RequiredReferencesArtifact, normalize_newlines, sha256_text
    from core.compiler import (
        IdentityTranslator,
        LlamaPromptTranslator,
        TRANSLATION_PROMPT_VERSION,
        compile_ref2va,
    )
    from core.emd import parse_emd
    from core.h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
    from core.inference import (
        LlamaCppLifecycle,
        LlamaRuntimeConfig,
        SuccessCache,
        build_cache_key,
    )

from ..common import gguf_model_choices, resolve_comfy_gguf_model


TRANSLATION_MODES = ("ja_to_en", "already_english")
CHAT_FORMATS = ("auto", "qwen", "gemma")
CACHE_MODES = ("reuse", "refresh", "disabled")
_COMPILER_CACHE_VERSION = "mvd-ref2va-compiler-cache-v15"
_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "prompts"
    / "prompt_translation_ja_en_system_prompt.txt"
)


def _system_prompt() -> str:
    value = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    if not value.strip():
        raise RuntimeError("Compiler translation system prompt is empty")
    return value.rstrip() + "\n"


def _interrupt() -> None:
    try:
        from comfy.model_management import throw_exception_if_processing_interrupted  # type: ignore
    except Exception:
        return
    throw_exception_if_processing_interrupted()


def _cache() -> SuccessCache | None:
    try:
        import folder_paths  # type: ignore

        root = Path(folder_paths.get_temp_directory())
    except Exception:
        return None
    return SuccessCache(root / "mv_director" / "compiler_cache")


def _cached_result(
    cached: dict[str, Any] | None,
) -> tuple[str, RequiredReferencesArtifact] | None:
    if cached is None:
        return None
    plan_json = cached.get("plan_json")
    references = cached.get("required_references")
    if not isinstance(plan_json, str) or not isinstance(references, dict):
        return None
    return plan_json, RequiredReferencesArtifact.from_dict(references)


class MVDirectorEMDCompiler:
    RETURN_TYPES = ("STRING", "MV_DIRECTOR_REQUIRED_REFERENCES", "STRING")
    RETURN_NAMES = ("plan_json", "required_references", "status")
    FUNCTION = "compile_emd"
    CATEGORY = "MV Director/Core"
    DESCRIPTION = "完全EMDをContext Loop向けRef2VA Plan JSONへ機械的に変換します。"

    def __init__(self) -> None:
        self._lifecycle = LlamaCppLifecycle()
        self._lock = threading.RLock()

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        models = gguf_model_choices()
        return {
            "required": {
                "emd_text": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "translation_mode": (list(TRANSLATION_MODES), {"default": "ja_to_en"}),
                "model_name": (models, {"default": models[0]}),
                "chat_format": (list(CHAT_FORMATS), {"default": "auto"}),
                "steps": ("INT", {"default": 8, "min": 1, "max": 100}),
                "max_tokens": ("INT", {"default": 4096, "min": 32, "max": 16384, "step": 32}),
                "temperature": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "top_p": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.01}),
                "repetition_penalty": ("FLOAT", {"default": 1.05, "min": 0.5, "max": 2.0, "step": 0.05}),
                "gpu_layers": ("INT", {"default": -1, "min": -1, "max": 1000}),
                "n_batch": ("INT", {"default": 256, "min": 32, "max": 4096, "step": 32}),
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
                "h3_timing_profile": ("MV_DIRECTOR_H3_TIMING_PROFILE",),
            },
        }

    def compile_emd(
        self,
        emd_text: str,
        translation_mode: str,
        model_name: str,
        chat_format: str,
        steps: int,
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
        cache_mode: str = "reuse",
        h3_timing_profile: H3TimingProfile | None = None,
    ) -> tuple[str, RequiredReferencesArtifact, str]:
        with self._lock:
            if translation_mode not in TRANSLATION_MODES:
                raise ValueError("translation_mode must be ja_to_en or already_english")
            if chat_format not in CHAT_FORMATS:
                raise ValueError("unknown chat_format")
            if cache_mode not in CACHE_MODES:
                raise ValueError("cache_mode must be reuse, refresh, or disabled")
            profile = h3_timing_profile or DEFAULT_H3_TIMING_PROFILE
            profile.validate()
            # Fail on EMD grammar before selecting or loading a language model.
            document = parse_emd(emd_text, timing_profile=profile)
            cache = _cache()

            def cache_status(cached: object) -> str:
                if cached is not None:
                    return "hit"
                return "miss" if cache_mode == "reuse" else cache_mode

            if translation_mode == "already_english":
                key = build_cache_key(
                    task="ref2va-emd-compiler",
                    algorithm_version=_COMPILER_CACHE_VERSION,
                    inputs={
                        "translation_mode": translation_mode,
                        "emd_text": normalize_newlines(emd_text),
                        "steps": steps,
                        "timing_profile": profile.to_dict(),
                    },
                )
                cached = _cached_result(
                    cache.get(key) if cache_mode == "reuse" and cache else None
                )
                self._lifecycle.clear()
                if cached is None:
                    result = compile_ref2va(
                        emd_text,
                        IdentityTranslator(),
                        steps=steps,
                        timing_profile=profile,
                    )
                    plan_json = result.plan_json()
                    references = result.required_references
                    if cache_mode in {"reuse", "refresh"} and cache is not None:
                        cache.put_success(
                            key,
                            {
                                "plan_json": plan_json,
                                "required_references": references.to_dict(),
                            },
                        )
                else:
                    plan_json, references = cached
                status = (
                    f"mode=already_english; scenes={len(document.scenes)}; "
                    f"references={len(references.references)}; model=not_loaded; "
                    f"cache={cache_status(cached)}"
                )
                return plan_json, references, status

            config = LlamaRuntimeConfig(
                chat_format="" if chat_format == "auto" else chat_format,
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
            model = resolve_comfy_gguf_model(model_name)
            system_prompt = _system_prompt()
            key = build_cache_key(
                task="ref2va-emd-compiler",
                algorithm_version=_COMPILER_CACHE_VERSION,
                inputs={
                    "translation_mode": translation_mode,
                    "translation_prompt_version": TRANSLATION_PROMPT_VERSION,
                    "emd_text": normalize_newlines(emd_text),
                    "steps": steps,
                    "timing_profile": profile.to_dict(),
                    "model": {
                        "selection_id": model.selection_id,
                        "fingerprint": model.fingerprint,
                        "size": model.size,
                        "mtime_ns": model.mtime_ns,
                    },
                    "system_prompt_sha256": sha256_text(system_prompt),
                    "runtime": config.to_dict(),
                },
            )
            cached = _cached_result(
                cache.get(key) if cache_mode == "reuse" and cache else None
            )
            if cached is not None:
                if not keep_model_loaded:
                    self._lifecycle.clear()
                plan_json, references = cached
                status = (
                    f"mode=ja_to_en; scenes={len(document.scenes)}; "
                    f"references={len(references.references)}; model=not_loaded; "
                    "translation_batches=0; estimated_token_batches=0; cache=hit"
                )
                return plan_json, references, status
            translator: LlamaPromptTranslator | None = None
            try:
                self._lifecycle.ensure_loaded(model.path, config)
                translator = LlamaPromptTranslator(
                    self._lifecycle,
                    system_prompt=system_prompt,
                    runtime_config=config,
                    interrupt_callback=_interrupt,
                )
                result = compile_ref2va(
                    emd_text,
                    translator,
                    steps=steps,
                    timing_profile=profile,
                )
                plan_json = result.plan_json()
                if cache_mode in {"reuse", "refresh"} and cache is not None:
                    cache.put_success(
                        key,
                        {
                            "plan_json": plan_json,
                            "required_references": result.required_references.to_dict(),
                        },
                    )
                status = (
                    f"mode=ja_to_en; scenes={len(document.scenes)}; "
                    f"references={len(result.required_references.references)}; "
                    f"translation_batches={translator.batch_count}; "
                    f"estimated_token_batches={translator.estimated_token_batches}; "
                    f"protocol_recovered={translator.protocol_recovered_count}; "
                    f"segmented_recovered={translator.segmented_recovered_count}; "
                    f"cleanup_recovered={translator.cleanup_recovered_count}; "
                    f"cache={cache_status(None)}"
                )
                return plan_json, result.required_references, status
            finally:
                if not keep_model_loaded:
                    self._lifecycle.clear()
