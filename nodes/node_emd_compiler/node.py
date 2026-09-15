"""ComfyUI wrapper for the deterministic Ref2VA EMD Compiler."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

try:
    from ...core.artifacts import RequiredReferencesArtifact
    from ...core.compiler import (
        IdentityTranslator,
        LlamaPromptTranslator,
        compile_ref2va,
    )
    from ...core.emd import parse_emd
    from ...core.h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
    from ...core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
except ImportError:  # Standalone repository tests.
    from core.artifacts import RequiredReferencesArtifact
    from core.compiler import IdentityTranslator, LlamaPromptTranslator, compile_ref2va
    from core.emd import parse_emd
    from core.h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
    from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig

from ..common import gguf_model_choices, resolve_comfy_gguf_model


TRANSLATION_MODES = ("ja_to_en", "already_english")
CHAT_FORMATS = ("auto", "qwen", "gemma")
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
                "steps": ("INT", {"default": 20, "min": 1, "max": 100}),
                "max_tokens": ("INT", {"default": 4096, "min": 32, "max": 16384, "step": 32}),
                "temperature": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "top_p": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.01}),
                "repetition_penalty": ("FLOAT", {"default": 1.05, "min": 0.5, "max": 2.0, "step": 0.05}),
                "gpu_layers": ("INT", {"default": -1, "min": -1, "max": 1000}),
                "n_batch": ("INT", {"default": 256, "min": 32, "max": 4096, "step": 32}),
                "n_ctx": ("INT", {"default": 32768, "min": 0, "max": 131072, "step": 1024}),
                "flash_attn": ("BOOLEAN", {"default": True}),
                "kv_cache_type": (["q8_0", "q4_0", "f16"], {"default": "q8_0"}),
                "op_offload": ("BOOLEAN", {"default": True}),
                "keep_model_loaded": ("BOOLEAN", {"default": False}),
                "seed": ("INT", {"default": 1, "min": 1, "max": 2147483647}),
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
        h3_timing_profile: H3TimingProfile | None = None,
    ) -> tuple[str, RequiredReferencesArtifact, str]:
        with self._lock:
            if translation_mode not in TRANSLATION_MODES:
                raise ValueError("translation_mode must be ja_to_en or already_english")
            if chat_format not in CHAT_FORMATS:
                raise ValueError("unknown chat_format")
            profile = h3_timing_profile or DEFAULT_H3_TIMING_PROFILE
            profile.validate()
            # Fail on EMD grammar before selecting or loading a language model.
            document = parse_emd(emd_text, timing_profile=profile)

            if translation_mode == "already_english":
                self._lifecycle.clear()
                result = compile_ref2va(
                    emd_text,
                    IdentityTranslator(),
                    steps=steps,
                    timing_profile=profile,
                )
                status = (
                    f"mode=already_english; scenes={len(document.scenes)}; "
                    f"references={len(result.required_references.references)}; model=not_loaded"
                )
                return result.plan_json(), result.required_references, status

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
            translator: LlamaPromptTranslator | None = None
            try:
                self._lifecycle.ensure_loaded(model.path, config)
                translator = LlamaPromptTranslator(
                    self._lifecycle,
                    system_prompt=_system_prompt(),
                    runtime_config=config,
                    interrupt_callback=_interrupt,
                )
                result = compile_ref2va(
                    emd_text,
                    translator,
                    steps=steps,
                    timing_profile=profile,
                )
                status = (
                    f"mode=ja_to_en; scenes={len(document.scenes)}; "
                    f"references={len(result.required_references.references)}; "
                    f"translation_batches={translator.batch_count}; "
                    f"estimated_token_batches={translator.estimated_token_batches}"
                )
                return result.plan_json(), result.required_references, status
            finally:
                if not keep_model_loaded:
                    self._lifecycle.clear()
