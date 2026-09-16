"""Lazy OpenAI Whisper lifecycle; never installs or downloads dependencies."""

from __future__ import annotations

import gc
import importlib
from pathlib import Path
import threading
from typing import Any

from .errors import LyricSegmentationError


class WhisperLifecycle:
    def __init__(self) -> None:
        self._model: Any | None = None
        self._signature: tuple[str, str, int, int] | None = None
        self._lock = threading.RLock()

    @staticmethod
    def resolve_device() -> str:
        try:
            torch = importlib.import_module("torch")
        except Exception as exc:
            raise LyricSegmentationError("PyTorch is unavailable") from exc
        return "cuda" if bool(torch.cuda.is_available()) else "cpu"

    @staticmethod
    def _import_whisper() -> Any:
        try:
            module = importlib.import_module("whisper")
        except Exception as exc:
            raise LyricSegmentationError(
                "OpenAI Whisper is not installed; install openai-whisper in the ComfyUI environment"
            ) from exc
        if not callable(getattr(module, "load_model", None)):
            raise LyricSegmentationError(
                "the imported whisper package is not OpenAI Whisper"
            )
        return module

    def ensure_loaded(self, path: Path, *, device: str) -> Any:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
        signature = (str(resolved), device, stat.st_size, stat.st_mtime_ns)
        with self._lock:
            if self._model is not None and self._signature == signature:
                return self._model
            self.clear()
            try:
                model = self._import_whisper().load_model(str(resolved), device=device)
            except LyricSegmentationError:
                raise
            except Exception as exc:
                raise LyricSegmentationError(
                    f"failed to load local Whisper model {resolved.name!r}"
                ) from exc
            if not callable(getattr(model, "transcribe", None)):
                raise LyricSegmentationError("loaded Whisper model has no transcribe method")
            self._model = model
            self._signature = signature
            return model

    def transcribe(
        self,
        audio: Any,
        *,
        language: str,
        device: str,
        initial_prompt: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            if self._model is None:
                raise LyricSegmentationError("Whisper model is not loaded")
            try:
                result = self._model.transcribe(
                    audio,
                    task="transcribe",
                    temperature=0.0,
                    beam_size=5,
                    word_timestamps=True,
                    language=language,
                    fp16=device == "cuda",
                    verbose=None,
                    initial_prompt=initial_prompt or None,
                    condition_on_previous_text=True,
                )
            except Exception as exc:
                raise LyricSegmentationError("OpenAI Whisper transcription failed") from exc
            if not isinstance(result, dict):
                raise LyricSegmentationError("OpenAI Whisper returned a non-object result")
            return result

    def clear(self) -> None:
        with self._lock:
            used_cuda = self._signature is not None and self._signature[1] == "cuda"
            self._model = None
            self._signature = None
            gc.collect()
            if used_cuda:
                try:
                    torch = importlib.import_module("torch")
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
