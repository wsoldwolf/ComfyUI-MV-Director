"""Lazy llama.cpp MTMD lifecycle for Vision observation."""

from __future__ import annotations

from contextlib import contextmanager
import gc
import importlib
import os
from pathlib import Path
import sys
import threading
from typing import Any, Callable, Iterable, Iterator

from ..inference import InferenceBackendError, LlamaRuntimeConfig

from .model_discovery import VisionModelPair


_NATIVE_OUTPUT_LOCK = threading.RLock()


def _flush_standard_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            pass


@contextmanager
def _suppress_native_output() -> Iterator[None]:
    """Temporarily suppress MTMD's direct writes to process stdout/stderr."""

    with _NATIVE_OUTPUT_LOCK:
        saved: list[tuple[int, int]] = []
        try:
            _flush_standard_streams()
            for descriptor in (1, 2):
                saved.append((descriptor, os.dup(descriptor)))
        except OSError:
            for _, duplicate in saved:
                os.close(duplicate)
            yield
            return
        try:
            with open(os.devnull, "w", encoding="utf-8") as sink:
                os.dup2(sink.fileno(), 1)
                os.dup2(sink.fileno(), 2)
                yield
        finally:
            _flush_standard_streams()
            for descriptor, duplicate in saved:
                os.dup2(duplicate, descriptor)
                os.close(duplicate)


class LlamaCppVisionLifecycle:
    def __init__(
        self,
        *,
        llama_module: Any = None,
        llama_class: Any = None,
        handler_class: Any = None,
    ) -> None:
        self._module = llama_module
        self._class = llama_class
        self._handler_class = handler_class
        self._model: Any | None = None
        self._handler: Any | None = None
        self._signature: tuple[Any, ...] | None = None

    def _dependencies(self) -> tuple[Any, Any, Any]:
        if self._module is None:
            try:
                self._module = importlib.import_module("llama_cpp")
            except Exception as exc:
                raise InferenceBackendError(
                    "llama-cpp-python is unavailable; install a Vision-capable build"
                ) from exc
        if self._class is None:
            self._class = getattr(self._module, "Llama", None)
        if self._handler_class is None:
            try:
                chat_format = importlib.import_module("llama_cpp.llama_chat_format")
                self._handler_class = getattr(chat_format, "MTMDChatHandler", None)
            except Exception:
                self._handler_class = None
        if self._class is None or self._handler_class is None:
            raise InferenceBackendError(
                "installed llama-cpp-python does not provide MTMDChatHandler"
            )
        return self._module, self._class, self._handler_class

    @staticmethod
    def _file_signature(path: Path) -> tuple[str, int, int]:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
        return str(resolved), stat.st_size, stat.st_mtime_ns

    def ensure_loaded(
        self, pair: VisionModelPair, config: LlamaRuntimeConfig
    ) -> Any:
        config.validate()
        try:
            signature = (
                *self._file_signature(pair.model_path),
                *self._file_signature(pair.projector_path),
                config.n_ctx,
                config.gpu_layers,
                config.n_batch,
                config.flash_attn,
                config.kv_cache_type,
                config.op_offload,
            )
        except OSError as exc:
            raise InferenceBackendError("Vision model pair cannot be read") from exc
        if self._model is not None and signature == self._signature:
            return self._model
        module, llama_class, handler_class = self._dependencies()
        kv_names = {
            "q8_0": "GGML_TYPE_Q8_0",
            "q4_0": "GGML_TYPE_Q4_0",
            "f16": "GGML_TYPE_F16",
        }
        kv_name = kv_names[config.kv_cache_type]
        if not hasattr(module, kv_name):
            raise InferenceBackendError(f"llama_cpp does not expose {kv_name}")
        self.clear()
        handler = None
        try:
            with _suppress_native_output():
                handler = handler_class(
                    clip_model_path=str(pair.projector_path.resolve(strict=True)),
                    verbose=False,
                    use_gpu=config.gpu_layers != 0,
                )
                model = llama_class(
                    model_path=str(pair.model_path.resolve(strict=True)),
                    n_ctx=config.n_ctx,
                    n_gpu_layers=config.gpu_layers,
                    n_batch=config.n_batch,
                    flash_attn=config.flash_attn,
                    type_k=getattr(module, kv_name),
                    type_v=getattr(module, kv_name),
                    offload_kqv=True,
                    op_offload=config.op_offload,
                    chat_handler=handler,
                    verbose=False,
                )
        except BaseException:
            self._close(handler)
            self.clear()
            raise
        self._handler = handler
        self._model = model
        self._signature = signature
        return model

    @staticmethod
    def _close(value: Any | None) -> None:
        close = getattr(value, "close", None)
        if callable(close):
            close()
            return
        stack = getattr(value, "_exit_stack", None)
        stack_close = getattr(stack, "close", None)
        if callable(stack_close):
            stack_close()

    def clear(self) -> None:
        model, handler = self._model, self._handler
        self._model = None
        self._handler = None
        self._signature = None
        with _suppress_native_output():
            if model is not None:
                self._close(model)
            if handler is not None:
                self._close(handler)
        gc.collect()

    @staticmethod
    def _collect(
        stream: Iterable[Any], interrupt_callback: Callable[[], Any] | None
    ) -> str:
        parts: list[str] = []
        for chunk in stream:
            if interrupt_callback is not None:
                interrupt_callback()
            if not isinstance(chunk, dict):
                raise InferenceBackendError("invalid Vision stream chunk")
            choices = chunk.get("choices")
            if not isinstance(choices, list):
                raise InferenceBackendError("Vision stream chunk has no choices")
            if not choices:
                continue
            first = choices[0]
            delta = first.get("delta") if isinstance(first, dict) else None
            if not isinstance(delta, dict):
                raise InferenceBackendError("invalid Vision stream delta")
            content = delta.get("content")
            if content is not None:
                if not isinstance(content, str):
                    raise InferenceBackendError("invalid Vision stream content")
                parts.append(content)
        result = "".join(parts)
        if not result.strip():
            raise InferenceBackendError("Vision model returned an empty response")
        return result

    def complete_observation(
        self,
        *,
        system_prompt: str,
        request: str,
        image_data_uri: str,
        config: LlamaRuntimeConfig,
        interrupt_callback: Callable[[], Any] | None = None,
    ) -> str:
        if self._model is None:
            raise InferenceBackendError("no Vision model is loaded")
        if interrupt_callback is not None:
            interrupt_callback()
        reset = getattr(self._model, "reset", None)
        if callable(reset):
            reset()
        completion = getattr(self._model, "create_chat_completion", None)
        if not callable(completion):
            raise InferenceBackendError("Vision model has no chat completion API")
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": request},
                    {"type": "image_url", "image_url": {"url": image_data_uri}},
                ],
            },
        ]
        with _suppress_native_output():
            stream = completion(
                messages=messages,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                top_p=config.top_p,
                repeat_penalty=config.repetition_penalty,
                seed=config.seed,
                stream=True,
            )
            return self._collect(stream, interrupt_callback)
