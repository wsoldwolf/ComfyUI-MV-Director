"""Small, injectable llama-cpp-python lifecycle.

This module does not import llama_cpp until a model is explicitly loaded.
It intentionally contains no prompt repair, grammar, or retry policy.
"""

from __future__ import annotations

import gc
import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .runtime import LlamaRuntimeConfig


class InferenceBackendError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TokenCount:
    count: int
    estimated: bool


def _model_signature(path: Path, config: LlamaRuntimeConfig) -> tuple[Any, ...]:
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    return (
        str(resolved),
        stat.st_size,
        stat.st_mtime_ns,
        config.n_ctx,
        config.gpu_layers,
        config.n_batch,
        config.flash_attn,
        config.kv_cache_type,
        config.op_offload,
        config.chat_format,
    )


class LlamaCppLifecycle:
    def __init__(self, *, llama_module: Any = None, llama_class: Any = None) -> None:
        self._module = llama_module
        self._class = llama_class
        self._model: Any | None = None
        self._signature: tuple[Any, ...] | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def effective_n_ctx(self) -> int | None:
        if self._model is None:
            return None
        accessor = getattr(self._model, "n_ctx", None)
        value = accessor() if callable(accessor) else accessor
        return value if isinstance(value, int) and value > 0 else None

    def _dependencies(self) -> tuple[Any, Any]:
        if self._module is None:
            try:
                self._module = importlib.import_module("llama_cpp")
            except Exception as exc:
                raise InferenceBackendError(
                    "llama-cpp-python is unavailable; install a compatible build"
                ) from exc
        if self._class is None:
            self._class = getattr(self._module, "Llama", None)
        if self._class is None:
            raise InferenceBackendError("llama_cpp.Llama is unavailable")
        return self._module, self._class

    def _kv_type(self, module: Any, selection: str) -> Any:
        names = {
            "q8_0": "GGML_TYPE_Q8_0",
            "q4_0": "GGML_TYPE_Q4_0",
            "f16": "GGML_TYPE_F16",
        }
        name = names[selection]
        if not hasattr(module, name):
            raise InferenceBackendError(
                f"installed llama-cpp-python does not expose {name}"
            )
        return getattr(module, name)

    def ensure_loaded(self, model_path: str | Path, config: LlamaRuntimeConfig) -> Any:
        config.validate()
        path = Path(model_path)
        try:
            signature = _model_signature(path, config)
        except OSError as exc:
            raise InferenceBackendError(f"GGUF model cannot be read: {path}") from exc
        if self._model is not None and signature == self._signature:
            return self._model

        module, llama_class = self._dependencies()
        kv_type = self._kv_type(module, config.kv_cache_type)
        self.clear()
        kwargs: dict[str, Any] = {
            "model_path": str(path.resolve(strict=True)),
            "n_ctx": config.n_ctx,
            "n_gpu_layers": config.gpu_layers,
            "n_batch": config.n_batch,
            "flash_attn": config.flash_attn,
            "type_k": kv_type,
            "type_v": kv_type,
            "offload_kqv": True,
            "op_offload": config.op_offload,
            "verbose": False,
        }
        if config.chat_format:
            kwargs["chat_format"] = config.chat_format
        try:
            model = llama_class(**kwargs)
        except BaseException:
            self.clear()
            raise
        self._model = model
        self._signature = signature
        return model

    def clear(self) -> None:
        model = self._model
        self._model = None
        self._signature = None
        if model is not None:
            close = getattr(model, "close", None)
            if callable(close):
                close()
        gc.collect()

    def count_serialized_prompt(self, prompt: str) -> TokenCount:
        if self._model is None:
            raise InferenceBackendError("no GGUF model is loaded")
        tokenizer = getattr(self._model, "tokenize", None)
        if callable(tokenizer):
            try:
                tokens = tokenizer(prompt.encode("utf-8"), add_bos=True)
                return TokenCount(len(tokens), False)
            except (TypeError, ValueError, RuntimeError):
                pass
        return TokenCount(max(1, (len(prompt.encode("utf-8")) + 2) // 3), True)

    @staticmethod
    def _supported_kwargs(callable_object: Any, values: Mapping[str, Any]) -> dict[str, Any]:
        try:
            signature = inspect.signature(callable_object)
        except (TypeError, ValueError):
            return dict(values)
        if any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ):
            return dict(values)
        return {key: value for key, value in values.items() if key in signature.parameters}

    def complete_chat(
        self,
        messages: list[dict[str, str]],
        config: LlamaRuntimeConfig,
        *,
        interrupt_callback: Callable[[], Any] | None = None,
        grammar: str | None = None,
    ) -> str:
        if self._model is None:
            raise InferenceBackendError("no GGUF model is loaded")
        if interrupt_callback is not None:
            interrupt_callback()
        completion = getattr(self._model, "create_chat_completion", None)
        if not callable(completion):
            raise InferenceBackendError("loaded model has no chat completion API")
        values: dict[str, Any] = {
            "messages": messages,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "repeat_penalty": config.repetition_penalty,
            "seed": config.seed,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
            "reasoning": False,
        }
        if grammar is not None:
            module, _ = self._dependencies()
            grammar_class = getattr(module, "LlamaGrammar", None)
            if grammar_class is None:
                raise InferenceBackendError("llama-cpp-python does not expose LlamaGrammar")
            values["grammar"] = grammar_class.from_string(grammar, verbose=False)
        supported = self._supported_kwargs(completion, values)
        if grammar is not None and "grammar" not in supported:
            raise InferenceBackendError("chat completion does not support grammar")
        try:
            stream = completion(**supported)
            return self._collect_chat_stream(stream, interrupt_callback)
        except InferenceBackendError:
            raise
        except BaseException:
            raise

    @staticmethod
    def _collect_chat_stream(
        stream: Iterable[Any], interrupt_callback: Callable[[], Any] | None
    ) -> str:
        parts: list[str] = []
        for chunk in stream:
            if interrupt_callback is not None:
                interrupt_callback()
            if not isinstance(chunk, dict):
                raise InferenceBackendError("llama.cpp returned an invalid stream chunk")
            choices = chunk.get("choices")
            if not isinstance(choices, list):
                raise InferenceBackendError("llama.cpp stream chunk has no choices")
            if not choices:
                continue
            first = choices[0]
            if not isinstance(first, dict):
                raise InferenceBackendError("llama.cpp stream choice is invalid")
            delta = first.get("delta", {})
            if not isinstance(delta, dict):
                raise InferenceBackendError("llama.cpp stream delta is invalid")
            content = delta.get("content")
            if content is not None:
                if not isinstance(content, str):
                    raise InferenceBackendError("llama.cpp stream content is invalid")
                parts.append(content)
        result = "".join(parts)
        if not result.strip():
            raise InferenceBackendError("llama.cpp returned an empty response")
        return result
