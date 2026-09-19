"""ComfyUI wrapper for the MV Director Timeline Planner."""

from __future__ import annotations

import json
from dataclasses import replace
import hashlib
import logging
from pathlib import Path
import threading
from time import perf_counter
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


_LOGGER = logging.getLogger("mv_director.nodes")


CACHE_MODES = ("reuse", "refresh", "disabled")
CHAT_FORMATS = ("auto", "qwen", "gemma")
LIP_SYNC_MODES = ("off", "context_loop", "audio_reference", "lyrics")
_PROMPT_FILES = {
    "visual-beats": "timeline_planner_visual_beats_system_prompt.txt",
    "song-direction": "timeline_planner_song_direction_system_prompt.txt",
    "shot-layout": "timeline_planner_shot_layout_system_prompt.txt",
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
        self._task_calls: dict[str, int] = {}
        self._primary_calls: dict[str, int] = {}
        self._expected_primary_calls: dict[str, int] = {}

    def reset_trace(self) -> None:
        self.trace.clear()
        self._task_calls.clear()
        self._primary_calls.clear()

    @staticmethod
    def _call_seed(base_seed: int, task: str, call_number: int, payload: str) -> int:
        """Derive a reproducible but distinct sampling stream per LLM call."""

        material = f"{base_seed}\0{task}\0{call_number}\0{payload}".encode("utf-8")
        digest = hashlib.sha256(material).digest()
        return int.from_bytes(digest[:8], "big") % 2_147_483_647 + 1

    def configure_progress(self, scene_count: int, scenes_per_batch: int) -> None:
        scene_batches = max(1, (scene_count + scenes_per_batch - 1) // scenes_per_batch)
        self._expected_primary_calls = {
            "visual-beats": scene_batches,
            "song-direction": 1,
            "shot-layout": scene_batches,
            "actions": scene_batches,
            "cameras": scene_batches,
        }

    @staticmethod
    def _request_summary(payload: str) -> tuple[int, str, str]:
        try:
            value = json.loads(payload)
        except (TypeError, ValueError):
            return 0, "unknown", "no"
        slots = value.get("slots")
        if not isinstance(slots, list):
            slots = []
        scenes = sorted(
            {
                int(item["scene_number"])
                for item in slots
                if isinstance(item, dict)
                and isinstance(item.get("scene_number"), int)
            }
        )
        if not scenes:
            scene_label = "n/a"
        elif len(scenes) == 1:
            scene_label = str(scenes[0])
        else:
            scene_label = f"{scenes[0]}-{scenes[-1]}"
        if value.get("retry") == "missing_slots_only":
            retry_label = "missing_slots"
        elif value.get("retry") == "isolated_missing_slot":
            retry_label = "isolated_missing_slot"
        elif "boundary_mix_retry_reason" in value:
            retry_label = "boundary_mix"
        elif value.get("retry") == "repeated_slots_only":
            retry_label = "diversity"
        else:
            retry_label = "no"
        return len(slots), scene_label, retry_label

    def complete_planner(
        self,
        *,
        task: str,
        system_prompt: str,
        payload: str,
        config: LlamaRuntimeConfig,
        interrupt_callback: Any = None,
    ) -> str:
        model_payload = f"/no_think\n{payload}"
        count = self.lifecycle.count_serialized_prompt(system_prompt + "\n" + model_payload)
        build_context_budget(
            count.count,
            config.max_tokens,
            self.lifecycle.effective_n_ctx or config.n_ctx,
            estimated=count.estimated,
        )
        call_number = self._task_calls.get(task, 0) + 1
        self._task_calls[task] = call_number
        call_config = replace(
            config,
            seed=self._call_seed(config.seed, task, call_number, payload),
        )
        slot_count, scene_label, retry_label = self._request_summary(payload)
        if retry_label == "no":
            primary_number = self._primary_calls.get(task, 0) + 1
            self._primary_calls[task] = primary_number
            expected = self._expected_primary_calls.get(task)
            progress = (
                f"{primary_number}/{expected}"
                if expected is not None
                else str(primary_number)
            )
        else:
            progress = "retry"
        started = perf_counter()
        _LOGGER.info(
            "[MV Director - Timeline Planner] inference started; task=%s; "
            "batch=%s; call=%d; retry=%s; scenes=%s; slots=%d; "
            "prompt_tokens=%d%s; max_tokens=%d; call_seed=%d",
            task,
            progress,
            call_number,
            retry_label,
            scene_label,
            slot_count,
            count.count,
            " (estimated)" if count.estimated else "",
            config.max_tokens,
            call_config.seed,
        )
        try:
            response = self.lifecycle.complete_chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": model_payload},
                ],
                call_config,
                interrupt_callback=interrupt_callback,
            )
        except BaseException:
            _LOGGER.error(
                "[MV Director - Timeline Planner] inference failed; task=%s; "
                "batch=%s; call=%d; elapsed=%.3fs",
                task,
                progress,
                call_number,
                perf_counter() - started,
            )
            raise
        _LOGGER.info(
            "[MV Director - Timeline Planner] inference completed; task=%s; "
            "batch=%s; call=%d; elapsed=%.3fs; response_chars=%d",
            task,
            progress,
            call_number,
            perf_counter() - started,
            len(response),
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
                "lip_sync_target": ("STRING", {"default": "サブジェクト1"}),
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
                "cache_mode": (list(CACHE_MODES), {"default": "reuse"}),
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
    ) -> Any:
        with self._lock:
            if cache_mode not in CACHE_MODES:
                raise ValueError("cache_mode must be reuse, refresh, or disabled")
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
                    "lip_sync_active": lip_sync_mode != "off",
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
            cached = cache.get(key) if cache_mode == "reuse" and cache else None
            self._backend.reset_trace()
            self._backend.configure_progress(len(template.scenes), scenes_per_batch)
            cache_status = "hit" if cached else (
                "miss" if cache_mode == "reuse" else cache_mode
            )
            content: PlannerContent | None = None
            missing: tuple[tuple[str, int, int], ...] = ()
            if cached and isinstance(cached.get("content"), dict):
                _LOGGER.info(
                    "[MV Director - Timeline Planner] cache hit; LLM inference skipped; "
                    "scenes=%d",
                    len(template.scenes),
                )
                content = PlannerContent.from_dict(cached["content"])
                if not keep_model_loaded:
                    self._lifecycle.clear()
            else:
                try:
                    load_started = perf_counter()
                    _LOGGER.info(
                        "[MV Director - Timeline Planner] model loading; model=%s; "
                        "scenes=%d; scene_batches=%d; n_ctx=%d; max_tokens=%d; "
                        "gpu_layers=%d; n_batch=%d; cache=%s",
                        model.selection_id,
                        len(template.scenes),
                        max(1, (len(template.scenes) + scenes_per_batch - 1) // scenes_per_batch),
                        config.n_ctx,
                        config.max_tokens,
                        config.gpu_layers,
                        config.n_batch,
                        cache_status,
                    )
                    self._lifecycle.ensure_loaded(model.path, config)
                    _LOGGER.info(
                        "[MV Director - Timeline Planner] model ready; elapsed=%.3fs; "
                        "effective_n_ctx=%d",
                        perf_counter() - load_started,
                        self._lifecycle.effective_n_ctx or config.n_ctx,
                    )
                    content, missing = generate_planner_content(
                        self._backend,
                        template=template,
                        concept_emd=concept,
                        direction=selected_direction,
                        lip_sync_mode=lip_sync_mode,
                        lip_sync_target=lip_sync_target,
                        scenes_per_batch=scenes_per_batch,
                        system_prompts=prompts,
                        runtime_config=config,
                        interrupt_callback=_interrupt,
                    )
                    if content is not None and cache_mode in {"reuse", "refresh"} and cache is not None:
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
                if content.song_direction_fallback:
                    _LOGGER.warning(
                        "[MV Director - Timeline Planner] advisory DIRECTION "
                        "was missing after bounded retries; continued with "
                        "per-scene visual beats and Direction Artifact"
                    )
                planned_shot_count = sum(
                    len(starts) for _, starts in content.shot_layouts
                )
                continued_scene_count = sum(
                    1 for _, value in content.scene_continuations if value
                )
                fallback_label = (
                    "none"
                    if not content.layout_fallback_scenes
                    else ",".join(
                        str(scene) for scene in content.layout_fallback_scenes
                    )
                )
                if content.repetition_warning_count:
                    _LOGGER.warning(
                        "[MV Director - Timeline Planner] diversity retry left "
                        "%d similar creative record(s); beat=%d; action=%d; "
                        "camera=%d; accepted AS IS",
                        content.repetition_warning_count,
                        content.beat_repetition_warning_count,
                        content.action_repetition_warning_count,
                        content.camera_repetition_warning_count,
                    )
                status = (
                    f"complete=yes; scenes={len(template.scenes)}; shots={planned_shot_count}; "
                    f"cuts={len(template.scenes) - continued_scene_count}; "
                    f"continuations={continued_scene_count}; "
                    f"issues={content.issue_count}; retries={len(content.retried_scenes)}; "
                    f"layout_repaired_scenes="
                    f"{'none' if not content.layout_repaired_scenes else ','.join(str(scene) for scene in content.layout_repaired_scenes)}; "
                    f"layout_fallback_scenes={fallback_label}; "
                    f"layout_mix_retry={'yes' if content.layout_mix_retry else 'no'}; "
                    f"protocol_recovered={content.protocol_recovered_count}; "
                    "song_direction_fallback="
                    f"{'yes' if content.song_direction_fallback else 'no'}; "
                    "repetition_warnings="
                    f"{content.repetition_warning_count}"
                    f"(beat={content.beat_repetition_warning_count},"
                    f"action={content.action_repetition_warning_count},"
                    f"camera={content.camera_repetition_warning_count}); "
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
            if content is None:
                message = (
                    "Timeline Planner did not produce a complete EMD; "
                    f"{status}. Compiler execution was blocked."
                )
                _LOGGER.error(message)
                try:
                    from comfy_execution.graph import ExecutionBlocker  # type: ignore
                except Exception as exc:
                    raise RuntimeError(message) from exc
                blocker = ExecutionBlocker(message)
                return {
                    "ui": {"status": [status]},
                    "result": (blocker, blocker, status),
                }
            return emd.text, emd, status
