from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from nodes.common.whisper_discovery import (
    NO_WHISPER_MODELS,
    collect_comfy_whisper_roots,
    discover_comfy_whisper_models,
    resolve_comfy_whisper_model,
    whisper_model_choices,
)


class _FolderPaths:
    def __init__(self, models_dir: Path, extras: list[Path] | None = None) -> None:
        self.models_dir = str(models_dir)
        self.folder_names_and_paths = {"whisper": object()}
        self._extras = extras or []

    def get_folder_paths(self, name: str):
        self.assert_name = name
        return [str(path) for path in self._extras]


class WhisperDiscoveryTests(unittest.TestCase):
    def test_discovers_recursive_local_pt_and_qualifies_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            default = root / "models" / "whisper"
            extra = root / "extra"
            default.mkdir(parents=True)
            extra.mkdir()
            (default / "small.pt").write_bytes(b"a")
            (extra / "small.pt").write_bytes(b"bb")
            module = _FolderPaths(root / "models", [extra])
            found = discover_comfy_whisper_models(module)
            self.assertEqual(
                [item.selection_id for item in found],
                ["[models] small.pt", "[whisper1] small.pt"],
            )
            self.assertEqual(resolve_comfy_whisper_model(found[0].selection_id, module), found[0])

    def test_placeholder_and_stale_selection_are_rejected(self) -> None:
        module = _FolderPaths(Path("missing"))
        self.assertEqual(whisper_model_choices(module), [NO_WHISPER_MODELS])
        with self.assertRaises(ValueError):
            resolve_comfy_whisper_model(NO_WHISPER_MODELS, module)
        with self.assertRaises(ValueError):
            resolve_comfy_whisper_model("C:/absolute/model.pt", module)


if __name__ == "__main__":
    unittest.main()
