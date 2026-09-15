"""ComfyUI wrapper for the MV Director Timeline Planner."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

try:
    from ...core.artifacts import DirectionArtifact, EMDTextArtifact, normalize_newlines, sha256_text
    from ...core.inference import (
        LlamaCppLifecycle,
        LlamaRuntimeConfig,
        SuccessCache,
        build_cache_key,
        build_context_budget,
    )
    from ...core.planner import (
        PLANNER_ALGORITHM_VERSION,
        PlannerContent,
        generate_planner_content,
        normalize_concept_emd,
        parse_template_emd,
        render_planner_content,
    )
except ImportError:  # Standalone repository tests.
    from core.artifacts import DirectionArtifact, EMDTextArtifact, normalize_newlines, sha256_text
    from core.inference import (
        LlamaCppLifecycle,
        LlamaRuntimeConfig,
        SuccessCache,
        build_cache_key,
        build_context_budget,
    )
    from core.planner import (
        PLANNER_ALGORITHM_VERSION,
        PlannerContent,
        generate_planner_content,
        normalize_concept_emd,
        parse_template_emd,
        render_planner_content,
    )

from ..common import gguf_model_choices, resolve_comfy_gguf_model


CACHE_MODES = ("use", "refresh", "off")
CHAT_FORMATS = ("auto", "qwen", "gemma")
LIP_SYNC_MODES = ("off", "context_loop", "audio_reference", "lyrics")
_PROMPT_FILES = {
    "lyric-notes": "timeline_planner_lyric_notes_system_prompt.txt",
    "song-direction": "timeline_planner_song_direction_system_prompt.txt",
    "actions": "timeline_planner_actions_system_prompt.txt",
    "cameras": "timeline_planner_cameras_system_prompt.txt",
}


def _system_prompts() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2] / "prompts"
    result = {
        task: (root / filename).read_text(encoding="utf-8").rstrip() + "\n"
        for task, filename in _PROMPT_FILES.items()
    }
    if any(not value.strip() for value in result.values()):
        raise RuntimeError("Timeline Planner system prompt is empty")
    return result


def _interrupt() -> None:
    try:
        from comfy.model_management import throw_exception_if_processing_interrupted  # type: ignore
    except Exception:
        return
    throw_exception_if_processing_interrupted()


def _temp_root() -> Path | None:
    try:
        import folder_paths  # type: ignore

        return Path(folder_paths.get_temp_directory()) / "mv_director"
    except Exception:
        return None


def _cache() -> SuccessCache | None:
    root = _temp_root()
    return SuccessCache(root / "planner_cache") if root is not None else None


class _LlamaPlannerBackend:
    def __init__(self, lifecycle: LlamaCppLifecycle) -> None:
        self.lifecycle = lifecycle
        self.trace: list[dict[str, str]] = []

    def reset_trace(self) -> None:
        self.trace.clear()

    def complete_planner(
        self,
        *,
        task: str,
        system_prompt: str,
        payload: str,
        config: LlamaRuntimeConfig,
        interrupt_callback: Any = None,
    ) -> str:
        count = self.lifecycle.count_serialized_prompt(system_prompt + "\n" + payload)
        build_context_budget(
            count.count,
            config.max_tokens,
            self.lifecycle.effective_n_ctx or config.n_ctx,
            estimated=count.estimated,
        )
        response = self.lifecycle.complete_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload},
            ],
            config,
            interrupt_callback=interrupt_callback,
        )
        self.trace.append({"task": task, "payload": payload, "response": response})
        return response


def _debug_write(key: str, payload: dict[str, object]) -> str | None:
    root = _temp_root()
    if root is None:
        return None
    path = root / "planner_debug" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return str(path)


class MVDirectorTimelinePlanner:
    RETURN_TYPES = ("STRING", "MV_DIRECTOR_EMD", "STRING")
    RETURN_NAMES = ("emd_text", "emd", "status")
    FUNCTION = "plan"
    CATEGORY = "MV Director/Core"
    DESCRIPTION = "確定済みTemplate EMDへ歌詞解釈、人物動作、カメラ、lip-sync方式を展開します。"

    def __init__(self) -> None:
        self._lifecycle = LlamaCppLifecycle()
        self._backend = _LlamaPlannerBackend(self._lifecycle)
        self._lock = threading.RLock()

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        models = gguf_model_choices()
        return {
            "required": {
                "template_emd": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "lip_sync_mode": (list(LIP_SYNC_MODES), {"default": "lyrics"}),
                "lip_sync_target": ("STRING", {"default": "人物1"}),
                "lip_sync_audio_slot": ("INT", {"default": 1, "min": 1, "max": 3}),
                "model_name": (models, {"default": models[0]}),
                "chat_format": (list(CHAT_FORMATS), {"default": "auto"}),
                "max_tokens": ("INT", {"default": 4096, "min": 32, "max": 16384, "step": 32}),
                "temperature": ("FLOAT", {"default": 0.1, "min": 0.1, "max": 1.0, "step": 0.05}),
                "top_p": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.01}),
                "repetition_penalty": ("FLOAT", {"default": 1.05, "min": 0.5, "max": 2.0, "step": 0.05}),
                "gpu_layers": ("INT", {"default": -1, "min": -1, "max": 1000}),
                "n_batch": ("INT", {"default": 256, "min": 32, "max": 4096, "step": 32}),
                "n_ctx": ("INT", {"default": 16384, "min": 0, "max": 131072, "step": 1024}),
                "flash_attn": ("BOOLEAN", {"default": True}),
                "kv_cache_type": (["q8_0", "f16"], {"default": "q8_0"}),
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
                "scenes_per_batch": ("INT", {"default": 3, "min": 1, "max": 6}),
                "cache_mode": (list(CACHE_MODES), {"default": "use"}),
            },
            "optional": {
                "concept_emd": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "direction": ("MV_DIRECTOR_DIRECTION",),
                "model_name_override": ("STRING", {"default": "", "forceInput": True}),
                "save_debug_output": ("BOOLEAN", {"default": False}),
            },
        }

    def plan(
        self,
        template_emd: str,
        lip_sync_mode: str,
        lip_sync_target: str,
        lip_sync_audio_slot: int,
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
        scenes_per_batch: int,
        cache_mode: str,
        concept_emd: str = "",
        direction: DirectionArtifact | None = None,
        model_name_override: str = "",
        save_debug_output: bool = False,
    ) -> tuple[str, EMDTextArtifact, str]:
        with self._lock:
            if cache_mode not in CACHE_MODES:
                raise ValueError("cache_mode must be use, refresh, or off")
            if lip_sync_mode not in LIP_SYNC_MODES:
                raise ValueError("unknown lip_sync_mode")
            if chat_format not in CHAT_FORMATS:
                raise ValueError("unknown chat_format")
            selected_direction = direction or DirectionArtifact()
            selected_direction.validate()
            template = parse_template_emd(template_emd)
            concept = normalize_concept_emd(concept_emd)
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
            selection = model_name_override.strip() or model_name
            model = resolve_comfy_gguf_model(selection)
            prompts = _system_prompts()
            key = build_cache_key(
                task="timeline-planner",
                algorithm_version=PLANNER_ALGORITHM_VERSION,
                inputs={
                    "template_emd": normalize_newlines(template_emd),
                    "concept_emd": concept,
                    "direction": selected_direction.to_dict(),
                    "lip_sync_target": lip_sync_target,
                    "scenes_per_batch": scenes_per_batch,
                    "model": {
                        "selection_id": model.selection_id,
                        "fingerprint": model.fingerprint,
                        "size": model.size,
                        "mtime_ns": model.mtime_ns,
                    },
                    "runtime": config.to_dict(),
                    "system_prompts": {task: sha256_text(value) for task, value in prompts.items()},
                },
            )
            cache = _cache()
            cached = cache.get(key) if cache_mode == "use" and cache else None
            self._backend.reset_trace()
            cache_status = "hit" if cached else ("miss" if cache_mode == "use" else cache_mode)
            content: PlannerContent | None = None
            missing: tuple[tuple[str, int, int], ...] = ()
            if cached and isinstance(cached.get("content"), dict):
                content = PlannerContent.from_dict(cached["content"])
                if not keep_model_loaded:
                    self._lifecycle.clear()
            else:
                try:
                    self._lifecycle.ensure_loaded(model.path, config)
                    content, missing = generate_planner_content(
                        self._backend,
                        template=template,
                        concept_emd=concept,
                        direction=selected_direction,
                        lip_sync_target=lip_sync_target,
                        scenes_per_batch=scenes_per_batch,
                        system_prompts=prompts,
                        runtime_config=config,
                        interrupt_callback=_interrupt,
                    )
                    if content is not None and cache_mode in {"use", "refresh"} and cache is not None:
                        cache.put_success(key, {"content": content.to_dict()})
                finally:
                    if not keep_model_loaded:
                        self._lifecycle.clear()

            if content is None:
                emd = EMDTextArtifact.create("MVD_EMD_TEMPLATE_V1", template_emd)
                labels = ",".join(f"{kind}:scene{scene}:slot{slot}" for kind, scene, slot in missing)
                status = f"complete=no; missing={labels}; cache={cache_status}"
            else:
                emd = render_planner_content(
                    content=content,
                    concept_emd=concept,
                    template=template,
                    direction=selected_direction,
                    lip_sync_mode=lip_sync_mode,
                    lip_sync_target=lip_sync_target,
                    lip_sync_audio_slot=lip_sync_audio_slot,
                )
                status = (
                    f"complete=yes; scenes={len(template.scenes)}; shots={len(template.shot_keys)}; "
                    f"issues={content.issue_count}; retries={len(content.retried_scenes)}; "
                    f"removed_dialogue={content.removed_generated_dialogue_count}; "
                    f"unused_protected={len(content.unused_protected_dialogue_ids)}; cache={cache_status}"
                )
            if save_debug_output:
                debug_path = _debug_write(
                    key,
                    {
                        "cache_key": key,
                        "status": status,
                        "content": None if content is None else content.to_dict(),
                        "trace": self._backend.trace,
                    },
                )
                status += f"; debug={debug_path or 'unavailable'}"
            return emd.text, emd, status
