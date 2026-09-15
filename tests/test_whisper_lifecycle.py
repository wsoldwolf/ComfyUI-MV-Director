from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.lyrics import WhisperLifecycle


class _Model:
    def __init__(self) -> None:
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        return {"segments": []}


class _WhisperModule:
    def __init__(self) -> None:
        self.model = _Model()
        self.loads = []

    def load_model(self, path: str, *, device: str):
        self.loads.append((path, device))
        return self.model


class WhisperLifecycleTests(unittest.TestCase):
    def test_loads_local_path_once_and_uses_fixed_transcribe_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "small.pt"
            path.write_bytes(b"checkpoint")
            module = _WhisperModule()
            lifecycle = WhisperLifecycle()
            with patch(
                "core.lyrics.whisper.importlib.import_module",
                side_effect=lambda name: module if name == "whisper" else None,
            ):
                first = lifecycle.ensure_loaded(path, device="cpu")
                second = lifecycle.ensure_loaded(path, device="cpu")
                result = lifecycle.transcribe("audio", language="ja", device="cpu")
                lifecycle.clear()
            self.assertIs(first, second)
            self.assertEqual(len(module.loads), 1)
            self.assertEqual(result, {"segments": []})
            self.assertEqual(
                module.model.calls[0][1],
                {
                    "task": "transcribe",
                    "temperature": 0.0,
                    "beam_size": 5,
                    "word_timestamps": True,
                    "language": "ja",
                    "fp16": False,
                    "verbose": None,
                },
            )


if __name__ == "__main__":
    unittest.main()
